import json
import unittest

from tests.unit.support import load_module, module_stub, package_stub


class FakeJsonResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status


class FakeRequest:
    method = 'POST'

    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')


def load_api():
    service_stub = module_stub(
        'apps.dx.dx_layer3.data_edit.services',
        VALID_TABLES_UPDATE={'dx_tse.dx_tse_tv_retail_com'},
        update_cell_value=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('DB service must not be called')
        ),
        save_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('DB service must not be called')
        ),
    )
    return load_module(
        'apps/dx/dx_layer3/data_edit/api.py',
        'apps.dx.dx_layer3.data_edit.api_under_test',
        stubs={
            'django': package_stub('django'),
            'django.http': module_stub(
                'django.http', JsonResponse=FakeJsonResponse,
            ),
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=lambda: (_ for _ in ()).throw(
                    AssertionError('DB connection must not be opened')
                ),
            ),
            'apps.common.response': module_stub(
                'apps.common.response', safe_error=lambda error: error,
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
            'apps.dx.dx_layer3.data_edit': package_stub(
                'apps.dx.dx_layer3.data_edit'
            ),
            'apps.dx.dx_layer3.data_edit.services': service_stub,
        },
    )


class TseLayer3ApiValidationTests(unittest.TestCase):
    def test_update_rejects_non_integer_row_id_before_db(self):
        api = load_api()
        response = api.update_cell(FakeRequest({
            'table_name': 'dx_tse.dx_tse_tv_retail_com',
            'row_id': 'bad-id',
            'column_name': 'item',
        }))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], '잘못된 ID 형식')

    def test_review_rejects_non_integer_rule_id_before_db(self):
        api = load_api()
        response = api.review(FakeRequest({
            'table_name': 'dx_tse.dx_tse_tv_retail_com',
            'record_id': 1,
            'column_name': 'item',
            'status': 'normal',
            'reason': '확인',
            'rule_id': 'bad-rule',
        }))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], '잘못된 규칙 ID 형식')


if __name__ == '__main__':
    unittest.main()
