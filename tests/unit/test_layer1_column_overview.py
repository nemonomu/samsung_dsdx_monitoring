"""Country overview reads existing comparisons without recording incidents."""
import json
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from django.test import RequestFactory

from apps.dx.dx_layer1.column_statistics import api, overview, reviews
from apps.dx.dx_layer1.column_statistics.comparison import KST
from apps.dx.dx_layer1.column_statistics.dates import day_range_sql


DAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 25, 15, tzinfo=KST)
SCOPE = ('SIEL', 'TV', 'Amazon')


def raw_window(scope=SCOPE, end=DAY, days=29, last_value=20):
    country, product, retailer = scope
    dates = [str(end - timedelta(days=days - 1 - offset)) for offset in range(days)]
    daily = [{'date': day, 'total': 100, 'counts': {'sku': 100}} for day in dates]
    daily[-1]['counts']['sku'] = last_value
    return {'country': country, 'product': product, 'retailer': retailer, 'columns': ['sku'],
            'dates': dates, 'daily': daily, 'updated_at': NOW.isoformat()}


class ColumnOverviewTests(unittest.TestCase):
    def test_country_filter_resolves_all_scopes_and_preserves_source_date(self):
        siel = overview.selected_scopes('SIEL', 'all', 'all', DAY)
        self.assertEqual(len(siel), 9)
        self.assertEqual({source_day for _, source_day in siel}, {DAY})
        jiomart = overview.selected_scopes('SIEL', 'all', 'Jiomart', DAY)
        self.assertEqual([scope[1] for scope, _ in jiomart], ['TV', 'REF', 'LDY'])
        usa = overview.selected_scopes('SEA', 'TV', 'all', DAY)
        self.assertEqual({source_day for _, source_day in usa}, {DAY - timedelta(days=1)})
        with self.assertRaises(ValueError):
            overview.selected_scopes('SIEL', 'all', 'Currys', DAY)

    def test_preparation_reuses_the_existing_history_and_reads_only_one_extra_day(self):
        history = raw_window(days=31)
        next_day = DAY + timedelta(days=1)
        file_cache = Mock()
        with patch.object(overview, '_prepared_cache', return_value=file_cache), \
                patch.object(overview, 'daily_counts', return_value=raw_window(end=next_day, days=1)) as counts, \
                patch.object(overview, 'raw_counts', return_value={str(next_day): 142}):
            overview.prepare_recent(history, {str(DAY): 117}, [DAY], DAY, NOW, 'test')
        counts.assert_called_once_with(*SCOPE, next_day, 1)
        snapshots = [call.args[1] for call in file_cache.set.call_args_list]
        self.assertEqual([snap['daily'][-1]['raw_total'] for snap in snapshots], [117, 142])
        self.assertEqual(snapshots[1]['dates'], [*history['dates'][-28:], str(next_day)])
        self.assertNotIn('raw_total', history['daily'][-1])

    def test_open_collection_is_not_prepared_as_a_finished_snapshot(self):
        early = NOW.replace(hour=1)
        file_cache = Mock()
        with patch.object(overview, '_prepared_cache', return_value=file_cache), \
                patch.object(overview, 'daily_counts') as counts:
            overview.prepare_recent(raw_window(), {str(DAY): 101}, [DAY], DAY, early, 'test')
        counts.assert_not_called()
        file_cache.set.assert_called_once()

    def test_overview_shows_confirmed_state_and_identifies_failed_scopes(self):
        prepared = overview._window(raw_window(), DAY, {str(DAY): 100}, NOW)
        comparison = overview._compare(prepared, DAY, NOW)
        fingerprint = reviews.fingerprint(reviews.context_for(comparison, comparison['comparisons'][0]))
        failed = (('SIEL', 'REF', 'Flipkart'), DAY)
        with patch.object(overview, '_prepared_counts', return_value={(SCOPE, DAY): prepared}), \
                patch.object(overview, '_live_counts', side_effect=RuntimeError('DB unavailable')) as live, \
                patch.object(overview, '_active_reviews', return_value={fingerprint}) as review_query, \
                self.assertLogs(overview.logger, level='WARNING'):
            result = overview.country_overview('SIEL', [(SCOPE, DAY), failed], include_reviews=True, now=NOW)
        live.assert_called_once_with(*failed)
        review_query.assert_called_once()
        row, error = result['rows']
        self.assertEqual(row['column_count'], 1)
        self.assertEqual(row['total'], 100)
        self.assertEqual(row['comparisons'], [{'column': 'sku', 'status': 'abnormal', 'review': {'active': True}}])
        self.assertEqual(error, {'product': 'REF', 'retailer': 'Flipkart', 'comparison_date': str(DAY), 'error': True})

    def test_country_request_uses_the_new_summary_without_requesting_details(self):
        factory = RequestFactory()
        with patch.object(overview, 'country_overview', return_value={'rows': []}) as summary:
            response = api.overview(factory.get('/dx/layer1/api/column-statistics/overview/',
                                                {'country': 'SIEL', 'date': str(DAY)}))
            invalid = api.overview(factory.get('/dx/layer1/api/column-statistics/overview/',
                                               {'country': 'SIEL', 'product': 'INVALID', 'date': str(DAY)}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(json.loads(response.content)['product'], 'all')
        self.assertEqual(len(summary.call_args.args[1]), 9)

    def test_native_siel_query_uses_kst_bounds_and_text_sources_keep_original_day(self):
        siel = {'country': 'SIEL', 'key': 'siel_tv', 'date_column': 'crawl_datetime'}
        seuk = {'country': 'SEUK', 'key': 'seuk_tv', 'date_column': 'crawl_datetime'}
        self.assertEqual(day_range_sql(siel).count("AT TIME ZONE 'Asia/Seoul'"), 2)
        self.assertIn("source.crawl_datetime < ((%s::date + 1)", day_range_sql(siel))
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)', day_range_sql(seuk))
