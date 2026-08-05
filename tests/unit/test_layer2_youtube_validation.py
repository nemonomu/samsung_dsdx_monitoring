import ast
import inspect
import textwrap
import unittest
from datetime import date, datetime
from unittest.mock import Mock

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


def common_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda alias=None: (
                f"NOT ({alias + '.' if alias else ''}account_name = 'Amazon' "
                f"AND {alias + '.' if alias else ''}redirect IS TRUE)"
            ),
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset({
                'market_trend',
                'openai_forecast_results',
                'openai_retailer_promotions',
                'market_comp_product',
                'market_comp_event',
            }),
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
        'apps.dx.dx_layer2.common': package_stub('apps.dx.dx_layer2.common'),
        'apps.dx.dx_layer2.common.context': module_stub(
            'apps.dx.dx_layer2.common.context',
            get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
        ),
    }


class YouTubeNullValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        stubs.update({
            'apps.common.db': module_stub(
                'apps.common.db',
                execute_dx_query=lambda _query: [],
                dx_table=lambda table: table,
            ),
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda *_: None
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                load_retail_columns=lambda: {},
                get_editable_columns=lambda *_: [],
            ),
        })
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_null_service_under_test',
            stubs,
        )
        cls._load_null_check_config = staticmethod(
            cls.service.load_null_check_config
        )

    def setUp(self):
        self.service.load_null_check_config = self._load_null_check_config
        self.service._null_check_config_cache = None
        self.service._null_check_config_cache_time = None
        self.service.log_error = lambda *_: None

    def test_legacy_db_rules_are_replaced_by_three_country_structure_checks(self):
        self.service.execute_dx_query = lambda _query: [{
            'category': 'youtube',
            'cat_display_name': 'YouTube',
            'display_order': 3,
            'has_retailer': False,
            'check_name': 'youtube_logs',
            'group_display_name': 'Logs',
            'table_name': 'youtube_collection_logs',
            'date_column': 'started_at',
            'check_column': 'keyword',
            'check_type': 'both',
            'display_columns': 'id|keyword',
            'query_columns': 'id|keyword',
            'query_days': 0,
        }]

        config = self.service.load_null_check_config()

        checks = config['youtube']['checks']
        self.assertEqual(
            {'youtube_country_runs', 'youtube_videos', 'youtube_comments'},
            set(checks),
        )
        self.assertNotIn('youtube_logs', checks)
        self.assertIn(
            'collection_country', checks['youtube_videos']['columns']
        )
        self.assertIn(
            'collection_batch_id', checks['youtube_comments']['columns']
        )
        self.assertNotIn(
            'youtube_collection_logs', self.service.VALID_TABLES_UPDATE
        )

    def test_failed_db_rule_load_returns_youtube_but_is_not_cached(self):
        attempts = {'count': 0}

        def fail(_query):
            attempts['count'] += 1
            raise RuntimeError('rule load failed')

        self.service.execute_dx_query = fail

        first = self.service.load_null_check_config()
        second = self.service.load_null_check_config()

        self.assertIn('youtube', first)
        self.assertIn('youtube', second)
        self.assertEqual(2, attempts['count'])
        self.assertIsNone(self.service._null_check_config_cache)

    def test_missing_display_order_does_not_hide_existing_tv_config(self):
        self.service.execute_dx_query = lambda _query: [{
            'category': 'tv',
            'cat_display_name': 'TV Retail',
            'display_order': None,
            'has_retailer': True,
            'check_name': 'amazon',
            'group_display_name': 'Amazon',
            'table_name': 'tv_retail_com',
            'date_column': 'crawl_datetime',
            'check_column': 'item',
            'check_type': 'both',
            'display_columns': 'id|item',
            'query_columns': 'id|item',
            'query_days': 0,
        }]

        config = self.service.load_null_check_config()

        self.assertIn('tv', config)
        self.assertIn('youtube', config)

    def test_null_stats_can_skip_only_youtube_for_transaction_recovery(self):
        self.service.load_null_check_config = lambda: {
            'youtube': self.service._YOUTUBE_NULL_CONFIG,
        }
        cursor = ScriptedCursor([])

        validation, total = self.service.get_null_stats(
            cursor, date(2026, 7, 29), include_youtube=False
        )

        self.assertEqual([], validation['tables'])
        self.assertEqual(0, total)
        self.assertEqual([], cursor.calls)

    def test_run_scope_can_count_null_collection_date_by_started_at(self):
        where_sql, params = self.service._build_null_date_where({
            'table_name': 'youtube_country_collection_runs',
            'date_column': 'collection_date',
            'youtube_scope': 'runs',
        }, date(2026, 7, 29))

        self.assertIn(
            'COALESCE(collection_date, DATE(started_at)) = %s', where_sql
        )
        self.assertEqual([date(2026, 7, 29)], params)

    def test_record_scope_handles_full_and_partial_country_batch_keys(self):
        where_sql, params = self.service._build_null_date_where({
            'table_name': 'youtube_videos',
            'date_column': 'created_at',
            'youtube_scope': 'records',
        }, date(2026, 7, 29))

        self.assertIn('matched_run.collection_country', where_sql)
        self.assertIn('matched_run.batch_id', where_sql)
        self.assertIn('batch_run.batch_id', where_sql)
        self.assertIn('country_run.collection_country', where_sql)
        self.assertIn('DATE(youtube_videos.created_at)', where_sql)
        self.assertNotIn('youtube_collection_logs', where_sql)
        self.assertEqual([date(2026, 7, 29)] * 5, params)

    def test_youtube_review_rejects_columns_outside_static_config(self):
        cursor = ScriptedCursor([])

        result = self.service.save_null_review(
            cursor, Mock(), 'youtube_videos', 1, 'account_name', 'normal',
            '', 'data_issue', date(2026, 7, 29), 'null', 'tester'
        )

        self.assertEqual(400, result['status_code'])
        self.assertEqual([], cursor.calls)

    def test_youtube_review_does_not_select_legacy_retail_columns(self):
        cursor = ScriptedCursor([
            {'fetchone': (None,)},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'youtube_videos', 1, 'title', 'normal',
            '', 'data_issue', date(2026, 7, 29), 'null', 'tester'
        )

        self.assertTrue(result['success'])
        self.assertIn('SELECT title FROM youtube_videos', cursor.calls[0][0])
        self.assertNotIn('account_name', cursor.calls[0][0])
        self.assertNotIn('item', cursor.calls[0][0])
        conn.commit.assert_called_once_with()

    def test_stopped_market_null_rules_are_not_loaded(self):
        self.service.execute_dx_query = lambda _query: [
            {
                'category': 'market', 'cat_display_name': 'Market',
                'display_order': 4, 'has_retailer': False,
                'check_name': 'market_comp_product',
                'group_display_name': 'Comp Product',
                'table_name': 'market_comp_product',
                'date_column': 'created_at', 'check_column': 'comp_brand',
                'check_type': 'both', 'display_columns': 'id|comp_brand',
                'query_columns': 'id|comp_brand', 'query_days': 0,
            },
            {
                'category': 'market', 'cat_display_name': 'Market',
                'display_order': 4, 'has_retailer': False,
                'check_name': 'market_trend',
                'group_display_name': 'Trend',
                'table_name': 'market_trend',
                'date_column': 'crawl_at_local_time', 'check_column': 'keyword',
                'check_type': 'both', 'display_columns': 'id|keyword',
                'query_columns': 'id|keyword', 'query_days': 0,
            },
        ]

        config = self.service.load_null_check_config()

        self.assertNotIn('market', config)
        self.assertNotIn('market_trend', self.service.VALID_TABLES_UPDATE)
        self.assertNotIn('market_comp_product', self.service.VALID_TABLES_UPDATE)


class YouTubeDuplicateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        stubs['apps.common.retail_columns'] = module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [],
            get_duplicate_key_columns=lambda *_: None,
            get_retailer_list=lambda: [],
            get_retail_duplicate_keys=lambda *_: [],
        )
        cls.service = load_module(
            'apps/dx/dx_layer2/anomaly_validation/services.py',
            'layer2_anomaly_service_under_test',
            stubs,
        )

    def test_stats_use_four_keys_and_ignore_created_at_date(self):
        cursor = ScriptedCursor([
            {'fetchone': (841,)},
            {'fetchone': (0,)},
        ])

        result = self.service._get_youtube_video_duplicate_stats(
            cursor, date(2026, 7, 29)
        )

        self.assertEqual(841, result['total_records'])
        self.assertEqual(0, result['duplicate_groups'])
        self.assertEqual([
            'video_id', 'keyword', 'collection_country', 'collection_batch_id'
        ], result['duplicate_keys'])
        for sql, params in cursor.calls:
            self.assertIn('youtube_country_collection_runs', sql)
            self.assertIn("v.category = 'HHP'", sql)
            self.assertNotIn('DATE(v.created_at)', sql)
            self.assertNotIn('youtube_collection_logs', sql)
            self.assertEqual((date(2026, 7, 29),), params)
        self.assertIn('v.collection_country', cursor.calls[1][0])
        self.assertIn('v.collection_batch_id', cursor.calls[1][0])

    def test_detail_groups_only_same_country_and_batch(self):
        cursor = ScriptedCursor([
            {'fetchone': (1,)},
            {'fetchall': [(
                'US', 'batch-a', 'video-a', 'galaxy', 2,
                101, 'Galaxy review', datetime(2026, 7, 30, 0, 5),
            )]},
        ])

        result = self.service.get_anomaly_detail(
            cursor, date(2026, 7, 29), 'youtube_videos', '', 1, 1, 50
        )

        duplicate = result['results']['duplicates'][0]
        self.assertEqual('US', duplicate['collection_country'])
        self.assertEqual('batch-a', duplicate['collection_batch_id'])
        self.assertEqual('video-a', duplicate['video_id'])
        self.assertEqual(2, duplicate['dup_count'])
        self.assertNotIn('collection_country', result['select_cols']['group'])
        self.assertNotIn('collection_batch_id', result['select_cols']['group'])
        count_sql, count_params = cursor.calls[0]
        detail_sql, detail_params = cursor.calls[1]
        self.assertIn('GROUP BY v.collection_country', count_sql)
        self.assertIn('y.collection_country = d.collection_country', detail_sql)
        self.assertIn('y.collection_batch_id = d.collection_batch_id', detail_sql)
        self.assertIn("y.category = 'HHP'", detail_sql)
        self.assertEqual((date(2026, 7, 29),), count_params)
        self.assertEqual((date(2026, 7, 29), 50, 0), detail_params)

    def test_legacy_logs_are_not_public_anomaly_targets(self):
        self.assertNotIn(
            'youtube_logs', self.service.VALID_TABLES_ANOMALY
        )
        self.assertNotIn('youtube_logs', self.service._DUP_TABLE_CONFIG)

    def test_stopped_market_duplicate_targets_are_not_public(self):
        self.assertNotIn('market_product', self.service.VALID_TABLES_ANOMALY)
        self.assertNotIn('market_event', self.service.VALID_TABLES_ANOMALY)
        self.assertNotIn('market_product', self.service._DUP_TABLE_CONFIG)
        self.assertNotIn('market_event', self.service._DUP_TABLE_CONFIG)
        self.assertNotIn('market_trend', self.service._DUP_TABLE_CONFIG)

    def test_stopped_market_duplicate_stats_do_not_query_source(self):
        cursor = ScriptedCursor([])

        result = self.service._get_market_duplicate_stats(
            cursor,
            date(2026, 8, 5),
            'market_comp_product',
            'created_at',
            ['batch_id'],
        )

        self.assertIsNone(result)
        self.assertEqual([], cursor.calls)

    def test_anomaly_stats_has_youtube_only_fallback_switch(self):
        source = inspect.getsource(self.service.get_anomaly_stats)
        self.assertIn('include_youtube=True', str(inspect.signature(
            self.service.get_anomaly_stats
        )))
        self.assertIn('if include_youtube:', source)
        self.assertIn('_get_youtube_video_duplicate_stats', source)


class YouTubeFormatValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        stubs.update({
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                validate_field=lambda *_args, **_kwargs: None,
                build_format_error_sql=lambda *_: 'FALSE',
                build_per_field_error_sql=lambda *_: [],
                get_editable_columns=lambda *_: [],
            ),
            'apps.common.db': module_stub(
                'apps.common.db', dx_table=lambda table: table
            ),
        })
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'layer2_format_service_under_test',
            stubs,
        )

    def test_youtube_format_routes_and_rules_are_disabled(self):
        for table in (
            'youtube', 'youtube_logs', 'youtube_videos', 'youtube_comments'
        ):
            self.assertNotIn(table, self.service.VALID_TABLES_FORMAT)
        for table in (
            'youtube_collection_logs', 'youtube_videos', 'youtube_comments'
        ):
            self.assertNotIn(table, self.service.VALID_TABLES_RULES)

    def test_format_stats_no_longer_builds_youtube_section(self):
        source = inspect.getsource(self.service.get_format_stats)
        self.assertNotIn('yt_tables', source)
        self.assertNotIn("'table': 'youtube'", source)

    def test_format_stats_interpolates_redirect_filter(self):
        source = inspect.getsource(self.service.get_format_stats)
        tree = ast.parse(textwrap.dedent(source))
        literal_sql = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

        self.assertFalse(any(
            '{get_tv_validation_condition' in value
            for value in literal_sql
        ))

    def test_stopped_market_format_detail_does_not_query_source(self):
        cursor = ScriptedCursor([])

        result = self.service.get_format_detail(
            cursor, date(2026, 8, 5), 'market', 'Comp Product', 1
        )

        self.assertEqual([], result['results'])
        self.assertEqual('', result['actual_table'])
        self.assertEqual([], cursor.calls)
        self.assertNotIn('market_trend', self.service.VALID_TABLES_RULES)
        self.assertNotIn(
            'market_comp_product', self.service.VALID_TABLES_RULES
        )


if __name__ == '__main__':
    unittest.main()
