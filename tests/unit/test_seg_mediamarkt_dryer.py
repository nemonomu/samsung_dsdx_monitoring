"""Mediamarkt dryer monitoring: original dates, statistics and eight NULL fields."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from apps.common.source_dates import source_date_sql, source_date_value
from apps.dx.dx_layer1.seg_retail import sources, seg_retail_repositories as repo
from apps.dx.dx_layer1.seg_retail import seg_retail_services as service
from apps.dx.dx_layer1.common import retail_batches
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import attach_comparisons
from apps.dx.dx_layer1.collection_statistics import automatic
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check
from apps.dx.dx_layer2 import seg_sources as config, seg_validation as nulls
from apps.dx.dx_layer3.cross_field import seg_sources as crossfield
from tests.unit.support import ScriptedCursor

DAY = date(2026, 10, 25)
KEY = 'seg_ldy_dryer'
FIELDS = {'sku', 'retailer_sku_name', 'final_sku_price', 'count_of_reviews',
          'count_of_star_ratings', 'star_rating', 'capacity', 'loading_type'}


class MediamarktDryerTests(unittest.TestCase):
    def test_original_date_and_schema_in_counts_history_and_batches(self):
        source = sources.get_seg_source(KEY)
        self.assertEqual(('Expert',), sources.active_retailers(source, DAY - timedelta(days=1)))
        self.assertEqual(('Mediamarkt', 'Expert'), sources.active_retailers(source, DAY))
        sql, params = repo.latest_main_counts_query(KEY, DAY)
        self.assertEqual([str(DAY), 'mediamarkt', 'expert'], params)
        self.assertIn(source_date_sql('crawl_datetime'), sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertEqual(str(DAY), source_date_value('2026-10-25T23:59:59-04:00'))
        cursor = ScriptedCursor([{'fetchall': []}])
        repo.get_previous_main_counts(cursor, KEY, DAY)
        self.assertIn("<> 'mediamarkt' OR", cursor.calls[0][0])
        self.assertIn("'2026-10-25'", cursor.calls[0][0])
        cursor = ScriptedCursor([{'fetchall': []}])
        retail_batches.fetch_batch_details(cursor, 'seg_retail', KEY, DAY, 'Mediamarkt')
        self.assertNotIn('page_type', cursor.calls[0][0])

    def test_live_counts_flow_into_statistics_without_summing_main_and_bsr(self):
        rows = [dict(retailer='Mediamarkt', main_count=213, bsr_count=100,
                     actual_count=213, batch_id='m_20261025_092117')]
        with patch.object(repo, 'get_latest_main_batch_counts', side_effect=lambda c, k, d: rows if k == KEY else []), \
                patch.object(repo, 'get_previous_main_counts', return_value=[]):
            check = service.get_layer1_stats(None, DAY, datetime(2026, 10, 26, 12))['check']
        entry = next(r for r in normalize_check(check, 'SEG', DAY)
                     if r['product'] == 'LDY_DRYER' and r['retailer'] == 'Mediamarkt')
        self.assertEqual((213, 100, 213), (entry['main'], entry['bsr'], entry['total']))
        self.assertEqual(str(DAY), entry['active_from'])
        self.assertEqual('db_original', entry['source_date_basis'])
        self.assertEqual('OK', entry['base_status'])

    def test_column_counts_include_optional_values_and_feed_alerts(self):
        cursor = Mock()
        names = columns.ordered_columns(sources.DRYER_COLUMNS)
        counts = {name: 213 for name in names}
        counts.update(sku=201, original_sku_price=127, savings=120)
        cursor.fetchall.return_value = [(str(DAY), 213, *(counts[n] for n in names))]

        @contextmanager
        def connection():
            yield None, cursor

        with patch.object(columns, 'dx_connection', connection), patch.object(
                columns, '_configured_retailers', side_effect=AssertionError('Use actual dryer columns')):
            data = columns.daily_counts('SEG', 'LDY_DRYER', 'Mediamarkt', DAY, 29)
        self.assertEqual(201, data['daily'][-1]['counts']['sku'])
        self.assertIn('original_sku_price', data['columns'])
        self.assertIn('savings', data['columns'])
        self.assertNotIn('ldy_capacity', data['columns'])
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])
        self.assertIn(source_date_sql('source.crawl_datetime'), cursor.execute.call_args.args[0])
        result = attach_comparisons(data, DAY, datetime.fromisoformat('2026-10-26T12:00:00+09:00'))
        self.assertEqual({'insufficient'}, {r['status'] for r in result['comparisons']})
        self.assertEqual(str(DAY), data['active_from'])
        self.assertTrue(any(s['product'] == 'LDY_DRYER' and 'Mediamarkt' in s['retailers']
                            for s in columns.catalog() if s['country'] == 'SEG'))

    def test_null_detail_and_summary_use_exact_allowlist(self):
        self.assertEqual(FIELDS, set(config.get_seg_null_columns(KEY, ' mediamarkt ')))
        row = dict.fromkeys(FIELDS, 'value')
        row.update(id=1, item='I1', sku=' ', star_rating='0', count_of_reviews=0,
                   original_sku_price=None, savings='', bsr_rank=None)
        mapping = dict(inspection_date=str(DAY), source_date=str(DAY), batch_id='m1')
        with patch.object(nulls, '_latest_rows', side_effect=lambda c, d, s, r: ([row] if r == 'Mediamarkt' else [], mapping)), \
                patch.object(nulls, '_load_normal_reviews', return_value={}), \
                patch.object(nulls, 'uses_new_policy', return_value=False):
            result = {'tables': []}
            self.assertEqual(1, nulls.append_null_stats(None, DAY, result, KEY + '_retail'))
            detail = nulls.null_detail(None, DAY, KEY, 'Mediamarkt', 'sku', days=1)
        self.assertEqual(['sku'], detail['results'][0]['null_fields'])
        self.assertEqual(FIELDS, set(detail['editable_cols']))
        self.assertEqual('crawl_datetime', detail['date_column'])
        self.assertNotIn('page_type', detail['select_cols'])
        self.assertFalse(nulls._missing('0'))
        self.assertTrue(nulls._missing(None))
        self.assertTrue(nulls._missing(''))
        self.assertIn("'mediamarkt'", config.record_scope(config.get_seg_source(KEY), DAY))
        self.assertNotIn("'mediamarkt'", config.record_scope(config.get_seg_source(KEY), DAY - timedelta(days=1)))
        for registry in (config.SEG_FORMAT_SOURCE_CONFIG, config.SEG_DUPLICATE_SOURCE_CONFIG, crossfield.SEG_SOURCE_CONFIG):
            self.assertEqual(('Mediamarkt', 'Expert'), registry[KEY]['retailers'])

    def test_saved_statistics_missing_new_retailer_are_refreshed(self):
        last_due = DAY + timedelta(days=3)
        days = [last_due - timedelta(days=i) for i in range(3, 112)]
        expert = [dict(product=p, retailer='Expert', bsr=100) for p in sources.EXPERT_COLUMNS]
        with patch.object(automatic.Daily, 'objects') as manager:
            manager.filter.return_value.values_list.return_value = [
                (d, expert if d >= sources.EXPERT_START_DATE else []) for d in days]
            self.assertEqual((DAY, DAY), automatic.history_range('SEG', last_due))
