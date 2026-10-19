"""Lowes dryer onboarding: original dates, latest counts and all daily batches."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.test import override_settings
from apps.common import costco_layer2 as policy
from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_value, source_date_sql
from apps.dx.dx_layer1.retail import lowes_dryer, retail_services as retail, retail_repositories as repo
from apps.dx.dx_layer1.common import retail_batches
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, minimum_days
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.management.commands import setup_lowes_dryer as setup
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs, db_rows
from tests.unit import test_layer2_sea_data_edit as edit_tests

TABLE = 'public.ldy_dryer_retail'
CATEGORY = 'sea_ldy_dryer_retail'


class LowesDryerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        fields = (*lowes_dryer.NULL_COLUMNS, 'loading_type', 'savings', 'original_sku_price', 'main_rank', 'bsr_rank')
        config = [dict(db_rows()[0], table_name=TABLE, date_column='crawl_datetime',
                       category=CATEGORY, check_name='lowes_sea_ldy_dryer',
                       group_display_name='Lowes', check_column=f) for f in fields]
        stubs['apps.common.db'].execute_dx_query = lambda *_: config
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py', 'lowes_dryer_null_test', stubs)
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_original_dates_and_launch_are_shared_by_queries_and_reviews(self):
        for raw, expected in [('2026-10-17T23:59:59-04:00', '2026-10-17'),
                              ('2026-10-18T00:00:00+09:00', '2026-10-18')]:
            self.assertEqual(expected, source_date_value(raw))
            row = policy.annotate_source_date({'account_name': 'Lowes', 'crawl_datetime': raw})
            self.assertEqual(expected, row['_source_date'])
            self.assertEqual(raw, row['crawl_datetime'])
        for retailer in ('Lowes', None):
            sql = policy.source_date_sql('crawl_datetime', 'source', retailer, product='ldy_dryer')
            self.assertIn(source_date_sql('source.crawl_datetime'), sql)
            self.assertIn('2026-10-17', sql)
            self.assertNotIn('AT TIME ZONE', sql)
        cursor = ScriptedCursor([])
        self.assertIsNone(repo.get_latest_appliance_main_batch(cursor, TABLE, 'crawl_datetime', '2026-10-16', 'Lowes'))
        self.assertIsNone(self.null._get_sea_null_anchor_batch(cursor, self.null.SEA_RETAIL_SOURCES['ldy_dryer'], '2026-10-16', 'Lowes'))
        self.assertFalse(cursor.calls)

    def test_latest_counts_do_not_add_overlapping_main_and_bsr(self):
        cursor = ScriptedCursor([{'fetchone': ('l_latest',)}, {'fetchone': (213, 89, 0, 217)}])
        self.assertEqual((213, 89, 0, 217, 'l_latest'), repo.query_appliance_counts_by_retailer(
            cursor, TABLE, 'crawl_datetime', '2026-10-18', 'Lowes'))
        sql, params = cursor.calls[-1]
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', sql)
        self.assertEqual(('2026-10-18', 'Lowes', 'l_latest'), params)
        self.assertNotIn('page_type', '\n'.join(q for q, _ in cursor.calls))

    def test_missing_and_d1_completion_start_at_launch(self):
        source = retail._get_layer1_source('LDY_DRYER')
        with patch.object(retail, '_matching_schedule_slots', return_value=[]), patch.object(
                retail, '_source_rows', return_value=[]):
            before, _, _ = retail._build_category(Mock(), source, date(2026, 10, 17), datetime(2026, 10, 19, tzinfo=KST))
            current, _, _ = retail._build_category(Mock(), source, date(2026, 10, 19), datetime(2026, 10, 19, tzinfo=KST))
        self.assertNotIn('Lowes', [r['retailer'] for r in before['time_slots'][0]['retailers']])
        row = next(r for r in current['time_slots'][0]['retailers'] if r['retailer'] == 'Lowes')
        self.assertEqual(('CRITICAL', 'complete', 0), (row['status'], row['collection_phase'], row['count']))
        normalized = next(r for r in calc.normalize_check({'categories': [current]}, 'SEA', date(2026, 10, 19)) if r['retailer'] == 'Lowes')
        self.assertEqual('2026-10-17', normalized['active_from'])
        self.assertEqual('db_original', normalized['source_date_basis'])
        self.assertTrue(calc.variable_bsr(normalized, 'SEA'))
        self.assertFalse(calc.exact_bsr(normalized, 'SEA'))
        received, _, _ = retail.check_retailer_data([('Lowes', 217, 213, 89, 0, 'l1')], 'LDY_DRYER')
        self.assertEqual('OK', next(r for r in received if r['retailer'] == 'Lowes')['status'])

    def test_bsr_observation_then_median_boundaries(self):
        row = dict(product='LDY_DRYER', retailer='Lowes', slot='daily', complete=True,
                   base_status='OK', main=213, bsr=89, total=217, observation_state='observing')
        self.assertEqual(('median_28d', 'observing', None, None), calc._compare_bsr(row, [], 'SEA'))
        row['observation_state'] = 'ready'
        self.assertEqual('insufficient', calc._compare_bsr(row, [], 'SEA')[1])
        history = [dict(row, source_date=f'2026-10-{d}', bsr=100) for d in range(17, 22)]
        for count, expected in [(89, None), (85, 'VOLUME_REVIEW'), (81, 'VOLUME_REVIEW'), (80, 'VOLUME_LOW')]:
            alert = calc._compare_bsr(dict(row, bsr=count), history, 'SEA')[3]
            self.assertEqual(expected, alert['status'] if alert else None)

    def test_two_batches_are_visible_without_page_type(self):
        cursor = Mock()
        cursor.fetchall.return_value = [('l_old', 't1', 't1', 233, 89, False, 237),
                                       ('l_new', 't2', 't2', 213, 89, True, 217)]
        cursor.mogrify.return_value = b'SELECT *;'
        result = retail_batches.fetch_batch_details(cursor, 'retail', 'ldy_dryer', '2026-10-18', 'Lowes')
        self.assertEqual(2, len(result['batches']))
        self.assertEqual([False, True], [b['applied'] for b in result['batches']])
        sql, params = cursor.execute.call_args.args
        self.assertNotIn('page_type', sql)
        self.assertIn(source_date_sql('crawl_datetime') + ' = %s', sql)
        self.assertEqual(('2026-10-18', 'lowes'), params)
        self.assertIn(source_date_sql('crawl_datetime') + ' = %s', cursor.mogrify.call_args.args[0])
        cursor.fetchall.return_value = [('lowes', 2)]
        self.assertEqual({'lowes': 2}, retail_batches.fetch_batch_counts(cursor, 'retail', 'ldy_dryer', '2026-10-18'))
        self.assertIn('COUNT(DISTINCT', cursor.execute.call_args.args[0])

    def test_loading_type_stays_in_statistics_but_not_null_validation(self):
        source = columns.select_source('SEA', 'LDY_DRYER', 'Lowes')
        retailer = next(r for r in source['retailers'] if r['name'] == 'Lowes')
        fields = columns.ordered_columns(policy.costco.COLUMNS['ldy_dryer'])
        self.assertIn('loading_type', fields)
        self.assertEqual(12, len(fields))
        sql, params = columns.query_spec(source, retailer, fields, date(2026, 10, 1), date(2026, 10, 18))
        self.assertIn('chosen_batch', sql)
        self.assertIn('2026-10-17', params)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertEqual(7, minimum_days({'country': 'SEA', 'retailer': 'Lowes'}))
        self.assertFalse(collection_complete('SEA', 'LDY_DRYER', 'Lowes', date(2026, 10, 18), datetime(2026, 10, 18, 23, tzinfo=KST)))
        self.assertTrue(collection_complete('SEA', 'LDY_DRYER', 'Lowes', date(2026, 10, 18), datetime(2026, 10, 19, tzinfo=KST)))
        null_fields = self.null.load_null_check_config()[CATEGORY]['checks']['lowes']['columns']
        self.assertEqual(set(lowes_dryer.NULL_COLUMNS), set(null_fields))
        self.assertEqual(11, len(null_fields))
        self.assertNotIn('Lowes', policy.dryer_source()['retailers'])
        for value in (0, '0', '0.0'):
            self.assertFalse(self.null._is_field_null(value, 'both'))
        for value in (None, '', '  '):
            self.assertTrue(self.null._is_field_null(value, 'both'))

    def test_null_review_detail_and_edit_use_lowes_latest_batch(self):
        source = self.null.SEA_RETAIL_SOURCES['ldy_dryer']
        sql, retailers = self.null._build_sea_latest_batch_record_query(source, 'capacity')
        self.assertIn('lowes', retailers)
        self.assertIn('2026-10-17', sql)
        self.assertNotIn('page_type', sql)
        cursor = ScriptedCursor([{'fetchone': (None, 'Lowes', '123')}, {}, {}])
        with patch.object(self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-18'}):
            result = self.edit.update_cell_value(cursor, Mock(), TABLE, 42, 'capacity', '7 Cu.Feet', date(2026, 10, 19), 'null', 'tester', 'fixed')
        self.assertTrue(result.get('success'), result)
        self.assertIn("'lowes'", cursor.calls[0][0])
        self.assertNotIn('page_type', cursor.calls[0][0])

    @override_settings(DEBUG=True)
    def test_registration_is_isolated_and_null_only(self):
        sql = setup.registration_sql()
        self.assertIn('public.test_monitoring_null_column', sql)
        self.assertNotIn('public.monitoring_null_column', sql)
        self.assertIn("'loading_type', FALSE, FALSE", sql)
        self.assertNotIn('UPDATE public.ldy_dryer_retail', sql)
        conn, cursor = Mock(), Mock()
        cursor.fetchall.return_value = [('LDY_DRYER', 11)]
        @contextmanager
        def connection():
            yield conn, cursor
        with patch.object(setup, 'dx_connection', connection):
            setup.Command().handle()
        conn.commit.assert_called_once()
