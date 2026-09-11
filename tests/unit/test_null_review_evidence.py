"""NULL carry-forward invariants, independent of Django and live databases."""

import copy
import json
import unittest
from datetime import date, datetime, timezone

from apps.common import null_review_evidence as reviews


class EvidenceCursor:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []
        self.rowcount = 0

    def execute(self, query, params=()):
        self.calls.append((query, params))

    def fetchone(self):
        return (101,)

    def fetchall(self):
        return self.rows


class NullReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.context = dict(table_name='public.ref_retail_com', country='SEA',
                            product_line='ref', retailer='Lowes')
        self.record = dict(id=42, item='000123', retailer_sku_name='Refrigerator A',
                           ref_capacity=None, star_rating=None)
        self.now = datetime(2026, 9, 12, 10, 30, tzinfo=reviews.KOREA)

    def capture(self, *, record=None, context=None, reason='상품페이지 내 항목 부재',
                day='2026-09-12', now=None, column='ref_capacity', memo='페이지에서 확인'):
        cursor = EvidenceCursor()
        metadata = reviews.save_manual_evidence(
            cursor, correction_id=51, inspection_date=day,
            record=record or self.record, column_name=column, reason=reason,
            reviewer='tester', memo=memo, now=now or self.now,
            **(context or self.context),
        )
        if not cursor.calls:
            return metadata, None, cursor
        params = cursor.calls[-1][1]
        row = dict(zip(reviews._EVIDENCE_COLUMNS[1:], params))
        row['id'] = 101
        row['value_snapshot'] = json.loads(row['value_snapshot'])
        return metadata, row, cursor

    def match(self, evidence, *, record=None, context=None, day='2026-09-13', column='ref_capacity'):
        return reviews.match_review(
            record or dict(self.record, id=43), column, day,
            evidence if isinstance(evidence, list) else [evidence],
            **(context or self.context),
        )

    def test_three_eligible_reasons_carry_across_all_five_countries(self):
        for country in sorted(reviews.COUNTRIES):
            for reason in sorted(reviews.ELIGIBLE_REASONS):
                with self.subTest(country=country, reason=reason):
                    context = dict(self.context, country=country)
                    _, row, _ = self.capture(context=context, reason=reason)
                    actual = self.match(row, context=context)
                    self.assertTrue(actual['auto_applied'])
                    self.assertEqual(actual['reason'], reason)
                    self.assertEqual(actual['original_crawl_date'], '2026-09-12')
                    self.assertEqual(actual['created_id'], 'tester')

    def test_manual_same_record_and_inspection_day_is_not_auto(self):
        _, row, _ = self.capture()
        result = self.match(row, record=self.record, day='2026-09-12')
        self.assertFalse(result['auto_applied'])
        self.assertIsNone(self.match(row, day='2026-09-12'))

    def test_changed_identity_field_or_scope_never_inherits(self):
        _, row, _ = self.capture()
        changes = [
            dict(record=dict(self.record, item='123')),
            dict(record=dict(self.record, retailer_sku_name='Refrigerator B')),
            dict(record=dict(self.record, retailer_sku_name='refrigerator a')),
            dict(context=dict(self.context, country='SEG')),
            dict(context=dict(self.context, retailer='Walmart')),
            dict(context=dict(self.context, product_line='TV')),
            dict(context=dict(self.context, table_name='other_ref_retail_com')),
            dict(column='star_rating'),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertIsNone(self.match(row, **change))

    def test_public_table_alias_and_edge_whitespace_are_stable(self):
        _, row, _ = self.capture()
        result = self.match(
            row, record=dict(self.record, id=43, retailer_sku_name=' Refrigerator A '),
            context=dict(self.context, table_name='ref_retail_com', retailer='LOWES'),
        )
        self.assertTrue(result['auto_applied'])

    def test_missing_item_or_product_name_is_not_an_auto_identity(self):
        for field in ('item', 'retailer_sku_name'):
            for value in (None, '', '   '):
                with self.subTest(field=field, value=value):
                    record = dict(self.record, **{field: value})
                    metadata, row, _ = self.capture(record=record)
                    self.assertFalse(metadata['auto_eligible'])
                    self.assertEqual(metadata['auto_exclusion_reason'],
                                     ('item' if field == 'item' else '제품명') + ' 정보 부족')
                    self.assertIsNone(self.match(row, record=record))
                    manual = self.match(row, record=record, day='2026-09-12')
                    self.assertFalse(manual['auto_applied'])
                    cursor = EvidenceCursor()
                    self.assertEqual(reviews.load_evidence(
                        cursor, inspection_date='2026-09-13', records=[record],
                        columns=['ref_capacity'], **self.context), [])
                    self.assertEqual(len(cursor.calls), 1)

    def test_exact_missing_representation_is_preserved(self):
        _, row, _ = self.capture()
        for value in ('', 'NULL', 'null', ' ', 0, False, '120 L'):
            with self.subTest(value=value):
                self.assertIsNone(self.match(row, record=dict(self.record, ref_capacity=value)))
        blank_record = dict(self.record, ref_capacity='')
        _, blank, _ = self.capture(record=blank_record)
        self.assertTrue(self.match(blank, record=dict(blank_record, id=44))['auto_applied'])
        self.assertIsNone(self.match(blank))

    def test_before_cutoff_is_not_loaded_or_backfilled(self):
        metadata, row, cursor = self.capture(day='2026-09-11')
        self.assertIsNone(metadata)
        self.assertIsNone(row)
        self.assertEqual(cursor.calls, [])
        cursor = EvidenceCursor()
        result = reviews.load_evidence(
            cursor, inspection_date='2026-09-11', records=[self.record],
            columns=['ref_capacity'], **self.context)
        self.assertEqual(result, [])
        self.assertEqual(cursor.calls, [])
        _, current, _ = self.capture()
        self.assertIsNone(self.match(current, day='2026-09-11'))
        self.assertIsNone(self.match([], day='2026-09-13'))

    def test_non_target_country_never_uses_evidence(self):
        context = dict(self.context, country='SEDA')
        metadata, row, cursor = self.capture(context=context)
        self.assertIsNone(metadata)
        self.assertEqual(cursor.calls, [])
        self.assertFalse(reviews.uses_new_policy('2026-09-13', 'SEDA'))

    def test_late_manual_confirmation_only_applies_from_actual_next_day(self):
        _, row, _ = self.capture(now=datetime(2026, 9, 15, 9, tzinfo=reviews.KOREA))
        self.assertEqual(row['auto_apply_from'], date(2026, 9, 16))
        self.assertIsNone(self.match(row, day='2026-09-13'))
        self.assertIsNone(self.match(row, day='2026-09-15'))
        self.assertTrue(self.match(row, day='2026-09-16')['auto_applied'])

    def test_korean_midnight_controls_manual_start_not_utc_date(self):
        utc_before = datetime(2026, 9, 11, 14, 59, tzinfo=timezone.utc)
        metadata, row, cursor = self.capture(now=utc_before)
        self.assertIsNone(metadata)
        self.assertEqual(cursor.calls, [])
        utc_after = datetime(2026, 9, 11, 15, 1, tzinfo=timezone.utc)
        _, row, _ = self.capture(now=utc_after)
        self.assertEqual(row['reviewed_at'].date(), date(2026, 9, 12))
        self.assertEqual(row['auto_apply_from'], date(2026, 9, 13))

    def test_future_inspection_date_cannot_seed_automatic_reviews(self):
        with self.assertRaisesRegex(ValueError, '미래 검수일'):
            self.capture(day='2026-09-13')

    def test_other_reasons_are_manual_only_and_block_older_evidence(self):
        _, old, _ = self.capture()
        for reason in ('상품페이지 없음', 'final_sku_price가 현재와 달라 보정 불가'):
            with self.subTest(reason=reason):
                _, row, _ = self.capture(reason=reason, now=self.now.replace(hour=11))
                row['id'] = 102
                self.assertIsNone(self.match([old, row]))
                manual = self.match(row, record=self.record, day='2026-09-12')
                self.assertFalse(manual['auto_applied'])
                self.assertFalse(manual['auto_eligible'])
                self.assertEqual(manual['auto_exclusion_reason'], '자동확인 대상 사유 아님')

    def test_normal_value_reason_spelling_variants_are_supported(self):
        for reason in ('해당값정상 확인', '해당 값 정상 확인', '해당값 정상 확인'):
            with self.subTest(reason=reason):
                _, row, _ = self.capture(reason=reason)
                self.assertEqual(self.match(row)['reason'], '해당값 정상 확인')

    def test_newer_different_value_blocks_fallback_to_old_value(self):
        _, old, _ = self.capture()
        _, newest, _ = self.capture(record=dict(self.record, ref_capacity=''), now=self.now.replace(hour=11))
        newest['id'] = 102
        self.assertIsNone(self.match([old, newest]))

    def test_revocation_stops_current_and_future_but_preserves_prior_provenance(self):
        _, row, _ = self.capture()
        row['revoked_at'] = datetime(2026, 9, 14, 9, tzinfo=reviews.KOREA)
        row['revoked_by'] = 'reviewer_b'
        historical = self.match(row, day='2026-09-13')
        self.assertTrue(historical['auto_applied'])
        self.assertTrue(historical['revoked_at'].startswith('2026-09-14'))
        self.assertIsNone(self.match(row, day='2026-09-14'))
        self.assertIsNone(self.match(row, day='2026-09-15'))

    def test_revoked_latest_evidence_does_not_fall_back(self):
        _, old, _ = self.capture()
        newest = copy.deepcopy(old)
        newest.update(id=102, reviewed_at=self.now.replace(hour=11), revoked_at=self.now.replace(hour=12))
        self.assertIsNone(self.match([newest, old]))

    def test_auto_keeps_original_manual_basis_without_arbitrary_expiry(self):
        _, row, _ = self.capture()
        first = self.match(row)
        future = self.match(row, day='2027-01-01')
        self.assertEqual(first['evidence_id'], future['evidence_id'])
        self.assertEqual(future['original_crawl_date'], '2026-09-12')
        self.assertEqual(future['created_at'], first['created_at'])

    def test_query_is_limited_to_requested_subjects_and_snapshot_is_parsed(self):
        _, row, _ = self.capture()
        row['value_snapshot'] = json.dumps(row['value_snapshot'])
        cursor = EvidenceCursor([tuple(row[name] for name in reviews._EVIDENCE_COLUMNS)])
        result = reviews.load_evidence(
            cursor, inspection_date='2026-09-13', records=[self.record],
            columns=['ref_capacity'], **self.context)
        self.assertEqual(len(cursor.calls[0][1][7]), 1)
        self.assertTrue(self.match(result)['auto_applied'])
        self.assertEqual(result[0]['value_snapshot'], {'type': 'null', 'value': None})

    def test_snapshot_does_not_depend_on_later_source_row_mutation(self):
        record = dict(self.record)
        _, row, _ = self.capture(record=record)
        record['retailer_sku_name'] = 'Replaced product'
        record['ref_capacity'] = '180 L'
        self.assertEqual(row['product_name'], 'Refrigerator A')
        self.assertEqual(row['value_snapshot'], {'type': 'null', 'value': None})
        self.assertIsNone(self.match(row, record=record))

    def test_revoke_is_idempotent_and_does_not_rewrite_snapshot(self):
        cursor = EvidenceCursor()
        cursor.rowcount = 1
        count = reviews.revoke_evidence(cursor, [51, 51], 'reviewer_b', '확인 취소', now=self.now)
        self.assertEqual(count, 1)
        self.assertEqual(cursor.calls[0][1][-1], [51])
        self.assertIn('revoked_at IS NULL', cursor.calls[0][0])
        self.assertNotIn('value_snapshot =', cursor.calls[0][0])

    def test_each_manually_confirmed_record_remains_manual_on_the_same_day(self):
        _, first, _ = self.capture()
        second_record = dict(self.record, id=43)
        _, second, _ = self.capture(record=second_record, now=self.now.replace(hour=11))
        second['id'] = 102
        evidence = reviews._EvidenceCollection([first, second])
        first_result = self.match(evidence, record=self.record, day='2026-09-12')
        second_result = self.match(evidence, record=second_record, day='2026-09-12')
        self.assertFalse(first_result['auto_applied'])
        self.assertEqual(first_result['evidence_id'], 101)
        self.assertFalse(second_result['auto_applied'])
        self.assertEqual(second_result['evidence_id'], 102)
        tomorrow = self.match(evidence, record=dict(self.record, id=44))
        self.assertTrue(tomorrow['auto_applied'])
        self.assertEqual(tomorrow['evidence_id'], 102)

    def test_reason_and_freeform_memo_are_preserved_on_later_queries(self):
        memo = '상품페이지의 상세 사양 확인\n용량 표기 없음. 문의란에는 "확인 중"으로 표시.'
        metadata, row, _ = self.capture(memo=memo)
        self.assertEqual(metadata['memo'], memo)
        self.assertEqual(metadata['auto_exclusion_reason'], '')
        automatic = self.match(row)
        self.assertEqual(automatic['reason'], '상품페이지 내 항목 부재')
        self.assertEqual(automatic['memo'], memo)
        self.assertTrue(automatic['auto_eligible'])

    def test_missing_identity_explanation_does_not_change_manual_acceptance(self):
        record = dict(self.record, item=None, retailer_sku_name=' ')
        metadata, row, _ = self.capture(record=record)
        self.assertEqual(metadata['auto_exclusion_reason'], 'item·제품명 정보 부족')
        manual = self.match(row, record=record, day='2026-09-12')
        self.assertFalse(manual['auto_applied'])
        self.assertEqual(manual['reason'], '상품페이지 내 항목 부재')
        self.assertIsNone(self.match(row, record=dict(record, id=43)))

    def test_field_matching_is_generic_across_countries_products_and_retailers(self):
        fields_by_product = {
            'TV': ('screen_size', 'product_url'),
            'REF': ('ref_capacity', 'star_rating'),
            'LDY': ('ldy_capacity', 'count_of_reviews'),
        }
        retailers_by_country = {
            'SEA': ('Amazon', 'Bestbuy'),
            'SEM': ('Liverpool',),
            'SIEL': ('Amazon', 'Flipkart'),
            'TSE': ('Homepro',),
            'SEG': ('Amazon', 'MediaMarkt', 'Otto'),
        }
        for country, retailers in retailers_by_country.items():
            for product, fields in fields_by_product.items():
                table = (f'public.{product.lower()}_retail_com' if country == 'SEA'
                         else f'dx_{country.lower()}.dx_{country.lower()}_{product.lower()}_retail_com')
                actual_retailers = ('Lowes', 'Bestbuy') if country == 'SEA' and product != 'TV' else retailers
                for retailer in actual_retailers:
                    context = dict(table_name=table, country=country,
                                   product_line=product, retailer=retailer)
                    for column in fields:
                        with self.subTest(country=country, product=product,
                                          retailer=retailer, column=column):
                            record = dict(self.record, **{column: None})
                            _, row, _ = self.capture(record=record, context=context, column=column)
                            next_record = dict(record, id=43)
                            self.assertTrue(self.match(row, record=next_record,
                                                       context=context, column=column)['auto_applied'])
                            self.assertIsNone(self.match(row, record=next_record,
                                                        context=dict(context, retailer='Another retailer'),
                                                        column=column))
                            self.assertIsNone(self.match(row, record=next_record,
                                                        context=context, column='different_column'))


if __name__ == '__main__':
    unittest.main()
