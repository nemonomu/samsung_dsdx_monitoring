import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

from apps.common import null_review_evidence as evidence
from apps.dx.dx_layer2 import null_review_state
from tests.unit.support import ScriptedCursor
from tests.unit.test_null_review_integration import captured_evidence, current_record


DAY = date(2026, 9, 12)
CONTEXT = dict(table_name='public.ref_retail_com', country='SEA',
               product_line='REF', retailer='Lowes')
METRICS = ('final_sku_price', 'original_sku_price', 'savings',
           'star_rating', 'count_of_star_ratings', 'count_of_reviews')
COLUMNS = ('sku', 'screen_size', 'model_year', *METRICS)


def record(**changes):
    return current_record(**{**dict.fromkeys(COLUMNS), **changes})


def decision(row, column='sku', reason=evidence.NON_TARGET_REASON, **changes):
    result = captured_evidence(CONTEXT, record=row, column=column, reason=reason)
    result.update(changes)
    return result


def state(rows, decisions, day=DAY, manual=None, columns=COLUMNS, context=CONTEXT):
    with patch.object(evidence, 'load_evidence', return_value=evidence._EvidenceCollection(decisions)):
        return null_review_state.review_state(
            Mock(), day, rows, columns, manual or {}, **context,
            is_null=lambda value, _column: value is None or value == '',
        )


