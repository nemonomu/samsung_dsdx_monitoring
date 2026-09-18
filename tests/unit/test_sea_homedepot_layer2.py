import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common import sea_layer2 as policy
from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_null_validation import common_stubs as null_stubs, db_rows
from tests.unit.test_layer2_sea_format_duplicate import common_stubs as format_stubs


class HomeDepotLayer2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = null_stubs()
        rows = db_rows()
        for product in ('ref', 'ldy'):
            sample = next(r for r in rows if r['table_name'] == product + '_retail_com')
            rows.extend(dict(sample, check_name='homedepot_' + product,
                             group_display_name='HomeDepot', check_column=column)
                        for column in (*policy.homedepot_null_columns(product), 'savings'))
        stubs['apps.common.db'].execute_dx_query = lambda *_: rows
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py',
                              'homedepot_null_under_test', stubs)
        cls.format = load_module('apps/dx/dx_layer2/format_validation/services.py',
                                'homedepot_format_under_test', format_stubs())
        seed = (Path(__file__).resolve().parents[2] / 'sql/setup_sea_homedepot_layer2.sql').read_text(encoding='utf-8')
        patterns = dict(re.findall(r"\('(SEA_HOMEDEPOT_\w+)', 'regex',\s*\$pattern\$(.*?)\$pattern\$", seed, re.S))
        fields = {'final_sku_price': 'USD', 'original_sku_price': 'USD',
                  'savings': 'SAVINGS', 'count_of_reviews': 'COUNT',
                  'count_of_star_ratings': 'COUNT', 'ref_capacity': 'CAPACITY',
                  'ldy_capacity': 'CAPACITY', 'calendar_week': 'WEEK'}
        rules = []
        for product in ('ref', 'ldy'):
            for field in policy.homedepot_format_columns(product):
                enum_values = {'account_name': 'HomeDepot', 'country': 'SEA', 'product': product.upper()}
                rule_type = ('enum' if field in enum_values else
                             'range_float' if field == 'star_rating' else 'regex')
                rules.append(dict(table_name=product + '_retail_com', column_name=field,
                                  account_name='HomeDepot', check_type=rule_type,
                                  pattern=patterns['SEA_HOMEDEPOT_' + fields[field]] if rule_type == 'regex' else None,
                                  rule_value=enum_values.get(field, '0~5' if field == 'star_rating' else None), error_message='invalid'))
        cls.validator = load_module('apps/common/retail_columns.py', 'homedepot_validator_under_test', {
            'apps.common.db': module_stub('apps.common.db', execute_dx_query=lambda *_: rules, dx_table=lambda n: n),
            'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
        })

    def test_rollout_does_not_mutate_shared_sources_or_tv(self):
        base = {'ref': {'retailers': ('Lowes',)}, 'ldy': {'retailers': ('Bestbuy',)},
                'tv': {'retailers': ('Amazon',)}}
        result = policy.layer2_sources(base)
        self.assertEqual(('Lowes',), base['ref']['retailers'])
        self.assertEqual(('Lowes', 'HomeDepot'), result['ref']['retailers'])
        self.assertNotIn('HomeDepot', result['tv']['retailers'])
        self.assertEqual(result, policy.layer2_sources(result))

    def test_null_config_has_eleven_fields_and_excludes_optional_savings(self):
        config = self.null.load_null_check_config()
        for product in ('ref', 'ldy'):
            columns = config['sea_' + product + '_retail']['checks']['homedepot']['columns']
            self.assertEqual(set(policy.homedepot_null_columns(product)), set(columns))
            self.assertEqual(11, len(columns))
            self.assertNotIn('savings', columns)

    def test_new_york_date_metadata_leaves_raw_timestamp_intact(self):
        for timestamp, expected in [('2026-09-18T01:59:39+00:00', '2026-09-17'),
                                    ('2026-09-18T04:00:00+00:00', '2026-09-18'),
                                    ('2026-01-18T04:59:59+00:00', '2026-01-17')]:
            row = policy.annotate_source_date({'account_name': 'HomeDepot', 'crawl_strdatetime': timestamp})
            self.assertEqual(expected, row['_source_date'])
            self.assertEqual(timestamp, row['crawl_strdatetime'])
        self.assertNotIn('_source_date', policy.annotate_source_date({'account_name': 'Lowes', 'crawl_strdatetime': '2026-09-17'}))

    def test_null_scope_uses_ny_latest_batch_without_page_type_requirement(self):
        source = self.null.SEA_RETAIL_SOURCES['ref']
        cursor = ScriptedCursor([{'fetchone': ('h20260918',)}])
        self.assertEqual('h20260918', self.null._get_sea_null_anchor_batch(cursor, source, '2026-09-22', 'HomeDepot'))
        sql, params = cursor.calls[0]
        self.assertIn('America/New_York', sql)
        self.assertNotIn('page_type', sql)
        self.assertEqual(('2026-09-22', 'HomeDepot'), params)
        scope, params = self.null._build_sea_null_scope(source, '2026-09-22', 'HomeDepot', 'h20260918')
        self.assertIn('America/New_York', scope)
        self.assertNotIn('page_type', scope)
        self.assertIn('batch_id = %s', scope)
        self.assertEqual(['2026-09-22', 'HomeDepot', 'h20260918'], params)

    def test_format_fetch_has_eleven_fields_and_no_main_anchor_for_homedepot(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        self.format._fetch_sea_format_rows(cursor, date(2026, 9, 20), date(2026, 9, 22),
                                           self.format.SEA_RETAIL_SOURCES['ldy'], 'HomeDepot')
        sql, params = cursor.calls[0]
        self.assertIn('America/New_York', sql)
        self.assertNotIn("= 'MAIN'", sql)
        self.assertNotIn("IN ('MAIN', 'BSR')", sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertEqual(11, len(self.format._get_sea_format_fields('ldy', 'HomeDepot')))
        for field in ('account_name', 'calendar_week', 'country', 'product'):
            self.assertIn('source.' + field, sql)
        self.assertNotIn("COALESCE(source.country", sql)
        self.assertIn('source.ldy_capacity', sql)
        self.assertEqual(('2026-09-20', '2026-09-22', 'HomeDepot') * 2, params)

    def test_format_rules_validate_actual_shapes_and_reject_malformed_values(self):
        cases = {'final_sku_price': (['$1,249.00', '$0.00'], ['1249.00', '$1,24.00', '$-1']),
                 'savings': (['$150.00 (11%)'], ['$150.00 (101%)', '11%']),
                 'star_rating': (['0.0', '5.0'], ['5.1', '-1', 'abc']),
                 'count_of_reviews': (['0', '1,234'], ['-1', '2.5', '1,23']),
                 'ref_capacity': (['21 cu ft', '0.75 cu ft'], ['21 L', '-1 cu ft'])}
        cases.update({
            'account_name': (['HomeDepot'], ['Homepro', 'homedepot']),
            'country': (['SEA'], ['SEM', 'USA']),
            'product': (['REF'], ['LDY', 'ref']),
            'calendar_week': (['2026-W38', '2026-W01', '2026-W53'],
                              ['w38', '2026-W00', '2026-W54', '2026-W1', '2026-w38']),
        })
        for field, (valid, invalid) in cases.items():
            for value in valid:
                self.assertIsNone(self.validator.validate_field('ref_retail_com', field, value, 'HomeDepot'), (field, value))
            for value in invalid:
                self.assertIsNotNone(self.validator.validate_field('ref_retail_com', field, value, 'HomeDepot'), (field, value))
        for field in ('savings', 'original_sku_price'):
            for value in (None, '', ' '):
                self.assertIsNone(self.validator.validate_field('ref_retail_com', field, value, 'HomeDepot'))
        self.assertIsNone(self.validator.validate_field('ref_retail_com', 'ref_capacity', '6 Liter', 'Lowes'))
        self.assertIsNone(self.validator.validate_field('ldy_retail_com', 'product', 'LDY', 'HomeDepot'))
        self.assertIsNotNone(self.validator.validate_field('ldy_retail_com', 'product', 'REF', 'HomeDepot'))

    def test_identity_errors_reach_field_counts_and_review_allowlist(self):
        row = {'id': 42, 'account_name': 'homedepot', 'country': 'SEM', 'product': 'REF',
               'calendar_week': 'w38', 'item': '123', 'crawl_strdatetime': '2026-09-01T01:59:39+00:00'}
        fields = ('account_name', 'calendar_week', 'country', 'product')
        with patch.object(self.format, '_fetch_sea_format_rows', return_value=[row]), \
             patch.object(self.format, '_load_sea_format_normal_reviews', return_value={}), \
             patch.object(self.format, 'validate_field', self.validator.validate_field):
            result = self.format.get_format_detail(Mock(), date(2026, 9, 1), 'sea_ldy_retail', 'HomeDepot', 1)
        self.assertEqual(dict.fromkeys(fields, 1), result['field_counts'])
        for field in fields:
            cursor = ScriptedCursor([{'fetchone': ('invalid', 'HomeDepot', '123')}, {'fetchone': None}, {'rowcount': 1}])
            result = self.null.save_null_review(cursor, Mock(), 'public.ldy_retail_com', 42, field,
                                                'normal', 'memo', 'reason', '2026-08-31', 'format', 'tester')
            self.assertTrue(result.get('success'), result)

    def test_format_detail_keeps_home_depot_current_utc_row_editable_on_d_minus_one(self):
        row = {'id': 42, 'account_name': 'HomeDepot', 'item': '123',
               'crawl_strdatetime': '2026-09-01T01:59:39+00:00', 'ldy_capacity': 'bad'}
        with patch.object(self.format, '_fetch_sea_format_rows', return_value=[row]), \
             patch.object(self.format, '_load_sea_format_normal_reviews', return_value={}), \
             patch.object(self.format, 'validate_field', self.validator.validate_field):
            result = self.format.get_format_detail(Mock(), date(2026, 9, 1), 'sea_ldy_retail', 'HomeDepot', 3)
        self.assertEqual('2026-08-31', result['editable_date'])
        self.assertEqual('2026-08-31', result['results'][0]['_source_date'])
        self.assertEqual({'ldy_capacity': 1}, result['field_counts'])

    def test_capacity_review_allows_homedepot_but_preserves_lowes_allowlist(self):
        for retailer, allowed in [('HomeDepot', True), ('Lowes', False)]:
            cursor = ScriptedCursor([{'fetchone': (None, retailer, '123')}, {'fetchone': None}, {'rowcount': 1}])
            conn = Mock()
            result = self.null.save_null_review(cursor, conn, 'public.ldy_retail_com', 42, 'ldy_capacity',
                                                'normal', 'memo', 'reason', '2026-08-31', 'null', 'tester')
            self.assertEqual(allowed, bool(result.get('success')))
            if allowed:
                conn.commit.assert_called_once()
                self.assertIn('America/New_York', cursor.calls[0][0])
            else:
                conn.commit.assert_not_called()

    def test_optional_price_can_be_reviewed_only_as_format(self):
        for kind, allowed in [('format', True), ('null', False)]:
            cursor = ScriptedCursor([{'fetchone': ('bad', 'HomeDepot', '123')}, {'fetchone': None}, {'rowcount': 1}])
            result = self.null.save_null_review(cursor, Mock(), 'public.ref_retail_com', 42, 'original_sku_price',
                                                'normal', 'memo', 'reason', '2026-08-31', kind, 'tester')
            self.assertEqual(allowed, bool(result.get('success')), result)

    def test_evidence_capture_uses_same_ny_source_date(self):
        cursor = ScriptedCursor([{'fetchone': (42, '123', 'Washer', None, 'HomeDepot')}])
        evidence = self.null._null_evidence_save_source('public.ldy_retail_com')
        result = self.null._capture_null_review_record(cursor, 'public.ldy_retail_com', 42,
                                                       'ldy_capacity', '2026-09-18', evidence, retailer='HomeDepot')
        self.assertEqual('123', result['item'])
        self.assertIn('America/New_York', cursor.calls[0][0])
        self.assertEqual((42, '2026-09-17'), cursor.calls[0][1])


if __name__ == '__main__':
    unittest.main()
