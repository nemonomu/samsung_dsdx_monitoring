import unittest
from datetime import date, datetime

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class Layer2NonProductNullValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db',
                execute_dx_query=lambda _query: [],
                dx_table=lambda table: table,
            ),
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda *_: None,
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                load_retail_columns=lambda: {},
                get_editable_columns=lambda *_: [],
            ),
            'apps.common.retail_validation': module_stub(
                'apps.common.retail_validation',
                get_tv_validation_condition=lambda alias=None: (
                    "NOT (account_name = 'Amazon' AND redirect IS TRUE)"
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
            'apps.dx.dx_layer2.common': package_stub(
                'apps.dx.dx_layer2.common'
            ),
            'apps.dx.dx_layer2.common.context': module_stub(
                'apps.dx.dx_layer2.common.context',
                get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_non_product_null_service_under_test',
            stubs,
        )

    @staticmethod
    def _config():
        return {
            'tv_retail': {
                'display_name': 'TV Retail',
                'display_order': 1,
                'has_retailer': True,
                'checks': {
                    'amazon': {
                        'display_name': 'Amazon',
                        'table_name': 'tv_retail_com',
                        'date_column': 'crawl_datetime',
                        'columns': {
                            'screen_size': {
                                'check_type': 'both',
                                'display_columns': [],
                                'query_columns': [],
                                'query_days': 0,
                            },
                        },
                    },
                },
            },
        }

    def setUp(self):
        self.service.load_null_check_config = self._config

    def test_condition_matches_only_false_product_by_item_and_retailer(self):
        condition = self.service.get_non_product_exclusion_condition(
            'tv_retail_com'
        )

        self.assertIn('FROM tv_item_mst non_product', condition)
        self.assertIn('non_product.is_product IS FALSE', condition)
        self.assertIn('non_product.item IS NOT DISTINCT FROM tv_retail_com.item', condition)
        self.assertIn(
            'non_product.account_name IS NOT DISTINCT FROM tv_retail_com.account_name',
            condition,
        )
        self.assertNotIn('is_checked', condition)
        self.assertEqual(
            '',
            self.service.get_non_product_exclusion_condition('youtube_videos'),
        )

    def test_null_summary_excludes_non_products(self):
        cursor = ScriptedCursor([
            {'fetchone': (10, 1)},
            {'fetchall': []},
        ])

        self.service.get_null_stats(cursor, date(2026, 8, 3))

        summary_sql = cursor.calls[0][0]
        self.assertIn('FROM tv_item_mst non_product', summary_sql)
        self.assertIn('non_product.is_product IS FALSE', summary_sql)

    def test_null_detail_and_history_expansion_exclude_non_products(self):
        description = [
            ('id',), ('item',), ('screen_size',), ('crawl_datetime',),
        ]
        row = (1, 'TV-1', None, datetime(2026, 8, 3, 12, 0, 0))
        cursor = ScriptedCursor([
            {'description': description, 'fetchall': [row]},
            {'fetchall': []},
            {'description': description, 'fetchall': [row]},
        ])

        self.service.get_null_detail(
            cursor,
            date(2026, 8, 3),
            'tv_retail',
            'Amazon',
            3,
            'screen_size',
        )

        self.assertEqual(3, len(cursor.calls))
        self.assertIn('FROM tv_item_mst non_product', cursor.calls[0][0])
        self.assertIn('FROM tv_item_mst non_product', cursor.calls[2][0])


if __name__ == '__main__':
    unittest.main()
