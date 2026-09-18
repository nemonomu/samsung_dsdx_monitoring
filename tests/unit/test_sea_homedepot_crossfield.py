import re
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from apps.common.sea_dates import appliance_source_date_value
from tests.unit.support import ScriptedCursor
from tests.unit.test_layer3_sea_crossfield import sea_services, _bestbuy_row, _rule
from tests.unit.test_layer3_sea_data_edit import services as edit_services, FakeConnection


def homedepot_row(**overrides):
    row = _bestbuy_row(account_name='HomeDepot', page_type=None, item='HD1',
                       batch_id='h20260918_015939', crawl_strdatetime='2026-09-18T01:59:39+00:00',
                       final_sku_price='$1,699.00', original_sku_price='$1,899.00',
                       savings='$200.00 (11%)', detailed_review_content=None, recommendation_intent=None)
    row.update(overrides)
    return row


class HomeDepotCrossfieldTests(unittest.TestCase):
    def setUp(self):
        self.exclusions = patch.object(sea_services, 'exclude_page_absent_records',
                                       side_effect=lambda cursor, day, rows, **kw: (rows, []))
        self.exclusions.start()
        self.addCleanup(self.exclusions.stop)

    def test_seed_and_runtime_enable_exactly_seven_rules_per_product(self):
        sql = (Path(__file__).resolve().parents[2] / 'sql/setup_sea_homedepot_crossfield.sql').read_text(encoding='utf-8')
        keys = re.findall(r"\('HomeDepot', '([a-z_0-9]+)',", sql)
        self.assertEqual(7, len(keys))
        self.assertEqual(sea_services.HOMEDEPOT_RULE_KEYS, set(keys))
        for product in ('sea_ref', 'sea_ldy'):
            rules = [_rule(i, key, 'HomeDepot', product) for i, key in enumerate(keys, 1)]
            cursor = ScriptedCursor([{'fetchall': rules}, {'fetchall': [homedepot_row()]}, {'fetchall': []}])
            result = sea_services.get_sea_cross_field_summary(cursor, date(2026, 9, 18), product)
            self.assertEqual(7, len(result['rule_summary']))
            self.assertEqual(0, result['total_anomalies'])
            self.assertEqual(['HomeDepot'], [r['retailer'] for r in result['retailers']])
            self.assertEqual(7, len(result['retailers'][0]['rules']))
            self.assertEqual('2026-09-17', result['source_date'])

    def test_excluded_rules_do_not_apply_even_if_configured(self):
        excluded = ['discount_rate_90', 'rank_page_type', 'review_body_count', 'recommendation_intent']
        cursor = ScriptedCursor([{'fetchall': [_rule(i, key, 'HomeDepot') for i, key in enumerate(excluded)]}])
        self.assertEqual([], sea_services.load_active_sea_rules(cursor, 'sea_ref'))
        errors = sea_services.evaluate_sea_row(homedepot_row(
            final_sku_price='$10.00', original_sku_price='$1,000.00', savings='$990.00 (99%)',
            page_type='main', main_rank=None))
        self.assertEqual(set(), errors)

    def test_each_enabled_relationship_detects_an_error(self):
        cases = {
            'review_count_match': {'count_of_reviews': '3', 'count_of_star_ratings': '2'},
            'rating_count_presence': {'star_rating': '0', 'count_of_reviews': '2', 'count_of_star_ratings': '2'},
            'final_original_price': {'final_sku_price': '$1,899.00'},
            'savings_missing': {'savings': None},
            'original_missing': {'original_sku_price': None},
            'savings_amount_match': {'savings': '$200.01 (11%)'},
            'final_missing': {'final_sku_price': None},
        }
        for key, values in cases.items():
            with self.subTest(rule=key):
                self.assertIn(key, sea_services.evaluate_sea_row(homedepot_row(**values)))

    def test_discount_amount_is_exact_and_display_percentage_is_not_an_eighth_rule(self):
        self.assertEqual(Decimal('200.00'), sea_services.parse_sea_savings('$200.00 (11%)', 'HomeDepot'))
        self.assertEqual(set(), sea_services.evaluate_sea_row(homedepot_row(savings='$200.00 (10%)')))
        self.assertEqual(set(), sea_services.evaluate_sea_row(homedepot_row(
            final_sku_price='$764.10', original_sku_price='$849.00', savings='$84.90 (10%)')))
        self.assertIn('savings_amount_match', sea_services.evaluate_sea_row(homedepot_row(
            final_sku_price='$764.10', original_sku_price='$849.00', savings='$84.91 (10%)')))
        self.assertIsNone(sea_services.parse_sea_savings('invalid', 'HomeDepot'))
        self.assertEqual(Decimal('200'), sea_services.parse_sea_savings('$200', 'Bestbuy'))

    def test_home_depot_case_is_preserved_for_edit_configuration(self):
        self.assertEqual('HomeDepot', sea_services._retailer_name(' HOMEDEPOT '))
        self.assertEqual(set(), sea_services.evaluate_sea_row(homedepot_row(account_name='homedepot')))

    def test_query_uses_new_york_date_and_includes_null_page_type(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        sea_services.load_latest_sea_rows(cursor, date(2026, 9, 18), 'sea_ref', from_date=date(2026, 9, 16))
        sql, params = cursor.calls[0]
        self.assertIn('America/New_York', sql)
        self.assertIn("IN ('bestbuy', 'lowes', 'homedepot')", sql)
        self.assertIn("LOWER(TRIM(account_name)) = 'homedepot' OR", sql)
        self.assertIn('anchor.batch_id = source.batch_id', sql)
        self.assertIn('anchor.batch_rank = 1', sql)
        self.assertEqual(('2026-09-15', '2026-09-17') * 2, params)

    def test_history_uses_ny_dates_and_only_current_findings(self):
        rows = [homedepot_row(id=9, crawl_strdatetime='2026-09-17T01:59:39+00:00'),
                homedepot_row(id=10, savings='$201.00 (11%)')]
        cursor = ScriptedCursor([{'fetchall': [_rule(1, 'savings_amount_match', 'HomeDepot')]},
                                 {'fetchall': rows}, {'fetchall': []}])
        result = sea_services.get_sea_cross_field_rule_detail(cursor, date(2026, 9, 18), 'sea_ref', 1, days=3)
        self.assertTrue(result['found'])
        self.assertEqual(1, result['total_anomalies'])
        anomalies = result['anomalies']
        self.assertEqual(['comparison_history', 'target'], [row['row_role'] for row in anomalies])
        self.assertEqual(['2026-09-16', '2026-09-17'], [row['row_source_date'] for row in anomalies])
        self.assertIn('HomeDepot', result['retailer_columns'])
        self.assertIn('America/New_York', result['query'])

    def test_new_york_boundary_and_non_homedepot_text_dates(self):
        self.assertEqual('2026-09-17', appliance_source_date_value(homedepot_row()))
        self.assertEqual('2026-01-17', appliance_source_date_value(homedepot_row(crawl_strdatetime='2026-01-18T04:59:59Z')))
        self.assertEqual('2026-09-18', appliance_source_date_value(homedepot_row(crawl_strdatetime='2026-09-18T04:00:00Z')))
        self.assertEqual('2026-08-30', appliance_source_date_value(_bestbuy_row()))

    def test_copy_query_uses_selected_inspection_date_latest_batches_and_escapes_items(self):
        query = sea_services.build_sea_display_query(date(2026, 9, 18), 'sea_ldy',
                    dict(rule_key='savings_amount_match'), days=3, retailer='HomeDepot',
                    retailer_item_pairs=[('HomeDepot', "item'1")])
        self.assertIn('America/New_York', query)
        self.assertIn("BETWEEN '2026-09-15' AND '2026-09-17'", query)
        self.assertIn('latest_batches', query)
        self.assertIn("item IN ('item''1')", query)
        self.assertNotIn('CURRENT_DATE', query)

    def test_normal_confirmation_suppresses_the_same_home_depot_rule(self):
        cursor = ScriptedCursor([{'fetchall': [_rule(1, 'savings_amount_match', 'HomeDepot')]},
                                 {'fetchall': [homedepot_row(savings='$201.00 (11%)')]},
                                 {'fetchall': [dict(record_id=10, column_name='savings', memo='', reason='',
                                                   created_id='tester', created_at='', rule_id=1)]}])
        result = sea_services.get_sea_cross_field_summary(cursor, date(2026, 9, 18), 'sea_ref')
        self.assertEqual(0, result['total_anomalies'])

    def test_value_edit_and_normal_review_keep_the_same_d_minus_one_batch_scope(self):
        conn = FakeConnection()
        cursor = ScriptedCursor([{'fetchone': ('$201.00 (11%)', None, 'HomeDepot', 'HD1')}, {}, {}])
        with patch.object(edit_services, 'get_editable_columns', return_value=['savings']):
            result = edit_services.update_cell_value(cursor, conn, 'public.ref_retail_com', 10, 'savings',
                                                     '$200.00 (11%)', '2026-09-18', 'cross_field', 'tester', '', 1)
        self.assertTrue(result['success'])
        self.assertIn('America/New_York', cursor.calls[0][0])
        self.assertIn("LOWER(TRIM(source.account_name)) = 'homedepot' OR", cursor.calls[0][0])
        self.assertEqual((10, '2026-09-17', '2026-09-17'), cursor.calls[0][1])
        cursor = ScriptedCursor([{'fetchone': ('$200.00 (11%)', 'HomeDepot', 'HD1')}, {'fetchone': None}, {}])
        result = edit_services.save_review(cursor, FakeConnection(), 'public.ldy_retail_com', 10, 'savings',
                                           'normal', 'checked', 'reason', '2026-09-18', 'cross_field', 'tester', 1)
        self.assertTrue(result['success'])
        self.assertIn('America/New_York', cursor.calls[0][0])
        self.assertEqual((10, '2026-09-17', '2026-09-17'), cursor.calls[0][1])


if __name__ == '__main__':
    unittest.main()
