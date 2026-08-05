import unittest

from tests.unit.support import load_module, module_stub, package_stub


class StoppedMarketDataEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
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
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                get_editable_columns=lambda *_: [],
            ),
        }
        cls.layer2 = load_module(
            'apps/dx/dx_layer2/data_edit/services.py',
            'layer2_data_edit_service_under_test',
            stubs,
        )
        cls.layer3 = load_module(
            'apps/dx/dx_layer3/data_edit/services.py',
            'layer3_data_edit_service_under_test',
            stubs,
        )

    def test_all_market_sources_are_blocked(self):
        for service in (self.layer2, self.layer3):
            self.assertTrue({
                'market_trend',
                'openai_forecast_results',
                'market_comp_product',
                'market_comp_event',
            }.isdisjoint(service.VALID_TABLES_UPDATE))

    def test_tv_and_youtube_remain_allowed(self):
        for service in (self.layer2, self.layer3):
            self.assertIn('tv_retail_com', service.VALID_TABLES_UPDATE)
            self.assertIn('youtube_videos', service.VALID_TABLES_UPDATE)
            self.assertIn('youtube_comments', service.VALID_TABLES_UPDATE)


if __name__ == '__main__':
    unittest.main()
