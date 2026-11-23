from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.common.siel_retail import SIEL_JIOMART_NULL_COLUMNS, get_siel_source
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check, observation_eligible
from apps.dx.dx_layer1.column_statistics.comparison import compare_columns
from apps.dx.dx_layer1.rank_monitoring.sources import catalog
from apps.dx.dx_layer1.siel_retail import jiomart, siel_retail_services
from apps.dx.dx_layer2.anomaly_validation import services as anomaly
from apps.dx.dx_layer2.data_edit import services as data_edit
from apps.dx.dx_layer2.null_validation import services as nulls
from tests.unit.support import ScriptedCursor


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


class JiomartNullValidationTests(TestCase):
    def test_null_config_requires_no_database_registration(self):
        with patch.object(nulls, 'execute_dx_query', return_value=[]), \
             patch.object(nulls, '_null_check_config_cache', None), \
             patch.object(nulls, '_null_check_config_cache_time', None):
            config = nulls.load_null_check_config()
        for product in ('tv', 'ref', 'ldy'):
            check = config[f'siel_{product}_retail']['checks']['jiomart']
            self.assertEqual(SIEL_JIOMART_NULL_COLUMNS, tuple(check['columns']))
            self.assertTrue(all(rule['check_type'] == 'both' for rule in check['columns'].values()))

    def test_edit_locks_only_latest_operating_jiomart_batch(self):
        source = get_siel_source('siel_ref')
        table = source['table_name']
        cursor = ScriptedCursor([{'fetchone': None}, {'fetchone': (None, 'Jiomart', 'item1', 'j1')}, {}, {}])
        result = data_edit.update_cell_value(
            cursor, Mock(), table, 42, 'count_of_reviews', '0', '2026-11-23', 'null', 'qa', 'reviewed',
        )
        self.assertTrue(result['success'], result)
        sql, params = cursor.calls[1]
        self.assertIn('crawl_datetime DESC NULLS LAST, id DESC', sql)
        self.assertIn('FOR UPDATE OF target', sql)
        self.assertNotIn('page_type', sql)
        self.assertEqual(('jiomart', '2026-11-23', '2026-11-23', 42), params)
        self.assertIn('null_check', cursor.calls[-1][1])
        disallowed = Mock()
        for column in ('ref_refrigerator_type', 'sku', 'original_sku_price'):
            self.assertIsNone(nulls.select_jiomart_null_record(disallowed, source, jiomart.START, 42, column))
        self.assertIsNone(nulls.select_jiomart_null_record(disallowed, source, jiomart.TEST_DAY, 42, 'star_rating'))
        disallowed.execute.assert_not_called()

    def test_normal_review_keeps_the_existing_siel_evidence_workflow(self):
        table = get_siel_source('siel_tv')['table_name']
        cursor = ScriptedCursor([
            {'fetchone': None}, {'fetchone': (None, 'Jiomart', 'item1', 'j1')},
            {'fetchone': (42, 'item1', 'Product', None, 'Jiomart')},
            {'fetchone': None}, {'fetchone': (101,)},
        ])
        connection = Mock()
        with patch.object(nulls, 'datetime', wraps=datetime) as clock, \
             patch('apps.common.null_review_evidence.save_manual_evidence', return_value={'id': 101}) as evidence:
            clock.now.return_value = datetime(2026, 11, 24, 12)
            result = nulls.save_null_review(
                cursor, connection, table, 42, 'star_rating', 'normal', '', '원본 확인',
                '2026-11-23', 'null', 'qa',
            )
        self.assertTrue(result['success'], result)
        self.assertEqual('Jiomart', evidence.call_args.kwargs['retailer'])
        self.assertEqual('TV', evidence.call_args.kwargs['product_line'])
        self.assertEqual('SIEL', evidence.call_args.kwargs['country'])
        connection.commit.assert_called_once()


class JiomartDuplicateValidationTests(TestCase):
    def test_item_duplicates_are_separate_from_shared_skus(self):
        def row(id, item, sku, main=None, bsr=None):
            return dict(id=id, item=item, sku=sku, main_rank=main, bsr_rank=bsr)

        rows = [
            row(1, 'i1', 'A', 1, 1), row(2, 'i1', 'B'),
            row(3, 'i2', 'C', 2, 2), row(4, 'i3', 'C'), row(5, '', 'C'),
        ]
        with patch.object(anomaly, '_fetch_siel_duplicate_rows', return_value=rows):
            first = anomaly.get_anomaly_detail(Mock(), jiomart.START, 'siel_tv_retail', 'Jiomart', 1, 1, 1)
            second = anomaly.get_anomaly_detail(Mock(), jiomart.START, 'siel_tv_retail', 'Jiomart', 1, 2, 1)
        results = first['results']
        self.assertEqual((1, 1, 2), (results['total_groups'], results['total_mapping_groups'], results['total_pages']))
        self.assertEqual('i1', results['duplicates'][0]['item'])
        self.assertTrue(first['readonly'])
        self.assertEqual([], first['editable_cols'])
        self.assertNotIn('page_type', first['select_cols']['group'])
        self.assertEqual('i2, i3', second['results']['mapping_conflicts'][0]['item'])
        self.assertEqual([], second['results']['duplicates'])
        self.assertIn('id IN (3, 4)', second['query'])

    def test_jiomart_duplicate_query_uses_latest_kst_batch_without_page_type(self):
        source = get_siel_source('siel_ldy')
        cursor = Mock()
        cursor.fetchall.return_value = []
        anomaly._fetch_siel_duplicate_rows(cursor, jiomart.START, source, 'Jiomart')
        sql, params = cursor.execute.call_args.args
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
        self.assertIn('crawl_datetime DESC NULLS LAST, id DESC', sql)
        self.assertNotIn('page_type', sql)
        self.assertEqual(['jiomart', '2026-11-22', '2026-11-22'], params)
