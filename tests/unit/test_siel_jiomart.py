from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.common.siel_retail import get_siel_source
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check, observation_eligible
from apps.dx.dx_layer1.column_statistics.comparison import compare_columns
from apps.dx.dx_layer1.rank_monitoring.sources import catalog
from apps.dx.dx_layer1.siel_retail import jiomart, siel_retail_services


class JiomartLayer1Tests(TestCase):
    def test_siel_business_day_bounds_keep_latest_batch_and_launch_date(self):
        source = get_siel_source('siel_ref')
        sql, params = jiomart.scope_sql(source['table_name'], jiomart.TEST_DAY, jiomart.START)
        self.assertEqual(['jiomart', '2026-11-22', '2026-11-22'], params)
        self.assertIn("source.crawl_datetime >= (%s::date::timestamp AT TIME ZONE 'Asia/Seoul')", sql)
        self.assertIn("source.crawl_datetime < ((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Seoul')", sql)
        self.assertIn("TO_CHAR(source.crawl_datetime AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD') AS source_day", sql)
        self.assertIn('crawl_datetime DESC NULLS LAST, id DESC', sql)
        for banned in ('jiomart_collection_dates', 'page_type', 'crawl_datetime::date', jiomart.TEST_BATCH):
            self.assertNotIn(banned, sql)
        for query in jiomart.copy_queries(source['table_name'], jiomart.START).values():
            self.assertTrue(query.startswith('WITH scoped AS'))
            self.assertIn("'2026-11-22'::date::timestamp AT TIME ZONE 'Asia/Seoul'", query)
        self.assertNotIn('Jiomart', source['retailers'])
        self.assertEqual(['TV', 'REF', 'LDY'], [row['product'] for row in catalog('SIEL')
                                               if row.get('bsr_retailers') == ['Jiomart']])

    def test_dashboard_counts_operating_batches_without_a_registry(self):
        now = datetime(2026, 11, 22, 11, tzinfo=jiomart.KST)
        legacy = [dict(retailer='Amazon', actual_count=300), dict(retailer='Flipkart', actual_count=300)]
        with patch.object(siel_retail_services.repo, 'get_latest_main_batch_counts', return_value=legacy), \
             patch.object(siel_retail_services.repo, 'get_jiomart_counts',
                          return_value=(366, 300, 100, 'batch', ['Jiomart'])):
            result = siel_retail_services.get_layer1_stats(Mock(), jiomart.START, now)
        check = result['check']
        self.assertEqual(2898, check['actual'])
        for category in check['categories']:
            retailer = category['retailers'][-1]
            self.assertEqual(('Jiomart', 'OK', 366, jiomart.WINDOW),
                             (retailer['retailer'], retailer['status'], retailer['actual'], retailer['collection_window']))
            self.assertTrue(retailer['copy_query'].startswith(f"SELECT *\nFROM {category['table_name']}\n"))
            self.assertIn("AND account_name = 'Jiomart'\n  AND batch_id = 'batch'", retailer['copy_query'])
        rows = normalize_check(check, 'SIEL', jiomart.START)
        for row in rows:
            if row['retailer'] == 'Jiomart':
                self.assertTrue(observation_eligible(row))
                self.assertEqual(jiomart.DATE_BASIS, row['source_date_basis'])

    def test_preview_deletion_keeps_dashboard_totals_and_observation(self):
        now = datetime(2026, 11, 20, 17, tzinfo=jiomart.KST)
        legacy = [dict(retailer='Amazon', actual_count=300), dict(retailer='Flipkart', actual_count=300)]
        with patch.object(siel_retail_services.repo, 'get_latest_main_batch_counts', return_value=legacy), \
             patch.object(siel_retail_services.repo, 'get_jiomart_counts') as counts:
            counts.return_value = (366, 300, 100, jiomart.TEST_BATCH, ['Jiomart'])
            preview = siel_retail_services.get_layer1_stats(Mock(), jiomart.TEST_DAY, now)
            counts.return_value = (0, 0, 0, None, None)
            deleted = siel_retail_services.get_layer1_stats(Mock(), jiomart.TEST_DAY, now)
        self.assertEqual(1800, preview['check']['actual'])
        self.assertEqual(1800, deleted['check']['actual'])
        self.assertEqual([], deleted['failed_items'])
        copy = preview['check']['categories'][0]['retailers'][-1]['copy_query']
        self.assertIn(f"crawl_datetime = TIMESTAMPTZ '{jiomart.TEST_TIMESTAMP}'", copy)
        rows = normalize_check(preview['check'], 'SIEL', jiomart.TEST_DAY)
        self.assertTrue(all(row['preview_mode'] and not observation_eligible(row)
                            for row in rows if row['retailer'] == 'Jiomart'))

    def test_collection_window_and_five_authoritative_completed_column_days(self):
        for hour, value in ((8, 'pending'), (9, 'collecting'), (10, 'collecting'), (11, 'complete')):
            self.assertEqual(value, jiomart.phase(jiomart.START, datetime(2026, 11, 22, hour, tzinfo=jiomart.KST)))
        days = [{'date': f'2026-11-{d}', 'total': 100 if d != 24 else 0,
                 'counts': {'sku': 100 if d < 27 else 20}} for d in range(20, 29)]
        data = dict(country='SIEL', product='REF', retailer='Jiomart', active_from=str(jiomart.START),
                    daily=days, columns=['sku'])
        completed = {row['date']: row['date'] >= str(jiomart.START) for row in days}
        self.assertEqual('preview', compare_columns(data, jiomart.TEST_DAY, completed)[0]['status'])
        self.assertEqual('insufficient', compare_columns(data, date(2026, 11, 27), completed)[0]['status'])
        ready = compare_columns(data, date(2026, 11, 28), completed)[0]
        self.assertEqual((5, 100, 'abnormal'), (ready['history_days'], ready['baseline'], ready['status']))
        self.assertEqual('uncollected', compare_columns(data, date(2026, 11, 24), completed)[0]['status'])

    def test_batch_copy_preserves_literal_account_names_and_next_day(self):
        table = get_siel_source('siel_tv')['table_name']
        sql = jiomart.copy_batch_query(table, date(2026, 11, 30), "b'1", ['Jiomart', ' jiomart '])
        self.assertEqual(
            f"SELECT *\nFROM {table}\n"
            "WHERE crawl_datetime >= TIMESTAMPTZ '2026-11-30 00:00:00+09'\n"
            "  AND crawl_datetime <  TIMESTAMPTZ '2026-12-01 00:00:00+09'\n"
            "  AND account_name IN ('Jiomart', ' jiomart ')\n"
            "  AND batch_id = 'b''1'\nORDER BY item, crawl_datetime;", sql,
        )
        self.assertIn('AND batch_id IS NULL', jiomart.copy_batch_query(table, jiomart.START, None, ['Jiomart']))
