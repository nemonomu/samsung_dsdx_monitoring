"""HomeDepot dryer cross-field checks reuse the SEM HomeDepot contract."""

import unittest
import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from django.test import RequestFactory
from apps.common.sem_retail import SEM_SOURCE_CONFIG, get_sem_editable_columns
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer2.sem_validation import _latest_rows
from apps.dx.dx_layer3.cross_field import sem_services
from apps.dx.dx_layer3.cross_field import api as crossfield_api
from apps.dx.dx_layer3.common import context as layer3_context
from apps.dx.dx_layer3.data_edit.services import _select_sem_record
from tests.unit.support import ScriptedCursor


DAY = date(2026, 10, 19)
KEY = 'sem_ldy_dryer'
TABLE = 'dx_sem.dx_sem_ldy_dryer_retail_com'
MAPPING = {'inspection_date': str(DAY), 'source_date': str(DAY), 'offset_days': 0}


def dryer(**changes):
    row = {
        'id': 101, 'batch_id': 'h20261019_010046', 'country': 'SEM',
        'account_name': 'HomeDepot', 'item': '126443',
        'crawl_datetime': '2026-10-19T01:10:00-06:00',
        'count_of_reviews': '378', 'star_rating': '4.3',
        'count_of_star_ratings': '378',
        'final_sku_price': '$9,599.00',
        'original_sku_price': '$15,479.00', 'savings': '-37%',
        'capacity': '22 kg', 'loading_type': None,
    }
    row.update(changes)
    return row


class SemDryerCrossfieldTests(unittest.TestCase):
    def test_eight_existing_homedepot_rules_and_discount_floor(self):
        self.assertEqual('2026-10-19', source_date_value(dryer()['crawl_datetime']))
        self.assertEqual([], sem_services._failed_rules(dryer(), 'HomeDepot', KEY))
        self.assertEqual([], sem_services._failed_rules(
            dryer(original_sku_price=None, savings=None), 'HomeDepot', KEY))
        cases = (
            ({'star_rating': '0'}, 'rating_count_consistency'),
            ({'count_of_reviews': '377'}, 'review_rating_count'),
            ({'original_sku_price': '$0.00'}, 'original_price_zero'),
            ({'final_sku_price': '$15,479.00'}, 'final_original_price'),
            ({'savings': None}, 'savings_missing'),
            ({'original_sku_price': None}, 'original_missing'),
            ({'final_sku_price': None}, 'final_missing'),
            ({'savings': '-38%'}, 'savings_rate_match'),
        )
        for changes, rule in cases:
            with self.subTest(rule=rule):
                self.assertIn(rule, sem_services._failed_rules(
                    dryer(**changes), 'HomeDepot', KEY))

    def test_summary_and_detail_use_only_homedepot_and_raw_day(self):
        target = dryer(savings=None)
        with patch.object(sem_services, '_latest_rows', return_value=([target], MAPPING)) as latest, \
                patch.object(sem_services, 'exclude_page_absent_records',
                             side_effect=lambda _cursor, _date, rows, **_kwargs: (rows, [])) as exclude, \
                patch.object(sem_services, '_history_rows', return_value=[]):
            summary = sem_services.get_sem_cross_field_summary(None, DAY, KEY)
            detail = sem_services.get_sem_cross_field_rule_detail(
                None, DAY, KEY, KEY + ':savings_missing', days=3)

        self.assertEqual(8, len(summary['rule_summary']))
        self.assertEqual(1, summary['total_checked'])
        self.assertEqual(['HomeDepot'], summary['rule_summary'][0]['retailers'])
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual([101], [row['id'] for row in detail['anomalies']])
        self.assertEqual(TABLE, detail['table_name'])
        self.assertIn('savings', detail['retailer_editable_columns']['HomeDepot'])
        self.assertIn('capacity', detail['retailer_columns']['HomeDepot'])
        self.assertIn('loading_type', detail['retailer_columns']['HomeDepot'])
        self.assertEqual('HomeDepot', latest.call_args.kwargs['retailer'])
        self.assertEqual('LDY_DRYER', exclude.call_args.kwargs['product_line'])
        self.assertIn('LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10)',
                      detail['queries']['HomeDepot'])

    def test_source_registry_keeps_existing_null_policy(self):
        self.assertTrue(SEM_SOURCE_CONFIG[KEY]['null_only'])
        self.assertEqual(('HomeDepot', 'Coppel'), SEM_SOURCE_CONFIG[KEY]['retailers'])
        self.assertTrue({'star_rating', 'count_of_star_ratings', 'count_of_reviews',
                         'final_sku_price', 'original_sku_price', 'savings'}
                        <= set(get_sem_editable_columns(KEY, 'HomeDepot')))

    def test_latest_batch_and_edit_use_original_crawl_date(self):
        cursor = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
        rows, mapping = _latest_rows(cursor, DAY, SEM_SOURCE_CONFIG[KEY], 'HomeDepot')
        self.assertEqual([], rows)
        self.assertEqual(str(DAY), mapping['source_date'])
        sql, params = cursor.calls[0]
        self.assertIn('LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10) = %s', sql)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10) = %s', sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id', sql)
        self.assertEqual((str(DAY), 'HomeDepot', str(DAY)), params)

        cursor = ScriptedCursor([{}])
        _select_sem_record(cursor, SEM_SOURCE_CONFIG[KEY], 'source.savings', 101, DAY)
        sql, params = cursor.calls[0]
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10) = %s', sql)
        self.assertIn('LEFT(BTRIM(CAST(anchor.crawl_datetime AS TEXT)), 10) = %s', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertEqual((101, str(DAY), 'SEM', 'homedepot', str(DAY)), params)

    def test_sidebar_and_api_route_dryer_summary_and_detail(self):
        with patch.object(layer3_context, 'load_timeseries_rules', return_value=[]), \
                patch.object(layer3_context, 'load_crossfield_rules', return_value=[]), \
                patch.object(layer3_context, 'load_category_rules', return_value=[]):
            sidebar = layer3_context._get_sidebar_items()
        sem_group = next(group for group in sidebar['cross_field']
                         if isinstance(group, dict) and group.get('name') == 'SEM Retail')
        self.assertEqual(['sem_tv', 'sem_ref', 'sem_ldy', KEY],
                         [item['detail_code'] for item in sem_group['children']])

        @contextmanager
        def connection():
            yield None, None

        factory = RequestFactory()
        with patch.object(crossfield_api, 'dx_connection', connection), \
                patch.object(crossfield_api.sem_services,
                             'get_sem_cross_field_summary', return_value={'configured': True}) as summary, \
                patch.object(crossfield_api.sem_services,
                             'get_sem_cross_field_rule_detail',
                             return_value={'found': True, 'rule_id': KEY + ':savings_missing'}) as detail:
            response = crossfield_api.cross_field_detail(factory.get(
                '/layer3/api/cross-field-detail/', {'date': str(DAY), 'type': KEY}))
            self.assertEqual({'configured': True}, json.loads(response.content))
            summary.assert_called_once_with(None, DAY, KEY)
            response = crossfield_api.cross_field_detail(factory.get(
                '/layer3/api/cross-field-detail/',
                {'date': str(DAY), 'type': KEY,
                 'rule_id': KEY + ':savings_missing', 'days': '3'}))
            self.assertEqual(KEY + ':savings_missing', json.loads(response.content)['rule_id'])
            detail.assert_called_once_with(None, DAY, KEY, KEY + ':savings_missing', 3)


if __name__ == '__main__':
    unittest.main()
