import unittest
from unittest.mock import patch

from tests.unit.support import load_module, module_stub, package_stub


LEGACY_CONFIG = {
    'tv_retail': {'display_name': 'TV Retail'},
    'youtube': {'display_name': 'YouTube'},
}


class Layer2TseSidebarContextTests(unittest.TestCase):
    def _load_context(self, categories):
        stubs = {
            'apps': package_stub('apps'),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.null_validation': package_stub(
                'apps.dx.dx_layer2.null_validation'
            ),
            'apps.dx.dx_layer2.null_validation.services': module_stub(
                'apps.dx.dx_layer2.null_validation.services',
                load_null_check_config=lambda: LEGACY_CONFIG,
                get_all_categories=lambda: categories,
            ),
        }
        context = load_module(
            'apps/dx/dx_layer2/common/context.py',
            'layer2_tse_sidebar_context_under_test',
            stubs=stubs,
        )
        return context, stubs

    def test_null_sidebar_has_non_click_parent_and_canonical_children(self):
        context, stubs = self._load_context([
            'tv_retail', 'youtube',
            'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail',
        ])

        with patch.dict('sys.modules', stubs):
            groups = context.build_sidebar_groups(
                'null_validation', focus='tse_ref_retail'
            )
        null_group, format_group, anomaly_group = groups
        tse_parent = null_group['items'][-1]

        self.assertEqual('TSE', tse_parent['name'])
        self.assertNotIn('detail_code', tse_parent)
        self.assertTrue(tse_parent['active'])
        self.assertEqual(
            [
                ('TSE TV', 'TV', 'tse_tv_retail', False),
                ('TSE REF', 'REF', 'tse_ref_retail', True),
                ('TSE LDY', 'LDY', 'tse_ldy_retail', False),
            ],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in tse_parent['children']
            ],
        )
        self.assertFalse(any(item.get('name') == 'TSE' for item in format_group['items']))
        self.assertFalse(any(item.get('name') == 'TSE' for item in anomaly_group['items']))

    def test_display_focus_activates_child_and_inactive_sources_are_hidden(self):
        context, stubs = self._load_context([
            'tv_retail', 'youtube', 'tse_tv_retail',
        ])

        with patch.dict('sys.modules', stubs):
            null_group = context.build_sidebar_groups(
                'null_validation', focus='TSE TV'
            )[0]
        tse_parent = null_group['items'][-1]

        self.assertEqual(['TSE TV'], [child['name'] for child in tse_parent['children']])
        self.assertEqual(['TV'], [child['label'] for child in tse_parent['children']])
        self.assertTrue(tse_parent['children'][0]['active'])
        self.assertEqual(
            ['TV Retail', 'YouTube'],
            [item['name'] for item in null_group['items'][:-1]],
        )

    def test_tse_parent_is_omitted_when_no_tse_source_is_active(self):
        context, stubs = self._load_context(['tv_retail', 'youtube'])

        with patch.dict('sys.modules', stubs):
            groups = context.build_sidebar_groups('null_validation')

        self.assertEqual(
            ['TV Retail', 'YouTube'],
            [item['name'] for item in groups[0]['items']],
        )


if __name__ == '__main__':
    unittest.main()
