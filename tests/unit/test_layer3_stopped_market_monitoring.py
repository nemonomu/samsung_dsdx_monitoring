import unittest

from tests.unit.support import load_module, module_stub, package_stub


class Layer3StoppedMarketMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db',
                get_dx_connection=lambda: None,
                dx_table=lambda table: table,
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
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda *_: None
            ),
            'apps.common.retail_validation': module_stub(
                'apps.common.retail_validation',
                apply_tv_validation_scope=lambda query, _table: query,
                get_tv_validation_condition=lambda: 'TRUE',
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
            'apps.dx.dx_layer3.dashboard': package_stub(
                'apps.dx.dx_layer3.dashboard'
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer3/dashboard/services.py',
            'layer3_dashboard_service_under_test',
            stubs,
        )

    def test_stopped_market_rules_are_excluded(self):
        for table_name in (
            'market_trend',
            'openai_forecast_results',
            'openai_retailer_promotions',
            'market_comp_product',
            'market_comp_event',
        ):
            self.assertTrue(self.service.is_excluded_retail_rule({
                'table_name': table_name,
                'section_code': 'market',
            }))

    def test_tv_and_youtube_tables_remain_enabled(self):
        self.assertFalse(self.service.is_excluded_retail_rule({
            'table_name': 'tv_retail_com',
            'section_code': 'tv',
        }))
        self.assertNotIn(
            'openai_forecast_results', self.service._ALLOWED_TABLES
        )


if __name__ == '__main__':
    unittest.main()
