import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from tests.unit.support import load_module, module_stub, package_stub


def json_response(data, status=200):
    response = dict(data)
    response['_status_code'] = status
    return response


def date_payload():
    source_dates = {
        'sea_tv': '2026-08-10',
        'sea_ref': '2026-08-10',
        'sea_ldy': '2026-08-10',
        'tse_tv': '2026-08-11',
        'tse_ref': '2026-08-11',
        'tse_ldy': '2026-08-11',
    }
    return {
        'inspection_date': '2026-08-11',
        'source_dates': source_dates,
        'date_mappings': {
            source_key: {'source_date': source_date}
            for source_key, source_date in source_dates.items()
        },
    }


def load_retail_api(
    get_backup_count,
    backup_all_retail,
    get_backup_status=lambda date: {},
):
    backup_stub = module_stub(
        'apps.common.backup',
        get_backup_count=get_backup_count,
        backup_all_retail=backup_all_retail,
        get_backup_status=get_backup_status,
    )
    stubs = {
        'django': package_stub('django'),
        'django.http': module_stub('django.http', JsonResponse=json_response),
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.response': module_stub(
            'apps.common.response', log_error=lambda error: str(error),
        ),
        'apps.common.backup': backup_stub,
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
        'apps.dx.dx_layer1.retail': package_stub('apps.dx.dx_layer1.retail'),
        'apps.dx.dx_layer1.retail.retail_services': module_stub(
            'apps.dx.dx_layer1.retail.retail_services',
        ),
    }
    module = load_module(
        'apps/dx/dx_layer1/retail/retail_api.py',
        'apps.dx.dx_layer1.retail.retail_api',
        stubs,
    )
    module._backup_test_stub = backup_stub
    return module


def call_backup_api(api, request_value):
    with patch.dict(sys.modules, {'apps.common.backup': api._backup_test_stub}):
        return api.backup_retail_data(request_value)


def call_backup_status_api(api, request_value):
    with patch.dict(sys.modules, {'apps.common.backup': api._backup_test_stub}):
        return api.backup_status(request_value)


def request(method='GET', date_value='2026-08-11'):
    query = {} if date_value is None else {'date': date_value}
    return SimpleNamespace(
        method=method,
        GET=query,
        POST={},
        user=SimpleNamespace(is_authenticated=True, username='tester'),
    )


class Layer1BackupApiTests(unittest.TestCase):
    def test_get_returns_all_pending_backup_counts(self):
        api = load_retail_api(
            lambda date: {
                'success': True,
                'tv_count': 1,
                'sea_ref_count': 5,
                'sea_ldy_count': 6,
                'tse_tv_count': 2,
                'tse_ref_count': 3,
                'tse_ldy_count': 4,
                'total_count': 21,
                **date_payload(),
            },
            lambda username, date: {},
        )

        response = call_backup_api(api, request())

        self.assertEqual(response['tv_count'], 1)
        self.assertEqual(response['sea_ref_count'], 5)
        self.assertEqual(response['sea_ldy_count'], 6)
        self.assertEqual(response['tse_tv_count'], 2)
        self.assertEqual(response['tse_ref_count'], 3)
        self.assertEqual(response['tse_ldy_count'], 4)
        self.assertEqual(response['total_count'], 21)
        self.assertEqual(response['hhp_count'], 0)
        self.assertEqual(response['inspection_date'], '2026-08-11')
        self.assertEqual(response['source_dates']['sea_tv'], '2026-08-10')
        self.assertEqual(response['_status_code'], 200)

    def test_post_returns_actual_integrated_backup_counts(self):
        api = load_retail_api(
            lambda date: {},
            lambda username, date: {
                'success': True,
                'tv': {'count': 1},
                'sea_ref': {'count': 5},
                'sea_ldy': {'count': 6},
                'tse_tv': {'count': 2},
                'tse_ref': {'count': 3},
                'tse_ldy': {'count': 4},
                **date_payload(),
            },
        )

        response = call_backup_api(api, request('POST'))

        self.assertTrue(response['success'])
        self.assertEqual(response['total_count'], 21)
        self.assertIn('SEA TV: 1건', response['message'])
        self.assertIn('SEA REF: 5건', response['message'])
        self.assertIn('SEA LDY: 6건', response['message'])
        self.assertIn('TSE LDY: 4건', response['message'])
        self.assertEqual(response['inspection_date'], '2026-08-11')
        self.assertEqual(response['source_dates']['sea_ref'], '2026-08-10')

    def test_post_reports_atomic_failure_without_partial_result_access(self):
        api = load_retail_api(
            lambda date: {},
            lambda username, date: {
                'success': False,
                'error': '전체 백업을 취소했습니다.',
            },
        )

        response = call_backup_api(api, request('POST'))

        self.assertFalse(response['success'])
        self.assertEqual(response['error'], '전체 백업을 취소했습니다.')

    def test_missing_or_invalid_inspection_date_returns_http_400(self):
        invalid_result = {
            'success': False,
            'error_code': 'invalid_inspection_date',
            'error': '검수일이 유효하지 않습니다.',
        }
        api = load_retail_api(
            lambda date: invalid_result,
            lambda username, date: invalid_result,
            get_backup_status=lambda date: invalid_result,
        )

        get_response = call_backup_api(api, request(date_value=None))
        post_response = call_backup_api(api, request('POST', 'invalid'))
        status_response = call_backup_status_api(
            api, request(date_value=None),
        )

        self.assertEqual(get_response['_status_code'], 400)
        self.assertEqual(post_response['_status_code'], 400)
        self.assertEqual(status_response['_status_code'], 400)
        self.assertEqual(
            status_response['error_code'],
            'invalid_inspection_date',
        )


if __name__ == '__main__':
    unittest.main()
