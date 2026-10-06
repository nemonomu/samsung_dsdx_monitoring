"""Costco format fixtures and latest-batch integration; no live DB or env."""
import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common import costco_layer2 as policy
from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_format_duplicate import common_stubs, SEA_SOURCES, resolve_date
from tests.unit.test_layer2_sea_null_validation import common_stubs as null_stubs
from tests.unit import test_layer2_sea_data_edit as edit_tests


class CostcoFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed = (Path(__file__).resolve().parents[2] / 'sql/setup_costco_format.sql').read_text(encoding='utf-8')
        patterns = dict(re.findall(r"\('(COSTCO_\w+)', 'regex', \$p\$(.*?)\$p\$", seed))
        field_templates = {'calendar_week': 'WEEK', 'screen_size': 'SCREEN',
                           'ref_capacity': 'CAPACITY', 'ldy_capacity': 'CAPACITY',
                           'ref_refrigerator_type': 'REF_TYPE',
                           **{field: 'USD' for field in policy.PRICES},
                           'count_of_reviews': 'COUNT', 'count_of_star_ratings': 'COUNT'}
        rows = []
        for product, fields in policy.FORMAT_COLUMNS.items():
            for field in fields:
                enum = {'account_name': 'Costco', 'country': 'SEA', 'product': product.upper(),
                        'ldy_loading_type': 'Front Load|Top Load'}
                kind = 'enum' if field in enum else 'range_float' if field == 'star_rating' else 'regex'
                rows.append(dict(table_name=product + '_retail_com', column_name=field, account_name='Costco',
                                 check_type=kind, rule_value=enum.get(field, '0~5' if field == 'star_rating' else None),
                                 pattern=patterns['COSTCO_' + field_templates[field]] if kind == 'regex' else None,
                                 error_message='invalid format'))
        cls.validator = load_module('apps/common/retail_columns.py', 'costco_format_validator', {
            'apps.common.db': module_stub('apps.common.db', execute_dx_query=lambda *_: rows, dx_table=lambda name: name),
            'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
        })
        stubs = common_stubs()
        stubs['apps.common.retail_columns'].validate_field = cls.validator.validate_field
        cls.service = load_module('apps/dx/dx_layer2/format_validation/services.py', 'costco_format_service', stubs)
        stubs = null_stubs()
        stubs['apps.common.inspection_dates'].resolve_monitoring_date = resolve_date
        cls.review = load_module('apps/dx/dx_layer2/null_validation/services.py', 'costco_format_review', stubs)
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_formats_accept_observed_values_and_reject_wrong_units_and_types(self):
        cases = {
            'final_sku_price': (['$1,249.99', '$0.00'], ['1249.99', '$1,24.99', '$-1']),
            'savings': (['$300', '$250.00'], ['10%', '$300 (10%)', 'Save 300']),
            'star_rating': (['0', '4.7', '5'], ['-1', '5.1', 'abc']),
            'count_of_reviews': (['0', '1,234'], ['-1', '2.5', '1,23']),
            'calendar_week': (['2026-W40', '2026-W53'], ['2026-W00', '2026-W54', '2026-40']),
            'screen_size': (['55 in.', '120 in.'], ['55 cm', '55']),
            'ref_capacity': (['27 cu.ft.', '26 cu. ft', '22.6 cu ft', '18.0 Cu. Ft.'], ['25 L', '-1 cu. ft.']),
            'ldy_capacity': (['4.5 cu. ft.', '5.3 cu ft.'], ['4.5 kg', 'large']),
            'ldy_loading_type': (['Front Load', 'Top Load'], ['front', 'Side Load']),
            'ref_refrigerator_type': (['French Door', 'Bottom Freezer | French Door', 'French Door | Side-by-Side'],
                                      ['Other', 'French Door | Unknown']),
        }
        for field, (valid, invalid) in cases.items():
            product = 'tv' if field == 'screen_size' else 'ldy' if field.startswith('ldy_') else 'ref'
            for value in valid + [None, '', '  ']:
                self.assertIsNone(self.validator.validate_field(product + '_retail_com', field, value, 'Costco'), (field, value))
            for value in invalid:
                self.assertIsNotNone(self.validator.validate_field(product + '_retail_com', field, value, 'Costco'), (field, value))

    def test_only_approved_fields_are_checked(self):
        self.assertEqual([10, 12, 12], [len(policy.FORMAT_COLUMNS[p]) for p in ('tv', 'ref', 'ldy')])
        for product in policy.FORMAT_COLUMNS:
            self.assertEqual({}, self.service.evaluate_sea_format_row({}, product, 'Costco'))
            self.assertNotIn('detailed_review_content', self.service._get_sea_format_fields(product, 'Costco'))
        errors = self.service.evaluate_sea_format_row({'ldy_loading_type': 'Invalid', 'ldy_capacity': '5 kg'}, 'ldy', 'Costco')
        self.assertEqual({'ldy_loading_type', 'ldy_capacity'}, set(errors))

    def test_tv_uses_utc_crawl_date_latest_batch_and_only_real_columns(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        self.service._fetch_sea_format_rows(cursor, date(2026, 10, 1), date(2026, 10, 5), SEA_SOURCES['tv'], 'Costco')
        sql, params = cursor.calls[0]
        self.assertIn('source.crawl_datetime', sql)
        for missing in ('source.sku', 'source.product,', 'source.page_type', 'crawl_strdatetime'):
            self.assertNotIn(missing, sql)
        self.assertIn('Asia/Seoul', sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertEqual(('2026-10-04', '2026-10-05', 'Costco') * 2, params)

    def test_tv_detail_displays_all_six_metrics_and_prices_in_kst(self):
        row = dict(id=42, account_name='Costco', item='C1', screen_size='wrong',
                   crawl_datetime='2026-10-04T16:00:00+00:00')
        with patch.object(self.service, '_fetch_sea_format_rows', return_value=[row]), \
             patch.object(self.service, '_load_sea_format_normal_reviews', return_value={}):
            result = self.service.get_format_detail(Mock(), date(2026, 10, 6), 'tv_retail', 'Costco', 1)
        self.assertEqual({'screen_size': 1}, result['field_counts'])
        self.assertEqual('2026-10-05', result['source_date'])
        self.assertEqual('2026-10-05 01:00:00', result['results'][0]['crawl_datetime'])
        self.assertTrue(set((*policy.METRICS, *policy.PRICES)) <= set(result['column_names']))
        self.assertEqual(set(policy.FORMAT_COLUMNS['tv']), set(result['editable_cols']))

    def test_format_fields_can_be_edited_and_reviewed_without_expanding_null_policy(self):
        registry = policy.sources(SEA_SOURCES)
        for product, fields in policy.FORMAT_COLUMNS.items():
            for field in fields:
                with patch.object(self.edit, 'SEA_RETAIL_SOURCES', registry), \
                     patch.object(self.edit, 'resolve_monitoring_date', resolve_date):
                    cursor = ScriptedCursor([{'fetchone': ('bad', 'Costco', 'C1')}, {}, {}])
                    result = self.edit.update_cell_value(cursor, Mock(), f'public.{product}_retail_com',
                        42, field, 'fixed', date(2026, 10, 6), 'format', 'tester', '')
                self.assertTrue(result.get('success'), (field, result))
                cursor = ScriptedCursor([{'fetchone': ('bad', 'Costco', 'C1')}, {'fetchone': None}, {}])
                result = self.review.save_null_review(cursor, Mock(), f'public.{product}_retail_com',
                    42, field, 'normal', 'verified', '사이트 확인', '2026-10-06', 'format', 'tester')
                self.assertTrue(result.get('success'), (field, result))
        self.assertNotIn('ldy_loading_type', policy.NULL_COLUMNS['ldy'])
        self.assertNotIn('ref_refrigerator_type', policy.NULL_COLUMNS['ref'])


if __name__ == '__main__':
    unittest.main()
