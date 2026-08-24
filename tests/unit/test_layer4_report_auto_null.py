import unittest

from tests.unit.support import load_module, module_stub


class Layer4ReportAutoNullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer4/report/services.py',
            'layer4_report_auto_null_under_test',
            stubs={
                'apps.common.db': module_stub(
                    'apps.common.db', dx_connection=None,
                ),
            },
        )

    def test_auto_applied_null_is_included_in_daily_report_payload(self):
        type_summary = {}
        reason_summary = []
        table_summary = {}
        details = []
        auto_reviews = [{
            'table_name': 'dx_tse.dx_tse_ldy_retail_com',
            'record_id': 4934,
            'column_name': 'sku',
            'memo': '',
            'created_id': 'y.k.kim',
            'retailer': 'Homepro',
            'item': '888213600004',
            'original_crawl_date': '2026-08-23',
            'original_created_at': '2026-08-23 15:21:18',
        }]

        self.service._merge_tse_auto_null_reviews(
            auto_reviews,
            type_summary,
            reason_summary,
            table_summary,
            details,
        )

        self.assertEqual(1, type_summary['null_check']['normal'])
        self.assertEqual(1, reason_summary[0]['count'])
        self.assertEqual('해당값정상 확인 (자동 적용)', reason_summary[0]['reason'])
        self.assertEqual(
            1,
            table_summary['dx_tse.dx_tse_ldy_retail_com'][
                'null_check'
            ]['normal'],
        )
        self.assertTrue(details[0]['auto_applied'])
        self.assertEqual('해당값정상 확인 (자동 적용)', details[0]['reason'])
        self.assertEqual('2026-08-23', details[0]['original_crawl_date'])


if __name__ == '__main__':
    unittest.main()
