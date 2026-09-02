import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import load_module, module_stub, package_stub


class FakeJsonResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status


class FakeRequest:
    def __init__(self, params):
        self.GET = params


@contextmanager
def fake_connection():
    yield object(), object()


def common_stubs():
    return {
        'django': package_stub('django'),
        'django.http': module_stub(
            'django.http', JsonResponse=FakeJsonResponse,
        ),
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_connection=fake_connection,
        ),
        'apps.common.params': module_stub(
            'apps.common.params', parse_date=lambda _value: date(2026, 9, 1),
        ),
        'apps.common.response': module_stub(
            'apps.common.response',
            safe_error=lambda error: (_ for _ in ()).throw(error),
            log_error=lambda *_args, **_kwargs: None,
        ),
        'apps.dx': package_stub('apps.dx'),
    }


class ValidationDetailDefaultTests(unittest.TestCase):
    def test_layer2_null_retail_defaults_to_three_days(self):
        captured = {}
        services = module_stub(
            'apps.dx.dx_layer2.null_validation.services',
            get_all_categories=lambda: {'tv_retail', 'youtube'},
            get_null_detail=lambda _cursor, _date, _category, _retailer,
            days, _column: captured.setdefault('days', days) or {},
        )
        stubs = common_stubs()
        stubs.update({
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.null_validation': package_stub(
                'apps.dx.dx_layer2.null_validation'
            ),
            'apps.dx.dx_layer2.null_validation.services': services,
        })
        api = load_module(
            'apps/dx/dx_layer2/null_validation/api.py',
            'apps.dx.dx_layer2.null_validation.api_defaults_under_test',
            stubs=stubs,
        )

        response = api.null_detail(FakeRequest({
            'date': '2026-09-01',
            'table': 'tv_retail',
            'column': 'item',
        }))

        self.assertEqual(200, response.status_code)
        self.assertEqual(3, captured['days'])

    def test_layer2_format_retail_defaults_to_three_days(self):
        captured = {}
        services = module_stub(
            'apps.dx.dx_layer2.format_validation.services',
            VALID_TABLES_FORMAT={'sea_ref_retail', 'hhp_retail'},
            VALID_TABLES_RULES=set(),
            get_format_detail=lambda _cursor, _date, _table, _retailer,
            days: captured.setdefault('days', days) or {},
            get_format_rules=lambda *_args: {},
        )
        stubs = common_stubs()
        stubs.update({
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.format_validation': package_stub(
                'apps.dx.dx_layer2.format_validation'
            ),
            'apps.dx.dx_layer2.format_validation.services': services,
        })
        api = load_module(
            'apps/dx/dx_layer2/format_validation/api.py',
            'apps.dx.dx_layer2.format_validation.api_defaults_under_test',
            stubs=stubs,
        )

        response = api.format_detail(FakeRequest({
            'date': '2026-09-01',
            'table': 'sea_ref_retail',
        }))

        self.assertEqual(200, response.status_code)
        self.assertEqual(3, captured['days'])

    def test_layer3_crossfield_retail_defaults_to_three_days(self):
        captured = {}
        tse_services = module_stub(
            'apps.dx.dx_layer3.cross_field.tse_services',
            get_tse_cross_field_rule_detail=lambda _cursor, _date,
            _product_line, _rule_id, days: {
                'found': True,
                'days': captured.setdefault('days', days),
            },
            get_tse_cross_field_summary=lambda *_args: {},
        )
        stubs = common_stubs()
        stubs.update({
            'apps.common.inspection_dates': module_stub(
                'apps.common.inspection_dates',
                resolve_monitoring_date=lambda *_args: {},
            ),
            'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
            'apps.dx.dx_layer3.cross_field': package_stub(
                'apps.dx.dx_layer3.cross_field'
            ),
            'apps.dx.dx_layer3.cross_field.services': module_stub(
                'apps.dx.dx_layer3.cross_field.services'
            ),
            'apps.dx.dx_layer3.cross_field.sea_services': module_stub(
                'apps.dx.dx_layer3.cross_field.sea_services'
            ),
            'apps.dx.dx_layer3.cross_field.tse_services': tse_services,
        })
        api = load_module(
            'apps/dx/dx_layer3/cross_field/api.py',
            'apps.dx.dx_layer3.cross_field.api_defaults_under_test',
            stubs=stubs,
        )

        response = api.cross_field_detail(FakeRequest({
            'date': '2026-09-01',
            'type': 'tse_tv',
            'rule_id': '1',
        }))

        self.assertEqual(200, response.status_code)
        self.assertEqual(3, captured['days'])


if __name__ == '__main__':
    unittest.main()
