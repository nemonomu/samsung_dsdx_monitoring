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
        tse_parent = next(
            item for item in null_group['items']
            if item['name'] == 'TSE Retail'
        )

        self.assertEqual('TSE Retail', tse_parent['name'])
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
        self.assertEqual(
            ['SEA Retail', 'TSE Retail', 'YouTube'],
            [item['name'] for item in null_group['items']],
        )
        self.assertEqual(
            ['SEA Retail', 'TSE Retail', 'YouTube'],
            [item['name'] for item in format_group['items']],
        )
        self.assertEqual(
            ['SEA Retail', 'TSE Retail', 'YouTube', 'NULL 검수 로그'],
            [item['name'] for item in anomaly_group['items']],
        )
        self.assertEqual(
            '/dx/layer2/review-log/', anomaly_group['items'][-1]['href']
        )

        sea_parent = null_group['items'][0]
        self.assertEqual('SEA Retail', sea_parent['name'])
        self.assertEqual(
            [('SEA Retail', 'TV', 'tv_retail', False)],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in sea_parent['children']
            ],
        )

        self.assertFalse(format_group['items'][1]['active'])
        self.assertFalse(anomaly_group['items'][1]['active'])

    def test_sea_parent_activates_its_tv_child(self):
        context, stubs = self._load_context([
            'tv_retail', 'youtube',
            'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail',
        ])

        for focus in ('SEA Retail', 'TV Retail', 'tv_retail'):
            with self.subTest(focus=focus), patch.dict('sys.modules', stubs):
                null_group = context.build_sidebar_groups(
                    'null_validation', focus=focus
                )[0]

            sea_parent = null_group['items'][0]
            self.assertTrue(sea_parent['active'])
            self.assertTrue(sea_parent['children'][0]['active'])

    def test_tse_children_are_active_in_format_and_duplicate_sections(self):
        context, stubs = self._load_context([
            'tv_retail', 'youtube',
            'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail',
        ])

        with patch.dict('sys.modules', stubs):
            format_group = context.build_sidebar_groups(
                'format_validation', focus='tse_tv_retail'
            )[1]
            anomaly_group = context.build_sidebar_groups(
                'anomaly_validation', focus='TSE LDY'
            )[2]

        format_tse = next(
            item for item in format_group['items']
            if item['name'] == 'TSE Retail'
        )
        anomaly_tse = next(
            item for item in anomaly_group['items']
            if item['name'] == 'TSE Retail'
        )
        self.assertTrue(format_tse['active'])
        self.assertTrue(format_tse['children'][0]['active'])
        self.assertTrue(anomaly_tse['active'])
        self.assertTrue(anomaly_tse['children'][2]['active'])

    def test_display_focus_activates_child_and_inactive_sources_are_hidden(self):
        context, stubs = self._load_context([
            'tv_retail', 'youtube', 'tse_tv_retail',
        ])

        with patch.dict('sys.modules', stubs):
            null_group = context.build_sidebar_groups(
                'null_validation', focus='TSE TV'
            )[0]
        tse_parent = next(
            item for item in null_group['items']
            if item['name'] == 'TSE Retail'
        )

        self.assertEqual(['TSE TV'], [child['name'] for child in tse_parent['children']])
        self.assertEqual(['TV'], [child['label'] for child in tse_parent['children']])
        self.assertTrue(tse_parent['children'][0]['active'])
        self.assertEqual(
            ['SEA Retail', 'YouTube'],
            [
                item['name'] for item in null_group['items']
                if item['name'] != 'TSE Retail'
            ],
        )

    def test_tse_parent_is_omitted_when_no_tse_source_is_active(self):
        context, stubs = self._load_context(['tv_retail', 'youtube'])

        with patch.dict('sys.modules', stubs):
            groups = context.build_sidebar_groups('null_validation')

        self.assertEqual(
            ['SEA Retail', 'YouTube'],
            [item['name'] for item in groups[0]['items']],
        )

    def test_null_review_log_is_active_under_duplicate_group(self):
        context, stubs = self._load_context(['tv_retail', 'youtube'])

        with patch.dict('sys.modules', stubs):
            anomaly_group = context.build_sidebar_groups(
                'null_review_log'
            )[2]

        self.assertTrue(anomaly_group['active'])
        self.assertTrue(anomaly_group['expanded'])
        self.assertTrue(anomaly_group['items'][-1]['active'])


if __name__ == '__main__':
    unittest.main()
