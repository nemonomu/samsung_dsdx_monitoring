import json
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory

from apps.dx.dx_layer1.column_statistics import api, services
from apps.dx.dx_layer1.column_statistics.comparison import (
    KST, compare_columns, collection_complete,
)


class ColumnStatisticsTests(unittest.TestCase):
    def test_order_and_exclusions_do_not_depend_on_missing_counts(self):
        columns = ['savings', 'star_rating', 'offer', 'id', 'sku', 'item',
                   'main_rank', 'bsr_rank', 'crawl_datetime', 'country',
                   'account_name', 'calendar_week', 'discount_type', 'item']
        self.assertEqual(services.ordered_columns(columns), [
            'item', 'sku', 'star_rating', 'savings', 'discount_type', 'offer'])

    def test_catalog_has_all_countries_and_no_all_selection(self):
        self.assertEqual({s['country'] for s in services.catalog()},
                         {'SEA', 'SEDA', 'SEG', 'SIEL', 'SEM', 'TSE'})
        for country, product, retailer in [('ALL', 'TV', 'Amazon'),
                                           ('SEA', 'TV', "Amazon'; SELECT 1"),
                                           ('SEG', 'LDY', 'Amazon')]:
            with self.assertRaises(ValueError):
                services.select_source(country, product, retailer)

    def test_home_depot_types_are_required_even_when_config_skips_them(self):
        from apps.dx.dx_layer4.collection_status.email_services import _configured_retailers
        for product, field in [('REF', 'ref_refrigerator_type'), ('LDY', 'ldy_loading_type')]:
            source = services.select_source('SEA', product, 'HomeDepot')
            source = {**source, 'retailers': tuple(r for r in source['retailers'] if r['name'] == 'HomeDepot')}
            cursor = MagicMock()
            cursor.fetchall.return_value = [('item', 'HomeDepot', False), (field, 'HomeDepot', True)]
            self.assertIn(field, _configured_retailers(cursor, source)[0]['columns'])

    def test_home_depot_dates_and_batch_are_consistent_with_email(self):
        source = services.select_source('SEA', 'REF', 'HomeDepot')
        retailer = next(r for r in source['retailers'] if r['name'] == 'HomeDepot')
        sql, params = services.query_spec(source, retailer, ['item', 'ref_refrigerator_type'], date(2026, 9, 20), date(2026, 9, 23))
        self.assertIn("AT TIME ZONE 'America/New_York'", sql)
        self.assertNotIn('source.page_type', sql)
        self.assertIn('IS NOT DISTINCT FROM latest.chosen_batch', sql)
        self.assertIn("'2026-09-20'", sql)
        self.assertEqual(params, ['homedepot', '2026-09-20', '2026-09-23', 'homedepot'])

    def test_counts_use_presence_without_discount_or_numeric_value_rules(self):
        source = services.select_source('SEA', 'TV', 'Bestbuy')
        retailer = source['retailers'][1]
        sql, _ = services.query_spec(source, retailer, ['original_sku_price', 'star_rating'], date(2026, 9, 20), date(2026, 9, 23))
        self.assertNotIn('savings', sql)
        self.assertNotIn(' > 0', sql)
        self.assertIn('source.star_rating IS NULL', sql)
        self.assertNotIn('latest AS', sql)

    def test_sea_tv_sku_uses_uncorrelated_membership_without_joining_master_rows(self):
        source = services.select_source('SEA', 'TV', 'Amazon')
        sql, _ = services.query_spec(source, source['retailers'][0], ['sku'], date(2026, 9, 20), date(2026, 9, 23))
        self.assertIn('sku_keys AS MATERIALIZED', sql)
        self.assertIn('FROM public.tv_item_mst WHERE sku IS NOT NULL', sql)
        self.assertIn('CASE WHEN source.item IS NULL', sql)
        self.assertIn('(SELECT account_name FROM sku_keys WHERE item IS NULL)', sql)
        self.assertIn('(SELECT item, account_name FROM sku_keys WHERE item IS NOT NULL)', sql)
        self.assertNotIn('JOIN sku_keys', sql)
        self.assertNotIn('EXISTS (SELECT 1 FROM public.tv_item_mst', sql)
        self.assertIn('source.redirect, FALSE) IS NOT TRUE', sql)

    def test_missing_days_are_zero_totals_and_collected_zero_is_retained(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [('2026-09-23', 10, 10, 0)]
        @contextmanager
        def connection():
            yield None, cursor
        def configured(_cursor, source):
            self.assertEqual([r['name'] for r in source['retailers']], ['Amazon'])
            return [{**source['retailers'][0], 'columns': ('item', 'savings')}]
        with patch.object(services, 'dx_connection', connection), patch.object(services, '_configured_retailers', configured):
            result = services.daily_counts('SEA', 'TV', 'Amazon', date(2026, 9, 23), 2)
        self.assertEqual(result['daily'][0], {'date': '2026-09-22', 'total': 0, 'counts': {'item': 0, 'savings': 0}})
        self.assertEqual(result['daily'][1]['counts']['savings'], 0)
        self.assertEqual(result['daily'][1]['total'], 10)

    def test_discontinued_fields_are_absent_from_statistics_and_alert_comparisons(self):
        policies = (
            ('SEG', ('TV', 'REF', 'LDY'), 'OTTO', 'summarized_review_content'),
            ('SEA', ('REF', 'LDY'), 'Lowes', 'available_quantity_for_purchase_fastdelivery'),
            ('SIEL', ('TV', 'REF', 'LDY'), 'Amazon', 'fastest_delivery'),
        )
        for country, products, retailer, field in policies:
            for product in products:
                with self.subTest(country=country, product=product, retailer=retailer):
                    cursor = MagicMock()
                    # A stale active DB setting must not restore a discontinued field.
                    cursor.fetchall.side_effect = [
                        [('item', retailer, False), (field, retailer, False)], [],
                    ]
                    @contextmanager
                    def connection():
                        yield None, cursor
                    with patch.object(services, 'dx_connection', connection):
                        data = services.daily_counts(country, product, retailer, date(2026, 9, 23), 29)
                    self.assertIn('item', data['columns'])
                    self.assertNotIn(field, data['columns'])
                    self.assertTrue(all(field not in day['counts'] for day in data['daily']))
                    self.assertNotIn('source.' + field, cursor.execute.call_args.args[0])
                    comparisons = compare_columns(data, date(2026, 9, 23), {day['date']: True for day in data['daily']})
                    self.assertNotIn(field, [row['column'] for row in comparisons])


class ColumnStatisticsApiTests(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_invalid_selection_and_unbounded_period_do_not_query_database(self):
        with patch.object(api, 'daily_counts') as query:
            for params in [{'country': 'ALL'}, {'days': '500'}, {'date': '2026-02-30'}, {'date': '9999-12-31'}]:
                self.assertEqual(api.daily(self.factory.get('/', params)).status_code, 400)
            query.assert_not_called()

    def test_query_failure_is_not_shown_as_zero_or_cached(self):
        with patch.object(api, 'daily_counts', side_effect=RuntimeError('private database detail')) as query:
            for _ in range(2):
                response = api.daily(self.factory.get('/', {'date': '2026-09-20'}))
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private', response.content.decode())
            self.assertEqual(query.call_count, 2)

    def test_success_is_cached_per_selection(self):
        fixture = {'columns': ['item'], 'dates': ['2026-09-20'], 'daily': []}
        with patch.object(api, 'daily_counts', return_value=fixture) as query, \
                patch.object(api, 'attach_comparisons', side_effect=lambda data, _: dict(data)):
            response = api.daily(self.factory.get('/', {'date': '2026-09-20'}))
            self.assertEqual(json.loads(response.content)['columns'], ['item'])
            api.daily(self.factory.get('/', {'date': '2026-09-20'}))
            self.assertEqual(query.call_count, 1)
            api.daily(self.factory.get('/', {'date': '2026-09-20', 'retailer': 'Walmart'}))
            self.assertEqual(query.call_count, 2)

    def test_baseline_window_is_independent_of_display_days_and_cache_is_not_trimmed(self):
        dates = [str(date(2026, 9, 20) - timedelta(days=28-i)) for i in range(29)]
        fixture = {'columns': ['item'], 'dates': dates, 'daily': [{'date': d} for d in dates]}
        with patch.object(api, 'daily_counts', return_value=fixture) as query, \
                patch.object(api, 'attach_comparisons', side_effect=lambda data, _: dict(data)):
            first = json.loads(api.daily(self.factory.get('/', {'date': '2026-09-20', 'days': 5})).content)
            second = json.loads(api.daily(self.factory.get('/', {'date': '2026-09-20', 'days': 14})).content)
            self.assertEqual(len(first['daily']), 5)
            self.assertEqual(len(second['daily']), 14)
            self.assertEqual(query.call_count, 1)
            self.assertEqual(query.call_args.args[-1], 29)


class ColumnComparisonTests(unittest.TestCase):
    target = date(2026, 9, 23)

    def compare(self, current, history=None, *, target_complete=True, total=300):
        history = [100] * 7 if history is None else history
        daily = [{'date': str(self.target - timedelta(days=i+1)), 'total': 300, 'counts': {'item': count}}
                 for i, count in enumerate(history)]
        daily.append({'date': str(self.target), 'total': total, 'counts': {'item': current}})
        complete = {day['date']: True for day in daily}
        complete[str(self.target)] = target_complete
        return compare_columns({'columns': ['item'], 'daily': daily}, self.target, complete)[0]

    def test_exact_thresholds_and_increase(self):
        for count, status in [(0, 'abnormal'), (30, 'abnormal'), (31, 'review'), (60, 'review'), (61, 'normal'), (150, 'normal')]:
            with self.subTest(count=count):
                row = self.compare(count)
                self.assertEqual(row['status'], status)
                self.assertEqual(row['ratio'], count)
                self.assertEqual(row['delta'], count - 100)

    def test_current_date_and_outliers_do_not_distort_median(self):
        row = self.compare(30, [100, 100, 100, 100, 100, 100, 10000])
        self.assertEqual(row['baseline'], 100)
        self.assertEqual(row['history_days'], 7)
        self.assertEqual(row['status'], 'abnormal')

    def test_28_day_window_excludes_older_values(self):
        row = self.compare(30, [100] * 28 + [9000] * 20)
        self.assertEqual(row['baseline'], 100)
        self.assertEqual(row['history_days'], 28)

    def test_unavailable_states_never_generate_alert(self):
        self.assertEqual(self.compare(0, [100] * 6)['status'], 'insufficient')
        self.assertEqual(self.compare(0, [0] * 7)['status'], 'no_baseline')
        self.assertEqual(self.compare(0, target_complete=False)['status'], 'pending')
        self.assertEqual(self.compare(0, total=0)['status'], 'uncollected')

    def test_pending_and_wholly_missing_history_are_excluded(self):
        daily = [{'date': str(self.target-timedelta(days=i)), 'total': 300, 'counts': {'item': 100}}
                 for i in range(9)]
        complete = {d['date']: True for d in daily}
        complete[daily[1]['date']] = False
        daily[2]['total'] = 0
        row = compare_columns({'columns': ['item'], 'daily': daily}, self.target, complete)[0]
        self.assertEqual(row['history_days'], 6)
        self.assertEqual(row['status'], 'insufficient')

    def test_zero_field_history_is_retained_when_products_were_collected(self):
        row = self.compare(20, [0, 0, 0, 100, 100, 100, 100])
        self.assertEqual(row['history_days'], 7)
        self.assertEqual(row['baseline'], 100)

    def test_seda_completion_respects_source_date_offset(self):
        now = datetime(2026, 9, 23, 20, tzinfo=KST)
        self.assertFalse(collection_complete('SEDA', 'TV', 'Magalu', self.target, now))
        self.assertTrue(collection_complete('SEDA', 'TV', 'Magalu', self.target-timedelta(days=1), now))

    def test_sea_uses_retailer_specific_schedule_and_missing_schedule_is_not_complete(self):
        now = datetime(2026, 9, 23, 13, tzinfo=KST)
        slots = [{'retailers': [{'name': 'Amazon'}], 'time_status': None},
                 {'retailers': [{'name': 'Walmart'}], 'time_status': 'COLLECTING'}]
        with patch('apps.common.dx_schedules.get_retail_time_slots', return_value=slots):
            self.assertTrue(collection_complete('SEA', 'TV', 'Amazon', self.target, now))
            self.assertFalse(collection_complete('SEA', 'TV', 'Walmart', self.target, now))
            self.assertFalse(collection_complete('SEA', 'TV', 'Bestbuy', self.target, now))
            self.assertTrue(collection_complete('SEA', 'REF', 'Bestbuy', self.target-timedelta(days=1), now))

    def test_homedepot_launch_and_collection_end(self):
        now = datetime(2026, 9, 23, 13, 59, tzinfo=KST)
        self.assertFalse(collection_complete('SEA', 'REF', 'HomeDepot', self.target, now))
        self.assertTrue(collection_complete('SEA', 'REF', 'HomeDepot', self.target, now+timedelta(minutes=1)))
        self.assertFalse(collection_complete('SEA', 'REF', 'HomeDepot', date(2026, 9, 19), now))
