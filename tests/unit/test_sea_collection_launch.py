import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

from apps.common.sea_collection import KST, homedepot_inspection_label
from apps.common.sea_dates import appliance_page_scope_sql
from apps.common.sea_layer2 import page_scope_sql
from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub
from tests.unit.test_layer2_sea_format_duplicate import common_stubs
from tests.unit import test_sea_homedepot_layer2 as hd_tests
from tests.unit.test_layer3_sea_crossfield import sea_services, _bestbuy_row
from tests.unit.test_layer4_email_report_data import load_service as load_email, load_registry


class CollectionCardTests(unittest.TestCase):
    def setUp(self):
        db = module_stub('apps.common.db', dx_table=lambda name: 'test_' + name)
        self.repo = load_module('apps/dx/dx_layer1/dashboard/collection_repositories.py',
                                'collection_repo_under_test', {'apps.common.db': db})
        self.calls = []
        self.results = {}

        @contextmanager
        def connection():
            yield object(), object()

        def fetch(cursor, source, target_date):
            self.calls.append((source[:2], str(target_date)))
            result = self.results.get(source[:2], (0, None, None, 0, 0))
            if isinstance(result, Exception):
                raise result
            return result

        package = 'apps.dx.dx_layer1.dashboard'
        self.service = load_module('apps/dx/dx_layer1/dashboard/collection_services.py',
            package + '.collection_service_under_test', {
                package: package_stub(package),
                'apps.common.db': module_stub('apps.common.db', dx_connection=connection),
                package + '.collection_repositories': module_stub(
                    package + '.collection_repositories', SOURCES=self.repo.SOURCES,
                    fetch_collection=fetch),
            })

    def test_first_collection_is_not_a_d_minus_one_query(self):
        self.results[('HomeDepot', 'REF')] = (300, '2026-09-20 13:23:00', 'h20', 300, 100)
        result = self.service.get_collection_status(date(2026, 9, 20), datetime(2026, 9, 20, 14, tzinfo=KST))
        self.assertEqual('2026-09-20', result['source_date'])
        self.assertEqual(['waiting', 'received', 'waiting'],
                         [r['status'] for r in result['retailers']])
        self.assertEqual(300, result['retailers'][1]['count'])
        self.assertEqual(300, result['retailers'][1]['main_count'])
        self.assertEqual(100, result['retailers'][1]['bsr_count'])
        self.assertEqual(['Walmart', 'HomeDepot', 'HomeDepot'],
                         [r['retailer'] for r in result['retailers']])
        self.assertTrue(all(day == '2026-09-20' for _, day in self.calls))
        self.assertNotIn('failed', result)

    def test_13_kst_boundary_and_prelaunch_homedepot_never_queries_old_data(self):
        for hour, minute, status in ((12, 59, 'scheduled'), (13, 0, 'waiting'), (14, 0, 'waiting')):
            self.calls.clear()
            result = self.service.get_collection_status(date(2026, 9, 18), datetime(2026, 9, 18, hour, minute, tzinfo=KST))
            self.assertEqual([status, 'scheduled', 'scheduled'],
                             [r['status'] for r in result['retailers']])
            self.assertEqual(1, len(self.calls))
            self.assertEqual('2026-09-20T13:00:00+09:00', result['retailers'][2]['scheduled_at'])

    def test_query_failure_is_separate_from_no_collection(self):
        self.results[('Walmart', 'TV')] = ValueError('unavailable')
        result = self.service.get_collection_status(date(2026, 9, 21), datetime(2026, 9, 21, 14, tzinfo=KST))
        self.assertEqual(['error', 'waiting', 'waiting'],
                         [r['status'] for r in result['retailers']])
        self.assertIsNone(result['retailers'][0]['count'])
        self.assertIsNone(result['retailers'][0]['main_count'])
        self.assertIsNone(result['retailers'][0]['bsr_count'])

    def test_sql_uses_only_exact_date_and_latest_batch_and_kst_display(self):
        for source in self.repo.SOURCES:
            cursor = ScriptedCursor([{'fetchone': (0, None, None, 0, 0)}])
            self.repo.fetch_collection(cursor, source, date(2026, 9, 20))
            sql, params = cursor.calls[0]
            self.assertEqual(('2026-09-20', source[0]) * 2, params)
            self.assertIn('public.test_' + source[2], sql)
            self.assertIn('IS NOT DISTINCT FROM latest.batch_id', sql)
            self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
            self.assertNotIn('page_type', sql)
            self.assertIn('COUNT(source.main_rank)', sql)
            self.assertIn('COUNT(source.bsr_rank)', sql)


class HomeDepotLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hd_tests.HomeDepotLayer2Tests.setUpClass()
        cls.null = hd_tests.HomeDepotLayer2Tests.null
        cls.format = hd_tests.HomeDepotLayer2Tests.format
        cls.duplicate = load_module('apps/dx/dx_layer2/anomaly_validation/services.py',
                                    'launch_duplicate_under_test', common_stubs())

    def test_no_queries_for_prelaunch_null_format_or_duplicates(self):
        source = self.null.SEA_RETAIL_SOURCES['ref']
        cursor = ScriptedCursor([])
        self.assertIsNone(self.null._get_sea_null_anchor_batch(cursor, source, '2026-09-19', 'HomeDepot'))
        self.assertEqual([], self.format._fetch_sea_format_rows(cursor, date(2026, 9, 17), date(2026, 9, 19), source, 'HomeDepot'))
        self.assertEqual([], self.duplicate._fetch_sea_duplicate_rows(cursor, '2026-09-19', source, 'HomeDepot'))
        self.assertEqual([], cursor.calls)
        self.assertIn('2026-09-20', page_scope_sql('anchor', anchor=True))
        self.assertIn('2026-09-20', appliance_page_scope_sql('anchor', anchor=True))

    def test_format_history_clamps_to_launch_day(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        self.format._fetch_sea_format_rows(cursor, date(2026, 9, 18), date(2026, 9, 20),
                                          self.format.SEA_RETAIL_SOURCES['ref'], 'HomeDepot')
        self.assertEqual(('2026-09-20', '2026-09-20', 'HomeDepot') * 2, cursor.calls[0][1])

    def test_crossfield_excludes_old_homedepot_but_keeps_other_retailers(self):
        old = _bestbuy_row(account_name='HomeDepot', crawl_strdatetime='2026-09-20T01:00:00Z')
        first = _bestbuy_row(id=11, account_name='HomeDepot', crawl_strdatetime='2026-09-20T04:00:00Z')
        bestbuy = _bestbuy_row(id=12)
        cursor = ScriptedCursor([{'fetchall': [old, first, bestbuy]}])
        rows = sea_services.load_latest_sea_rows(cursor, date(2026, 9, 21), 'sea_ref')
        self.assertEqual([11, 12], [row['id'] for row in rows])

    def test_first_inspection_day_and_missing_data_are_never_normal(self):
        self.assertEqual('9/20 수집 예정', homedepot_inspection_label('2026-09-20', 300))
        self.assertEqual('수집 대기', homedepot_inspection_label('2026-09-21', 0))
        self.assertEqual('수집 확인 · 건수 기준 미정', homedepot_inspection_label('2026-09-21', 300))
        cursor = ScriptedCursor([{}, {}])
        validation = {'tables': []}
        with patch.object(self.duplicate, '_fetch_sea_duplicate_rows', return_value=[]):
            self.assertEqual(0, self.duplicate._append_sea_anomaly_stats(cursor, '2026-09-21', validation))
        for table in validation['tables']:
            hd = next(r for r in table['retailers'] if r['retailer'] == 'HomeDepot')
            self.assertEqual('PENDING', hd['status'])
            self.assertEqual('수집 대기', hd['validation_label'])

    def test_email_does_not_count_old_homedepot_as_missing(self):
        source = next(s for s in load_registry().EMAIL_REPORT_SOURCES if s['key'] == 'sea_ref')
        retailer = next(r for r in source['retailers'] if r['name'] == 'HomeDepot')
        cursor = ScriptedCursor([])
        result = load_email(cursor)._query_retailer(cursor, source, {**retailer, 'columns': ('item',)}, '2026-09-19')
        self.assertEqual(0, result['total_count'])
        self.assertEqual(0, result['columns'][0]['null_count'])
        self.assertEqual([], cursor.calls)
