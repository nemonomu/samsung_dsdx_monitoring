import unittest
from datetime import date
from unittest.mock import Mock, patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SEA_SOURCES = {
    'tv': {
        'product_key': 'tv',
        'source_key': 'sea_tv',
        'category': 'TV',
        'table_name': 'public.tv_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Bestbuy', 'Walmart'),
        'latest_main_batch': False,
    },
    'ref': {
        'product_key': 'ref',
        'source_key': 'sea_ref',
        'category': 'REF',
        'table_name': 'public.ref_retail_com',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
        'latest_main_batch': True,
    },
    'ldy': {
        'product_key': 'ldy',
        'source_key': 'sea_ldy',
        'category': 'LDY',
        'table_name': 'public.ldy_retail_com',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
        'latest_main_batch': True,
    },
}

NULL_COLUMNS = {
    'ref': (
        'item', 'product_url', 'account_name', 'country',
        'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
        'ref_capacity', 'retailer_sku_name', 'sku', 'star_rating',
    ),
    'ldy': (
        'item', 'product_url', 'account_name', 'country',
        'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
        'retailer_sku_name', 'sku', 'star_rating',
    ),
}


def db_rows():
    rows = []
    for product, columns in NULL_COLUMNS.items():
        for retailer in ('Bestbuy', 'Lowes'):
            for column in columns:
                display_columns = [
                    'crawl_strdatetime', 'item', 'account_name', 'country',
                    'sku', 'retailer_sku_name', 'product_url',
                ]
                if column not in display_columns:
                    display_columns.append(column)
                rows.append({
                    'category': 'sea_retail',
                    'cat_display_name': 'SEA Retail',
                    'display_order': 9,
                    'has_retailer': True,
                    'check_name': f'{retailer.lower()}_{product}',
                    'group_display_name': f'{retailer} {product.upper()}',
                    'table_name': f'{product}_retail_com',
                    'date_column': 'crawl_strdatetime',
                    'check_column': column,
                    'check_type': 'both',
                    'display_columns': '|'.join(display_columns),
                    'query_columns': (
                        f'id|crawl_strdatetime|batch_id|account_name|country|'
                        f'page_type|item|sku|retailer_sku_name|{column}|'
                        f'product_url'
                    ),
                    'query_days': 0,
                })
    return rows


def common_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', execute_dx_query=lambda _query: db_rows(),
            dx_table=lambda table: table,
        ),
        'apps.common.response': module_stub(
            'apps.common.response', log_error=lambda *_args: None,
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            load_retail_columns=lambda: {},
            get_editable_columns=lambda product_line, _retailer: (
                ['sku'] if product_line in {'sea_ref', 'sea_ldy'} else []
            ),
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda *_args: 'TRUE',
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.inspection_dates': module_stub(
            'apps.common.inspection_dates',
            resolve_monitoring_date=lambda inspection, _country, source_key: {
                'inspection_date': str(inspection),
                'source_date': '2026-08-30',
                'offset_days': -1,
                'source_key': source_key,
            },
        ),
        'apps.common.sea_retail': module_stub(
            'apps.common.sea_retail', SEA_RETAIL_SOURCES=SEA_SOURCES,
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
        'apps.dx.dx_layer2.common': package_stub(
            'apps.dx.dx_layer2.common'
        ),
        'apps.dx.dx_layer2.common.context': module_stub(
            'apps.dx.dx_layer2.common.context',
            get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
        ),
    }


