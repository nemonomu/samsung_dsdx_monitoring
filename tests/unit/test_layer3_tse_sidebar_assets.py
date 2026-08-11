import unittest

from django.template import Context, Engine

from tests.unit.support import REPO_ROOT


class Layer3TseSidebarAssetTests(unittest.TestCase):
    def test_shared_sidebar_renders_flat_items_and_non_click_tse_children(self):
        template_path = REPO_ROOT / 'templates/includes/_sidebar.html'
        template = Engine(debug=True).from_string(
            template_path.read_text(encoding='utf-8')
        )
        rendered = template.render(Context({
            'sidebar_title': 'Layer 3',
            'sidebar_base_url': '/dx/layer3/',
            'section': 'cross_field',
            'sidebar_groups': [{
                'key': 'cross_field',
                'icon': 'x',
                'label': 'Cross field',
                'expanded': True,
                'active': True,
                'items': [
                    {
                        'name': 'SEA Retail',
                        'detail_code': 'tv',
                        'active': False,
                    },
                    {
                        'name': 'TSE Retail',
                        'active': True,
                        'children': [{
                            'name': 'TSE REF',
                            'label': 'REF',
                            'detail_code': 'tse_ref',
                            'active': True,
                        }],
                    },
                ],
            }],
        }))

        self.assertIn(
            "onSubitemClick('cross_field', 'SEA Retail', 'tv')", rendered
        )
        self.assertIn('class="sidebar-subgroup active"', rendered)
        self.assertIn(
            'class="sidebar-subgroup-title">TSE Retail</div>', rendered
        )
        self.assertIn('data-item-name="TSE REF"', rendered)
        self.assertIn('data-detail-code="tse_ref"', rendered)
        self.assertIn(
            "onSubitemClick('cross_field', 'TSE REF', 'tse_ref')",
            rendered,
        )
        self.assertIn('>\n                            REF\n', rendered)

    def test_layer3_javascript_routes_focus_with_detail_code(self):
        source = (
            REPO_ROOT
            / 'apps/dx/dx_layer3/static/dx_layer3/js/common.js'
        ).read_text(encoding='utf-8')

        self.assertIn(
            "const detailCodeParam = urlParams.get('detail_code') || '';",
            source,
        )
        self.assertIn(
            'showDetail(SECTION_CATEGORY_MAP[section], focusParam, detailCodeParam);',
            source,
        )
        self.assertIn(
            'const itemName = item.dataset.itemName || item.textContent.trim();',
            source,
        )
        self.assertIn("if (date) params.push('date=' + date);", source)
        self.assertIn(
            "if (detailCode) params.push('detail_code=' + encodeURIComponent(detailCode));",
            source,
        )
        self.assertIn(
            "if (detailCode === 'tv') type = 'tv';",
            source,
        )
        self.assertIn(
            "checkName === 'TV 논리적 일관성'",
            source,
        )
        self.assertIn(
            "return 'SEA Retail';",
            source,
        )
        self.assertIn(
            'const displayName = getLayer3DisplayName(check.name, check.detail_code || \'\');',
            source,
        )
        self.assertIn(
            'let title = getLayer3DisplayName(checkName, detailCode);',
            source,
        )
        self.assertIn(
            "getLayer3DisplayName(checkName, '') + ' - 검증 규칙'",
            source,
        )
        self.assertIn(
            "const crossfieldChecks = ['TV 논리적 일관성'",
            source,
        )
        self.assertIn(
            "if (detailCode === 'tse_tv' || checkName.includes('TSE TV')) type = 'tse_tv';",
            source,
        )

    def test_crossfield_detail_shows_a_message_when_retailer_rows_are_missing(self):
        source = (
            REPO_ROOT
            / 'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js'
        ).read_text(encoding='utf-8')

        self.assertIn(
            '해당 리테일러의 상세 데이터를 찾을 수 없습니다. 다시 조회해 주세요.',
            source,
        )
        self.assertNotIn(
            'if (!retailerData || !retailerData[retailer]) return;',
            source,
        )

    def test_sidebar_css_keeps_children_visible_without_a_nested_toggle(self):
        source = (REPO_ROOT / 'static/css/sidebar.css').read_text(encoding='utf-8')

        self.assertIn('.dx-sidebar .sidebar-subgroup-title {', source)
        self.assertIn('.dx-sidebar .sidebar-subgroup-children {', source)
        self.assertIn('.dx-sidebar .sidebar-subgroup-child {', source)
        self.assertNotIn('.sidebar-subgroup.expanded', source)


if __name__ == '__main__':
    unittest.main()
