import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SIEL_SOURCES = {
    'siel_tv': {
        'source_key': 'siel_tv',
        'category': 'TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ref': {
        'source_key': 'siel_ref',
        'category': 'REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ldy': {
        'source_key': 'siel_ldy',
        'category': 'LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
}

SIEL_COLUMNS = {
    'siel_tv': {
        'Amazon': (
            'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'screen_size', 'sku', 'star_rating',
        ),
        'Flipkart': (
            'count_of_reviews', 'count_of_star_ratings',
            'estimated_annual_electricity_use', 'final_sku_price',
            'model_year', 'retailer_sku_name', 'screen_size', 'sku',
            'star_rating',
        ),
    },
    'siel_ref': {
        'Amazon': (
            'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'sku', 'star_rating',
        ),
        'Flipkart': (
            'count_of_reviews', 'count_of_star_ratings',
            'final_sku_price', 'ref_capacity', 'ref_refrigerator_type',
            'retailer_sku_name', 'sku', 'star_rating',
        ),
    },
    'siel_ldy': {
        'Amazon': (
            'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'sku', 'star_rating',
        ),
        'Flipkart': (
            'count_of_reviews', 'count_of_star_ratings',
            'final_sku_price', 'ldy_capacity', 'retailer_sku_name', 'sku',
            'star_rating',
        ),
    },
}


def db_rows():
    rows = []
    for source_key, retailers in SIEL_COLUMNS.items():
        source = SIEL_SOURCES[source_key]
        for retailer, columns in retailers.items():
            for column in columns:
                rows.append({
                    'category': 'legacy_siel_retail',
                    'cat_display_name': 'Legacy SIEL Retail',
                    'display_order': 99,
                    'has_retailer': True,
                    'check_name': f'{retailer.lower()}_{source_key}',
                    'group_display_name': retailer,
                    'table_name': source['table_name'].split('.')[-1],
                    'date_column': 'crawl_datetime',
                    'check_column': column,
                    'check_type': 'both',
                    'display_columns': (
                        'crawl_datetime|item|account_name|country|sku|'
                        f'retailer_sku_name|{column}|batch_id'
                    ),
                    'query_columns': (
                        'id|crawl_datetime|batch_id|account_name|country|'
                        f'page_type|item|sku|retailer_sku_name|{column}|'
                        'product_url'
                    ),
                    # Must be ignored for SIEL; history never suppresses NULLs.
                    'query_days': 3,
                })
    # A stale Amazon-only rule must fail closed even when present in DB config.
    rows.append({
        **rows[0],
        'check_name': 'amazon_siel_tv',
        'group_display_name': 'Amazon',
        'table_name': 'dx_siel_tv_retail_com',
        'check_column': 'model_year',
    })
    return rows


def common_stubs():
    def redirect_condition(alias=None):
        prefix = f'{alias}.' if alias else ''
        return (
            f"NOT ({prefix}account_name = 'Amazon' "
            f"AND {prefix}redirect IS TRUE)"
        )

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
            get_editable_columns=lambda *_args: [],
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=redirect_condition,
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.inspection_dates': module_stub(
            'apps.common.inspection_dates',
            resolve_monitoring_date=lambda inspection, country, source_key: {
                'inspection_date': str(inspection),
                'source_date': str(inspection),
                'offset_days': 0,
                'country': country,
                'source_key': source_key,
            },
        ),
        'apps.common.sea_retail': module_stub(
            'apps.common.sea_retail', SEA_RETAIL_SOURCES={},
        ),
        'apps.common.siel_retail': module_stub(
            'apps.common.siel_retail',
            SIEL_BUSINESS_TIMEZONE='Asia/Seoul',
            SIEL_SOURCE_CONFIG=SIEL_SOURCES,
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


def minimal_config(source_key, retailer, column):
    source = SIEL_SOURCES[source_key]
    category = f'{source_key}_retail'
    return {
        category: {
            'display_name': f"SIEL {source['category']}",
            'display_order': 4,
            'has_retailer': True,
            'checks': {
                retailer.lower(): {
                    'display_name': retailer,
                    'table_name': source['table_name'],
                    'date_column': source['date_column'],
                    'columns': {
                        column: {
                            'check_type': 'both',
                            'display_columns': [
                                'crawl_datetime', 'item', 'account_name',
                                'country', 'sku', 'retailer_sku_name',
                                column, 'product_url',
                            ],
                            'query_columns': [
                                'id', 'crawl_datetime', 'batch_id',
                                'account_name', 'page_type', 'item', column,
                                'product_url',
                            ],
                            'query_days': 0,
                        },
                    },
                },
            },
        },
    }


class SIELLayer2NullValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_siel_null_service_under_test',
            common_stubs(),
        )

    def test_db_config_is_reduced_to_the_exact_40_rule_matrix(self):
        config = self.service.load_null_check_config()

        self.assertEqual(
            {
                'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail',
                'youtube',
            },
            set(config),
        )
        configured_count = 0
        for source_key, retailers in SIEL_COLUMNS.items():
            category = f'{source_key}_retail'
            for retailer, expected_columns in retailers.items():
                actual_columns = config[category]['checks'][
                    retailer.lower()
                ]['columns']
                self.assertEqual(set(expected_columns), set(actual_columns))
                configured_count += len(actual_columns)
                for rule in actual_columns.values():
                    self.assertEqual(0, rule['query_days'])
                    self.assertNotIn('batch_id', rule['display_columns'])
                    self.assertIn('product_url', rule['display_columns'])
        self.assertEqual(40, configured_count)
        self.assertNotIn(
            'model_year',
            config['siel_tv_retail']['checks']['amazon']['columns'],
        )

    def test_dbeaver_seed_contains_the_same_exact_40_rule_matrix(self):
        sql = (
            Path(__file__).resolve().parents[2]
            / 'sql' / 'seed_siel_null_monitoring.sql'
        ).read_text(encoding='utf-8')
        value_block = sql.split(
            'CREATE TEMP TABLE _siel_null_rule_seed', 1
        )[0]
        seeded_rules = set(re.findall(
            r"\('(siel_(?:tv|ref|ldy))', '(amazon|flipkart)', '([^']+)'\)",
            value_block,
        ))
        expected_rules = {
            (source_key, retailer.lower(), column)
            for source_key, retailers in SIEL_COLUMNS.items()
            for retailer, columns in retailers.items()
            for column in columns
        }

        self.assertEqual(expected_rules, seeded_rules)
        self.assertEqual(40, len(seeded_rules))
        self.assertIn('query_days', sql)
        self.assertIn('0::integer AS query_days', sql)
        self.assertNotIn('monitoring_format_rules', sql)

    def test_summary_uses_kst_d_latest_main_batch_without_fallback(self):
        config = minimal_config('siel_tv', 'Amazon', 'sku')
        cursor = ScriptedCursor([
            {'fetchone': ('a_20260831_090000',)},
            {'fetchone': (10, 4)},
            {'fetchall': []},
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=config
        ), patch.object(
            self.service, '_append_tse_null_stats', return_value=0
        ):
            result, issues = self.service.get_null_stats(
                cursor, date(2026, 8, 31), include_youtube=False
            )

        self.assertEqual(4, issues)
        table = result['tables'][0]
        self.assertEqual('siel_tv_retail', table['table'])
        self.assertEqual('2026-08-31', table['inspection_date'])
        self.assertEqual('2026-08-31', table['source_date'])
        self.assertEqual(0, table['offset_days'])
        self.assertEqual(
            'a_20260831_090000', table['retailers'][0]['batch_id']
        )

        anchor_sql, anchor_params = cursor.calls[0]
        self.assertIn('FROM dx_siel.dx_siel_tv_retail_com anchor', anchor_sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", anchor_sql)
        self.assertIn("= 'main'", anchor_sql)
        self.assertEqual(
            ['2026-08-31', '2026-08-31', 'Amazon'], anchor_params
        )

        count_sql, count_params = cursor.calls[1]
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', count_sql)
        self.assertIn("IN ('main', 'bsr')", count_sql)
        self.assertIn(
            "NOT (account_name = 'Amazon' AND redirect IS TRUE)",
            count_sql,
        )
        self.assertNotIn("INTERVAL '3 days'", count_sql)
        self.assertEqual(
            [
                '2026-08-31', '2026-08-31', 'Amazon',
                'a_20260831_090000',
            ],
            count_params,
        )

    def test_missing_main_anchor_returns_zero_without_recent_date_fallback(self):
        config = minimal_config('siel_tv', 'Amazon', 'sku')
        cursor = ScriptedCursor([
            {'fetchone': None},
            {'fetchone': (0, 0)},
            {'fetchall': []},
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=config
        ), patch.object(
            self.service, '_append_tse_null_stats', return_value=0
        ):
            result, issues = self.service.get_null_stats(
                cursor, date(2026, 8, 31), include_youtube=False
            )

        self.assertEqual(0, issues)
        self.assertEqual(0, result['tables'][0]['total_records'])
        count_sql, count_params = cursor.calls[1]
        self.assertIn('WHERE FALSE', count_sql)
        self.assertEqual([], count_params)
        self.assertNotIn('MAX(', count_sql)

    def test_detail_history_keeps_current_null_and_comparison_rows(self):
        config = minimal_config('siel_ldy', 'Flipkart', 'sku')
        description = [
            ('id',), ('account_name',), ('page_type',), ('item',),
            ('sku',), ('crawl_datetime',), ('batch_id',), ('product_url',),
        ]
        cursor = ScriptedCursor([
            {'fetchone': ('f_20260831_090000',)},
            {
                'description': description,
                'fetchall': [(
                    42, 'Flipkart', 'main', 'item-1', None,
                    '2026-08-31 08:50:00', 'f_20260831_090000', 'https://p/1',
                )],
            },
            {'fetchall': []},
            {
                'description': description,
                'fetchall': [
                    (
                        41, 'Flipkart', 'main', 'item-1', 'OLD-SKU',
                        '2026-08-30 08:40:00', 'f_20260830_090000',
                        'https://p/1',
                    ),
                    (
                        42, 'Flipkart', 'main', 'item-1', None,
                        '2026-08-31 08:50:00', 'f_20260831_090000',
                        'https://p/1',
                    ),
                ],
            },
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=config
        ):
            result = self.service.get_null_detail(
                cursor, date(2026, 8, 31), 'siel_ldy_retail',
                'Flipkart', 2, 'sku',
            )

        self.assertEqual([41, 42], [row['id'] for row in result['results']])
        self.assertEqual([], result['editable_cols'])
        self.assertEqual('2026-08-31', result['source_date'])
        self.assertEqual(0, result['offset_days'])
        self.assertEqual('Asia/Seoul', result['business_timezone'])
        self.assertEqual(2, result['history_days'])
        self.assertEqual([], result['results'][0]['null_fields'])
        self.assertEqual(['sku'], result['results'][1]['null_fields'])

        history_sql, history_params = cursor.calls[3]
        self.assertIn('WITH latest_batches AS', history_sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", history_sql)
        self.assertIn('SELECT DISTINCT ON', history_sql)
        self.assertIn(
            'source.batch_id IS NOT DISTINCT FROM latest.batch_id',
            history_sql,
        )
        self.assertIn(
            "NOT (source.account_name = 'Amazon' "
            "AND source.redirect IS TRUE)",
            history_sql,
        )
        self.assertEqual(
            [
                '2026-08-30', '2026-08-31', 'Flipkart', 'Flipkart',
                'item-1',
            ],
            history_params,
        )

    def test_detail_displays_siel_timestamptz_as_kst_not_utc_date(self):
        config = minimal_config('siel_tv', 'Amazon', 'sku')
        description = [
            ('id',), ('account_name',), ('page_type',), ('item',),
            ('sku',), ('crawl_datetime',), ('batch_id',), ('product_url',),
        ]
        cursor = ScriptedCursor([
            {'fetchone': ('a_20260902_160000',)},
            {
                'description': description,
                'fetchall': [(
                    91, 'Amazon', 'main', 'item-9', None,
                    datetime(2026, 9, 2, 16, 10, tzinfo=timezone.utc),
                    'a_20260902_160000', 'https://p/9',
                )],
            },
            {'fetchall': []},
        ])

        with patch.object(
            self.service, 'load_null_check_config', return_value=config
        ):
            result = self.service.get_null_detail(
                cursor, date(2026, 9, 3), 'siel_tv_retail',
                'Amazon', 1, 'sku',
            )

        self.assertEqual('2026-09-03', result['source_date'])
        self.assertEqual(
            '2026-09-03 01:10:00',
            result['results'][0]['crawl_datetime'],
        )
        self.assertEqual(
            'a_20260902_160000', result['results'][0]['batch_id']
        )

    def test_review_allows_empty_memo_and_rechecks_retailer_column_matrix(self):
        empty_memo_cursor = ScriptedCursor([
            {'fetchone': (None, 'Amazon', 'item-1')},
            {'fetchone': None},
            {},
        ])
        empty_memo_conn = Mock()
        empty_memo = self.service.save_null_review(
            empty_memo_cursor, empty_memo_conn,
            'dx_siel.dx_siel_ref_retail_com', 42, 'sku', 'normal', '',
            '수집처 특례', '2026-08-31', 'null', 'tester',
        )
        self.assertTrue(empty_memo['success'])
        self.assertIsNone(empty_memo_cursor.calls[2][1][11])
        empty_memo_conn.commit.assert_called_once_with()

        amazon_cursor = ScriptedCursor([
            {'fetchone': (None, 'Amazon', 'item-1')},
        ])
        wrong_retailer_column = self.service.save_null_review(
            amazon_cursor, Mock(), 'dx_siel.dx_siel_ref_retail_com', 42,
            'ref_capacity', 'normal', '확인 메모', '수집처 특례',
            '2026-08-31', 'null', 'tester',
        )
        self.assertEqual(
            '허용되지 않는 리테일러별 컬럼',
            wrong_retailer_column['error'],
        )

        cursor = ScriptedCursor([
            {'fetchone': (None, 'Flipkart', 'item-2')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()
        accepted = self.service.save_null_review(
            cursor, conn, 'dx_siel.dx_siel_ref_retail_com', 77,
            'ref_capacity', 'normal', '확인 메모', '수집처 특례',
            '2026-08-31', 'null', 'tester',
        )

        self.assertTrue(accepted['success'])
        scope_sql, scope_params = cursor.calls[0]
        self.assertIn('WITH latest_main_batches AS', scope_sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", scope_sql)
        self.assertIn(
            "NOT (source.account_name = 'Amazon' "
            "AND source.redirect IS TRUE)",
            scope_sql,
        )
        self.assertEqual(
            (
                '2026-08-31', '2026-08-31', 'amazon', 'flipkart', 77,
                '2026-08-31', '2026-08-31',
            ),
            scope_params,
        )
        conn.commit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
