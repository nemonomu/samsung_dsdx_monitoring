import unittest
from types import SimpleNamespace

from tests.unit.support import load_module, module_stub, package_stub


TSE_SOURCE_CONFIG = {
    'tse_tv': {
        'category': 'TV',
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
    },
    'tse_ref': {
        'category': 'REF',
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
    },
    'tse_ldy': {
        'category': 'LDY',
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
    },
}

SIEL_SOURCE_CONFIG = {
    'siel_tv': {
        'category': 'TV',
        'section_code': 'siel_tv_retail',
        'display_name': 'SIEL TV',
    },
    'siel_ref': {
        'category': 'REF',
        'section_code': 'siel_ref_retail',
        'display_name': 'SIEL REF',
    },
    'siel_ldy': {
        'category': 'LDY',
        'section_code': 'siel_ldy_retail',
        'display_name': 'SIEL LDY',
    },
}


class Layer3TseSidebarContextTests(unittest.TestCase):
    def _load_context(self, crossfield_rules):
        return load_module(
            'apps/dx/dx_layer3/common/context.py',
            'layer3_tse_sidebar_context_under_test',
            stubs={
                'apps': package_stub('apps'),
                'apps.common': package_stub('apps.common'),
                'apps.common.siel_retail': module_stub(
                    'apps.common.siel_retail',
                    SIEL_SOURCE_CONFIG=SIEL_SOURCE_CONFIG,
                ),
                'apps.common.tse_retail': module_stub(
                    'apps.common.tse_retail',
                    TSE_SOURCE_CONFIG=TSE_SOURCE_CONFIG,
                ),
                'apps.dx': package_stub('apps.dx'),
                'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
                'apps.dx.dx_layer3.dashboard': package_stub(
                    'apps.dx.dx_layer3.dashboard'
                ),
                'apps.dx.dx_layer3.dashboard.services': module_stub(
                    'apps.dx.dx_layer3.dashboard.services',
                    load_timeseries_rules=lambda: [],
                    load_crossfield_rules=lambda: crossfield_rules,
                    load_category_rules=lambda: [],
                ),
            },
        )

    def test_crossfield_sidebar_groups_active_tse_rules_under_one_parent(self):
        context = self._load_context([
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
            {'section_code': 'sentiment', 'section_name': 'Sentiment'},
            {'section_code': 'tse_tv_retail', 'section_name': 'TSE TV'},
            {'section_code': 'tse_ref_retail', 'section_name': 'TSE REF'},
            {'section_code': 'tse_ref_retail', 'section_name': 'TSE REF'},
            {'section_code': 'tse_ldy_retail', 'section_name': 'TSE LDY'},
        ])

        crossfield_group = context._build_sidebar_groups(
            'cross_field', focus='TSE REF', detail_code='tse_ref'
        )[1]

        self.assertEqual(
            ['SEA Retail', 'TSE Retail', 'Sentiment'],
            [item['name'] for item in crossfield_group['items']],
        )
        sea_parent = crossfield_group['items'][0]
        self.assertEqual(
            [('SEA Retail', 'TV', 'tv', False)],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in sea_parent['children']
            ],
        )
        tse_parent = crossfield_group['items'][1]
        self.assertTrue(tse_parent['active'])
        self.assertEqual(
            [
                ('TSE TV', 'TV', 'tse_tv', False),
                ('TSE REF', 'REF', 'tse_ref', True),
                ('TSE LDY', 'LDY', 'tse_ldy', False),
            ],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in tse_parent['children']
            ],
        )

    def test_detail_code_alone_marks_the_matching_child_active(self):
        context = self._load_context([
            {'section_code': 'tse_tv_retail', 'section_name': 'TSE TV'},
            {'section_code': 'tse_ref_retail', 'section_name': 'TSE REF'},
        ])

        crossfield_group = context._build_sidebar_groups(
            'cross_field', detail_code='tse_tv'
        )[1]
        tse_parent = crossfield_group['items'][0]

        self.assertTrue(tse_parent['active'])
        self.assertEqual(
            [True, False],
            [child['active'] for child in tse_parent['children']],
        )

    def test_siel_rules_are_grouped_between_sea_and_tse(self):
        context = self._load_context([
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
            {'section_code': 'siel_tv_retail', 'section_name': 'SIEL TV'},
            {'section_code': 'siel_ref_retail', 'section_name': 'SIEL REF'},
            {'section_code': 'siel_ldy_retail', 'section_name': 'SIEL LDY'},
            {'section_code': 'tse_tv_retail', 'section_name': 'TSE TV'},
        ])

        crossfield_group = context._build_sidebar_groups(
            'cross_field', detail_code='siel_ref'
        )[1]

        self.assertEqual(
            ['SEA Retail', 'SIEL Retail', 'TSE Retail'],
            [item['name'] for item in crossfield_group['items']],
        )
        siel_parent = crossfield_group['items'][1]
        self.assertTrue(siel_parent['active'])
        self.assertEqual(
            [
                ('SIEL TV', 'TV', 'siel_tv', False),
                ('SIEL REF', 'REF', 'siel_ref', True),
                ('SIEL LDY', 'LDY', 'siel_ldy', False),
            ],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in siel_parent['children']
            ],
        )

    def test_tse_parent_is_omitted_when_no_tse_rule_is_active(self):
        context = self._load_context([
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
        ])

        crossfield_group = context._build_sidebar_groups('cross_field')[1]

        self.assertEqual('SEA Retail', crossfield_group['items'][0]['name'])
        self.assertFalse(crossfield_group['items'][0]['active'])
        self.assertEqual(
            [('SEA Retail', 'TV', 'tv', False)],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in crossfield_group['items'][0]['children']
            ],
        )

    def test_sea_identity_activates_renamed_item_without_text_inference(self):
        context = self._load_context([
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
        ])

        crossfield_group = context._build_sidebar_groups(
            'cross_field', focus='SEA Retail', detail_code='tv'
        )[1]

        self.assertTrue(crossfield_group['items'][0]['active'])
        self.assertTrue(crossfield_group['items'][0]['children'][0]['active'])

    def test_sea_ref_and_ldy_share_the_sea_parent(self):
        context = self._load_context([
            {'section_code': 'tv_retail', 'section_name': 'TV Retail'},
            {'section_code': 'sea_ref_retail', 'section_name': 'SEA REF'},
            {'section_code': 'sea_ldy_retail', 'section_name': 'SEA LDY'},
        ])

        crossfield_group = context._build_sidebar_groups(
            'cross_field', focus='SEA REF', detail_code='sea_ref'
        )[1]
        sea_parent = crossfield_group['items'][0]

        self.assertEqual('SEA Retail', sea_parent['name'])
        self.assertTrue(sea_parent['active'])
        self.assertEqual(
            [
                ('SEA Retail', 'TV', 'tv', False),
                ('SEA REF', 'REF', 'sea_ref', True),
                ('SEA LDY', 'LDY', 'sea_ldy', False),
            ],
            [
                (
                    child['name'], child['label'],
                    child['detail_code'], child['active'],
                )
                for child in sea_parent['children']
            ],
        )

    def test_build_context_preserves_selected_date_and_tse_identity(self):
        context = self._load_context([
            {'section_code': 'tse_ldy_retail', 'section_name': 'TSE LDY'},
        ])
        request = SimpleNamespace(GET={
            'date': '2026-08-10',
            'focus': 'TSE LDY',
            'detail_code': 'tse_ldy',
        })

        result = context.build_context('cross_field', request)
        tse_parent = result['sidebar_groups'][1]['items'][0]

        self.assertEqual('2026-08-10', result['target_date'])
        self.assertTrue(tse_parent['active'])
        self.assertTrue(tse_parent['children'][0]['active'])


if __name__ == '__main__':
    unittest.main()
