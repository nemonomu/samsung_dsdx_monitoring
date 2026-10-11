import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from apps.common.sea_collection import KST
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.dx.dx_layer1.retail import costco, retail_services as svc, retail_repositories as repo
from apps.dx.dx_layer1.dashboard import collection_services as dday
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.seg_retail import seg_retail_services as seg


@contextmanager
def connection():
    yield None, MagicMock()


class DryerTests(unittest.TestCase):
    def test_source_scope_counts_start_and_date(self):
        self.assertNotIn('ldy_dryer', SEA_RETAIL_SOURCES)
        source = svc._get_layer1_source('LDY_DRYER')
        self.assertEqual('public.ldy_dryer_retail', source['table_name'])
        self.assertFalse(costco.enabled('2026-10-08', 'ldy_dryer'))
        cursor = MagicMock()
        self.assertIsNone(repo.get_latest_appliance_main_batch(cursor, source['table_name'], 'crawl_datetime', '2026-10-08', 'Costco'))
        cursor.execute.assert_not_called()
        cursor.fetchone.side_effect = [('c9',), (300, 100, 0, 332)]
        counts = repo.query_appliance_counts_by_retailer(cursor, source['table_name'], 'crawl_datetime', '2026-10-09', 'Costco')
        self.assertEqual((300, 100, 0, 332, 'c9'), counts)
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])
        with patch.object(svc, '_matching_schedule_slots', return_value=[]), patch.object(svc, '_source_rows', return_value=[('Costco', 332, 300, 100, 0, 'c9')]):
            category, failures, contract = svc._build_category(cursor, source, date(2026, 10, 10), datetime(2026, 10, 11, tzinfo=KST))
        self.assertEqual('2026-10-09', contract['source_date'])
        self.assertEqual(332, category['total'])
        self.assertEqual([], failures)
        rows = calc.normalize_check({'categories': [category]}, 'SEA', date(2026, 10, 10))
        self.assertEqual('LDY_DRYER', rows[0]['product'])
        self.assertEqual('2026-10-09', rows[0]['active_from'])

    def test_dday_dryer_order_schedule_and_bsr(self):
        for count, expected in [(99, 'abnormal'), (100, 'received'), (101, 'abnormal')]:
            with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection', return_value=(300, None, 'c11', 300, count)):
                rows = dday.get_collection_status(date(2026, 10, 11), datetime(2026, 10, 11, 16, tzinfo=KST))['retailers']
            self.assertEqual('LDY_DRYER', rows[-1]['product'])
            self.assertEqual(expected, rows[-1]['status'])
            self.assertEqual('2026-10-11T13:00:00+09:00', rows[-1]['scheduled_at'])

    def test_column_statistics_use_dryer_schema(self):
        source = columns.select_source('SEA', 'LDY_DRYER', 'Costco')
        sql, params = columns.query_spec(source, source['retailers'][0], ['capacity', 'loading_type'], date(2026, 10, 1), date(2026, 10, 11))
        self.assertIn('public.ldy_dryer_retail', sql)
        self.assertIn('2026-10-09', params)
        self.assertNotIn('page_type', sql)
        self.assertIn('crawl_datetime', sql)

    def test_exact_bsr_without_five_day_wait(self):
        for country, retailer in [('SEA', 'Costco'), ('SEG', 'Expert')]:
            for count in (99, 100, 101):
                row = dict(product='LDY_DRYER', retailer=retailer, slot='daily', main=300,
                           bsr=count, total=300, complete=True, base_status='OK')
                result = calc.compare_rows([row], [], country)[0]
                self.assertEqual(count != 100, bool(result['alerts']))
                result = calc.current_volume_decision(result, country)
                self.assertEqual(count != 100, bool(result['alerts']))
                self.assertTrue(calc.comparison_rules(result, country)['bsr']['exact'])
                self.assertEqual(count == 100, svc._meets_retailer_criteria(
                    {'count': 300, 'main': 300, 'bsr': count}, {'bsr_exact': 100, 'total_min': 1}))
                if retailer == 'Expert':
                    with patch.object(seg.repo, 'get_latest_main_batch_counts', return_value=[{'retailer': 'expert', 'main_count': 300, 'bsr_count': count, 'actual_count': 300}]), patch.object(seg.repo, 'get_previous_main_counts', return_value=[]):
                        check = seg.get_layer1_stats(None, date(2026, 10, 11), datetime(2026, 10, 11, 12, tzinfo=KST))['check']
                    expert = check['categories'][-1]['retailers'][0]
                    self.assertEqual('OK' if count == 100 else 'CRITICAL', expert['status'])