class SEALayer2NullValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_sea_null_service_under_test',
            common_stubs(),
        )

    def test_db_settings_are_split_into_canonical_ref_and_ldy_categories(self):
        config = self.service.load_null_check_config()

        self.assertEqual(
            {'sea_ref_retail', 'sea_ldy_retail', 'youtube'}, set(config)
        )
        self.assertEqual(
            set(NULL_COLUMNS['ref']),
            set(config['sea_ref_retail']['checks']['bestbuy']['columns']),
        )
        self.assertNotIn(
            'ref_refrigerator_type',
            config['sea_ref_retail']['checks']['bestbuy']['columns'],
        )
        self.assertEqual(
            set(NULL_COLUMNS['ldy']),
            set(config['sea_ldy_retail']['checks']['lowes']['columns']),
        )
        self.assertEqual(
            'public.ref_retail_com',
            config['sea_ref_retail']['checks']['bestbuy']['table_name'],
        )
        self.assertEqual(
            [
                'crawl_strdatetime', 'item', 'account_name', 'country',
                'sku', 'retailer_sku_name', 'product_url', 'ref_capacity',
            ],
            config['sea_ref_retail']['checks']['bestbuy']['columns'][
                'ref_capacity'
            ]['display_columns'],
        )
        self.assertNotIn(
            'batch_id',
            config['sea_ldy_retail']['checks']['lowes']['columns'][
                'star_rating'
            ]['display_columns'],
        )

    def test_sea_tv_summary_uses_crawl_datetime_d_minus_one_without_anchor(self):
        tv_config = {
            'tv_retail': {
                'display_name': 'TV Retail',
                'display_order': 1,
                'has_retailer': True,
                'checks': {
                    'amazon_tv': {
                        'display_name': 'Amazon',
                        'table_name': 'tv_retail_com',
                        'date_column': 'crawl_datetime',
                        'columns': {
                            'item': {
                                'check_type': 'both',
                                'display_columns': ['id', 'item'],
                                'query_columns': ['id', 'item'],
                                'query_days': 0,
                            },
                        },
                    },
                },
            },
        }
        cursor = ScriptedCursor([
            {'fetchone': (300, 2)},
            {'fetchall': []},
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=tv_config
        ), patch.object(
            self.service, '_append_tse_null_stats', return_value=0
        ):
            result, issues = self.service.get_null_stats(
                cursor, date(2026, 8, 31), include_youtube=False
            )

        self.assertEqual(2, issues)
        table = result['tables'][0]
        self.assertEqual('2026-08-31', table['inspection_date'])
        self.assertEqual('2026-08-30', table['source_date'])
        self.assertEqual(-1, table['offset_days'])
        self.assertIsNone(table['retailers'][0]['batch_id'])
        self.assertEqual(2, len(cursor.calls))

        summary_sql, summary_params = cursor.calls[0]
        self.assertIn('DATE(crawl_datetime) = %s', summary_sql)
        self.assertIn('FROM tv_retail_com', summary_sql)
        self.assertIn('AND TRUE', summary_sql)
        self.assertEqual(['2026-08-30', 'Amazon'], summary_params)
        self.assertNotIn('ORDER BY anchor.id DESC', summary_sql)

        correction_sql, correction_params = cursor.calls[1]
        self.assertIn(
            'record_id IN (SELECT id FROM tv_retail_com', correction_sql
        )
        self.assertEqual(
            [
                'tv_retail_com', '2026-08-31', 'Amazon',
                '2026-08-30', 'Amazon',
            ],
            correction_params,
        )

    def test_sea_tv_detail_uses_crawl_datetime_d_minus_one_without_batch(self):
        tv_config = {
            'tv_retail': {
                'display_name': 'TV Retail',
                'display_order': 1,
                'has_retailer': True,
                'checks': {
                    'amazon_tv': {
                        'display_name': 'Amazon',
                        'table_name': 'tv_retail_com',
                        'date_column': 'crawl_datetime',
                        'columns': {
                            'item': {
                                'check_type': 'both',
                                'display_columns': ['id', 'item'],
                                'query_columns': ['id', 'item'],
                                'query_days': 0,
                            },
                        },
                    },
                },
            },
        }
        description = [
            ('id',), ('account_name',), ('item',), ('crawl_datetime',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(7, 'Amazon', None, '2026-08-30 17:00:13')],
            },
            {'fetchall': []},
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=tv_config
        ), patch.object(
            self.service, 'load_retail_columns',
            return_value={'tv': {'Amazon': ['id', 'item']}},
        ), patch.object(
            self.service, 'get_editable_columns',
            return_value=['item'],
        ):
            result = self.service.get_null_detail(
                cursor, date(2026, 8, 31), 'tv_retail',
                'Amazon', 1, 'item',
            )

        self.assertEqual([7], [row['id'] for row in result['results']])
        self.assertEqual('2026-08-31', result['inspection_date'])
        self.assertEqual('2026-08-30', result['source_date'])
        self.assertEqual(-1, result['offset_days'])
        self.assertIsNone(result['batch_id'])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(['id', 'item'], result['select_cols'])
        self.assertEqual(['item'], result['editable_cols'])

        detail_sql, detail_params = cursor.calls[0]
        self.assertIn(
            'crawl_datetime::timestamp >= %s AND '
            'crawl_datetime::timestamp < %s',
            detail_sql,
        )
        self.assertIn('FROM tv_retail_com', detail_sql)
        self.assertIn('AND TRUE', detail_sql)
        self.assertEqual(
            ['2026-08-30', '2026-08-31', 'Amazon'], detail_params
        )
        self.assertNotIn('batch_id = %s', detail_sql)

        correction_sql, correction_params = cursor.calls[1]
        self.assertIn('FROM monitoring_corrections', correction_sql)
        self.assertEqual(
            ('tv_retail_com', '2026-08-31', 'item'), correction_params
        )

    def test_summary_uses_d_minus_one_latest_main_anchor_and_same_batch(self):
        ref_counts = (300,) + (1,) + (0,) * (
            len(NULL_COLUMNS['ref']) - 1
        )
        ldy_counts = (200,) + (0,) * len(NULL_COLUMNS['ldy'])
        cursor = ScriptedCursor([
            {'fetchone': ('b_ref',)}, {'fetchone': ref_counts},
            {'fetchall': []},
            {'fetchone': ('l_ref',)},
            {'fetchone': (299,) + (0,) * len(NULL_COLUMNS['ref'])},
            {'fetchall': []},
            {'fetchone': ('b_ldy',)}, {'fetchone': ldy_counts},
            {'fetchall': []},
            {'fetchone': ('l_ldy',)}, {'fetchone': ldy_counts},
            {'fetchall': []},
        ])

        result, issues = self.service.get_null_stats(
            cursor, date(2026, 8, 31), include_youtube=False
        )

        self.assertEqual(1, issues)
        ref_table = result['tables'][0]
        self.assertEqual('sea_ref_retail', ref_table['table'])
        self.assertEqual('2026-08-31', ref_table['inspection_date'])
        self.assertEqual('2026-08-30', ref_table['source_date'])
        self.assertEqual(-1, ref_table['offset_days'])
        self.assertEqual('b_ref', ref_table['retailers'][0]['batch_id'])

        anchor_sql, anchor_params = cursor.calls[0]
        self.assertIn('FROM public.ref_retail_com anchor', anchor_sql)
        self.assertIn("= 'MAIN'", anchor_sql)
        self.assertIn('ORDER BY anchor.id DESC', anchor_sql)
        self.assertEqual(('2026-08-30', 'Bestbuy'), anchor_params)

        count_sql, count_params = cursor.calls[1]
        self.assertIn('FROM public.ref_retail_com', count_sql)
        self.assertIn("IN ('MAIN', 'BSR')", count_sql)
        self.assertIn('batch_id = %s', count_sql)
        self.assertIn('OR account_name IS NULL', count_sql)
        self.assertEqual(
            ['2026-08-30', 'Bestbuy', 'b_ref'], count_params
        )
        self.assertNotIn('MAX(', count_sql)
        correction_sql, correction_params = cursor.calls[2]
        self.assertIn(
            'record_id IN (SELECT id FROM public.ref_retail_com',
            correction_sql,
        )
        self.assertEqual(
            [
                'public.ref_retail_com', '2026-08-31', 'Bestbuy',
                '2026-08-30', 'Bestbuy', 'b_ref',
            ],
            correction_params,
        )

    def test_detail_returns_only_exact_source_date_anchor_batch_scope(self):
        description = [
            ('id',), ('account_name',), ('page_type',), ('item',),
            ('sku',), ('crawl_strdatetime',), ('batch_id',),
        ]
        cursor = ScriptedCursor([
            {'fetchone': ('l_260830_191936',)},
            {
                'description': description,
                'fetchall': [(
                    42, 'Lowes', 'main', 'item-1', None,
                    '2026-08-30 19:19:36', 'l_260830_191936',
                )],
            },
            {'fetchall': []},
        ])

        result = self.service.get_null_detail(
            cursor, date(2026, 8, 31), 'sea_ldy_retail',
            'Lowes', 1, 'sku',
        )

        self.assertEqual([42], [row['id'] for row in result['results']])
        self.assertEqual('2026-08-30', result['source_date'])
        self.assertEqual('2026-08-31', result['inspection_date'])
        self.assertEqual('l_260830_191936', result['batch_id'])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(1, result['history_days'])
        self.assertEqual(['sku'], result['editable_cols'])
        self.assertEqual(
            [
                'crawl_strdatetime', 'item', 'account_name', 'country',
                'sku', 'retailer_sku_name', 'product_url',
            ],
            result['display_config']['sku']['select_columns'],
        )
        self.assertNotIn(
            'batch_id', result['display_config']['sku']['select_columns']
        )

        detail_sql, detail_params = cursor.calls[1]
        self.assertIn('FROM public.ldy_retail_com', detail_sql)
        self.assertIn("IN ('MAIN', 'BSR')", detail_sql)
        self.assertIn('OR account_name IS NULL', detail_sql)
        self.assertEqual(
            ['2026-08-30', 'Lowes', 'l_260830_191936'],
            detail_params,
        )
        correction_sql, correction_params = cursor.calls[2]
        self.assertIn('FROM monitoring_corrections', correction_sql)
        self.assertEqual('2026-08-31', correction_params[1])

    def test_appliance_detail_expands_two_days_with_each_days_anchor_batch(self):
        description = [
            ('id',), ('account_name',), ('page_type',), ('item',),
            ('sku',), ('crawl_strdatetime',), ('batch_id',),
        ]
        cursor = ScriptedCursor([
            {'fetchone': ('l_260830_191936',)},
            {
                'description': description,
                'fetchall': [(
                    42, 'Lowes', 'main', 'item-1', None,
                    '2026-08-30 19:19:36', 'l_260830_191936',
                )],
            },
            {'fetchall': []},
            {
                'description': description,
                'fetchall': [
                    (
                        41, 'Lowes', 'main', 'item-1', 'OLD-SKU',
                        '2026-08-29 19:04:00', 'l_260829_190400',
                    ),
                    (
                        42, 'Lowes', 'main', 'item-1', None,
                        '2026-08-30 19:19:36', 'l_260830_191936',
                    ),
                ],
            },
        ])

        result = self.service.get_null_detail(
            cursor, date(2026, 8, 31), 'sea_ldy_retail',
            'Lowes', 2, 'sku',
        )

        self.assertEqual([41, 42], [row['id'] for row in result['results']])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(2, result['history_days'])
        self.assertEqual('2026-08-30', result['source_date'])

        history_sql, history_params = cursor.calls[3]
        self.assertIn('WITH latest_batches AS', history_sql)
        self.assertIn('SELECT DISTINCT ON', history_sql)
        self.assertIn("= 'MAIN'", history_sql)
        self.assertIn("IN ('MAIN', 'BSR')", history_sql)
        self.assertIn(
            'source.batch_id IS NOT DISTINCT FROM latest.batch_id',
            history_sql,
        )
        self.assertIn('OR source.account_name IS NULL', history_sql)
        self.assertEqual(
            ['2026-08-29', '2026-08-30', 'Lowes', 'Lowes', 'item-1'],
            history_params,
        )

    def test_normal_review_accepts_only_configured_column_in_anchor_scope(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Lowes', 'item-1')},
            {'fetchone': None},
            {'rowcount': 1},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'public.ldy_retail_com', 42, 'sku',
            'normal', '확인 메모', '수집처 특례', '2026-08-31',
            'null', 'tester',
        )

        self.assertTrue(result['success'])
        scope_sql, scope_params = cursor.calls[0]
        self.assertIn('FROM public.ldy_retail_com source', scope_sql)
        self.assertIn(
            'SELECT DISTINCT ON (LOWER(TRIM(anchor.account_name)))',
            scope_sql,
        )
        self.assertIn(
            'resolved.batch_id IS NOT DISTINCT FROM source.batch_id',
            scope_sql,
        )
        self.assertIn("IN ('MAIN', 'BSR')", scope_sql)
        self.assertEqual(
            (
                '2026-08-30', 'bestbuy', 'lowes', 42,
                '2026-08-30',
            ),
            scope_params,
        )
        conn.commit.assert_called_once_with()

        blocked = self.service.save_null_review(
            ScriptedCursor([]), Mock(), 'public.ldy_retail_com', 42,
            'ref_capacity', 'normal', '메모', '사유', '2026-08-31',
            'null', 'tester',
        )
        self.assertEqual('허용되지 않는 컬럼', blocked['error'])

    def test_blank_account_name_review_uses_retailer_resolved_from_batch(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Lowes', 'item-2')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'public.ref_retail_com', 77, 'account_name',
            'normal', '확인 메모', '수집처 특례', '2026-08-31',
            'null', 'tester',
        )

        self.assertTrue(result['success'])
        scope_sql, scope_params = cursor.calls[0]
        self.assertIn(
            'resolved.batch_id IS NOT DISTINCT FROM source.batch_id',
            scope_sql,
        )
        self.assertEqual(
            (
                '2026-08-30', 'bestbuy', 'lowes', 77,
                '2026-08-30',
            ),
            scope_params,
        )
        insert_params = cursor.calls[2][1]
        self.assertEqual('account_name', insert_params[4])
        self.assertEqual('Lowes', insert_params[13])
        self.assertEqual('item-2', insert_params[14])
        conn.commit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
