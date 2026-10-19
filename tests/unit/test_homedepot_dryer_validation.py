"""Format, duplicate, cross-field and audited detail routing for HomeDepot dryers."""
import re
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import override_settings
from django.core.management.base import CommandError
from apps.common.sea_layer2 import homedepot_format_columns
from apps.dx.dx_layer1.management.commands import setup_homedepot_dryer_validation as setup
from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_format_duplicate import common_stubs
from tests.unit import test_layer2_sea_data_edit as edit_tests
from tests.unit.test_layer3_sea_crossfield import sea_services as cross, _rule
from tests.unit.test_layer3_sea_data_edit import services as cross_edits, FakeConnection

TABLE = 'public.ldy_dryer_retail'
SECTION = 'sea_ldy_dryer_retail'
KEY = 'sea_ldy_dryer'
DAY = date(2026, 10, 16)


def row(**updates):
    value = dict(id=1, country='SEA', account_name='HomeDepot', item='123', sku='D1',
                 retailer_sku_name='Dryer', product_url='https://www.homedepot.com/p/123',
                 batch_id='h1', crawl_datetime='2026-10-15T23:30:00-04:00', calendar_week='2026-W42',
                 capacity='7.4 cu ft', loading_type='Front Load', count_of_reviews='2',
                 count_of_star_ratings='2', star_rating='4.5', final_sku_price='$700.00',
                 original_sku_price='$900.00', savings='$200.00 (22%)', main_rank=1, bsr_rank=1)
    value.update(updates)
    return value


def rules(retailer='HomeDepot', offset=0):
    return [dict(_rule(i, key, retailer, KEY), table_name=TABLE,
                 date_column='crawl_datetime', section_code=SECTION)
            for i, key in enumerate(sorted(cross.HOMEDEPOT_RULE_KEYS), offset + 1)]


class HomeDepotDryerValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed = Path('sql/setup_homedepot_dryer_validation.sql').read_text(encoding='utf-8')
        patterns = dict(re.findall(r"\('SEA_HOMEDEPOT_DRYER_(\w+)', 'regex',\s*\$pattern\$(.*?)\$pattern\$", seed, re.S))
        mapping = {'final_sku_price': 'USD', 'original_sku_price': 'USD', 'savings': 'SAVINGS',
                   'count_of_reviews': 'COUNT', 'count_of_star_ratings': 'COUNT',
                   'capacity': 'CAPACITY', 'calendar_week': 'WEEK'}
        fields = []
        for field in homedepot_format_columns('ldy_dryer'):
            fields.append(dict(table_name='ldy_dryer_retail', column_name=field, account_name='HomeDepot',
                check_type='regex' if field in mapping else 'range_float' if field == 'star_rating' else 'enum',
                pattern=patterns[mapping[field]] if field in mapping else None,
                rule_value={'account_name': 'HomeDepot', 'country': 'SEA', 'star_rating': '0~5'}.get(field),
                error_message='invalid'))
        validator = load_module('apps/common/retail_columns.py', 'dryer_format_validator', {
            'apps.common.db': module_stub('apps.common.db', execute_dx_query=lambda *_: fields, dx_table=lambda n: n),
            'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
        })
        stubs = common_stubs()
        stubs['apps.common.retail_columns'].validate_field = validator.validate_field
        cls.format = load_module('apps/dx/dx_layer2/format_validation/services.py', 'dryer_format_test', stubs)
        cls.dup = load_module('apps/dx/dx_layer2/anomaly_validation/services.py', 'dryer_duplicate_test', common_stubs())
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_ten_fields_and_valid_shapes(self):
        self.assertEqual(10, len(homedepot_format_columns('ldy_dryer')))
        self.assertEqual(('Bestbuy', 'Costco', 'HomeDepot', 'Lowes'),
                         self.format.SEA_RETAIL_SOURCES['ldy_dryer']['retailers'])
        for updates in ({}, dict(original_sku_price=None, savings=None),
                        dict(final_sku_price='$1,249.00', capacity='0.6 cu ft'),
                        dict(star_rating='0.0', count_of_reviews='0', count_of_star_ratings='0')):
            self.assertFalse(self.format.evaluate_sea_format_row(row(**updates), 'ldy_dryer', 'HomeDepot'))

    def test_each_format_rejects_bad_values(self):
        for field, value in dict(account_name='Lowes', country='SIEL', calendar_week='2026-W54',
                                final_sku_price='700', original_sku_price='$1,24.00', savings='$200 (101%)',
                                star_rating='5.1', count_of_reviews='-1', count_of_star_ratings='1.5',
                                capacity='7.4 L').items():
            self.assertIn(field, self.format.evaluate_sea_format_row(row(**{field: value}), 'ldy_dryer', 'HomeDepot'))

    def test_format_query_and_detail_use_actual_schema_latest_batch_original_day(self):
        source = self.format.SEA_RETAIL_SOURCES['ldy_dryer']
        cursor = ScriptedCursor([])
        self.assertFalse(self.format._fetch_sea_format_rows(cursor, '2026-10-13', '2026-10-14', source, 'HomeDepot'))
        self.assertFalse(cursor.calls)
        cursor = ScriptedCursor([{'fetchall': []}])
        self.format._fetch_sea_format_rows(cursor, '2026-10-13', '2026-10-15', source, 'HomeDepot')
        sql, params = cursor.calls[0]
        self.assertEqual(('2026-10-15', '2026-10-15', 'HomeDepot') * 2, params)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertNotIn('source.product,', sql)
        for forbidden in ('page_type', 'crawl_strdatetime', 'AT TIME ZONE', 'ldy_dryer_capacity'):
            self.assertNotIn(forbidden, sql)
        bad = row(capacity='7.4 L')
        with patch.object(self.format, '_fetch_sea_format_rows', return_value=[bad]), patch.object(
                self.format, '_load_sea_format_normal_reviews', return_value={}):
            result = self.format._get_sea_format_detail(Mock(), DAY, SECTION, 'HomeDepot', 1)
        self.assertEqual({'capacity': 1}, result['field_counts'])
        self.assertEqual('2026-10-15', result['source_date'])
        self.assertEqual('2026-10-15', result['results'][0]['_source_date'])
        self.assertEqual(set(homedepot_format_columns('ldy_dryer')), set(result['editable_cols']))
        self.assertNotIn('page_type', result['column_names'])
        self.assertEqual([], self.format._get_sea_format_detail(Mock(), DAY, SECTION, 'Bestbuy', 1)['results'])

    def test_duplicate_item_scope_allows_shared_sku_and_other_batches(self):
        group = lambda rows: self.dup.build_sea_duplicate_groups(rows, 'HomeDepot', 'ldy_dryer')
        self.assertFalse(group([row(), row(id=2, item='456')]))
        self.assertFalse(group([row(), row(id=2, batch_id='h2')]))
        self.assertFalse(group([row(), row(id=2, account_name='Costco')]))
        self.assertEqual('완전 중복', group([row(), row(id=2)])[0]['duplicate_type'])
        self.assertEqual('상품 매핑 충돌', group([row(), row(id=2, sku='D2')])[0]['duplicate_type'])
        source = self.dup.SEA_RETAIL_SOURCES['ldy_dryer']
        cursor = ScriptedCursor([])
        self.assertEqual([], self.dup._fetch_sea_duplicate_rows(cursor, '2026-10-14', source, 'HomeDepot'))
        self.assertFalse(cursor.calls)
        cursor = ScriptedCursor([{'fetchall': []}])
        self.dup._fetch_sea_duplicate_rows(cursor, '2026-10-15', source, 'HomeDepot')
        self.assertNotIn('page_type', cursor.calls[0][0])
        self.assertIn('2026-10-15', cursor.calls[0][0])

    def test_duplicate_detail_includes_copyable_exact_record_query(self):
        with patch.object(self.dup, '_fetch_sea_duplicate_rows', return_value=[row(), row(id=2)]):
            result = self.dup.get_anomaly_detail(Mock(), DAY, SECTION, 'HomeDepot', 1, 1, 50)
        self.assertEqual(1, result['results']['total_groups'])
        self.assertEqual(2, result['query_record_count'])
        self.assertIn('FROM public.ldy_dryer_retail', result['query'])
        self.assertIn('id IN (1, 2)', result['query'])
        self.assertTrue(result['readonly'])
        self.assertNotIn('page_type', result['select_cols']['group'])

    def test_seven_home_depot_relationships(self):
        self.assertFalse(cross.evaluate_sea_row(row(), KEY))
        self.assertFalse(cross.evaluate_sea_row(row(original_sku_price=None, savings=None), KEY))
        self.assertFalse(cross.evaluate_sea_row(row(star_rating='0', count_of_reviews='0', count_of_star_ratings='0'), KEY))
        for expected, updates in {
            'review_count_match': dict(count_of_reviews='3'),
            'rating_count_presence': dict(star_rating='0'),
            'final_original_price': dict(final_sku_price='$900.00'),
            'savings_missing': dict(savings=None),
            'original_missing': dict(original_sku_price=None),
            'final_missing': dict(final_sku_price=None),
            'savings_amount_match': dict(savings='$199.99 (22%)'),
        }.items():
            self.assertIn(expected, cross.evaluate_sea_row(row(**updates), KEY))
        self.assertFalse(cross.evaluate_sea_row(row(savings='$200.00 (21%)'), KEY))

    def test_crossfield_rules_and_queries_keep_retailers_separate(self):
        configured = rules() + rules('Bestbuy', 10) + rules('Costco', 20)
        loaded = cross.load_active_sea_rules(ScriptedCursor([{'fetchall': configured}]), KEY)
        self.assertEqual(21, len(loaded))
        self.assertTrue(all(len(r['_retailers']) == 1 for r in loaded))
        cursor = ScriptedCursor([{'fetchall': []}])
        cross.load_latest_sea_rows(cursor, DAY, KEY)
        self.assertIn("'homedepot'", cursor.calls[0][0])
        self.assertIn('2026-10-15', cursor.calls[0][0])
        self.assertNotIn('page_type', cursor.calls[0][0])

    def test_crossfield_detail_history_and_normal_confirmation(self):
        configured = rules()
        rule_id = next(r['id'] for r in configured if r['validation_type'] == 'savings_amount_match')
        current = row(savings='$199.00 (22%)')
        previous = row(id=2, crawl_datetime='2026-10-14T23:30:00-04:00', batch_id='previous')
        cursor = ScriptedCursor([{'fetchall': configured}, {'fetchall': [previous, current]}, {'fetchall': []}])
        with patch.object(cross, 'exclude_page_absent_records', side_effect=lambda c, d, rows, **kw: (rows, [])):
            result = cross.get_sea_cross_field_rule_detail(cursor, DAY, KEY, rule_id, 3)
        self.assertTrue(result['found'])
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(6, len(result['editable_columns']))
        cursor = ScriptedCursor([{'fetchone': ('$199.00 (22%)', 'HomeDepot', '123')}, {'fetchone': None}, {}])
        result = cross_edits.save_review(cursor, FakeConnection(), TABLE, 1, 'savings', 'normal', 'checked', 'checked', str(DAY), 'cross_field', 'tester', rule_id=rule_id)
        self.assertTrue(result.get('success'), result)

    def test_format_and_crossfield_edits_have_scoped_audit_queries(self):
        for field in ('capacity', 'savings', 'calendar_week'):
            cursor = ScriptedCursor([{'fetchone': ('bad', 'HomeDepot', '123')}, {}, {}])
            with patch.object(self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-15'}):
                result = self.edit.update_cell_value(cursor, Mock(), TABLE, 1, field, 'value', DAY, 'format', 'tester', 'checked')
            self.assertTrue(result.get('success'), result)
            self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])
        cursor = ScriptedCursor([{'fetchone': ('$1', 'h1', 'HomeDepot', '123')}, {}, {}])
        result = cross_edits.update_cell_value(cursor, FakeConnection(), TABLE, 1, 'savings', '$2.00 (1%)', str(DAY), 'cross_field', 'tester', 'checked', rule_id=1)
        self.assertTrue(result.get('success'), result)
        self.assertIn("'homedepot'", cursor.calls[0][0])
        self.assertIn('2026-10-15', cursor.calls[0][0])

    @override_settings(DEBUG=True)
    def test_registration_scope_counts_and_rollback_on_failure(self):
        sql = setup.registration_sql()
        self.assertIn('public.test_monitoring_format_rules', sql)
        self.assertIn('public.monitoring_validation_rules', sql)
        self.assertNotIn('public.test_monitoring_validation_rules', sql)
        self.assertNotIn('UPDATE public.ldy_dryer_retail', sql)
        conn, cursor = Mock(), Mock()
        @contextmanager
        def connection():
            yield conn, cursor
        with patch.object(setup, 'dx_connection', connection):
            cursor.fetchall.return_value = setup.EXPECTED
            setup.Command().handle()
            conn.commit.assert_called_once()
            conn.reset_mock()
            cursor.fetchall.return_value = [('format', 0)]
            with self.assertRaises(CommandError):
                setup.Command().handle()
            conn.commit.assert_not_called()
