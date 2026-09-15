import unittest
from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import Mock, patch

from apps.common import null_review_evidence as evidence
from apps.dx.dx_layer2 import null_review_state
from tests.unit.support import ScriptedCursor
from tests.unit.test_null_review_integration import captured_evidence, current_record


DAY = date(2026, 9, 12)
CONTEXT = dict(table_name='public.ref_retail_com', country='SEA',
               product_line='REF', retailer='Lowes')


def page_evidence(context=CONTEXT, record=None, **changes):
    row = captured_evidence(context, record=record or current_record(),
                            reason=evidence.PAGE_ABSENT_REASON)
    row.update(changes)
    return row


class PageAbsenceNullTests(unittest.TestCase):
    def state(self, records, entries, manual=None, day=DAY, context=CONTEXT):
        with patch.object(evidence, 'load_evidence', return_value=evidence._EvidenceCollection(entries)):
            return null_review_state.review_state(
                Mock(), day, records, ['sku', 'final_sku_price', 'star_rating'],
                manual or {}, **context,
                is_null=lambda value, _column: value is None or value == '',
            )

    def test_one_confirmation_links_other_nulls_and_retains_manual_reason(self):
        record = current_record(final_sku_price=None, star_rating=None)
        original = page_evidence(record=record)
        reviews, stats, logs = self.state([record], [original])
        self.assertFalse(reviews['42_sku']['auto_applied'])
        self.assertEqual(1, stats['manual_reviewed_count'])
        self.assertEqual(2, stats['auto_reviewed_count'])
        for column in ('final_sku_price', 'star_rating'):
            review = reviews[f'42_{column}']
            self.assertTrue(review['same_record_applied'])
            self.assertEqual(evidence.PAGE_ABSENT_REASON, review['reason'])
            self.assertEqual(original['correction_id'], review['correction_id'])
            self.assertEqual('sku', review['source_column'])
            self.assertEqual('페이지 확인', review['memo'])
        self.assertEqual({'연동 자동확인'}, {row['application_type'] for row in logs})
        manual = {'42_star_rating': {'reason': '해당값 정상 확인', 'created_id': 'another'}}
        reviews, stats, _ = self.state([record], [original], manual)
        self.assertEqual(manual['42_star_rating'], reviews['42_star_rating'])
        self.assertEqual(2, stats['manual_reviewed_count'])
        self.assertEqual(1, stats['auto_reviewed_count'])

    def test_record_date_table_country_product_and_retailer_are_boundaries(self):
        record = current_record(final_sku_price=None, star_rating=None)
        original = page_evidence(record=record)
        cases = [dict(records=[dict(record, id=43)]), dict(day=date(2026, 9, 13)),
                 dict(context=dict(CONTEXT, table_name='other_table')),
                 dict(context=dict(CONTEXT, country='SEG')),
                 dict(context=dict(CONTEXT, product_line='LDY')),
                 dict(context=dict(CONTEXT, retailer='Bestbuy'))]
        for changes in cases:
            with self.subTest(changes=changes):
                args = dict(records=[record], entries=[original])
                args.update(changes)
                reviews, stats, _ = self.state(**args)
                self.assertEqual({}, reviews)
                self.assertEqual(0, stats['reviewed_null_count'])

    def test_present_values_are_not_reviewed_and_missing_identity_can_link_exact_row(self):
        record = current_record(item=None, retailer_sku_name=None,
                                final_sku_price='100', star_rating=None)
        reviews, stats, _ = self.state([record], [page_evidence(record=record)])
        self.assertNotIn('42_final_sku_price', reviews)
        self.assertTrue(reviews['42_star_rating']['same_record_applied'])
        self.assertEqual(2, stats['raw_null_count'])

    def test_revocation_restores_linked_findings_and_preserves_other_manual_review(self):
        record = current_record(final_sku_price=None, star_rating=None)
        original = page_evidence(record=record, revoked_at=datetime(2026, 9, 12, 11, tzinfo=evidence.KOREA))
        manual = {'42_star_rating': {'reason': '해당값 정상 확인'}}
        reviews, stats, logs = self.state([record], [original], manual)
        self.assertEqual(manual, reviews)
        self.assertEqual(1, stats['reviewed_null_count'])
        self.assertEqual([], logs)
        included, excluded = evidence.exclude_page_absent_records(
            ScriptedCursor([{'fetchall': [original]}]), DAY, [record],
            **{key: value for key, value in CONTEXT.items() if key != 'retailer'},
        )
        self.assertEqual([record], included)
        self.assertEqual([], excluded)

    def test_other_reasons_remain_field_specific_and_later_manual_decision_wins(self):
        record = current_record(final_sku_price=None, star_rating=None)
        original = page_evidence(record=record)
        for reason in ('상품페이지 내 항목 부재', '수집 대상 제품 아님', '해당값 정상 확인'):
            latest = dict(original, id=102, reason=reason,
                          reviewed_at=datetime(2026, 9, 12, 11, tzinfo=evidence.KOREA))
            reviews, stats, _ = self.state([record], [original, latest])
            self.assertEqual({'42_sku'}, set(reviews))
            self.assertEqual(0, stats['auto_reviewed_count'])

    def test_other_column_is_loaded_even_when_only_one_null_field_is_requested(self):
        original = page_evidence()
        cursor = ScriptedCursor([{'fetchall': [original]}])
        loaded = evidence.load_evidence(
            cursor, inspection_date=DAY, records=[current_record()],
            columns=['star_rating'], **CONTEXT,
        )
        sql, params = cursor.calls[0]
        self.assertIn('column_name = ANY(%s) OR reason = ANY(%s)', sql)
        self.assertEqual(3, params.count(list(evidence.RECORD_REVIEW_REASONS)))
        self.assertIsNotNone(evidence.page_absence_review(current_record(), DAY, loaded, **CONTEXT))

    def test_late_page_confirmation_links_the_selected_inspection_day_only(self):
        record = current_record(final_sku_price=None, star_rating=None)
        original = page_evidence(record=record,
                                 reviewed_at=datetime(2026, 9, 15, 10, tzinfo=evidence.KOREA))
        reviews, stats, _ = self.state([record], [original])
        self.assertFalse(reviews['42_sku']['auto_applied'])
        self.assertEqual(3, stats['reviewed_null_count'])
        reviews, stats, _ = self.state([record], [original], day=date(2026, 9, 15))
        self.assertEqual({}, reviews)
        self.assertEqual(0, stats['reviewed_null_count'])


