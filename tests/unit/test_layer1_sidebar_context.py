import unittest

from tests.unit.support import load_module, module_stub, package_stub


class Layer1SidebarContextTests(unittest.TestCase):
    def _load_context(self):
        schedules = [
            {'check_type': 'youtube', 'schedule_type': 'daily'},
            {'check_type': 'seda_retail', 'schedule_type': 'daily'},
            {'check_type': 'tse_retail', 'schedule_type': 'daily'},
            {'check_type': 'sem_retail', 'schedule_type': 'daily'},
            {'check_type': 'seg_retail', 'schedule_type': 'daily'},
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
            [
                'SEA Retail', 'SEDA Retail', 'SIEL Retail', 'SEG Retail', 'SEM Retail',
                'TSE Retail', 'YouTube',
            ],
            [item['name'] for item in daily['items']],
        )
        self.assertTrue(daily['items'][2]['active'])
        self.assertEqual('SEDA Retail', context.SECTION_TITLES['seda_retail'])
        self.assertEqual('SIEL Retail', context.SECTION_TITLES['siel_retail'])
        self.assertEqual('TSE Retail', context.SECTION_TITLES['tse_retail'])

    def test_unrelated_period_sections_remain_available(self):
        context = self._load_context()

        groups = context._build_sidebar_groups('macro_cpi')
        period = groups[1]

        self.assertEqual(['소비자 물가 지수'], [item['name'] for item in period['items']])
        self.assertTrue(period['items'][0]['active'])

    def test_rank_menus_have_country_children_and_do_not_reuse_inspection_date(self):
        groups = self._load_context()._build_sidebar_groups('rank_samsung_SEG')
        rank_groups = [g for g in groups if g['key'].startswith('rank_')]
        self.assertEqual(['전체 상품 순위', '삼성 제품 순위'], [g['label'] for g in rank_groups])
        self.assertFalse(rank_groups[0]['active'])
        self.assertTrue(rank_groups[1]['expanded'])
        self.assertEqual(8, len(rank_groups[0]['items']))
        selected = [item for item in rank_groups[1]['items'] if item['active']]
        self.assertEqual('/dx/layer1/rank/samsung/SEG/', selected[0]['href'])
        self.assertTrue(all(item['ignore_target_date'] for group in rank_groups for item in group['items']))


if __name__ == '__main__':
    unittest.main()
