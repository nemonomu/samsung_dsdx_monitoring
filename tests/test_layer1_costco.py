"""Costco Layer 1 integration tests; isolated SQLite and mocked source reads only."""
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=['apps.dx.dx_layer1'],
                       DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
                       USE_TZ=True, TIME_ZONE='Asia/Seoul', SECRET_KEY='costco-tests')
import django
django.setup()
from django.test import SimpleTestCase, TestCase
from django.test.runner import DiscoverRunner
from apps.common.sea_collection import KST
from apps.dx.dx_layer1.retail import costco, retail_repositories as repo, retail_services as retail
from apps.dx.dx_layer1.dashboard import collection_services as dday, collection_repositories as dday_repo
from apps.dx.dx_layer1.column_statistics import services as columns, comparison
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.collection_statistics import collector, automatic
from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily, CollectionWeeklySnapshot as Weekly
from apps.dx.dx_layer4.collection_status.email_registry import EMAIL_REPORT_SOURCES


@contextmanager
def connection(cursor=None):
    yield None, cursor or MagicMock()


class CostcoTests(SimpleTestCase):
    def test_monitoring_starts_october_fourth(self):
        self.assertFalse(costco.enabled('2026-10-03'))
        self.assertTrue(costco.enabled('2026-10-04'))
        cursor = MagicMock()
        self.assertIsNone(repo.get_latest_appliance_main_batch(
            cursor, 'public.ref_retail_com', 'crawl_strdatetime', '2026-10-03', 'Costco'))
        cursor.execute.assert_not_called()
        source = columns.select_source('SEA', 'REF', 'Costco')
        retailer = next(r for r in source['retailers'] if r['name'] == 'Costco')
        _, params = columns.query_spec(source, retailer, ['item'], date(2026, 9, 20), date(2026, 10, 6))
        self.assertIn('2026-10-04', params)

    def test_deadline_in_kst_and_naive_kst(self):
        day = date(2026, 10, 6)
        for stamp, expected in [(datetime(2026, 10, 6, 14, 59, tzinfo=KST), False),
                                (datetime(2026, 10, 6, 15, tzinfo=KST), True),
                                (datetime(2026, 10, 6, 15), True)]:
            self.assertEqual(costco.complete(day, stamp), expected)
            for product in ('TV', 'REF', 'LDY'):
                self.assertEqual(comparison.collection_complete('SEA', product, 'Costco', day, stamp.replace(tzinfo=KST)), expected)

    def test_dday_zero_received_and_error_are_distinct(self):
        for hour, minute, count, expected in [(12, 59, 0, 'scheduled'), (13, 0, 0, 'waiting'),
                                              (14, 59, 0, 'waiting'), (15, 0, 0, 'uncollected'),
                                              (15, 1, 91, 'received')]:
            with patch.object(dday, 'dx_connection', connection), patch.object(
                    dday, 'fetch_collection', return_value=(count, '2026-10-06 13:03:13', 'c6', count, count)):
                result = dday.get_collection_status(date(2026, 10, 6), datetime(2026, 10, 6, hour, minute, tzinfo=KST))
            rows = [r for r in result['retailers'] if r['retailer'] == 'Costco']
            self.assertEqual(len(rows), 3)
            self.assertEqual({r['status'] for r in rows}, {expected})
        with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection', side_effect=RuntimeError):
            result = dday.get_collection_status(date(2026, 10, 6), datetime(2026, 10, 6, 16, tzinfo=KST))
        self.assertTrue(all(r['status'] == 'error' and r['count'] is None for r in result['retailers']))

    def test_latest_combined_batch_counts_all_products(self):
        for product, main, bsr, total in [('tv', 90, 89, 91), ('ref', 205, 100, 205), ('ldy', 300, 100, 304)]:
            cursor = MagicMock()
            cursor.fetchone.side_effect = [('c6',), (main, bsr, 0, total)]
            column = 'crawl_datetime' if product == 'tv' else 'crawl_strdatetime'
            result = repo.query_appliance_counts_by_retailer(cursor, f'public.{product}_retail_com', column, '2026-10-06', 'Costco')
            self.assertEqual(result, (main, bsr, 0, total, 'c6'))
            for call in cursor.execute.call_args_list:
                self.assertNotIn('page_type', call.args[0])
                self.assertIn("AT TIME ZONE 'Asia/Seoul'", call.args[0])
            self.assertIn('batch_id IS NOT DISTINCT FROM %s', cursor.execute.call_args.args[0])

    def test_tv_summary_replaces_all_batch_costco_count(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [('Walmart', 300, 300, 100, 0, 'w'), ('Costco', 182, 180, 178, 0, 'old, new')]
        cursor.fetchone.side_effect = [('new',), (90, 89, 0, 91)]
        rows = repo.query_retail_counts(cursor, 'public.tv_retail_com', 'crawl_datetime::timestamp',
                                       'promotion_position', '2026-10-06 00:00:00', '2026-10-07 00:00:00')
        self.assertEqual(rows[-1], ('Costco', 91, 90, 89, 0, 'new'))
        self.assertEqual(len(rows), 2)

    def test_dday_query_parses_utc_instead_of_assuming_new_york(self):
        cursor = MagicMock()
        for source in dday_repo.SOURCES:
            if source[0] != 'Costco':
                continue
            dday_repo.fetch_collection(cursor, source, date(2026, 10, 6))
            sql = cursor.execute.call_args.args[0]
            self.assertIn('::timestamptz', sql)
            self.assertNotIn('America/New_York', sql)
            self.assertNotIn('page_type', sql)

    def test_layer1_d_minus_one_and_cutoff_do_not_use_other_retailer_schedule(self):
        source = retail._get_layer1_source('tv')
        for hour, status in [(14, 'COLLECTING'), (15, 'CRITICAL')]:
            with patch.object(retail, '_matching_schedule_slots', return_value=[]), patch.object(retail, '_source_rows', return_value=[]):
                category, _, _ = retail._build_category(MagicMock(), source, date(2026, 10, 7), datetime(2026, 10, 6, hour))
            row = next(r for r in category['time_slots'][0]['retailers'] if r['retailer'] == 'Costco')
            self.assertEqual(category['source_date'], '2026-10-06')
            self.assertEqual(row['status'], status)

    def test_catalog_columns_and_queries_are_layer1_only(self):
        self.assertFalse(any(r['name'] == 'Costco' for s in EMAIL_REPORT_SOURCES for r in s['retailers']))
        for product in ('TV', 'REF', 'LDY'):
            source = columns.select_source('SEA', product, 'Costco')
            retailer = next(r for r in source['retailers'] if r['name'] == 'Costco')
            fields = columns.ordered_columns(costco.COLUMNS[product.lower()])
            sql, _ = columns.query_spec(source, retailer, fields, date(2026, 10, 5), date(2026, 10, 10))
            self.assertNotIn('page_type', sql)
            self.assertIn('latest AS', sql)
            self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
            date_column = 'crawl_datetime' if product == 'TV' else 'crawl_strdatetime'
            self.assertIn(costco.source_date_sql('source.' + date_column), sql)
            self.assertNotIn('CAST(source.batch_id AS TEXT)', sql)
            self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.chosen_batch', sql)
            self.assertIn('product_url', fields)
            self.assertIn('savings', fields)
            if product == 'TV':
                self.assertNotIn('sku', fields)
                self.assertNotIn('tv_item_mst', sql)

    def test_existing_sea_tv_keeps_batch_date_after_costco_query(self):
        source = columns.select_source('SEA', 'TV', 'Costco')
        retailer = next(r for r in source['retailers'] if r['name'] == 'Costco')
        columns.query_spec(source, retailer, ['item'], date(2026, 10, 4), date(2026, 10, 6))
        self.assertEqual('batch_id', source['date_column'])
        for retailer in source['retailers']:
            if retailer['name'] == 'Costco':
                continue
            sql, _ = columns.query_spec(source, retailer, ['item'], date(2026, 10, 4), date(2026, 10, 6))
            self.assertIn("substring(CAST(source.batch_id AS TEXT) from '([0-9]{8})')", sql)
            self.assertNotIn('::timestamptz', sql)

    def test_costco_column_history_requires_five_valid_prior_days(self):
        target = date(2026, 10, 10)
        daily = [{'date': str(target - timedelta(days=i)), 'total': 100, 'counts': {'item': 100}} for i in range(5, 0, -1)]
        daily.append({'date': str(target), 'total': 50, 'counts': {'item': 50}})
        data = {'country': 'SEA', 'retailer': 'Costco', 'product': 'TV', 'daily': daily, 'columns': ['item']}
        completed = {r['date']: True for r in daily}
        row = comparison.compare_columns(data, target, completed)[0]
        self.assertEqual((row['baseline'], row['status'], row['history_days']), (100, 'review', 5))
        row = comparison.compare_columns({**data, 'daily': daily[1:]}, target, completed)[0]
        self.assertEqual(row['status'], 'insufficient')
        self.assertEqual(comparison.minimum_days({**data, 'retailer': 'Walmart'}), 7)

    def test_five_day_observation_then_median_review_for_main_and_bsr(self):
        current = dict(product='TV', retailer='Costco', slot='일일', main=80, bsr=75, total=91,
                       complete=True, base_status='OK', baseline_eligible=True)
        history = [{**current, 'source_date': f'2026-10-0{i}', 'main': n, 'bsr': 89}
                   for i, n in zip(range(5, 10), [90, 90, 100, 100, 900])]
        observing = calc.compare_rows([current], history[:4], 'SEA')[0]
        self.assertEqual(observing['observation_state'], 'observing')
        self.assertEqual(observing['alerts'], [])
        ready = calc.compare_rows([current], history, 'SEA')[0]
        self.assertEqual(ready['baselines']['main']['value'], 100)
        self.assertEqual(ready['baselines']['bsr']['value'], 89)
        self.assertEqual({a['status'] for a in ready['alerts']}, {'VOLUME_REVIEW'})
        self.assertEqual(set(calc.comparison_rules(ready, 'SEA')), {'main', 'bsr'})

    def test_original_detail_uses_all_requested_columns_and_latest_batch(self):
        for product in ('tv', 'ref', 'ldy'):
            with patch.object(retail, 'dx_connection', connection), patch.object(repo, 'get_latest_appliance_main_batch', return_value='c6'), patch.object(repo, 'get_appliance_raw_data_list', return_value=[{'id': 1}]) as raw:
                result = retail.get_retailer_raw_data(product, 'Costco', '일일', date(2026, 10, 7))
            self.assertNotIn('error', result)
            self.assertEqual(result['batch_id'], 'c6')
            self.assertEqual(result['columns'], list(costco.COLUMNS[product]))
            self.assertEqual(raw.call_args.args[-1], date(2026, 10, 6))

    def test_column_information_includes_costco_without_mutating_shared_config(self):
        original = {'Bestbuy': ['item']}
        with patch.object(retail, 'get_all_retailer_columns', return_value=original):
            info = retail.get_retailer_columns_info()
        self.assertNotIn('Costco', original)
        for product in ('tv', 'ref', 'ldy'):
            self.assertEqual(info[product]['columns']['Costco'], list(costco.COLUMNS[product]))


class CostcoSnapshotTests(TestCase):
    def test_collector_publishes_three_products_with_five_day_medians(self):
        def loader(country, inspection):
            count = 80 if inspection == date(2026, 10, 11) else 100
            return {'check_type': 'retail', 'categories': [
                {'name': product, 'time_slots': [{'name': '일일', 'retailers': [
                    {'retailer': 'Costco', 'count': count, 'batch_id': 'c' + str(inspection),
                     'status': 'OK', 'collection_phase': 'complete',
                     'items': [{'name': 'Main Rank', 'count': count}, {'name': 'BSR Rank', 'count': 89}]}]}]}
                for product in ('TV', 'REF', 'LDY')]}
        result = collector.refresh_country('SEA', date(2026, 10, 5), date(2026, 10, 10),
                                           loader=loader, today=date(2026, 10, 11))
        self.assertEqual(result['errors'], 0)
        self.assertEqual(result['updated'], 6)
        first = Daily.objects.get(source_date=date(2026, 10, 5))
        self.assertTrue(all(r['observation_state'] == 'observing' and r['observation_days'] == 1 for r in first.rows))
        latest = Daily.objects.get(source_date=date(2026, 10, 10))
        self.assertEqual({r['product'] for r in latest.rows}, {'TV', 'REF', 'LDY'})
        for row in latest.rows:
            self.assertEqual(row['observation_state'], 'ready')
            self.assertEqual(row['baselines']['main']['value'], 100)
            self.assertEqual(row['alerts'][0]['status'], 'VOLUME_REVIEW')
        self.assertTrue(Weekly.objects.exists())

    def test_history_with_missing_costco_is_backfilled(self):
        end = date(2026, 10, 10)
        from django.utils import timezone
        complete = [{'product': p, 'retailer': 'Costco', 'bsr': 89} for p in ('TV', 'REF', 'LDY')]
        Daily.objects.bulk_create([
            Daily(country='SEA', source_date=end - timedelta(days=i),
                  inspection_date=end - timedelta(days=i - 1), rows=complete,
                  digest='test', updated_at=timezone.now()) for i in range(3, 112)])
        self.assertIsNone(automatic.history_range('SEA', end))
        Daily.objects.filter(source_date=date(2026, 10, 5)).update(rows=[])
        self.assertEqual(automatic.history_range('SEA', end), (date(2026, 10, 5), date(2026, 10, 5)))


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests([
        '__main__', 'tests.unit.test_layer1_column_statistics'])))
