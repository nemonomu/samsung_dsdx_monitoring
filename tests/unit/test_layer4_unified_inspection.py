import unittest
from types import SimpleNamespace

from django.template import Context, Engine

from tests.unit.support import REPO_ROOT, load_module, module_stub, package_stub


class FakeJsonResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status


class FakeRequest:
    def __init__(self, target_date=None):
        self.GET = {}
        if target_date is not None:
            self.GET['date'] = target_date


def load_api():
    resolver = load_module(
        'apps/common/inspection_dates.py',
        'apps.common.inspection_dates',
    )
    package = 'apps.dx.dx_layer4.unified_inspection'
    return load_module(
        'apps/dx/dx_layer4/unified_inspection/api.py',
        f'{package}.api_under_test',
        stubs={
            'django': package_stub('django'),
            'django.http': module_stub(
                'django.http', JsonResponse=FakeJsonResponse,
            ),
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.inspection_dates': resolver,
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer4': package_stub('apps.dx.dx_layer4'),
            package: package_stub(package),
        },
    )


class UnifiedInspectionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_api()

    def test_api_returns_five_visible_rows_and_fifteen_sources(self):
        response = self.api.date_mapping(FakeRequest('2026-08-20'))

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.data['success'])
        self.assertTrue(response.data['read_only'])
        self.assertEqual('2026-08-20', response.data['inspection_date'])
        self.assertEqual(5, len(response.data['countries']))
        self.assertEqual(15, response.data['source_count'])
        self.assertEqual(
            15,
            sum(
                len(country['sources'])
                for country in response.data['countries']
            ),
        )

        countries = {
            item['country']: item for item in response.data['countries']
        }
        self.assertEqual('2026-08-19', countries['SEA']['source_date'])
        self.assertEqual('D-1', countries['SEA']['rule'])
        self.assertEqual('2026-08-19', countries['SEDA']['source_date'])
        self.assertEqual('D-1', countries['SEDA']['rule'])
        for country in ('SEG', 'SIEL', 'TSE'):
            self.assertEqual(
                '2026-08-20', countries[country]['source_date']
            )
            self.assertEqual('D', countries[country]['rule'])

    def test_missing_or_invalid_date_returns_400_without_defaulting(self):
        for value in (None, '', '2026-02-30'):
            with self.subTest(value=value):
                response = self.api.date_mapping(FakeRequest(value))
                self.assertEqual(400, response.status_code)
                self.assertFalse(response.data['success'])
                self.assertNotIn('countries', response.data)


class UnifiedInspectionPageWiringTests(unittest.TestCase):
    def test_context_exposes_direct_active_sidebar_link(self):
        context_module = load_module(
            'apps/dx/dx_layer4/common/context.py',
            'tests._layer4_context_for_unified_inspection',
        )
        request = SimpleNamespace(
            GET={'date': '2026-08-20'},
            user=SimpleNamespace(
                is_authenticated=True,
                is_staff=False,
                is_superuser=False,
            ),
        )

        context = context_module.build_context(
            'unified_inspection', request
        )
        group = context['sidebar_groups'][0]

        self.assertEqual('통합 검수', context['section_title'])
        self.assertEqual('unified_inspection', group['key'])
        self.assertEqual('/dx/layer4/unified-inspection/', group['href'])
        self.assertTrue(group['ignore_target_date'])
        self.assertTrue(group['active'])
        self.assertEqual('2026-08-20', context['target_date'])

    def test_route_template_and_asset_keep_the_step_read_only_and_visible(self):
        urls = (
            REPO_ROOT / 'apps/dx/dx_layer4/urls.py'
        ).read_text(encoding='utf-8')
        template = (
            REPO_ROOT
            / 'apps/dx/dx_layer4/templates/layer4/unified_inspection.html'
        ).read_text(encoding='utf-8')
        script = (
            REPO_ROOT
            / 'apps/dx/dx_layer4/static/dx_layer4/js/unified_inspection.js'
        ).read_text(encoding='utf-8')
        base_template = (
            REPO_ROOT
            / 'apps/dx/dx_layer4/templates/layer4/base_layer4.html'
        ).read_text(encoding='utf-8')
        common_script = (
            REPO_ROOT
            / 'apps/dx/dx_layer4/static/dx_layer4/js/common.js'
        ).read_text(encoding='utf-8')
        sidebar = (
            REPO_ROOT / 'templates/includes/_sidebar.html'
        ).read_text(encoding='utf-8')

        self.assertIn("path('unified-inspection/'", urls)
        self.assertIn("path('api/unified-inspection/date-mapping/'", urls)
        self.assertIn('읽기 전용', template)
        self.assertIn('실제 데이터일', template)
        self.assertIn('데이터가 없어도 다른 날짜로 자동 대체하지 않습니다.', template)
        self.assertIn('ui-mapping-body', template)
        self.assertIn('TSE 실제 조회 확인', template)
        self.assertIn('ui-tse-body', template)
        self.assertNotIn('offset_days=', template)
        self.assertIn('기존 Layer1 조회를 읽기 전용으로 재사용합니다.', template)
        self.assertIn(
            '/dx/layer4/api/unified-inspection/date-mapping/?date=',
            script,
        )
        self.assertIn('/dx/layer1/api/stats/?date=', script)
        self.assertIn('&check_type=tse_retail', script)
        self.assertIn('mapping.source_date', script)
        self.assertIn('data.target_date', script)
        self.assertIn("? 'unifiedInspectionDate'", base_template)
        self.assertIn("section === 'unified_inspection'", common_script)
        self.assertIn('not group.ignore_target_date', sidebar)

    def test_sidebar_does_not_mix_inspection_date_into_the_new_page(self):
        template_path = REPO_ROOT / 'templates/includes/_sidebar.html'
        template = Engine(debug=True).from_string(
            template_path.read_text(encoding='utf-8')
        )
        rendered = template.render(Context({
            'sidebar_title': 'Layer 4',
            'sidebar_base_url': '/dx/layer4/',
            'section': 'collection_status',
            'target_date': '2026-08-20',
            'sidebar_groups': [
                {
                    'key': 'unified_inspection',
                    'icon': 'x',
                    'label': '통합 검수',
                    'href': '/dx/layer4/unified-inspection/',
                    'ignore_target_date': True,
                    'active': False,
                },
                {
                    'key': 'legacy_direct_link',
                    'icon': 'x',
                    'label': '기존 링크',
                    'href': '/legacy/',
                    'active': False,
                },
            ],
        }))

        self.assertIn('href="/dx/layer4/unified-inspection/"', rendered)
        self.assertNotIn(
            '/dx/layer4/unified-inspection/?date=', rendered
        )
        self.assertIn('href="/legacy/?date=2026-08-20"', rendered)


if __name__ == '__main__':
    unittest.main()
