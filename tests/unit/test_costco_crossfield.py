"""Costco cross-field tests without environment files or live database access."""
import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common import retail_validation
from tests.unit.support import ScriptedCursor
from tests.unit.test_layer3_sea_crossfield import sea_services as service, _bestbuy_row, _rule
from tests.unit.test_layer3_sea_data_edit import services as edits, FakeConnection
from tests.unit import test_layer3_stopped_market_monitoring as dashboard_tests


FIELDS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews',
          'final_sku_price', 'original_sku_price', 'savings')


def row(product='ref', **updates):
    value = _bestbuy_row(account_name='Costco', page_type=None, batch_id='c_20261005',
                        detailed_review_content=None, recommendation_intent=None,
                        crawl_strdatetime='2026-10-04T16:00:00+00:00')
    if product == 'tv':
        value['crawl_datetime'] = value.pop('crawl_strdatetime')
        value.pop('sku')
    value.update(updates)
    return value


def rule(key, product='ref', index=1):
    value = _rule(index, key, 'Costco', 'sea_' + product)
    value.update(table_name=f'public.{product}_retail_com',
                 section_code='tv_retail' if product == 'tv' else f'sea_{product}_retail',
                 date_column='crawl_datetime' if product == 'tv' else 'crawl_strdatetime')
    return value


