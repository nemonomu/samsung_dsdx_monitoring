import unittest
from datetime import date, datetime, time

from tests.unit.support import load_module, module_stub, package_stub


SOURCE_CONFIG = {
    'tse_tv': {
        'category': 'TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
    },
    'tse_ref': {
        'category': 'REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
    },
    'tse_ldy': {
        'category': 'LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
    },
}


def collection_phase(current_time):
    if current_time < time(9, 0):
        return 'pending'
    if current_time <= time(9, 30):
        return 'collecting'
    return 'complete'


def count_status(actual, expected=300):
    if int(actual or 0) >= int(expected or 300) - 100:
        return 'ok'
    return 'critical'


class TseLayer1ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_module = module_stub(
            'apps.dx.dx_layer1.tse_retail.tse_retail_repositories'
        )
        cls.columns_module = module_stub(
            'apps.common.retail_columns',
            get_tse_retailer_columns=lambda _product_line: {
                'Homepro': {'retailer': 'homepro'},
            },
        )
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.retail_columns': cls.columns_module,
            'apps.common.tse_retail': module_stub(
                'apps.common.tse_retail',
                TSE_EXPECTED_COUNT=300,
                TSE_SOURCE_CONFIG=SOURCE_CONFIG,
                display_tse_retailer=lambda value: (
                    'Homepro' if str(value).lower() == 'homepro' else str(value)
                ),
                get_tse_collection_phase=collection_phase,
                get_tse_count_status=count_status,
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
            'apps.dx.dx_layer1.tse_retail': package_stub(
                'apps.dx.dx_layer1.tse_retail'
            ),
            'apps.dx.dx_layer1.tse_retail.tse_retail_repositories': cls.repo_module,
        }
        cls.service = load_module(
            'apps/dx/dx_layer1/tse_retail/tse_retail_services.py',
            'apps.dx.dx_layer1.tse_retail.tse_retail_services_under_test',
            stubs,
        )

    def setUp(self):
        self.columns_module.get_tse_retailer_columns = lambda _product_line: {
            'Homepro': {'retailer': 'homepro'},
        }

    def _set_counts(self, counts):
        def latest_counts(_cursor, product_line, _target_date):
            return counts.get(product_line, [])
        self.repo_module.get_latest_batch_counts = latest_counts

    def test_response_contract_and_future_retailer_are_dynamic(self):
        self._set_counts({
            'tse_tv': [
                {
                    'retailer': 'Homepro', 'batch_id': 'tv-home',
                    'actual_count': 300, 'main_count': 180, 'bsr_count': 100,
                },
                {
                    'retailer': 'New Retail', 'batch_id': 'tv-new',
                    'actual_count': 250, 'main_count': 150, 'bsr_count': 80,
                },
            ],
            'tse_ref': [
                {'retailer': 'Homepro', 'batch_id': 'ref-home', 'actual_count': 300},
            ],
            'tse_ldy': [
                {'retailer': 'Homepro', 'batch_id': 'ldy-home', 'actual_count': 287},
            ],
        })

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 10), datetime(2026, 8, 10, 9, 31)
        )
        check = result['check']

        self.assertEqual('tse_retail', check['check_type'])
        self.assertEqual('RDP 09:00~09:30', check['collection_window'])
        self.assertEqual('OK', check['status'])
        self.assertEqual([], result['failed_items'])
        self.assertEqual(['TV', 'REF', 'LDY'], [c['category'] for c in check['categories']])

        tv = check['categories'][0]
        self.assertEqual('tse_tv', tv['product_line'])
        self.assertEqual('dx_tse.dx_tse_tv_retail_com', tv['table_name'])
        self.assertEqual(600, tv['expected'])
        self.assertEqual(550, tv['actual'])
        self.assertEqual(550, tv['total'])
        self.assertEqual(
            ['Homepro', 'New Retail'],
            [item['retailer'] for item in tv['retailers']],
        )
        self.assertEqual('tv-new', tv['retailers'][1]['batch_id'])
        self.assertEqual(150, tv['retailers'][1]['main_count'])
        self.assertEqual(80, tv['retailers'][1]['bsr_count'])
        self.assertEqual(1200, check['expected'])
        self.assertEqual(1137, check['actual'])

    def test_time_phases_use_rdp_0900_to_0930(self):
        self._set_counts({
            product_line: [{
                'retailer': 'Homepro',
                'batch_id': product_line,
                'actual_count': 300,
            }]
            for product_line in SOURCE_CONFIG
        })

        pending = self.service.get_layer1_stats(
            object(), date(2026, 8, 10), datetime(2026, 8, 10, 8, 59)
        )['check']
        collecting = self.service.get_layer1_stats(
            object(), date(2026, 8, 10), datetime(2026, 8, 10, 9, 15)
        )['check']
        complete = self.service.get_layer1_stats(
            object(), date(2026, 8, 10), datetime(2026, 8, 10, 9, 31)
        )['check']

        self.assertEqual(('pending', 'PENDING'), (pending['phase'], pending['status']))
        self.assertEqual(
            ('collecting', 'COLLECTING'),
            (collecting['phase'], collecting['status']),
        )
        self.assertEqual(('complete', 'OK'), (complete['phase'], complete['status']))

    def test_count_status_boundaries(self):
        self.assertEqual('OK', self.service._status_for_count(300, 'complete'))
        self.assertEqual('OK', self.service._status_for_count(299, 'complete'))
        self.assertEqual('OK', self.service._status_for_count(200, 'complete'))
        self.assertEqual('CRITICAL', self.service._status_for_count(199, 'complete'))

    def test_configured_retailer_without_data_is_zero_and_failed(self):
        self._set_counts({product_line: [] for product_line in SOURCE_CONFIG})

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 9), datetime(2026, 8, 10, 8, 0)
        )

        self.assertEqual('CRITICAL', result['check']['status'])
        self.assertEqual(3, len(result['failed_items']))
        for category in result['check']['categories']:
            self.assertEqual(300, category['expected'])
            self.assertEqual(0, category['actual'])
            self.assertEqual('Homepro', category['retailers'][0]['retailer'])


if __name__ == '__main__':
    unittest.main()
