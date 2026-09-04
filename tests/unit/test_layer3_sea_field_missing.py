import unittest
from datetime import date, timedelta
from unittest.mock import patch

from apps.common import inspection_dates
from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


SEA_SOURCES = {
    'ref': {
        'source_key': 'sea_ref',
        'category': 'REF',
        'table_name': 'public.ref_retail_com',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
    },
    'ldy': {
        'source_key': 'sea_ldy',
        'category': 'LDY',
        'table_name': 'public.ldy_retail_com',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
    },
}


def get_sea_source(value):
    key = str(value).lower().replace('sea_', '')
    return SEA_SOURCES[key]


sea_services = load_module(
    'apps/dx/dx_layer3/field_missing/sea_services.py',
    'apps.dx.dx_layer3.field_missing.sea_services',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.sea_retail': module_stub(
            'apps.common.sea_retail', get_sea_retail_source=get_sea_source,
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
        'apps.dx.dx_layer3.field_missing': package_stub(
            'apps.dx.dx_layer3.field_missing'
        ),
    },
)


services = load_module(
    'apps/dx/dx_layer3/field_missing/services.py',
    'layer3_sea_field_missing_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_missing_exclude_conditions=lambda *_args: [],
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda: 'TRUE',
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
        'apps.dx.dx_layer3.field_missing': package_stub(
            'apps.dx.dx_layer3.field_missing'
        ),
        'apps.dx.dx_layer3.field_missing.sea_services': sea_services,
        'apps.dx.dx_layer3.dashboard': package_stub(
            'apps.dx.dx_layer3.dashboard'
        ),
        'apps.dx.dx_layer3.dashboard.services': module_stub(
            'apps.dx.dx_layer3.dashboard.services',
            validate_exclude_condition=lambda _condition: True,
        ),
    },
)

api = load_module(
    'apps/dx/dx_layer3/field_missing/api.py',
    'apps.dx.dx_layer3.field_missing.api',
    {
        'django': package_stub('django'),
        'django.http': module_stub('django.http', JsonResponse=dict),
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_connection=lambda: None
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns', get_editable_columns=lambda *_: []
        ),
        'apps.common.response': module_stub(
            'apps.common.response',
            safe_error=lambda error: {'error': str(error)},
            log_error=lambda _error: None,
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
        'apps.dx.dx_layer3.field_missing': package_stub(
            'apps.dx.dx_layer3.field_missing'
        ),
        'apps.dx.dx_layer3.field_missing.sea_services': sea_services,
        'apps.dx.dx_layer3.field_missing.services': services,
    },
)


