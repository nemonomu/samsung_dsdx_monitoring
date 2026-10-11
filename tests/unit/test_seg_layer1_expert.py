"""Expert onboarding regressions, with no live database access."""
import unittest
from datetime import date, datetime
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

from apps.common.seg_retail import SEG_SOURCE_CONFIG as shared_sources
from apps.dx.dx_layer1.seg_retail import sources, seg_retail_repositories as repo
from apps.dx.dx_layer1.seg_retail import seg_retail_services as service
from apps.dx.dx_layer1.common import retail_batches
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check, build_week
from apps.dx.dx_layer1.collection_statistics import automatic
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete
from apps.dx.dx_layer4.collection_status.email_registry import EMAIL_REPORT_SOURCES
from tests.unit.support import ScriptedCursor


class ExpertLayer1Tests(unittest.TestCase):
    def test_sources_only_extend_layer1(self):
        self.assertEqual(list(sources.SEG_SOURCE_CONFIG), ['seg_tv', 'seg_ref', 'seg_ldy', 'seg_ldy_dryer'])
        self.assertNotIn('seg_ldy_dryer', shared_sources)
        self.assertTrue(all('Expert' not in s['retailers'] for s in shared_sources.values()))
        self.assertFalse(any(r['name'] == 'Expert' for s in EMAIL_REPORT_SOURCES for r in s['retailers']))

    def test_expert_uses_latest_batch_without_requiring_page_type(self):
        for product in ('tv', 'ref', 'ldy'):
            sql, params = repo.latest_main_counts_query('seg_' + product, '2026-10-11')
            self.assertIn('expert', params)
            self.assertIn("WHERE LOWER(BTRIM(page_type)) = 'main' OR LOWER(BTRIM(account_name)) = 'expert'", sql)
            self.assertIn("OR latest.retailer_key = 'expert'", sql)
            self.assertIn('rows.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        sql, params = repo.latest_main_counts_query('seg_ldy_dryer', '2026-10-11')
        self.assertEqual(params, ['2026-10-11', 'expert'])
        self.assertIn('dx_seg.dx_seg_ldy_dryer_retail', sql)
        self.assertIn('crawl_datetime', sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('crawl_strdatetime', sql)

    def test_dryer_history_and_batch_details_use_actual_schema(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        repo.get_previous_main_counts(cursor, 'seg_ldy_dryer', '2026-10-12')
        sql, params = cursor.calls[0]
        self.assertNotIn('page_type', sql)
        self.assertNotIn('crawl_strdatetime', sql)
        self.assertIn("'2026-10-11'", sql)
        self.assertEqual(params, ['2026-10-12', 'expert', 7])
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        result = retail_batches.fetch_batch_details(cursor, 'seg_retail', 'seg_ldy_dryer', '2026-10-11', 'Expert')
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])
        self.assertEqual('최신 배치 반영', result['aggregation_basis'])

    def check(self, day, hour=12, missing=False):
        def counts(_cursor, product, _day):
            return [dict(retailer=name, main_count=0 if missing else 300,
                         bsr_count=0 if missing else 100,
                         actual_count=0 if missing else 400 if product == 'seg_ref' and name == 'Expert' else 300)
                    for name in sources.SEG_SOURCE_CONFIG[product]['retailers']]
        with patch.object(repo, 'get_latest_main_batch_counts', side_effect=counts), patch.object(repo, 'get_previous_main_counts', return_value=[]):
            return service.get_layer1_stats(None, day, datetime.combine(day, datetime.min.time()).replace(hour=hour))['check']

    def test_start_date_counts_order_and_existing_status_policy(self):
        before = self.check(date(2026, 10, 10))
        self.assertEqual(8, sum(len(c['retailers']) for c in before['categories']))
        check = self.check(date(2026, 10, 11))
        self.assertEqual(['TV', 'REF', 'LDY', 'LDY_DRYER'], [c['category'] for c in check['categories']])
        self.assertEqual(12, sum(len(c['retailers']) for c in check['categories']))
        self.assertEqual(3700, check['raw_count'])
        self.assertEqual(3600, check['main_count'])
        for cat in check['categories']:
            self.assertEqual('Expert', cat['retailers'][-1]['retailer'])
        self.assertEqual('OK', check['status'])
        self.assertEqual('COLLECTING', self.check(date(2026, 10, 11), 10, True)['status'])
        self.assertEqual('CRITICAL', self.check(date(2026, 10, 11), 12, True)['status'])
        self.assertEqual('PENDING', self.check(date(2026, 10, 11), 6, True)['status'])
        rows = normalize_check(check, 'SEG', date(2026, 10, 11))
        expert = [r for r in rows if r['retailer'] == 'Expert']
        self.assertEqual(4, len(expert))
        self.assertTrue(all(r['active_from'] == '2026-10-11' for r in expert))
        weekly = build_week({date(2026, 10, 11): rows}, date(2026, 10, 5), date(2026, 10, 11))
        for row in weekly:
            if row['retailer'] == 'Expert':
                self.assertTrue(all(day['state'] == 'not_scheduled' for day in row['daily'][:6]))

    def test_expert_columns_do_not_require_db_configuration_or_page_type(self):
        for product in sources.EXPERT_COLUMNS:
            source = columns.select_source('SEG', product, 'Expert')
            retailer = next(r for r in source['retailers'] if r['name'] == 'Expert')
            sql, params = columns.query_spec(source, retailer, ['sku'], date(2026, 10, 1), date(2026, 10, 11))
            self.assertNotIn('page_type', sql)
            self.assertIn('2026-10-11', params)
            self.assertIn('IS NOT DISTINCT FROM latest.chosen_batch', sql)
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        @contextmanager
        def connection():
            yield None, cursor
        with patch.object(columns, 'dx_connection', connection), patch.object(columns, '_configured_retailers', side_effect=AssertionError('Expert must use collected columns')):
            data = columns.daily_counts('SEG', 'LDY_DRYER', 'Expert', date(2026, 10, 11), 7)
        self.assertIn('loading_type', data['columns'])
        self.assertIn('capacity', data['columns'])
        self.assertNotIn('ldy_capacity', data['columns'])
        self.assertNotIn('id', data['columns'])
        self.assertFalse(collection_complete('SEG', 'LDY_DRYER', 'Expert', date(2026, 10, 10)))

    def test_background_refresh_revisits_snapshots_missing_expert(self):
        from datetime import timedelta
        last_due = date(2026, 10, 15)
        days = [last_due - timedelta(days=i) for i in range(3, 112)]
        rows = [dict(product=p, retailer='Expert', bsr=100) for p in sources.EXPERT_COLUMNS]
        with patch.object(automatic.Daily, 'objects') as manager:
            query = manager.filter.return_value.values_list
            query.return_value = [(day, rows if day >= sources.EXPERT_START_DATE else []) for day in days]
            self.assertIsNone(automatic.history_range('SEG', last_due))
            query.return_value = [(day, [] if day == date(2026, 10, 12) else rows) for day in days]
            self.assertEqual((date(2026, 10, 12), date(2026, 10, 12)), automatic.history_range('SEG', last_due))
