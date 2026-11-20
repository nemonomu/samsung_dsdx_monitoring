from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.common.siel_retail import get_siel_source
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check, observation_eligible
from apps.dx.dx_layer1.column_statistics.comparison import compare_columns
from apps.dx.dx_layer1.rank_monitoring.sources import catalog
from apps.dx.dx_layer1.siel_retail import jiomart, siel_retail_services


class JiomartLayer1Tests(TestCase):
    def test_recorded_day_and_timestamp_order_are_separate(self):
        source = get_siel_source('siel_ref')
        sql, params = jiomart.scope_sql(source['table_name'], jiomart.START, jiomart.START, registered=True)
        self.assertEqual(['jiomart', '2026-11-22', '2026-11-22'], params)
        self.assertIn('recorded.source_collection_date', sql)
        self.assertIn('recorded.crawl_datetime = source.crawl_datetime', sql)
        self.assertIn('crawl_datetime DESC NULLS LAST, id DESC', sql)
        for banned in ('AT TIME ZONE', 'page_type', 'crawl_datetime::date', jiomart.TEST_BATCH):
            self.assertNotIn(banned, sql)
        self.assertNotIn('Jiomart', source['retailers'])
        self.assertEqual(['TV', 'REF', 'LDY'], [row['product'] for row in catalog('SIEL')
                                               if row.get('bsr_retailers') == ['Jiomart']])

    def test_preview_deletion_keeps_dashboard_totals_and_observation(self):
        now = datetime(2026, 11, 20, 17, tzinfo=jiomart.KST)
        legacy = [dict(retailer='Amazon', actual_count=300), dict(retailer='Flipkart', actual_count=300)]
        with patch.object(siel_retail_services.repo, 'get_latest_main_batch_counts', return_value=legacy), \
             patch.object(siel_retail_services.repo, 'get_jiomart_counts') as counts:
            counts.return_value = (366, 300, 100, jiomart.TEST_BATCH)
            preview = siel_retail_services.get_layer1_stats(Mock(), jiomart.TEST_DAY, now)
            counts.return_value = (0, 0, 0, None)
            deleted = siel_retail_services.get_layer1_stats(Mock(), jiomart.TEST_DAY, now)
        self.assertEqual(1800, preview['check']['actual'])
        self.assertEqual(1800, deleted['check']['actual'])
        self.assertEqual([], deleted['failed_items'])
        rows = normalize_check(preview['check'], 'SIEL', jiomart.TEST_DAY)
        self.assertTrue(all(row['preview_mode'] and not observation_eligible(row)
                            for row in rows if row['retailer'] == 'Jiomart'))

    def test_collection_window_and_five_authoritative_completed_column_days(self):
        for hour, value in ((8, 'pending'), (9, 'collecting'), (10, 'collecting'), (11, 'complete')):
            self.assertEqual(value, jiomart.phase(jiomart.START, datetime(2026, 11, 22, hour, tzinfo=jiomart.KST)))
        days = [{'date': f'2026-11-{d}', 'total': 100 if d != 24 else 0,
                 'counts': {'sku': 100 if d < 27 else 20}} for d in range(20, 29)]
        data = dict(country='SIEL', product='REF', retailer='Jiomart', active_from=str(jiomart.START),
                    source_date_ready_from=str(jiomart.START), daily=days, columns=['sku'])
        completed = {row['date']: row['date'] >= str(jiomart.START) for row in days}
        self.assertEqual('preview', compare_columns(data, jiomart.TEST_DAY, completed)[0]['status'])
        self.assertEqual('insufficient', compare_columns(data, date(2026, 11, 27), completed)[0]['status'])
        ready = compare_columns(data, date(2026, 11, 28), completed)[0]
        self.assertEqual((5, 100, 'abnormal'), (ready['history_days'], ready['baseline'], ready['status']))
        data['source_date_ready_from'] = None
        self.assertEqual('unverified_start', compare_columns(data, date(2026, 11, 24), completed)[0]['status'])