class SeaFieldMissingDateTests(unittest.TestCase):
    def test_api_keeps_inspection_date_and_passes_source_date_to_queries(self):
        inspection_date, source_date, contract = api._resolve_request_dates(
            '2026-09-01', 'tv'
        )

        self.assertEqual(date(2026, 9, 1), inspection_date)
        self.assertEqual(date(2026, 8, 31), source_date)
        self.assertEqual('2026-09-01', contract['inspection_date'])
        self.assertEqual('2026-08-31', contract['source_date'])

    def test_tv_maps_inspection_date_to_previous_source_date(self):
        contract = services.resolve_field_missing_date_contract(
            date(2026, 9, 1), 'tv'
        )

        self.assertEqual('2026-09-01', contract['inspection_date'])
        self.assertEqual('2026-08-31', contract['source_date'])
        self.assertEqual(-1, contract['offset_days'])
        self.assertEqual('sea_tv', contract['source_key'])

    def test_ref_and_ldy_use_fixed_requested_columns(self):
        self.assertEqual(
            [
                'ref_capacity', 'ref_refrigerator_type', 'sku',
                'recommendation_intent',
            ],
            services.get_field_missing_validation_columns('sea_ref'),
        )
        self.assertEqual(
            ['ldy_capacity', 'ldy_loading_type', 'sku'],
            services.get_field_missing_validation_columns('sea_ldy'),
        )

    def test_ref_detail_columns_keep_all_configured_columns(self):
        configured = [
            {'column_name': 'final_sku_price', 'related_columns': ''},
            {
                'column_name': 'recommendation_intent',
                'related_columns': 'legacy_related',
            },
            {'column_name': 'detailed_review_content', 'related_columns': ''},
        ]
        retail_columns_stub = module_stub(
            'apps.common.retail_columns',
            get_retail_columns_with_related=lambda *_args: configured,
        )
        with patch.dict(
            'sys.modules',
            {'apps.common.retail_columns': retail_columns_stub},
        ):
            result = api._columns_with_related('sea_ref', 'Bestbuy')

        names = [column['column_name'] for column in result]
        self.assertEqual('final_sku_price', names[0])
        self.assertIn('detailed_review_content', names)
        self.assertIn('ref_capacity', names)
        self.assertIn('ref_refrigerator_type', names)
        self.assertIn('sku', names)
        self.assertEqual(1, names.count('recommendation_intent'))

    def test_recommendation_intent_uses_review_context_by_default(self):
        self.assertEqual(
            [
                'detailed_review_content',
                'count_of_reviews',
                'count_of_star_ratings',
            ],
            services.get_field_missing_default_related_columns(
                'sea_ref', 'recommendation_intent'
            ),
        )

    def test_ref_maps_inspection_date_to_previous_source_date(self):
        contract = services.resolve_field_missing_date_contract(
            date(2026, 9, 1), 'sea_ref'
        )

        self.assertEqual('2026-09-01', contract['inspection_date'])
        self.assertEqual('2026-08-31', contract['source_date'])
        self.assertEqual('sea_ref', contract['source_key'])

    def test_detection_uses_source_date_but_reviews_use_inspection_date(self):
        cursor = ScriptedCursor([
            {'fetchall': [('TV-1', 1, 1)]},
            {'fetchone': (1,)},
            {'fetchall': []},
        ])

        result = services.field_missing_detection(
            cursor,
            date(2026, 8, 31),
            'tv',
            'Amazon',
            {'Amazon': ['sku']},
            inspection_date=date(2026, 9, 1),
        )

        detection_params = cursor.calls[0][1]
        self.assertEqual(
            (
                'Amazon', date(2026, 8, 30), date(2026, 8, 29),
                date(2026, 8, 31),
            ),
            detection_params,
        )
        self.assertEqual(
            ('tv_retail_com', '2026-09-01', 'Amazon'),
            cursor.calls[2][1],
        )
        self.assertEqual('2026-08-31', result['date'])
        self.assertEqual(
            ['2026-08-30', '2026-08-29'], result['prev_dates']
        )
        self.assertEqual(1, result['summary']['total_missing_cases'])

    def test_ref_detects_existing_gap_and_new_null_item(self):
        values = {
            'ref_capacity': '25 cu ft',
            'sku': 'SKU-1',
            'recommendation_intent': '90% would recommend to a friend',
            'detailed_review_content': 'review1 - good',
            'count_of_reviews': 1,
            'count_of_star_ratings': 1,
            'final_sku_price': '$999.99',
            'product_url': 'https://example.test/ref',
        }
        rows = [
            {
                'id': 1, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'OLD-1', 'crawl_strdatetime': '2026-08-30',
                'ref_refrigerator_type': 'French Door', **values,
            },
            {
                'id': 2, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'OLD-1', 'crawl_strdatetime': '2026-08-31',
                'ref_refrigerator_type': None, **values,
            },
            {
                'id': 3, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'NEW-NULL', 'crawl_strdatetime': '2026-08-31',
                'ref_refrigerator_type': None, **values,
            },
            {
                'id': 4, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'NEW-OK', 'crawl_strdatetime': '2026-08-31',
                'ref_refrigerator_type': 'Top Freezer', **values,
            },
        ]
        cursor = ScriptedCursor([
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = services.field_missing_detection(
            cursor, date(2026, 8, 31), 'sea_ref', 'Bestbuy', {},
            inspection_date=date(2026, 9, 1),
        )

        self.assertEqual(2, result['summary']['total_missing_cases'])
        self.assertEqual(1, len(result['missing_fields']))
        finding = result['missing_fields'][0]
        self.assertEqual('ref_refrigerator_type', finding['column'])
        self.assertEqual(1, finding['new_items'])
        self.assertEqual(1, finding['existing_missing_items'])
        sql, params = cursor.calls[0]
        self.assertIn('ranked_batches', sql)
        self.assertIn("IN ('MAIN', 'BSR')", sql)
        self.assertIn('public.ref_retail_com', sql)
        self.assertEqual('Bestbuy', params[2])

    def test_ref_detail_labels_only_first_seen_null_item_as_new(self):
        values = {
            'ref_capacity': '25 cu ft',
            'sku': 'SKU-1',
            'recommendation_intent': '90% would recommend to a friend',
            'detailed_review_content': 'review1 - good',
            'count_of_reviews': 1,
            'count_of_star_ratings': 1,
            'final_sku_price': '$999.99',
            'product_url': 'https://example.test/ref',
        }
        rows = [
            {
                'id': 1, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'OLD-1', 'crawl_strdatetime': '2026-08-30',
                'ref_refrigerator_type': 'French Door', **values,
            },
            {
                'id': 2, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'OLD-1', 'crawl_strdatetime': '2026-08-31',
                'ref_refrigerator_type': None, **values,
                'recommendation_intent': None,
            },
            {
                'id': 3, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'NEW-NULL', 'crawl_strdatetime': '2026-08-31',
                'ref_refrigerator_type': None, **values,
                'recommendation_intent': None,
            },
        ]
        cursor = ScriptedCursor([
            {'fetchall': rows},
            {'fetchall': []},
        ])

        display_fields = (
            services.get_field_missing_validation_columns('sea_ref') + [
                'detailed_review_content', 'count_of_reviews',
                'count_of_star_ratings', 'final_sku_price',
            ]
        )
        related_columns = (
            services.get_field_missing_default_related_columns(
                'sea_ref', 'recommendation_intent'
            )
        )
        result = services.field_missing_detail_by_field(
            cursor, date(2026, 8, 31), 'sea_ref', 'Bestbuy',
            'recommendation_intent', 3, [], display_fields,
            related_columns, ['recommendation_intent'],
            inspection_date=date(2026, 9, 1),
        )

        finding_types = {
            row['item']: row['finding_type'] for row in result['data']
        }
        self.assertEqual('missing', finding_types['OLD-1'])
        self.assertEqual('new', finding_types['NEW-NULL'])
        self.assertEqual(1, result['new_item_count'])
        self.assertNotIn('batch_id', result['columns'])
        self.assertIn('product_url', result['columns'])
        self.assertIn('final_sku_price', result['columns'])
        self.assertEqual(
            [
                'id', 'crawl_strdatetime', 'item',
                'recommendation_intent', 'detailed_review_content',
                'count_of_reviews', 'count_of_star_ratings', 'product_url',
            ],
            result['default_columns'],
        )

    def test_thirty_day_ref_detail_keeps_each_item_in_date_order(self):
        target_date = date(2026, 8, 31)
        rows = []
        row_id = 1
        for item_index in range(4):
            for day in range(29, -1, -1):
                rows.append({
                    'id': row_id,
                    'account_name': 'Bestbuy',
                    'page_type': 'MAIN',
                    'item': f'REF-{item_index}',
                    'crawl_strdatetime': str(
                        target_date - timedelta(days=day)
                    ),
                    'recommendation_intent': (
                        None if day == 0 else
                        '90% would recommend to a friend'
                    ),
                    'product_url': 'https://example.test/ref',
                })
                row_id += 1
        cursor = ScriptedCursor([
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = services.field_missing_detail_by_field(
            cursor, target_date, 'sea_ref', 'Bestbuy',
            'recommendation_intent', 30, [],
            ['recommendation_intent'], ['recommendation_intent'],
            ['recommendation_intent'],
            inspection_date=date(2026, 9, 1),
        )

        self.assertEqual(4, result['today_null_count'])
        self.assertEqual(
            [str(target_date)] * 4,
            [result['data'][index]['crawl_strdatetime']
             for index in (29, 59, 89, 119)],
        )
        self.assertEqual(
            {'REF-0', 'REF-1', 'REF-2', 'REF-3'},
            {result['data'][index]['item']
             for index in (29, 59, 89, 119)},
        )

    def test_thirty_day_display_does_not_change_three_day_classification(self):
        target_date = date(2026, 8, 31)
        rows = [
            {
                'id': 1, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'NEW-IN-WINDOW',
                'crawl_strdatetime': '2026-08-10',
                'recommendation_intent': None,
                'product_url': 'https://example.test/old',
            },
            {
                'id': 2, 'account_name': 'Bestbuy', 'page_type': 'MAIN',
                'item': 'NEW-IN-WINDOW',
                'crawl_strdatetime': str(target_date),
                'recommendation_intent': None,
                'product_url': 'https://example.test/target',
            },
        ]
        cursor = ScriptedCursor([
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = services.field_missing_detail_by_field(
            cursor, target_date, 'sea_ref', 'Bestbuy',
            'recommendation_intent', 30, [],
            ['recommendation_intent'], ['recommendation_intent'],
            ['recommendation_intent'],
            inspection_date=date(2026, 9, 1),
        )

        self.assertEqual(1, result['today_null_count'])
        self.assertEqual(1, result['new_item_count'])
        self.assertEqual(
            ['2026-08-10', '2026-08-31'],
            [row['crawl_strdatetime'] for row in result['data']],
        )

    def test_ldy_detects_new_null_item_in_latest_batch_scope(self):
        rows = [{
            'id': 10,
            'account_name': 'Lowes',
            'page_type': 'MAIN',
            'item': 'NEW-LDY',
            'crawl_strdatetime': '2026-08-31',
            'ldy_capacity': '5.0 cu ft',
            'ldy_loading_type': None,
            'sku': 'LDY-SKU',
            'product_url': 'https://example.test/ldy',
        }]
        cursor = ScriptedCursor([
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = services.field_missing_detection(
            cursor, date(2026, 8, 31), 'sea_ldy', 'Lowes', {},
            inspection_date=date(2026, 9, 1),
        )

        self.assertEqual(1, result['summary']['total_missing_cases'])
        self.assertEqual(
            'ldy_loading_type', result['missing_fields'][0]['column']
        )
        self.assertEqual(1, result['missing_fields'][0]['new_items'])
        self.assertIn('public.ldy_retail_com', cursor.calls[0][0])


if __name__ == '__main__':
    unittest.main()
