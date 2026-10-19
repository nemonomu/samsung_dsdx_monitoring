import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.sem_retail import (
    get_sem_required_columns, get_sem_table_columns, SEM_DRYER_FIRST_SOURCE_DATE,
)
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer1.sem_retail import sem_retail_repositories as repo
from apps.dx.dx_layer1.sem_retail import sem_retail_services as layer1
from apps.dx.dx_layer1.column_statistics.services import select_source, query_spec
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check
from apps.dx.dx_layer2 import sem_validation as layer2


DAY = date(2026, 10, 19)
KST = timezone(timedelta(hours=9))


class SemDryerMonitoringTests(unittest.TestCase):
    def test_recorded_date_and_same_day_inspection(self):
        self.assertEqual(date(2026, 10, 18), SEM_DRYER_FIRST_SOURCE_DATE)
        self.assertEqual('2026-10-18', source_date_value('2026-10-18T23:59:59-04:00'))
        self.assertEqual('2026-10-19', source_date_value('2026-10-19T00:00:00+00:00'))
        mapping = resolve_monitoring_date(DAY, 'SEM', 'sem_ldy_dryer')
        self.assertEqual('2026-10-19', mapping['source_date'])
        self.assertEqual(0, mapping['offset_days'])

    def test_latest_batch_query_uses_original_timestamp_date(self):
        cursor = Mock()
        cursor.description = [
            ('retailer',), ('batch_id',), ('actual_count',),
            ('main_count',), ('bsr_count',),
        ]
        cursor.fetchall.return_value = [('HomeDepot', 'h20261019_010046', 24, 24, 0)]
        result = repo.get_latest_batch_counts(cursor, 'sem_ldy_dryer', 'HomeDepot', DAY)
        sql, params = cursor.execute.call_args.args
        self.assertIn('LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10)', sql)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)', sql)
        self.assertIn('ORDER BY id DESC', sql)
        self.assertEqual(('2026-10-19', 'HomeDepot', '2026-10-19', 'HomeDepot'), params)
        self.assertEqual(24, result['main_count'])

    def test_layer1_after_deadline_marks_missing_as_critical(self):
        with patch.object(layer1.repo, 'get_latest_batch_counts', return_value=None), \
             patch.object(layer1.repo, 'get_previous_main_counts', return_value=[{'main_count': 22}]):
            result = layer1.get_layer1_stats(None, DAY, datetime(2026, 10, 19, 14, 0, tzinfo=KST))
        dryer = next(c for c in result['check']['categories'] if c['name'] == 'LDY_DRYER')
        self.assertEqual('CRITICAL', dryer['status'])
        self.assertEqual('HomeDepot', dryer['retailers'][0]['retailer'])
        self.assertEqual('2026-10-19', dryer['source_date'])
        self.assertTrue(any('LDY_DRYER' in item['source'] for item in result['failed_items']))

    def test_null_scope_is_eleven_and_loading_type_is_statistical_only(self):
        required = get_sem_required_columns('sem_ldy_dryer', 'HomeDepot')
        self.assertEqual(11, len(required))
        self.assertIn('capacity', required)
        self.assertNotIn('loading_type', required)
        self.assertNotIn('original_sku_price', required)
        self.assertNotIn('savings', required)
        self.assertIn('loading_type', get_sem_table_columns('sem_ldy_dryer'))
        self.assertEqual('sem_ldy_dryer', layer2.product_line_for('sem_ldy_dryer_retail'))

    def test_null_summary_checks_capacity_but_ignores_loading_type(self):
        row = {field: 'value' for field in get_sem_required_columns('sem_ldy_dryer', 'HomeDepot')}
        row.update(id=1, account_name='HomeDepot', item='I1', loading_type=None, capacity=None)
        mapping = resolve_monitoring_date(DAY, 'SEM', 'sem_ldy_dryer')
        with patch.object(layer2, '_latest_rows', return_value=([row], mapping)), \
             patch.object(layer2, '_load_normal_reviews', return_value={}), \
             patch.object(layer2, 'uses_new_policy', return_value=False):
            summary = {'tables': []}
            count = layer2.append_null_stats(None, DAY, summary, 'sem_ldy_dryer_retail')
        self.assertEqual(1, count)
        self.assertEqual({'capacity': 1}, {key: value for key, value in
                         summary['tables'][0]['retailers'][0]['fields_detail'].items() if value})
        self.assertNotIn('loading_type', summary['tables'][0]['fields'])

    def test_column_statistics_include_loading_type_and_latest_batch(self):
        source = select_source('SEM', 'LDY_DRYER', 'HomeDepot')
        retailer = dict(source['retailers'][0], columns=('item', 'loading_type', 'capacity'))
        sql, params = query_spec(source, retailer, retailer['columns'], DAY, DAY)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)', sql)
        self.assertIn('source.loading_type', sql)
        self.assertIn('latest.chosen_batch', sql)
        self.assertIn('2026-10-19', params)

    def test_collection_statistics_includes_dryer_from_first_source_day(self):
        check = {'categories': [{'name': 'LDY_DRYER', 'retailers': [
            {'retailer': 'HomeDepot', 'main_count': 24, 'bsr_count': 0,
             'raw_count': 24, 'batch_id': 'h20261019_010046', 'status': 'OK'},
        ]}]}
        rows = normalize_check(check, 'SEM', DAY)
        self.assertEqual(1, len(rows))
        self.assertEqual('LDY_DRYER', rows[0]['product'])
        self.assertEqual('2026-10-18', rows[0]['active_from'])
        self.assertEqual('db_original', rows[0]['source_date_basis'])
        self.assertEqual([], normalize_check(check, 'SEM', date(2026, 10, 17)))

    def test_registration_sql_and_backup_sql_keep_source_rows_untouched(self):
        monitoring = Path('sql/setup_sem_homedepot_dryer_monitoring.sql').read_text(encoding='utf-8')
        backup = Path('sql/setup_sea_sem_dryer_backup.sql').read_text(encoding='utf-8')
        self.assertIn("'sem_ldy_dryer_retail'", monitoring)
        self.assertIn("('loading_type', FALSE, TRUE)", monitoring)
        self.assertIn('Expected eleven SEM dryer NULL fields', monitoring)
        self.assertIn('public.ldy_dryer_retail_backup', backup)
        self.assertIn('dx_sem.dx_sem_ldy_dryer_retail_com_backup', backup)
        self.assertNotIn('UPDATE public.ldy_dryer_retail ', backup)
        self.assertNotIn('UPDATE dx_sem.dx_sem_ldy_dryer_retail_com ', backup)


if __name__ == '__main__':
    unittest.main()
