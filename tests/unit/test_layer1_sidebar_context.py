import unittest

from tests.unit.support import load_module, module_stub, package_stub


class Layer1SidebarContextTests(unittest.TestCase):
    def _load_context(self):
        schedules = [
            {'check_type': 'youtube', 'schedule_type': 'daily'},
            {'check_type': 'tse_retail', 'schedule_type': 'daily'},
            {'check_type': 'siel_retail', 'schedule_type': 'daily'},
            {'check_type': 'retail', 'schedule_type': 'daily'},
            {'check_type': 'macro_cpi', 'schedule_type': 'monthly'},
        ]
        return load_module(
            'apps/dx/dx_layer1/common/context.py',
            'tests._layer1_context_under_test',
            {
                'apps': package_stub('apps'),
                'apps.common': package_stub('apps.common'),
                'apps.common.dx_schedules': module_stub(
                    'apps.common.dx_schedules',
                    load_collection_schedules=lambda: schedules,
                ),
                'apps.common.monitoring_exclusions': module_stub(
                    'apps.common.monitoring_exclusions',
                    DISABLED_CHECK_TYPES=frozenset(),
                ),
            },
        )

    def test_primary_daily_sidebar_order_and_labels(self):
        context = self._load_context()

        groups = context._build_sidebar_groups('siel_retail')
        daily = groups[0]

        self.assertEqual(
            ['SEA Retail', 'SIEL Retail', 'TSE Retail', 'YouTube'],
            [item['name'] for item in daily['items']],
        )
        self.assertTrue(daily['items'][1]['active'])
        self.assertEqual('SIEL Retail', context.SECTION_TITLES['siel_retail'])
        self.assertEqual('TSE Retail', context.SECTION_TITLES['tse_retail'])

    def test_unrelated_period_sections_remain_available(self):
        context = self._load_context()

        groups = context._build_sidebar_groups('macro_cpi')
        period = groups[1]

        self.assertEqual(['소비자 물가 지수'], [item['name'] for item in period['items']])
        self.assertTrue(period['items'][0]['active'])


if __name__ == '__main__':
    unittest.main()