class PageAbsenceCrossfieldTests(unittest.TestCase):
    def test_country_engines_skip_page_absent_row_before_all_rule_evaluation(self):
        from tests.unit import test_layer3_sea_crossfield as sea
        from tests.unit import test_layer3_siel_crossfield as siel
        from tests.unit import test_layer3_tse_crossfield as tse
        from apps.dx.dx_layer3.cross_field import seg_services as seg
        engines = [
            (sea.sea_services, 'sea', 'sea_ref', sea._bestbuy_row,
             sea.sea_services._source_for_product_line),
            (siel.siel_services, 'siel', 'siel_tv', siel._amazon_row,
             siel.siel_services.get_siel_source),
            (tse.tse_services, 'tse', 'tse_tv', tse._valid_row,
             tse.tse_services.get_tse_source),
            (seg, 'seg', 'seg_tv', lambda **kw: dict(account_name='Amazon', **kw), seg.get_seg_source),
        ]
        for service, country, product, factory, source_for in engines:
            with self.subTest(country=country), ExitStack() as stack:
                source = source_for(product)
                source_day = '2026-09-11' if country == 'sea' else str(DAY)
                record = factory(id=42, item='same', retailer_sku_name='Product A', sku=None,
                                 **{source.get('date_column', 'crawl_datetime'): source_day})
                replacement = dict(record, id=43)
                context = dict(table_name=source['table_name'], country=country.upper(),
                               product_line=product.rsplit('_', 1)[-1].upper(),
                               retailer=record['account_name'])
                original = page_evidence(context, record)
                rule = dict(rule_id=1, rule_key='final_original_price', retailer='ALL',
                            _all_retailers=True,
                            detail_name='price', detail_code='price', error_message='price',
                            field1='final_sku_price', field2='original_sku_price')
                stack.enter_context(patch.object(service, f'load_active_{country}_rules', return_value=[rule]))
                stack.enter_context(patch.object(service, f'load_latest_{country}_rows',
                                                 return_value=[record, replacement]))
                stack.enter_context(patch.object(service, '_load_normal_corrections', return_value=[]))
                evaluate = stack.enter_context(patch.object(service, f'evaluate_{country}_row',
                                                           return_value={'final_original_price'}))
                cursor = ScriptedCursor([{'fetchall': [original]}])
                result = getattr(service, f'build_{country}_crossfield_result')(cursor, DAY, product)
                self.assertEqual(1, result['total_checked'])
                self.assertEqual(1, result['total_anomalies'])
                self.assertEqual([43], [row['id'] for row in result['source_rows']])
                self.assertEqual([42], [entry['record_id'] for entry in result['page_exclusions']])
                evaluate.assert_called_once_with(replacement)

    def test_sem_exclusion_affects_summary_and_detail(self):
        from apps.dx.dx_layer3.cross_field import sem_services as sem
        source = sem.SEM_SOURCE_CONFIG['sem_ref']
        record = current_record(account_name='Liverpool', final_sku_price='100',
                                original_sku_price='100', crawl_datetime=str(DAY))
        context = dict(table_name=source['table_name'], country='SEM', product_line='REF', retailer='Liverpool')
        original = page_evidence(context, record)
        mapping = dict(inspection_date=str(DAY), source_date=str(DAY), offset_days=0)
        def rows(*args, **kwargs):
            return ([] if kwargs.get('retailer') else [record]), mapping
        with patch.object(sem, '_latest_rows', side_effect=rows), patch.object(sem, '_failed_rules') as evaluate:
            cursor = ScriptedCursor([{'fetchall': [original]}])
            summary = sem.get_sem_cross_field_summary(cursor, DAY, 'sem_ref')
            self.assertEqual(0, summary['total_checked'])
            self.assertEqual(0, summary['total_anomalies'])
            self.assertEqual(42, summary['page_exclusions'][0]['record_id'])
            cursor = ScriptedCursor([{'fetchall': [original]}])
            detail = sem.get_sem_cross_field_rule_detail(cursor, DAY, 'sem_ref', 'sem_ref:final_original_price')
            self.assertEqual([], detail['anomalies'])
            evaluate.assert_not_called()

    def test_sql_tv_rules_exclude_source_even_when_select_omits_id(self):
        from apps.dx.dx_layer3.dashboard import services as dashboard
        cursor = Mock()
        cursor.fetchall.return_value = [('other',)]
        cursor.description = [('item',)]
        connection = Mock()
        connection.cursor.return_value = cursor
        rule = dict(rule_id=1, query='SELECT item FROM {table} WHERE DATE({date_col}) = %s')
        with patch.object(dashboard, 'get_dx_connection', return_value=connection), \
                patch.object(dashboard, 'get_all_no_review_texts', return_value=''):
            count, results = dashboard.execute_crossfield_query(
                rule, 'tv_retail_com', 'crawl_datetime', date(2026, 9, 11),
                'tv_retail', [{'record_id': 42}],
            )
        self.assertEqual(1, count)
        self.assertEqual([{'item': 'other'}], results)
        sql, params = cursor.execute.call_args.args
        self.assertTrue(sql.startswith('WITH tv_retail_com AS ('))
        self.assertIn('AND id <> ALL(%s)', sql)
        self.assertEqual(1, sql.count('WITH tv_retail_com AS ('))
        self.assertIn('redirect IS TRUE', sql)
        self.assertEqual(([42], date(2026, 9, 11)), params)


if __name__ == '__main__':
    unittest.main()
