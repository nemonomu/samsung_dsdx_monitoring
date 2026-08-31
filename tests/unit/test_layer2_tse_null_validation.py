import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


TSE_SOURCES = {
    'tse_tv': {
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
    },
    'tse_ref': {
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
    },
    'tse_ldy': {
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
    },
}


def tse_columns_config():
    return {
        'tse_tv': {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['country', 'account_name', 'sku'],
                'editable_columns': [
                    'country', 'account_name', 'sku',
                    'original_sku_price', 'batch_id',
                ],
            },
        },
        'tse_ref': {},
        'tse_ldy': {},
    }


def common_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', execute_dx_query=lambda _query: [],
            dx_table=lambda table: table,
        ),
        'apps.common.response': module_stub(
            'apps.common.response', log_error=lambda *_: None,
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            load_retail_columns=lambda: {},
            get_editable_columns=lambda *_: [],
            load_tse_retail_columns=tse_columns_config,
        ),
        'apps.common.tse_retail': module_stub(
            'apps.common.tse_retail',
            TSE_COUNTRY='TSE',
            TSE_SOURCE_CONFIG=TSE_SOURCES,
            TSE_UNASSIGNED_DISPLAY_NAME='리테일러 미지정',
            TSE_UNASSIGNED_RETAILER='__unassigned__',
            TSE_TABLE_TO_PRODUCT_LINE={
                source['table_name']: key
                for key, source in TSE_SOURCES.items()
            },
            get_tse_required_columns=lambda product_line: {
                'tse_tv': ('country', 'account_name', 'sku'),
                'tse_ref': ('country', 'ref_capacity'),
                'tse_ldy': ('country', 'ldy_capacity'),
            }[product_line],
            get_tse_editable_columns=lambda product_line: {
                'tse_tv': (
                    'country', 'account_name', 'sku',
                    'original_sku_price', 'savings',
                ),
                'tse_ref': (
                    'country', 'ref_capacity', 'original_sku_price', 'savings',
                ),
                'tse_ldy': (
                    'country', 'ldy_capacity', 'original_sku_price', 'savings',
                ),
            }[product_line],
            get_tse_product_line_for_table=lambda table: {
                source['table_name']: key for key, source in TSE_SOURCES.items()
            }[table],
            tse_retailer_include_unassigned=lambda _retailer: False,
            tse_retailer_supports_column=lambda *_args: True,
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda *_: 'TRUE',
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
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


class TSELayer2NullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_tse_null_service_under_test',
            common_stubs(),
        )
        cls.runtime = cls.service._get_tse_runtime()

    def test_summary_uses_latest_batch_and_active_required_columns(self):
        cursor = ScriptedCursor([
            {'fetchone': ('h20260810_095803', 300, 0, 0, 1)},
            {'fetchall': []},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
        ])

        tables, issue_count = self.service._get_tse_null_tables(
            cursor, date(2026, 8, 10), self.runtime,
            tse_columns_config(),
        )

        self.assertEqual(1, issue_count)
        self.assertEqual('TSE TV', tables[0]['table_name'])
        self.assertEqual(300, tables[0]['retailers'][0]['total'])
        self.assertEqual(
            {'country': 0, 'account_name': 0, 'sku': 1},
            tables[0]['retailers'][0]['fields_detail'],
        )
        summary_sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com source', summary_sql)
        self.assertIn('LEFT(TRIM(source.crawl_datetime), 10) = %s', summary_sql)
        self.assertIn('ORDER BY source.id DESC LIMIT 1', summary_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', summary_sql)
        self.assertNotIn('OR source.account_name IS NULL', summary_sql)
        self.assertIn('source.country = %s', summary_sql)
        self.assertIn('source.country IS NULL', summary_sql)
        self.assertNotIn('batch_id AS null_batch_id', summary_sql)
        self.assertEqual(
            (
                '2026-08-10', 'homepro', 'TSE',
                '2026-08-10', 'homepro', 'TSE',
            ),
            params,
        )

    def test_two_retailers_exclude_unassigned_rows_from_both_scopes(self):
        config = tse_columns_config()
        config['tse_tv']['Lotuss'] = {
            'retailer': 'lotuss',
            'required_columns': ['sku'],
            'editable_columns': ['sku'],
        }
        cursor = ScriptedCursor([
            {'fetchone': ('homepro-batch', 300, 0, 0, 0)},
            {'fetchone': ('lotuss-batch', 86, 0)},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
        ])

        tables, issue_count = self.service._get_tse_null_tables(
            cursor, date(2026, 8, 14), self.runtime, config,
        )

        self.assertEqual(0, issue_count)
        self.assertEqual(
            ['Homepro', 'Lotuss'],
            [row['retailer'] for row in tables[0]['retailers']],
        )
        homepro_sql = cursor.calls[0][0]
        lotuss_sql = cursor.calls[1][0]
        self.assertNotIn('OR source.account_name IS NULL', homepro_sql)
        self.assertNotIn('OR source.account_name IS NULL', lotuss_sql)

    def test_unassigned_account_rows_get_their_own_null_review_bucket(self):
        cursor = ScriptedCursor([
            {'fetchone': ('homepro-batch', 300, 0, 0, 0)},
            {'fetchone': (2, 'unknown-batch')},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
        ])

        tables, issue_count = self.service._get_tse_null_tables(
            cursor, date(2026, 8, 14), self.runtime,
            tse_columns_config(),
        )

        self.assertEqual(2, issue_count)
        self.assertEqual(
            ['Homepro', '리테일러 미지정'],
            [row['retailer'] for row in tables[0]['retailers']],
        )
        unassigned = tables[0]['retailers'][1]
        self.assertEqual(2, unassigned['total'])
        self.assertEqual({'account_name': 2}, unassigned['fields_detail'])
        self.assertIn(
            'source.account_name IS NULL', cursor.calls[1][0]
        )
        self.assertIn('WITH latest_batch AS', cursor.calls[1][0])
        self.assertIn(
            'source.batch_id IS NOT DISTINCT FROM', cursor.calls[1][0]
        )

    def test_unassigned_account_detail_is_editable_and_not_homepro_scoped(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('product_url',),
        ]
        cursor = ScriptedCursor([{
            'description': description,
            'fetchall': [(
                41, 'unknown-batch', 'TSE', None, 'TV-41',
                '2026-08-14T09:58:03+09:00', 'https://example.test/41',
            )],
        }])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 14), 'tse_tv_retail',
            '리테일러 미지정', 'account_name', self.runtime,
            tse_columns_config(),
        )

        self.assertEqual([41], [row['id'] for row in result['results']])
        self.assertEqual(['account_name'], result['editable_cols'])
        self.assertEqual(['account_name'], result['results'][0]['null_fields'])
        self.assertEqual('', result['query_retailer'])
        self.assertTrue(result['query_include_unassigned'])
        detail_sql = cursor.calls[0][0]
        self.assertIn('WITH latest_batches AS', detail_sql)
        self.assertIn('source.account_name IS NULL', detail_sql)
        self.assertNotIn("LOWER(source.account_name)", detail_sql)

    def test_tse_query_failure_rolls_back_only_tse_savepoint(self):
        class FailingCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=None):
                normalized = ' '.join(sql.split())
                self.calls.append((normalized, params))
                if normalized.startswith('WITH latest_batch AS'):
                    raise RuntimeError('TSE table unavailable')

        cursor = FailingCursor()
        validation = {'tables': [{'table': 'tv_retail'}]}

        issue_count = self.service._append_tse_null_stats(
            cursor, date(2026, 8, 10), validation
        )

        self.assertEqual(0, issue_count)
        self.assertEqual([{'table': 'tv_retail'}], validation['tables'])
        sql_calls = [sql for sql, _params in cursor.calls]
        self.assertEqual('SAVEPOINT layer2_tse_null_stats', sql_calls[0])
        self.assertIn('WITH latest_batch AS', sql_calls[1])
        self.assertEqual(
            'ROLLBACK TO SAVEPOINT layer2_tse_null_stats', sql_calls[2]
        )
        self.assertEqual(
            'RELEASE SAVEPOINT layer2_tse_null_stats', sql_calls[3]
        )

    def test_detail_rejects_unconfigured_or_injected_column_before_sql(self):
        cursor = ScriptedCursor([])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku; DROP TABLE x', self.runtime, tse_columns_config(),
        )

        self.assertEqual([], result['results'])
        self.assertEqual([], cursor.calls)

    def test_detail_returns_only_latest_batch_rows_and_db_editable_allowlist(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',),
            ('original_sku_price',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(
                    11, 'h20260810_095803', 'TSE', 'Homepro', 'TV-1',
                    '2026-08-10T09:58:03+09:00', None, '฿10,000',
                )],
            },
            {'fetchall': []},
        ])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku', self.runtime, tse_columns_config(),
        )

        self.assertEqual([11], [row['id'] for row in result['results']])
        self.assertEqual(['sku'], result['results'][0]['null_fields'])
        self.assertEqual(
            ['country', 'account_name', 'sku', 'original_sku_price'],
            result['editable_cols'],
        )
        self.assertNotIn('batch_id', result['editable_cols'])
        self.assertEqual(
            'dx_tse.dx_tse_tv_retail_com', result['actual_table']
        )
        detail_sql = cursor.calls[0][0]
        self.assertIn('CROSS JOIN latest_batch', detail_sql)
        self.assertIn('source.sku IS NULL', detail_sql)
        self.assertNotIn('OR source.account_name IS NULL', detail_sql)
        self.assertIn('source.country = %s', detail_sql)
        self.assertEqual(
            (
                '2026-08-10', 'homepro', 'TSE',
                '2026-08-10', 'homepro', 'TSE',
            ),
            cursor.calls[0][1],
        )

    def test_country_null_detail_keeps_missing_country_inside_tse_batch(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',), ('product_url',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(
                    11, 'h20260810_095803', None, 'Homepro', 'TV-1',
                    '2026-08-10T09:58:03+09:00', 'SKU-1',
                    'https://example.test/tv-1',
                )],
            },
            {'fetchall': []},
        ])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'country', self.runtime, tse_columns_config(),
        )

        self.assertEqual([11], [row['id'] for row in result['results']])
        detail_sql = cursor.calls[0][0]
        self.assertIn('source.country = %s', detail_sql)
        self.assertIn('source.country IS NULL', detail_sql)
        self.assertIn('source.country IS NULL', detail_sql)

    def test_detail_keeps_all_columns_but_uses_compact_default_display(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',),
            ('final_sku_price',), ('original_sku_price',), ('savings',),
            ('product_url',), ('retailer_sku_name',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(
                    11, 'h20260810_095803', 'TSE', 'Homepro', 'TV-1',
                    '2026-08-10T09:58:03+09:00', None,
                    '10,000', '12,000', '2,000',
                    'https://example.test/tv-1', 'Example TV',
                )],
            },
            {'fetchall': []},
        ])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku', self.runtime, tse_columns_config(),
        )

        all_columns = [column[0] for column in description]
        self.assertEqual(all_columns, result['select_cols'])
        self.assertEqual([
            'id', 'item', 'sku', 'retailer_sku_name',
            'final_sku_price', 'original_sku_price', 'savings',
            'crawl_datetime', 'product_url',
        ], result['query_config']['sku'])
        self.assertEqual(
            [
                'id', 'crawl_datetime', 'item', 'retailer_sku_name',
                'sku', 'product_url',
            ],
            result['display_config']['sku']['select_columns'],
        )
        self.assertEqual('homepro', result['query_retailer'])
        self.assertFalse(result['query_include_unassigned'])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(1, result['history_days'])
        self.assertTrue(result['latest_batch_only'])

    def test_price_field_uses_compact_price_display_group(self):
        select_columns = [
            'id', 'batch_id', 'crawl_datetime', 'item',
            'final_sku_price', 'original_sku_price', 'savings',
            'product_url', 'retailer_sku_name',
        ]

        display_columns = self.service._get_tse_null_display_columns(
            'final_sku_price', select_columns
        )

        self.assertEqual([
            'id', 'crawl_datetime', 'item', 'retailer_sku_name',
            'final_sku_price', 'original_sku_price', 'savings',
            'product_url',
        ], display_columns)

    def test_review_null_detail_groups_all_three_review_fields(self):
        review_columns = [
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
        ]
        for selected_column in review_columns:
            with self.subTest(selected_column=selected_column):
                self.assertEqual(
                    review_columns,
                    self.service._get_tse_null_related_columns(
                        selected_column, review_columns
                    ),
                )

        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',),
            ('star_rating',), ('count_of_star_ratings',),
            ('count_of_reviews',), ('final_sku_price',),
            ('original_sku_price',), ('savings',), ('product_url',),
            ('retailer_sku_name',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [
                    (
                        11, 'batch-1', 'TSE', 'Homepro', 'TV-1',
                        '2026-08-10T09:58:03+09:00', 'SKU-1',
                        None, '10', '10', '฿10,000', '฿12,000',
                        '฿2,000 (-16%)', 'https://example.test/tv-1',
                        'Example TV 1',
                    ),
                    (
                        12, 'batch-1', 'TSE', 'Homepro', 'TV-2',
                        '2026-08-10T09:58:03+09:00', 'SKU-2',
                        '4.5', None, None, '฿20,000', '฿22,000',
                        '฿2,000 (-9%)', 'https://example.test/tv-2',
                        'Example TV 2',
                    ),
                ],
            },
            {'fetchall': []},
        ])
        config = tse_columns_config()
        config['tse_tv']['Homepro']['required_columns'].extend(review_columns)
        runtime = dict(self.runtime)
        max_required = self.runtime['max_required']
        runtime['max_required'] = lambda product_line: (
            (*max_required(product_line), 'star_rating',
             'count_of_star_ratings', 'count_of_reviews')
            if product_line == 'tse_tv'
            else max_required(product_line)
        )

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'star_rating', runtime, config,
        )

        self.assertEqual([11, 12], [row['id'] for row in result['results']])
        self.assertEqual(
            ['star_rating'], result['results'][0]['null_fields']
        )
        self.assertEqual(
            ['count_of_star_ratings', 'count_of_reviews'],
            result['results'][1]['null_fields'],
        )
        detail_sql = cursor.calls[0][0]
        for review_column in (
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
        ):
            self.assertIn(f'source.{review_column} IS NULL', detail_sql)
            self.assertIn(
                review_column,
                result['display_config']['star_rating']['select_columns'],
            )
            self.assertIn(
                review_column, result['query_config']['star_rating']
            )
        self.assertIn(' OR ', detail_sql)
        review_params = cursor.calls[1][1]
        self.assertEqual(
            [
                'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            ],
            list(review_params[4:7]),
        )

    def test_normal_review_identity_is_hidden_for_thirteen_days_then_rechecked(self):
        record = {
            'id': 12,
            'item': 'TV-1',
            'retailer_sku_name': 'Example TV',
        }
        reviews = [{
            'record_id': 11,
            'column_name': 'sku',
            'reason': self.service.TSE_NORMAL_VALUE_REASON,
            'crawl_date': date(2026, 8, 11),
            'identity': ('tv-1', 'example tv'),
        }]

        self.assertTrue(self.service._is_tse_review_suppressed(
            record, 'sku', date(2026, 8, 12), reviews
        ))
        self.assertTrue(self.service._is_tse_review_suppressed(
            record, 'sku', date(2026, 8, 24), reviews
        ))
        self.assertFalse(self.service._is_tse_review_suppressed(
            record, 'sku', date(2026, 8, 25), reviews
        ))
        changed_name = dict(record, retailer_sku_name='Different TV')
        self.assertFalse(self.service._is_tse_review_suppressed(
            changed_name, 'sku', date(2026, 8, 12), reviews
        ))

        other_reason = [dict(reviews[0], reason='상품페이지 내 항목 부재')]
        self.assertFalse(self.service._is_tse_review_suppressed(
            record, 'sku', date(2026, 8, 12), other_reason
        ))
        same_record = dict(record, id=11)
        self.assertTrue(self.service._is_tse_review_suppressed(
            same_record, 'sku', date(2026, 8, 11), other_reason
        ))

    def test_summary_excludes_recently_reviewed_item_and_retailer_sku(self):
        cursor = ScriptedCursor([
            {'fetchone': ('h20260811_095803', 1, 0, 0, 1)},
            {'fetchall': [(
                11, 'sku', 'checked', 'tester', None,
                self.service.TSE_NORMAL_VALUE_REASON,
                date(2026, 8, 10), 'TV-1', 'Example TV',
            )]},
            {'fetchall': [(
                12, 'TV-1', 'Example TV', 'TSE', 'Homepro', None,
            )]},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
            {'fetchone': (0, None)},
        ])

        tables, issue_count = self.service._get_tse_null_tables(
            cursor, date(2026, 8, 11), self.runtime,
            tse_columns_config(),
        )

        self.assertEqual(0, issue_count)
        self.assertEqual(
            0, tables[0]['retailers'][0]['fields_detail']['sku']
        )
        review_sql, review_params = cursor.calls[1]
        self.assertIn('reviewed_source.retailer_sku_name', review_sql)
        self.assertEqual('2026-07-29', review_params[1])
        self.assertEqual('2026-08-11', review_params[2])

    def test_detail_expands_seed_items_to_latest_batch_per_day(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',), ('product_url',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [
                    (
                        11, 'h20260810_095803', 'TSE', 'Homepro',
                        'TV-1', '2026-08-10T09:58:03+09:00', None,
                        'https://example.test/tv-1',
                    ),
                    (
                        12, 'h20260810_095803', 'TSE', 'Homepro',
                        'TV-2', '2026-08-10T09:58:03+09:00', None,
                        'https://example.test/tv-2',
                    ),
                ],
            },
            {
                'fetchall': [
                    (
                        12, 'sku', 'checked', 'tester', None,
                        self.service.TSE_NORMAL_VALUE_REASON,
                        date(2026, 8, 10), 'TV-2', None,
                    ),
                ],
            },
            {
                'description': description,
                'fetchall': [
                    (
                        1, 'h20260712_095803', 'TSE', 'Homepro',
                        'TV-1', '2026-07-12T09:58:03+09:00', 'SKU-1',
                        'https://example.test/tv-1',
                    ),
                    (
                        11, 'h20260810_095803', 'TSE', 'Homepro',
                        'TV-1', '2026-08-10T09:58:03+09:00', None,
                        'https://example.test/tv-1',
                    ),
                ],
            },
        ])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku', self.runtime, tse_columns_config(), days=45,
        )

        self.assertEqual(30, result['history_days'])
        self.assertFalse(result['latest_batch_only'])
        self.assertEqual([1, 11], [row['id'] for row in result['results']])
        self.assertEqual([], result['results'][0]['null_fields'])
        self.assertEqual(['sku'], result['results'][1]['null_fields'])
        history_sql, history_params = cursor.calls[2]
        self.assertIn('WITH latest_batches AS', history_sql)
        self.assertIn('SELECT DISTINCT ON', history_sql)
        self.assertIn('LEFT(TRIM(source.crawl_datetime), 10)', history_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', history_sql)
        self.assertIn('source.country = %s', history_sql)
        self.assertEqual(
            (
                '2026-07-12', '2026-08-10', 'homepro', 'TSE',
                'homepro', 'TSE', 'TV-1',
            ),
            history_params,
        )
        self.assertNotIn('TV-2', history_params)

    def test_normal_value_review_log_includes_identity_and_processing_time(self):
        created_at = datetime(2026, 8, 24, 14, 35, 10)
        cursor = ScriptedCursor([
            {'fetchall': [(
                91, 'dx_tse.dx_tse_tv_retail_com', 12, 'Homepro',
                'TV-1', 'sku', self.service.TSE_NORMAL_VALUE_REASON,
                '사이트 값 확인', date(2026, 8, 24), 'tester', created_at,
            )]},
            {'fetchall': [(12, 'TV-1', 'Example TV')]},
        ])

        with patch.object(
            self.service,
            'get_tse_auto_applied_null_reviews',
            return_value=[],
        ):
            result = self.service.get_tse_null_review_logs(
                cursor, date(2026, 8, 24)
            )

        self.assertEqual(1, result['total'])
        self.assertEqual('Example TV', result['logs'][0]['retailer_sku_name'])
        self.assertEqual('2026-08-24 14:35:10', result['logs'][0]['created_at'])
        self.assertEqual('tester', result['logs'][0]['created_id'])
        self.assertEqual('해당값 정상 처리 · 14일 후 재검수', result['logs'][0]['handling'])
        log_sql, log_params = cursor.calls[0]
        self.assertIn("correction.correction_type = 'null_check'", log_sql)
        self.assertIn('correction.reason IN', log_sql)
        self.assertEqual('2026-08-24', log_params[0])

    def test_prior_normal_review_is_emitted_as_today_auto_applied_log(self):
        created_at = datetime(2026, 8, 23, 15, 21, 18)
        cursor = ScriptedCursor([
            {'fetchall': [(
                20, 'TV-1', 'Example TV',
                '2026-08-24T09:00:03+09:00', 'TSE', 'Homepro', None,
            )]},
            {'fetchall': [(
                11, 'sku', 'checked', 'tester', created_at,
                self.service.TSE_NORMAL_VALUE_REASON,
                date(2026, 8, 23), 'TV-1', 'Example TV',
            )]},
        ])

        logs = self.service.get_tse_auto_applied_null_reviews(
            cursor, date(2026, 8, 24)
        )

        self.assertEqual(1, len(logs))
        self.assertTrue(logs[0]['auto_applied'])
        self.assertEqual('2026-08-24', logs[0]['applied_date'])
        self.assertEqual('2026-08-23', logs[0]['original_crawl_date'])
        self.assertEqual('2026-08-23 15:21:18', logs[0]['original_created_at'])
        self.assertEqual('sku', logs[0]['column_name'])
        self.assertEqual('이전 해당값 정상 확인 자동 적용 · 14일 후 재검수', logs[0]['handling'])
        review_sql, review_params = cursor.calls[1]
        self.assertIn("correction.correction_type = 'null_check'", review_sql)
        self.assertEqual('2026-08-11', review_params[1])
        self.assertEqual('2026-08-23', review_params[2])

    def test_item_null_expands_with_null_predicate_instead_of_id_fallback(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',), ('product_url',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(
                    11, 'h20260810_095803', 'TSE', 'Homepro', None,
                    '2026-08-10T09:58:03+09:00', 'SKU-1',
                    'https://example.test/tv-1',
                )],
            },
            {'fetchall': []},
            {
                'description': description,
                'fetchall': [
                    (
                        1, 'h20260808_095803', 'TSE', 'Homepro', None,
                        '2026-08-08T09:58:03+09:00', 'SKU-1',
                        'https://example.test/tv-1',
                    ),
                    (
                        11, 'h20260810_095803', 'TSE', 'Homepro', None,
                        '2026-08-10T09:58:03+09:00', 'SKU-1',
                        'https://example.test/tv-1',
                    ),
                ],
            },
        ])
        runtime = dict(self.runtime)
        runtime['max_required'] = lambda product_line: (
            *self.runtime['max_required'](product_line), 'item',
        )
        config = tse_columns_config()
        config['tse_tv']['Homepro']['required_columns'].append('item')

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'item', runtime, config, days=3,
        )

        self.assertEqual([1, 11], [row['id'] for row in result['results']])
        history_sql, history_params = cursor.calls[2]
        self.assertIn('WITH latest_batches AS', history_sql)
        self.assertIn('source.item IS NULL', history_sql)
        self.assertNotIn('source.item IN (', history_sql)
        self.assertEqual(
            (
                '2026-08-08', '2026-08-10', 'homepro', 'TSE',
                'homepro', 'TSE',
            ),
            history_params,
        )

    def test_normal_review_is_recorded_for_active_required_column(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Homepro', 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11, 'sku',
            'normal', 'checked', 'source_issue', date(2026, 8, 10),
            'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertIn(
            'SELECT sku, account_name, item FROM dx_tse.dx_tse_tv_retail_com',
            cursor.calls[0][0],
        )
        self.assertIn('source.country = %s', cursor.calls[0][0])
        self.assertIn('source.country IS NULL', cursor.calls[0][0])
        self.assertIn(
            'LEFT(TRIM(source.crawl_datetime), 10) = %s',
            cursor.calls[0][0],
        )
        self.assertEqual((11, 'TSE', '2026-08-10'), cursor.calls[0][1])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        insert_params = cursor.calls[2][1]
        self.assertEqual('null_check', insert_params[1])
        self.assertEqual('dx_tse.dx_tse_tv_retail_com', insert_params[2])
        self.assertEqual('normal', insert_params[10])
        conn.commit.assert_called_once_with()

    def test_country_null_record_can_be_marked_normal(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Homepro', 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11, 'country',
            'normal', 'checked', 'source_issue', date(2026, 8, 10),
            'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertIn('source.country IS NULL', cursor.calls[0][0])
        self.assertEqual((11, 'TSE', '2026-08-10'), cursor.calls[0][1])
        conn.commit.assert_called_once_with()

    def test_normal_review_rejects_edit_only_column(self):
        cursor = ScriptedCursor([])

        result = self.service.save_null_review(
            cursor, Mock(), 'dx_tse.dx_tse_tv_retail_com', 11,
            'original_sku_price', 'normal', '', 'source_issue',
            date(2026, 8, 10), 'null', 'tester',
        )

        self.assertEqual(400, result['status_code'])
        self.assertEqual([], cursor.calls)

    def test_format_review_allows_configured_edit_only_price_column(self):
        cursor = ScriptedCursor([
            {'fetchone': ('13,820', 'Homepro', 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11,
            'original_sku_price', 'normal', 'checked', 'source_issue',
            date(2026, 8, 10), 'format', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertIn(
            'SELECT original_sku_price, account_name, item',
            cursor.calls[0][0],
        )
        self.assertEqual('format_check', cursor.calls[2][1][1])
        conn.commit.assert_called_once_with()

    def test_unassigned_bucket_can_review_missing_account_name(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, None, 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11,
            'account_name', 'normal', 'checked', 'source_issue',
            date(2026, 8, 10), 'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual('__unassigned__', cursor.calls[2][1][-2])

if __name__ == '__main__':
    unittest.main()
