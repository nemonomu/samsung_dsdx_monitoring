import unittest
from unittest.mock import patch

from tests.unit.support import load_module, module_stub, package_stub


CONFIG = {
    'tv_retail': {'display_name': 'TV Retail'},
    'sea_ref_retail': {'display_name': 'SEA REF'},
    'sea_ldy_retail': {'display_name': 'SEA LDY'},
    'siel_tv_retail': {'display_name': 'SIEL TV'},
    'siel_ref_retail': {'display_name': 'SIEL REF'},
    'siel_ldy_retail': {'display_name': 'SIEL LDY'},
    'youtube': {'display_name': 'YouTube'},
}


class Layer2SielSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stubs = {
            'apps': package_stub('apps'),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.null_validation': package_stub(
                'apps.dx.dx_layer2.null_validation'
            ),
            'apps.dx.dx_layer2.null_validation.services': module_stub(
                'apps.dx.dx_layer2.null_validation.services',
                load_null_check_config=lambda: CONFIG,
                get_all_categories=lambda: list(CONFIG),
            ),
        }
        cls.context = load_module(
            'apps/dx/dx_layer2/common/context.py',
            'layer2_siel_sidebar_context_under_test',
            stubs=cls.stubs,
        )

    def test_siel_parent_and_children_exist_in_all_layer2_sidebars(self):
        with patch.dict('sys.modules', self.stubs):
            groups = self.context.build_sidebar_groups(
                'null_validation', focus='siel_ref_retail'
            )

        null_items = groups[0]['items']
        self.assertEqual(
            ['SEA Retail', 'SIEL Retail', 'YouTube'],
            [item['name'] for item in null_items],
        )
        siel_parent = null_items[1]
        self.assertTrue(siel_parent['active'])
        self.assertEqual(
            [
                ('TV', 'siel_tv_retail', False),
                ('REF', 'siel_ref_retail', True),
                ('LDY', 'siel_ldy_retail', False),
            ],
            [
                (child['label'], child['detail_code'], child['active'])
                for child in siel_parent['children']
            ],
        )
        for group in groups[1:3]:
            siel_parent = next(
                item for item in group['items']
                if item['name'] == 'SIEL Retail'
            )
            self.assertEqual(
                ['TV', 'REF', 'LDY'],
                [child['label'] for child in siel_parent['children']],
            )

    def test_legacy_sidebar_items_include_siel_for_all_validation_types(self):
        with patch.dict('sys.modules', self.stubs):
            items = self.context.get_sidebar_items()

        self.assertEqual(
            {
                'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail',
            },
            {
                item['key'] for item in items['null']
                if item['key'].startswith('siel_')
            },
        )
        for key in ('format', 'anomaly'):
            self.assertEqual(
                {
                    'siel_tv_retail', 'siel_ref_retail',
                    'siel_ldy_retail',
                },
                {
                    item['key'] for item in items[key]
                    if item['key'].startswith('siel_')
                },
            )


if __name__ == '__main__':
    unittest.main()