class NonTargetNullReviewTests(unittest.TestCase):
    def test_sem_item_1195391749_inherits_sku_exclusion_for_appliance_fields(self):
        context = dict(table_name='dx_sem.dx_sem_ldy_retail_com', country='SEM',
                       product_line='LDY', retailer='Liverpool')
        previous = record(id=3349, item='1195391749',
                          retailer_sku_name='Lavadora con luz y sonido juego de rol para niños',
                          ldy_capacity=None, ldy_loading_type=None)
        basis = captured_evidence(context, record=previous, column='sku', reason=evidence.NON_TARGET_REASON)
        basis.update(inspection_date=date(2026, 9, 17), auto_apply_from=date(2026, 9, 18),
                     reviewed_at=datetime(2026, 9, 17, 10, 41, tzinfo=evidence.KOREA))
        target = dict(previous, id=3649)
        columns = ['ldy_capacity', 'ldy_loading_type']
        cursor = ScriptedCursor([{'fetchall': [basis]}])
        loaded = evidence.load_evidence(cursor, inspection_date=date(2026, 9, 18),
                                        records=[target], columns=columns, **context)
        sql, params = cursor.calls[0]
        self.assertIn('UNNEST(%s::text[], %s::text[])', sql)
        self.assertNotIn('1195391749', sql)
        self.assertIn(['1195391749'], params)
        reviews, stats, _ = state([target], loaded, day=date(2026, 9, 18), columns=columns, context=context)
        self.assertEqual(2, stats['auto_reviewed_count'])
        for field in columns:
            self.assertEqual('sku', reviews[f'3649_{field}']['source_column'])

    def test_product_exclusion_carries_specs_in_all_six_countries(self):
        for country in evidence.COUNTRIES:
            context = dict(CONTEXT, country=country)
            basis = captured_evidence(context, record=record(), column='sku', reason=evidence.NON_TARGET_REASON)
            reviews, stats, _ = state([record(id=43)], [basis], day=date(2026, 9, 13), context=context)
            self.assertEqual({'43_sku', '43_screen_size', '43_model_year'}, set(reviews))
            self.assertEqual(3, stats['auto_reviewed_count'])

    def test_same_collection_links_specs_but_six_metrics_remain_findings(self):
        row = record()
        basis = decision(row)
        reviews, stats, logs = state([row], [basis])
        self.assertEqual({'42_sku', '42_screen_size', '42_model_year'}, set(reviews))
        self.assertFalse(reviews['42_sku']['auto_applied'])
        self.assertEqual(1, stats['manual_reviewed_count'])
        self.assertEqual(2, stats['auto_reviewed_count'])
        self.assertEqual(6, stats['raw_null_count'] - stats['reviewed_null_count'])
        for entry in logs:
            self.assertEqual(evidence.NON_TARGET_REASON, entry['reason'])
            self.assertEqual('연동 자동확인', entry['application_type'])
            self.assertEqual(basis['correction_id'], entry['correction_id'])
            self.assertEqual('페이지 확인', entry['memo'])
        for column in METRICS:
            self.assertEqual(1, stats['raw_fields_detail'][column])
            self.assertEqual(0, stats['reviewed_fields_detail'][column])

    def test_existing_metric_confirmations_cannot_hide_nulls_today_or_later(self):
        for column in METRICS:
            for value in (None, ''):
                with self.subTest(column=column, value=value):
                    row = record(**{column: value})
                    basis = decision(row, column)
                    legacy = {f'42_{column}': {'reason': evidence.NON_TARGET_REASON}}
                    for day, target in ((DAY, row), (date(2026, 9, 13), dict(row, id=43))):
                        reviews, stats, _ = state([target], [basis], day=day,
                                                  manual=legacy if day == DAY else {}, columns=[column])
                        self.assertEqual({}, reviews)
                        self.assertEqual(1, stats['raw_null_count'])
                        self.assertEqual(0, stats['reviewed_null_count'])
                    reviews, _, _ = state([row], [], manual=legacy, columns=[column])
                    self.assertEqual({}, reviews)

    def test_non_target_carries_across_fields_in_next_collection(self):
        original = record()
        reviews, _, _ = state([record(id=43)], [decision(original)], day=date(2026, 9, 13))
        self.assertEqual({'43_sku', '43_screen_size', '43_model_year'}, set(reviews))
        self.assertTrue(reviews['43_sku']['auto_applied'])
        self.assertNotIn('same_record_applied', reviews['43_sku'])
        self.assertEqual('sku', reviews['43_screen_size']['source_column'])
        self.assertEqual('수집 대상 제외 자동확인', reviews['43_screen_size']['application_type'])

    def test_carry_forward_requires_unchanged_product_and_active_manual_basis(self):
        original = record()
        basis = decision(original)
        for change in ({'item': 'different'}, {'retailer_sku_name': 'changed'},
                       {'item': None}, {'retailer_sku_name': None}):
            reviews, _, _ = state([record(id=43, **change)], [basis], day=date(2026, 9, 13))
            self.assertEqual({}, reviews)
        for change in ({'revoked_at': datetime(2026, 9, 13, 1, tzinfo=evidence.KOREA)},
                       {'reason': '상품페이지 내 항목 부재'},
                       {'auto_apply_from': date(2026, 9, 14)}):
            reviews, _, _ = state([record(id=43)], [dict(basis, **change)],
                                   day=date(2026, 9, 13), columns=['screen_size'])
            self.assertEqual({}, reviews)
        # Do not resurrect an older product exclusion after a newer decision/cancellation.
        for reason in (evidence.NON_TARGET_REASON, '상품페이지 내 항목 부재'):
            newer = dict(basis, id=999, reason=reason,
                         reviewed_at=datetime(2026, 9, 12, 23, tzinfo=evidence.KOREA),
                         revoked_at=datetime(2026, 9, 13, 1, tzinfo=evidence.KOREA))
            reviews, _, _ = state([record(id=43)], [basis, newer],
                                   day=date(2026, 9, 13), columns=['screen_size'])
            self.assertEqual({}, reviews)

    def test_non_target_spec_propagation_cannot_override_revoked_target_or_cross_scope(self):
        original = record()
        basis = decision(original)
        revoked = decision(original, column='screen_size', id=998,
                           revoked_at=datetime(2026, 9, 13, 1, tzinfo=evidence.KOREA))
        reviews, _, _ = state([record(id=43)], [basis, revoked],
                               day=date(2026, 9, 13), columns=['screen_size'])
        self.assertEqual({}, reviews)
        for scope in ({'country': 'SEG'}, {'product_line': 'TV'},
                      {'table_name': 'other'}, {'retailer': 'Bestbuy'}):
            reviews, _, _ = state([record(id=43)], [basis], day=date(2026, 9, 13),
                                   context=dict(CONTEXT, **scope), columns=['screen_size'])
            self.assertEqual({}, reviews)

    def test_metric_based_exclusion_cannot_authorize_other_specifications(self):
        original = record()
        for column in METRICS:
            reviews, _, _ = state([record(id=43)], [decision(original, column)],
                                   day=date(2026, 9, 13), columns=['screen_size'])
            self.assertEqual({}, reviews)

    def test_new_batch_and_other_country_retailer_or_table_do_not_link(self):
        row = record()
        basis = decision(row)
        cases = [dict(rows=[record(id=43)]), dict(context=dict(CONTEXT, country='SEG')),
                 dict(context=dict(CONTEXT, table_name='other')),
                 dict(context=dict(CONTEXT, product_line='TV')),
                 dict(context=dict(CONTEXT, retailer='Bestbuy'))]
        for changes in cases:
            with self.subTest(changes=changes):
                args = dict(rows=[row], decisions=[basis])
                args.update(changes)
                reviews, _, _ = state(**args)
                self.assertEqual({}, reviews)

    def test_preserves_other_manual_reasons_and_page_absence_policy(self):
        row = record()
        manual = {'42_star_rating': {'reason': '해당값 정상 확인'},
                  '42_model_year': {'reason': '상품페이지 내 항목 부재'}}
        reviews, _, _ = state([row], [decision(row)], manual=manual)
        for key, value in manual.items():
            self.assertEqual(value, reviews[key])
        page = decision(row, 'screen_size', reason=evidence.PAGE_ABSENT_REASON, id=102)
        reviews, stats, _ = state([row], [decision(row), page])
        self.assertEqual(9, stats['reviewed_null_count'])
        for column in METRICS:
            self.assertEqual(evidence.PAGE_ABSENT_REASON, reviews[f'42_{column}']['reason'])

    def test_missing_identity_late_confirmation_and_cancellation(self):
        row = record(item=None, retailer_sku_name=None)
        basis = decision(row, reviewed_at=datetime(2026, 9, 15, 10, tzinfo=evidence.KOREA))
        reviews, _, _ = state([row], [basis])
        self.assertTrue(reviews['42_screen_size']['same_record_applied'])
        self.assertFalse(reviews['42_sku']['auto_eligible'])
        basis['revoked_at'] = datetime(2026, 9, 15, 11, tzinfo=evidence.KOREA)
        reviews, stats, logs = state([row], [basis])
        self.assertEqual({}, reviews)
        self.assertEqual(0, stats['reviewed_null_count'])
        self.assertEqual([], logs)

    def test_non_target_decision_does_not_exclude_crossfield_validation(self):
        row = record(account_name='Lowes')
        cursor = ScriptedCursor([{'fetchall': [decision(row)]}])
        included, excluded = evidence.exclude_page_absent_records(
            cursor, DAY, [row], **{key: value for key, value in CONTEXT.items() if key != 'retailer'},
        )
        self.assertEqual([row], included)
        self.assertEqual([], excluded)


if __name__ == '__main__':
    unittest.main()
