import json
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory

from apps.dx.dx_layer1.column_statistics import api, services


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

    def test_sea_tv_sku_uses_exists_so_master_duplicates_do_not_inflate_counts(self):
        source = services.select_source('SEA', 'TV', 'Amazon')
        sql, _ = services.query_spec(source, source['retailers'][0], ['sku'], date(2026, 9, 20), date(2026, 9, 23))
        self.assertIn('EXISTS (SELECT 1 FROM public.tv_item_mst', sql)
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
        with patch.object(api, 'daily_counts', return_value={'columns': ['item']}) as query:
            response = api.daily(self.factory.get('/', {'date': '2026-09-20'}))
            self.assertEqual(json.loads(response.content)['columns'], ['item'])
            api.daily(self.factory.get('/', {'date': '2026-09-20'}))
            self.assertEqual(query.call_count, 1)
            api.daily(self.factory.get('/', {'date': '2026-09-20', 'retailer': 'Walmart'}))
            self.assertEqual(query.call_count, 2)
