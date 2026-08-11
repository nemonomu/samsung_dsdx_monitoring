import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from tests.unit.support import load_module, module_stub, package_stub


def load_retail_api(get_backup_count, backup_all_retail):
    backup_stub = module_stub(
        'apps.common.backup',
        get_backup_count=get_backup_count,
        backup_all_retail=backup_all_retail,
        get_backup_status=lambda date: {},
    )
    stubs = {
        'django': package_stub('django'),
        'django.http': module_stub('django.http', JsonResponse=lambda data: data),
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


def request(method='GET'):
    return SimpleNamespace(
        method=method,
        GET={'date': '2026-08-11'},
        POST={},
        user=SimpleNamespace(is_authenticated=True, username='tester'),
    )


class Layer1BackupApiTests(unittest.TestCase):
    def test_get_returns_all_pending_backup_counts(self):
        api = load_retail_api(
            lambda date: {
                'success': True,
                'tv_count': 1,
                'tse_tv_count': 2,
                'tse_ref_count': 3,
                'tse_ldy_count': 4,
                'total_count': 10,
            },
            lambda username, date: {},
        )

        response = call_backup_api(api, request())

        self.assertEqual(response['tv_count'], 1)
        self.assertEqual(response['tse_tv_count'], 2)
        self.assertEqual(response['tse_ref_count'], 3)
        self.assertEqual(response['tse_ldy_count'], 4)
        self.assertEqual(response['total_count'], 10)
        self.assertEqual(response['hhp_count'], 0)

    def test_post_returns_actual_integrated_backup_counts(self):
        api = load_retail_api(
            lambda date: {},
            lambda username, date: {
                'success': True,
                'tv': {'count': 1},
                'tse_tv': {'count': 2},
                'tse_ref': {'count': 3},
                'tse_ldy': {'count': 4},
            },
        )

        response = call_backup_api(api, request('POST'))

        self.assertTrue(response['success'])
        self.assertEqual(response['total_count'], 10)
        self.assertIn('SEA TV: 1건', response['message'])
        self.assertIn('TSE LDY: 4건', response['message'])

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


if __name__ == '__main__':
    unittest.main()