class CostcoCrossfieldTests(unittest.TestCase):
    def setUp(self):
        self.exclusions = patch.object(service, 'exclude_page_absent_records',
                                        side_effect=lambda cursor, day, rows, **kw: (rows, []))
        self.exclusions.start()
        self.addCleanup(self.exclusions.stop)

    def test_missing_review_body_is_never_a_costco_finding(self):
        self.assertEqual(set(), service.evaluate_sea_row(row()))
        self.assertFalse(service._retailer_supported('review_body_count', 'Costco'))
        self.assertFalse(service._retailer_supported('rank_page_type', 'Costco'))
        self.assertFalse(service._retailer_supported('recommendation_intent', 'Costco'))
        sql = retail_validation.apply_tv_validation_scope(
            'SELECT * FROM tv_retail_com WHERE count_of_reviews > 0', 'tv_retail_com', exclude_costco=True)
        self.assertIn("<> 'costco'", sql)
        self.assertNotIn("<> 'costco'", retail_validation.apply_tv_validation_scope(
            'SELECT * FROM tv_retail_com', 'tv_retail_com'))

    def test_all_seven_rules_detect_their_inconsistent_values(self):
        cases = {'review_count_match': {'count_of_reviews': '3'},
                 'rating_count_presence': {'star_rating': '0'},
                 'final_original_price': {'final_sku_price': '$1,000'},
                 'savings_missing': {'savings': None},
                 'original_missing': {'original_sku_price': None},
                 'final_missing': {'final_sku_price': None},
                 'savings_amount_match': {'savings': '$101'}}
        self.assertEqual(service.HOMEDEPOT_RULE_KEYS, set(cases))
        for key, change in cases.items():
            self.assertIn(key, service.evaluate_sea_row(row(**change)))
        self.assertEqual(set(), service.evaluate_sea_row(row(original_sku_price=None, savings=None)))
        self.assertNotIn('savings_amount_match', service.evaluate_sea_row(
            row(original_sku_price='$1,149.99', final_sku_price='$899.99', savings='$250')))

    def test_three_product_summaries_use_seven_rules_without_review_body(self):
        for product in ('tv', 'ref', 'ldy'):
            rules = [rule(key, product, i) for i, key in enumerate(sorted(service.HOMEDEPOT_RULE_KEYS), 1)]
            rules.append(rule('review_body_count', product, 99))
            cursor = ScriptedCursor([{'fetchall': rules}, {'fetchall': [row(product)]}, {'fetchall': []}])
            result = service.get_sea_cross_field_summary(cursor, date(2026, 10, 6), 'sea_' + product)
            self.assertEqual(7, len(result['rule_summary']))
            self.assertEqual(0, result['total_anomalies'])
            self.assertEqual(1, result['total_checked'])
            sql = cursor.calls[1][0]
            self.assertIn('Asia/Seoul', sql)
            self.assertIn('2026-10-04', sql)
            if product == 'tv':
                self.assertNotIn('crawl_strdatetime', sql)
                self.assertNotIn('page_type', sql)
                self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
            for summary in result['rule_summary']:
                self.assertTrue(set(FIELDS) <= set(summary['select_fields'].split('|')))

    def test_tv_detail_has_kst_history_six_fields_and_one_current_finding(self):
        rows = [row('tv', id=9, crawl_datetime='2026-10-03T16:00:00+00:00'),
                row('tv', savings='$101')]
        cursor = ScriptedCursor([{'fetchall': [rule('savings_amount_match', 'tv')]},
                                 {'fetchall': rows}, {'fetchall': []}])
        result = service.get_sea_cross_field_rule_detail(cursor, date(2026, 10, 6), 'sea_tv', 1, 3)
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(['comparison_history', 'target'], [r['row_role'] for r in result['anomalies']])
        self.assertEqual('2026-10-05 01:00:00', result['anomalies'][1]['crawl_datetime'])
        self.assertEqual(set(FIELDS), set(result['editable_columns']))
        self.assertTrue(set(FIELDS) <= set(result['select_fields'].split('|')))
        self.assertNotIn('sku,', result['queries']['Costco'])
        self.assertIn('Asia/Seoul', result['queries']['Costco'])

    def test_page_absence_excludes_all_crossfield_checks(self):
        cursor = ScriptedCursor([{'fetchall': [rule('savings_amount_match')]},
                                 {'fetchall': [row(savings='$101')]}, {'fetchall': []}])
        with patch.object(service, 'exclude_page_absent_records', return_value=([], [{'record_id': 10}])) as exclude:
            result = service.get_sea_cross_field_summary(cursor, date(2026, 10, 6), 'sea_ref')
        self.assertEqual(0, result['total_anomalies'])
        self.assertEqual('SEA', exclude.call_args.kwargs['country'])
        self.assertEqual([{'record_id': 10}], result['page_exclusions'])

    def test_current_manual_confirmation_suppresses_only_that_rule(self):
        cursor = ScriptedCursor([{'fetchall': [rule('savings_amount_match')]},
                                 {'fetchall': [row(savings='$101')]},
                                 {'fetchall': [dict(record_id=10, column_name='savings', rule_id=1)]}])
        result = service.get_sea_cross_field_summary(cursor, date(2026, 10, 6), 'sea_ref')
        self.assertEqual(0, result['total_anomalies'])
        self.assertEqual('2026-10-06', cursor.calls[-1][1][0])

    def test_tv_edit_is_latest_batch_only_and_missing_row_does_not_write(self):
        cursor = ScriptedCursor([{'fetchone': None}])
        result = edits.update_cell_value(cursor, FakeConnection(), 'public.tv_retail_com',
            42, 'savings', '$100', '2026-10-06', 'cross_field', 'tester', '')
        self.assertEqual(404, result['status'])
        self.assertEqual(1, len(cursor.calls))
        sql, params = cursor.calls[0]
        self.assertIn('ORDER BY anchor.id DESC LIMIT 1', sql)
        self.assertIn('Asia/Seoul', sql)
        self.assertNotIn('crawl_strdatetime', sql)
        self.assertEqual((42, '2026-10-05', '2026-10-05'), params)

    def test_six_fields_edit_and_audit_for_all_products(self):
        for product in ('tv', 'ref', 'ldy'):
            for field in FIELDS:
                cursor = ScriptedCursor([{'fetchone': ('1', None, 'Costco', 'item-1')}, {}, {}])
                with patch.object(edits, 'get_editable_columns', return_value=list(FIELDS)):
                    result = edits.update_cell_value(cursor, FakeConnection(), f'public.{product}_retail_com',
                        42, field, '2', '2026-10-06', 'cross_field', 'tester', 'verified', rule_id=1)
                self.assertTrue(result.get('success'), result)
                self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])
                self.assertEqual((42, '2026-10-05', '2026-10-05'), cursor.calls[0][1])

    def test_tv_dispatch_skips_legacy_costco_rules_and_appends_current_findings(self):
        from apps.dx.dx_layer3.cross_field import sea_services as runtime
        dashboard_tests.Layer3StoppedMarketMonitoringTests.setUpClass()
        dashboard = dashboard_tests.Layer3StoppedMarketMonitoringTests.service
        rules = [dict(rule_id=1, section_code='tv_retail', table_name='tv_retail_com',
                      date_column='crawl_datetime', retailer='ALL'),
                 dict(rule_id=2, section_code='tv_retail', table_name='public.tv_retail_com',
                      date_column='crawl_datetime', retailer='Costco')]
        cursor = Mock()
        with patch.object(dashboard, 'load_crossfield_rules', return_value=rules), \
             patch.object(dashboard, 'load_page_exclusions', return_value=[]), \
             patch.object(dashboard, 'execute_crossfield_query', return_value=(0, [])) as legacy, \
             patch.object(runtime, 'build_sea_crossfield_result', return_value={
                 'rule_results': [dict(rule_id=2, error_count=1)],
                 'total_checked': 88, 'page_exclusions': []}) as costco:
            result = dashboard.validate_crossfield(date(2026, 10, 5), 'tv_retail', cursor=cursor)
        self.assertEqual(1, legacy.call_count)
        costco.assert_called_once_with(cursor, date(2026, 10, 6), 'sea_tv')
        self.assertEqual(1, result['total_errors'])
        self.assertEqual(88, result['costco_total_checked'])
        self.assertEqual('Costco', result['rule_results'][-1]['retailer'])

    def test_seed_enables_exactly_seven_types_and_six_display_fields(self):
        sql = (Path(__file__).resolve().parents[2] / 'sql/setup_costco_crossfield.sql').read_text(encoding='utf-8')
        keys = re.findall(r"\('([a-z_]+)', '[^']+', '[a-z_]+',", sql)
        self.assertEqual(service.HOMEDEPOT_RULE_KEYS, set(keys) - {'tv', 'sea_ref', 'sea_ldy'})
        self.assertIn('|'.join(FIELDS), sql)
        self.assertIn("lower(trim(retailer)) = 'costco'", sql)


if __name__ == '__main__':
    unittest.main()
