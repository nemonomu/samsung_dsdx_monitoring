"""Bestbuy dryer routing, counts and review regressions (no live database)."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.test import override_settings
from apps.common import costco_layer2 as policy
from apps.common.sea_collection import KST
from apps.dx.dx_layer1.retail import retail_services as retail, retail_repositories as repo
from apps.dx.dx_layer1.retail import bestbuy_dryer
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.management.commands.setup_bestbuy_dryer import registration_sql, Command
from apps.dx.dx_layer2 import null_review_state
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs, db_rows
from tests.unit.test_layer2_sea_format_duplicate import common_stubs as anomaly_stubs
from tests.unit.test_layer2_sea_data_edit import SEALayer2DataEditTests

TABLE = 'public.ldy_dryer_retail'
CATEGORY = 'sea_ldy_dryer_retail'
DAY = date(2026, 10, 13)


def record(**updates):
    row = dict(id=1844, account_name='Bestbuy', country='SEA', item='JJ8VPZ6896',
               sku='DVE45T6000W', retailer_sku_name='Dryer', capacity=None,
               product_url='https://www.bestbuy.com/product/dryer/JJ8VPZ6896',
               crawl_datetime='2026-10-12 19:07:00', batch_id='b_20261012_190628',
               final_sku_price='$549.99', original_sku_price=None, savings=None,
               star_rating='Not yet reviewed', count_of_reviews='0', count_of_star_ratings='0',
               main_rank=1, bsr_rank=1, loading_type=None)
    row.update(updates)
    return row


class BestbuyDryerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        config = [dict(db_rows()[0], table_name=TABLE, date_column='crawl_datetime',
                       category=CATEGORY, check_name='bestbuy_sea_ldy_dryer',
                       group_display_name='Bestbuy', check_column=field)
                  for field in (*policy.NULL_COLUMNS['ldy_dryer'], 'sku', 'loading_type', 'savings')]
        stubs['apps.common.db'].execute_dx_query = lambda *_: config
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py', 'bestbuy_dryer_null_test', stubs)
        cls.dup = load_module('apps/dx/dx_layer2/anomaly_validation/services.py', 'bestbuy_dryer_dup_test', anomaly_stubs())
        SEALayer2DataEditTests.setUpClass()
        cls.edit = SEALayer2DataEditTests.service

    def test_collection_order_counts_and_launch(self):
        source = retail._get_layer1_source('LDY_DRYER')
        self.assertEqual(('Bestbuy', 'Costco', 'HomeDepot'), source['retailers'])
        cur = ScriptedCursor([])
        self.assertIsNone(repo.get_latest_appliance_main_batch(cur, TABLE, 'crawl_datetime', '2026-10-11', 'Bestbuy'))
        self.assertFalse(cur.calls)
        cur = ScriptedCursor([{'fetchone': ('b1',)}, {'fetchone': (300, 100, 0, 306)}])
        self.assertEqual((300, 100, 0, 306, 'b1'), repo.query_appliance_counts_by_retailer(cur, TABLE, 'crawl_datetime', '2026-10-12', 'Bestbuy'))
        for sql, params in cur.calls:
            self.assertNotIn('page_type', sql)
            self.assertNotIn('Asia/Seoul', sql)
            self.assertIn('Bestbuy', params)
        with patch.object(retail, '_matching_schedule_slots', return_value=[]), patch.object(
                retail, '_source_rows', return_value=[('Bestbuy', 306, 300, 100, 0, 'b1'), ('Costco', 300, 300, 99, 0, 'c1')]):
            category, _, _ = retail._build_category(Mock(), source, DAY, datetime(2026, 10, 13, tzinfo=KST))
        retailers = category['time_slots'][0]['retailers']
        self.assertEqual(['Bestbuy', 'Costco'], [r['retailer'] for r in retailers])
        self.assertEqual(606, category['total'])
        self.assertEqual('OK', retailers[0]['status'])
        rows = calc.normalize_check({'categories': [category]}, 'SEA', DAY)
        self.assertEqual('2026-10-12', rows[0]['active_from'])
        self.assertTrue(calc.exact_bsr(rows[0], 'SEA'))
        self.assertFalse(calc.exact_bsr(dict(rows[0], product='LDY'), 'SEA'))
        for count in (99, 100, 101):
            row = dict(rows[0], bsr=count, complete=True, base_status='OK')
            self.assertEqual(count != 100, bool(calc.compare_rows([row], [], 'SEA')[0]['alerts']))

    def test_column_statistics_same_schema_latest_batch_and_date(self):
        source = columns.select_source('SEA', 'LDY_DRYER', 'Bestbuy')
        self.assertEqual(['Bestbuy', 'Costco', 'HomeDepot'], [r['name'] for r in source['retailers']])
        fields = columns.ordered_columns(policy.costco.COLUMNS['ldy_dryer'])
        sql, params = columns.query_spec(source, source['retailers'][0], fields, date(2026, 10, 1), date(2026, 10, 12))
        self.assertIn('2026-10-12', params)
        self.assertIn('bestbuy', params)
        self.assertIn('chosen_batch', sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('Asia/Seoul', sql)
        self.assertIn('sku', fields)
        self.assertIn('loading_type', fields)
        self.assertNotIn('main_rank', fields)
        self.assertFalse(collection_complete('SEA', 'LDY_DRYER', 'Bestbuy', date(2026, 10, 12), datetime(2026, 10, 12, 23, tzinfo=KST)))
        self.assertTrue(bestbuy_dryer.complete('2026-10-12', datetime(2026, 10, 13, tzinfo=KST)))

    def test_null_fields_and_missing_semantics(self):
        fields = self.null.load_null_check_config()[CATEGORY]['checks']['bestbuy']['columns']
        self.assertEqual(set((*policy.NULL_COLUMNS['ldy_dryer'], 'sku')), set(fields))
        self.assertEqual(11, len(fields))
        for value in ('0', 0, 'Not yet reviewed'):
            self.assertFalse(self.null._is_field_null(value, 'both'))
        self.assertTrue(self.null._is_field_null(None, 'both'))
        source = policy.dryer_source()
        cur = ScriptedCursor([{'fetchone': ('b1',)}])
        self.null._get_sea_null_anchor_batch(cur, source, '2026-10-12', 'Bestbuy')
        sql = cur.calls[0][0]
        self.assertNotIn('page_type', sql)
        self.assertNotIn('Asia/Seoul', sql)
        scope, _ = self.null._build_sea_null_scope(source, '2026-10-12', 'Bestbuy', 'b1')
        self.assertNotIn('page_type', scope)

    def test_null_detail_and_three_day_history(self):
        row = record()
        cur = ScriptedCursor([{'fetchone': (row['batch_id'],)},
                              {'description': [(k,) for k in row], 'fetchall': [tuple(row.values())]},
                              {}, {}, {}, {}, {}])
        contract = dict(inspection_date=str(DAY), source_date='2026-10-12', offset_days=-1, source_key='sea_ldy_dryer')
        with patch.object(self.null, 'get_editable_columns', return_value=['capacity', 'sku']), patch.object(self.null, 'resolve_monitoring_date', return_value=contract):
            result = self.null.get_null_detail(cur, DAY, CATEGORY, 'Bestbuy', 3, 'capacity')
        self.assertEqual(1, result['raw_null_count'])
        self.assertIn('sku', result['display_config']['capacity']['select_columns'])
        self.assertEqual('2026-10-12', result['results'][0]['crawl_datetime'][:10])
        queries = '\n'.join(sql for sql, _ in cur.calls)
        self.assertIn('latest_batches', queries)
        self.assertNotIn('page_type', queries)
        self.assertNotIn('Asia/Seoul', queries)

    def test_null_review_and_edit_are_retailer_scoped(self):
        cur = ScriptedCursor([{'fetchone': (None, 'Bestbuy', 'JJ8VPZ6896')},
                              {'fetchone': (1844, 'JJ8VPZ6896', 'Dryer', None, 'Bestbuy')},
                              {'fetchone': None}, {'fetchone': (101,)}])
        with patch.object(null_review_state.null_review_evidence, 'save_manual_evidence', return_value={'auto_eligible': True}) as saved:
            result = self.null.save_null_review(cur, Mock(), TABLE, 1844, 'capacity', 'normal', 'checked', '상품페이지 내 항목 부재', str(DAY), 'null', 'tester')
        self.assertTrue(result.get('success'), result)
        self.assertEqual('Bestbuy', saved.call_args.kwargs['retailer'])
        for field in ('capacity', 'sku'):
            cur = ScriptedCursor([{'fetchone': (None, 'Bestbuy', 'JJ8VPZ6896')}, {}, {}])
            with patch.object(self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-12'}):
                result = self.edit.update_cell_value(cur, Mock(), TABLE, 1844, field, 'value', DAY, 'null', 'tester', 'fixed')
            self.assertTrue(result.get('success'), result)
            self.assertNotIn('page_type', cur.calls[0][0])
            self.assertIn('INSERT INTO monitoring_corrections', cur.calls[-1][0])

    def test_duplicate_item_scope_separates_retailers_and_batches(self):
        row = record()
        def groups(rows):
            return self.dup.build_sea_duplicate_groups(rows, 'Bestbuy', 'ldy_dryer')
        self.assertFalse(groups([row]))
        self.assertFalse(groups([row, record(id=2, batch_id='next')]))
        self.assertFalse(groups([row, record(id=2, account_name='Costco')]))
        self.assertFalse(groups([row, record(id=2, item='different')]))
        self.assertEqual('완전 중복', groups([row, record(id=2)])[0]['duplicate_type'])
        self.assertEqual('상품 매핑 충돌', groups([row, record(id=2, sku='different')])[0]['duplicate_type'])
        cur = ScriptedCursor([{'fetchall': []}])
        self.dup._fetch_sea_duplicate_rows(cur, '2026-10-12', policy.dryer_source(), 'Bestbuy')
        self.assertNotIn('page_type', cur.calls[0][0])
        self.assertNotIn('Asia/Seoul', cur.calls[0][0])
        legacy = policy.sources(__import__('apps.common.sea_retail', fromlist=['SEA_RETAIL_SOURCES']).SEA_RETAIL_SOURCES)['ldy']
        cur = ScriptedCursor([{'fetchall': []}])
        self.dup._fetch_sea_duplicate_rows(cur, '2026-10-12', legacy, 'Bestbuy')
        self.assertIn('page_type', cur.calls[0][0])

    @override_settings(DEBUG=True)
    def test_registration_targets_monitoring_tables_and_checks_count(self):
        sql = registration_sql()
        self.assertIn('public.test_monitoring_null_column', sql)
        self.assertNotIn('public.monitoring_null_column', sql)
        self.assertNotIn('BEGIN;', sql)
        self.assertNotIn('COMMIT;', sql)
        self.assertNotIn('UPDATE public.ldy_dryer_retail', sql)
        self.assertIn("'sku', TRUE, TRUE", sql)
        conn, cur = Mock(), Mock()
        cur.fetchall.return_value = [('LDY_DRYER', 11)]
        @contextmanager
        def connection():
            yield conn, cur
        with patch('apps.dx.dx_layer1.management.commands.setup_bestbuy_dryer.dx_connection', connection):
            Command().handle()
        conn.commit.assert_called_once()
