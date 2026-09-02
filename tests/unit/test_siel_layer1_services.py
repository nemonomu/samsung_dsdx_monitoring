import unittest
from datetime import date, datetime, time

from tests.unit.support import load_module, module_stub, package_stub


SOURCE_CONFIG = {
    'siel_tv': {
        'source_key': 'siel_tv', 'category': 'TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ref': {
        'source_key': 'siel_ref', 'category': 'REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ldy': {
        'source_key': 'siel_ldy', 'category': 'LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'retailers': ('Amazon', 'Flipkart'),
    },
}


def collection_phase(current_time):
    return 'collecting' if current_time <= time(9, 0) else 'complete'


def count_status(actual):
    return 'ok' if int(actual or 0) >= 200 else 'critical'


def resolve_date(inspection_date, country, source_key):
    value = str(inspection_date)[:10]
    return {
        'inspection_date': value,
        'source_date': value,
        'offset_days': 0,
        'country': country,
        'source_key': source_key,
    }


class SielLayer1ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_module = module_stub(
            'apps.dx.dx_layer1.siel_retail.siel_retail_repositories'
        )
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.inspection_dates': module_stub(
                'apps.common.inspection_dates',
                resolve_monitoring_date=resolve_date,
            ),
            'apps.common.siel_retail': module_stub(
                'apps.common.siel_retail',
                SIEL_CHECK_TYPE='siel_retail',
                SIEL_COUNTRY='SIEL',
                SIEL_EXPECTED_COUNT=300,
                SIEL_OK_THRESHOLD=200,
                SIEL_SOURCE_CONFIG=SOURCE_CONFIG,
                display_siel_retailer=lambda value: str(value).title(),
                get_siel_collection_phase=collection_phase,
                get_siel_count_status=count_status,
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
            'apps.dx.dx_layer1.siel_retail': package_stub(
                'apps.dx.dx_layer1.siel_retail'
            ),
            'apps.dx.dx_layer1.siel_retail.siel_retail_repositories': (
                cls.repo_module
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer1/siel_retail/siel_retail_services.py',
            'apps.dx.dx_layer1.siel_retail.siel_retail_services_under_test',
            stubs,
        )

    def _set_counts(self, counts):
        def latest_counts(_cursor, product_line, source_date):
            self.assertEqual('2026-08-11', source_date)
            return counts.get(product_line, [])
        self.repo_module.get_latest_main_batch_counts = latest_counts

    def test_completed_response_uses_same_day_and_fixed_retailers(self):
        self._set_counts({
            'siel_tv': [
                {
                    'retailer': 'Amazon', 'batch_id': 'tv-a',
                    'actual_count': 333, 'main_count': 300,
                    'bsr_count': 33,
                },
                {
                    'retailer': 'Flipkart', 'batch_id': 'tv-f',
                    'actual_count': 300, 'main_count': 300,
                    'bsr_count': 0,
                },
            ],
            'siel_ref': [
                {
                    'retailer': 'Amazon', 'batch_id': 'ref-a',
                    'actual_count': 333, 'main_count': 300,
                    'bsr_count': 33,
                },
                {
                    'retailer': 'Flipkart', 'batch_id': 'ref-f',
                    'actual_count': 302, 'main_count': 300,
                    'bsr_count': 2,
                },
            ],
            'siel_ldy': [
                {
                    'retailer': 'Amazon', 'batch_id': 'ldy-a',
                    'actual_count': 240, 'main_count': 174,
                    'bsr_count': 66,
                },
                {
                    'retailer': 'Flipkart', 'batch_id': 'ldy-f',
                    'actual_count': 309, 'main_count': 300,
                    'bsr_count': 9,
                },
            ],
        })

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 11), datetime(2026, 8, 11, 9, 0, 1)
        )
        check = result['check']

        self.assertEqual('siel_retail', check['check_type'])
        self.assertEqual('2026-08-11', check['inspection_date'])
        self.assertEqual('2026-08-11', check['source_date'])
        self.assertEqual(0, check['offset_days'])
        self.assertEqual('KST 09:00 완료 기준', check['collection_window'])
        self.assertEqual('OK', check['status'])
        self.assertEqual(1800, check['expected'])
        self.assertEqual(1817, check['actual'])
        self.assertEqual([], result['failed_items'])
        self.assertEqual(
            ['TV', 'REF', 'LDY'],
            [category['category'] for category in check['categories']],
        )
        ldy_amazon = check['categories'][2]['retailers'][0]
        self.assertEqual('ldy-a', ldy_amazon['batch_id'])
        self.assertEqual(174, ldy_amazon['main_count'])
        self.assertEqual(66, ldy_amazon['bsr_count'])

    def test_before_completion_zero_is_collecting(self):
        self._set_counts({})

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 11), datetime(2026, 8, 11, 8, 59)
        )

        self.assertEqual('COLLECTING', result['check']['status'])
        self.assertEqual([], result['failed_items'])
        self.assertTrue(all(
            retailer['status'] == 'COLLECTING'
            for category in result['check']['categories']
            for retailer in category['retailers']
        ))

    def test_after_completion_zero_is_critical_without_fallback(self):
        self._set_counts({})

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 11), datetime(2026, 8, 11, 9, 1)
        )

        self.assertEqual('CRITICAL', result['check']['status'])
        self.assertEqual(6, len(result['failed_items']))
        self.assertTrue(all(
            item['error_type'] == '수집 건수 없음'
            for item in result['failed_items']
        ))

    def test_future_date_is_pending(self):
        self._set_counts({})

        result = self.service.get_layer1_stats(
            object(), date(2026, 8, 11), datetime(2026, 8, 10, 23, 0)
        )

        self.assertEqual('PENDING', result['check']['status'])
        self.assertEqual([], result['failed_items'])


if __name__ == '__main__':
    unittest.main()
