import unittest
from unittest.mock import patch

from tests.unit.support import load_module, module_stub, package_stub


class Layer2SegSidebarTests(unittest.TestCase):
    def test_seg_is_below_siel_for_null_and_duplicate_only(self):
        config = {
            'siel_tv_retail': {'display_name': 'SIEL TV'},
            'sem_tv_retail': {'display_name': 'SEM TV'},
            'youtube': {'display_name': 'YouTube'},
        }
        categories = [
            *config,
            'seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail',
        ]
        stubs = {
            'apps': package_stub('apps'),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.null_validation': package_stub(
                'apps.dx.dx_layer2.null_validation'
            ),
            'apps.dx.dx_layer2.null_validation.services': module_stub(
                'apps.dx.dx_layer2.null_validation.services',
                load_null_check_config=lambda: config,
                get_all_categories=lambda: categories,
            ),
        }
        context = load_module(
            'apps/dx/dx_layer2/common/context.py',
            'layer2_seg_sidebar_context_under_test',
            stubs=stubs,
        )

        with patch.dict('sys.modules', stubs):
            groups = context.build_sidebar_groups(
                'null_validation', focus='seg_ref_retail'
            )

        null_names = [item['name'] for item in groups[0]['items']]
        format_names = [item['name'] for item in groups[1]['items']]
        duplicate_names = [item['name'] for item in groups[2]['items']]
        self.assertEqual(
            ['SIEL Retail', 'SEG Retail', 'SEM Retail', 'YouTube'],
            null_names,
        )
        self.assertEqual(
            ['SIEL Retail', 'SEG Retail', 'SEM Retail', 'YouTube'],
            duplicate_names,
        )
        self.assertEqual(
            ['SIEL Retail', 'SEM Retail', 'YouTube'], format_names
        )
        seg_parent = groups[0]['items'][1]
        self.assertTrue(seg_parent['active'])
        self.assertEqual(
            [
                ('TV', 'seg_tv_retail', False),
                ('REF', 'seg_ref_retail', True),
                ('LDY', 'seg_ldy_retail', False),
            ],
            [
                (child['label'], child['detail_code'], child['active'])
                for child in seg_parent['children']
            ],
        )


if __name__ == '__main__':
    unittest.main()
