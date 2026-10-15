"""HomeDepot dryer: original dates, Layer 1 and NULL-only onboarding."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.test import override_settings
from apps.common import costco_layer2 as policy, sea_layer2
from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer1.retail import retail_services as retail, retail_repositories as repo, homedepot_dryer
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.dashboard import collection_services as dday
from apps.dx.dx_layer1.management.commands import setup_homedepot_dryer as setup
from apps.dx.dx_layer2 import null_review_state
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs, db_rows
from tests.unit.test_layer2_sea_format_duplicate import common_stubs as anomaly_stubs
from tests.unit import test_layer2_sea_data_edit as edit_tests

TABLE = 'public.ldy_dryer_retail'
CATEGORY = 'sea_ldy_dryer_retail'
DAY = date(2026, 10, 16)


class HomeDepotDryerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        fields = (*sea_layer2.homedepot_null_columns('ldy_dryer'), 'loading_type', 'savings', 'original_sku_price')
        config = [dict(db_rows()[0], table_name=TABLE, date_column='crawl_datetime',
                       category=CATEGORY, check_name='homedepot_sea_ldy_dryer',
                       group_display_name='HomeDepot', check_column=f) for f in fields]
        stubs['apps.common.db'].execute_dx_query = lambda *_: config
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py', 'homedepot_dryer_null_test', stubs)
        cls.dup = load_module('apps/dx/dx_layer2/anomaly_validation/services.py', 'homedepot_dryer_dup_test', anomaly_stubs())
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_launch_and_counts_do_not_add_main_and_bsr(self):
        cursor = ScriptedCursor([])
        self.assertIsNone(repo.get_latest_appliance_main_batch(cursor, TABLE, 'crawl_datetime', '2026-10-14', 'HomeDepot'))
        self.assertFalse(cursor.calls)
        cursor = ScriptedCursor([{'fetchone': ('h1',)}, {'fetchone': (268, 100, 0, 268)}])
        self.assertEqual((268, 100, 0, 268, 'h1'), repo.query_appliance_counts_by_retailer(cursor, TABLE, 'crawl_datetime', '2026-10-15', 'HomeDepot'))
        for sql, params in cursor.calls:
            self.assertNotIn('page_type', sql)
            self.assertNotIn('AT TIME ZONE', sql)
            self.assertIn('HomeDepot', params)
        source = retail._get_layer1_source('LDY_DRYER')
        with patch.object(retail, '_matching_schedule_slots', return_value=[]), patch.object(
                retail, '_source_rows', return_value=[('HomeDepot', 268, 268, 100, 0, 'h1')]):
            category, _, _ = retail._build_category(Mock(), source, DAY, datetime(2026, 10, 16, tzinfo=KST))
            before, _, _ = retail._build_category(Mock(), source, date(2026, 10, 15), datetime(2026, 10, 15, tzinfo=KST))
        home = next(r for r in category['time_slots'][0]['retailers'] if r['retailer'] == 'HomeDepot')
        self.assertEqual(268, home['count'])
        self.assertIsNone(home['criteria'])
        self.assertEqual('complete', home['collection_phase'])
        self.assertNotIn('HomeDepot', [r['retailer'] for r in before['time_slots'][0]['retailers']])
        normalized = next(r for r in calc.normalize_check({'categories': [category]}, 'SEA', DAY) if r['retailer'] == 'HomeDepot')
        self.assertEqual('2026-10-15', normalized['active_from'])
        self.assertEqual('db_original', normalized['source_date_basis'])
        self.assertTrue(calc.variable_bsr(normalized, 'SEA'))
        self.assertFalse(calc.exact_bsr(normalized, 'SEA'))

    def test_column_statistics_use_latest_batch_and_d1_completion(self):
        source = columns.select_source('SEA', 'LDY_DRYER', 'HomeDepot')
        retailer = next(r for r in source['retailers'] if r['name'] == 'HomeDepot')
        sql, params = columns.query_spec(source, retailer, ['sku', 'capacity'], date(2026, 10, 1), date(2026, 10, 15))
        self.assertIn('2026-10-15', params)
        self.assertIn('chosen_batch', sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertFalse(collection_complete('SEA', 'LDY_DRYER', 'HomeDepot', date(2026, 10, 15), datetime(2026, 10, 15, 23, tzinfo=KST)))
        self.assertTrue(homedepot_dryer.complete('2026-10-15', datetime(2026, 10, 16, tzinfo=KST)))

    def test_same_day_receipt_card_starts_on_original_collection_date(self):
        @contextmanager
        def connection():
            yield Mock(), Mock()
        with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection', return_value=(268, '2026-10-15 13:00:07', 'h1', 268, 100)):
            before = dday.get_collection_status(date(2026, 10, 14))
            current = dday.get_collection_status(date(2026, 10, 15))
        self.assertFalse(any(homedepot_dryer.matches(r['product'], r['retailer']) for r in before['retailers']))
        home = next(r for r in current['retailers'] if homedepot_dryer.matches(r['product'], r['retailer']))
        self.assertEqual('2026-10-15', home['source_date'])
        self.assertEqual(268, home['count'])
        self.assertEqual('received', home['status'])
        self.assertEqual('2026-10-15T13:00:00+09:00', home['scheduled_at'])

    def test_null_fields_match_ldy_with_capacity_mapping(self):
        fields = self.null.load_null_check_config()[CATEGORY]['checks']['homedepot']['columns']
        expected = {'capacity' if f == 'ldy_capacity' else f for f in sea_layer2.homedepot_null_columns('ldy')}
        self.assertEqual(expected, set(fields))
        self.assertEqual(11, len(fields))
        for value in ('0', 0, '0.0'):
            self.assertFalse(self.null._is_field_null(value, 'both'))
        for value in (None, '', '  '):
            self.assertTrue(self.null._is_field_null(value, 'both'))

    def test_null_dates_preserve_offset_date_and_launch_gate(self):
        raw = '2026-10-15T23:37:34-04:00'
        row = policy.annotate_source_date({'account_name': 'HomeDepot', 'crawl_datetime': raw})
        self.assertEqual('2026-10-15', row['_source_date'])
        self.assertEqual(raw, row['crawl_datetime'])
        self.assertEqual('2026-10-15', source_date_value(raw))
        source = self.null.SEA_RETAIL_SOURCES['ldy_dryer']
        cursor = ScriptedCursor([])
        self.assertIsNone(self.null._get_sea_null_anchor_batch(cursor, source, '2026-10-14', 'HomeDepot'))
        self.assertFalse(cursor.calls)
        sql, retailers = self.null._build_sea_latest_batch_record_query(source, 'capacity')
        self.assertIn('2026-10-15', sql)
        self.assertIn('homedepot', retailers)
        self.assertNotIn('crawl_strdatetime', sql)
        self.assertNotIn('page_type', sql)

    def test_null_detail_history_uses_real_dryer_columns(self):
        row = dict(id=42, account_name='HomeDepot', country='SEA', item='123', sku='D1',
                   capacity=None, retailer_sku_name='Dryer', product_url='https://www.homedepot.com/p/123',
                   crawl_datetime='2026-10-15T04:00:07+00:00', batch_id='h1')
        cursor = ScriptedCursor([{'fetchone': ('h1',)},
                                {'description': [(k,) for k in row], 'fetchall': [tuple(row.values())]},
                                {}, {}, {}, {}, {}])
        contract = dict(inspection_date=str(DAY), source_date='2026-10-15', offset_days=-1, source_key='sea_ldy_dryer')
        with patch.object(self.null, 'get_editable_columns', return_value=['capacity', 'sku']), patch.object(self.null, 'resolve_monitoring_date', return_value=contract):
            result = self.null.get_null_detail(cursor, DAY, CATEGORY, 'HomeDepot', 3, 'capacity')
        self.assertEqual(1, result['raw_null_count'])
        queries = '\n'.join(sql for sql, _ in cursor.calls)
        self.assertIn('latest_batches', queries)
        self.assertNotIn('page_type', queries)
        self.assertNotIn('ldy_dryer_capacity', queries)

    def test_null_review_and_edit_keep_retailer_scope(self):
        cursor = ScriptedCursor([{'fetchone': (None, 'HomeDepot', '123')},
                                {'fetchone': (42, '123', 'Dryer', None, 'HomeDepot')},
                                {'fetchone': None}, {'fetchone': (101,)}])
        with patch.object(self.null, 'datetime', wraps=datetime) as clock, patch.object(null_review_state.null_review_evidence, 'save_manual_evidence', return_value={'auto_eligible': True}) as saved:
            clock.now.return_value = datetime(2026, 10, 16, tzinfo=KST)
            result = self.null.save_null_review(cursor, Mock(), TABLE, 42, 'capacity', 'normal', 'checked', 'checked', str(DAY), 'null', 'tester')
        self.assertTrue(result.get('success'), result)
        self.assertEqual('HomeDepot', saved.call_args.kwargs['retailer'])
        for field in ('capacity', 'sku'):
            cursor = ScriptedCursor([{'fetchone': (None, 'HomeDepot', '123')}, {}, {}])
            with patch.object(self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-15'}):
                result = self.edit.update_cell_value(cursor, Mock(), TABLE, 42, field, 'value', DAY, 'null', 'tester', 'fixed')
            self.assertTrue(result.get('success'), result)

    def test_duplicate_rollout_does_not_enable_other_dryer_format_policies(self):
        self.assertNotIn('HomeDepot', policy.dryer_source()['retailers'])
        self.assertIn('HomeDepot', self.dup.SEA_RETAIL_SOURCES['ldy_dryer']['retailers'])
        self.assertNotIn('ldy_dryer', policy.FORMAT_COLUMNS)

    @override_settings(DEBUG=True)
    def test_registration_is_null_only_and_transaction_checked(self):
        sql = setup.registration_sql()
        self.assertIn('public.test_monitoring_null_column', sql)
        self.assertNotIn('public.monitoring_null_column', sql)
        self.assertNotIn('SET duplicate_key', sql)
        self.assertNotIn('UPDATE public.ldy_dryer_retail', sql)
        self.assertNotIn('BEGIN;', sql)
        conn, cursor = Mock(), Mock()
        cursor.fetchall.return_value = [('LDY_DRYER', 11)]
        @contextmanager
        def connection():
            yield conn, cursor
        with patch.object(setup, 'dx_connection', connection):
            setup.Command().handle()
        conn.commit.assert_called_once()
