import unittest

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class SielLayer1RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.siel_retail': module_stub(
                'apps.common.siel_retail',
                SIEL_BUSINESS_TIMEZONE='Asia/Seoul',
                get_siel_source=lambda product_line: {
                    'table_name': {
                        'siel_tv': 'dx_siel.dx_siel_tv_retail_com',
                        'siel_ref': 'dx_siel.dx_siel_ref_retail_com',
                        'siel_ldy': 'dx_siel.dx_siel_ldy_retail_com',
                    }[product_line],
                    'date_column': 'crawl_datetime',
                    'retailers': ('Amazon', 'Flipkart'),
                },
            ),
        }
        cls.repo = load_module(
            'apps/dx/dx_layer1/siel_retail/siel_retail_repositories.py',
            'siel_layer1_repository_under_test',
            stubs,
        )

    def test_kst_day_latest_main_anchor_and_same_batch_scope(self):
        cursor = ScriptedCursor([{
            'fetchall': [
                ('Amazon', 'a_20260810_203044', 333, 300, 33),
                ('Flipkart', 'f_20260810_230012', 302, 300, 2),
            ],
        }])

        result = self.repo.get_latest_main_batch_counts(
            cursor, 'siel_tv', '2026-08-11'
        )

        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_siel.dx_siel_tv_retail_com', sql)
        self.assertEqual(2, sql.count("AT TIME ZONE 'Asia/Seoul'"))
        self.assertIn(
            "LOWER(BTRIM(CAST(page_type AS TEXT))) = 'main'", sql
        )
        self.assertIn('ORDER BY LOWER(BTRIM(CAST(account_name AS TEXT))), id DESC', sql)
        self.assertIn('rows.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertIn("IN ('main', 'bsr')", sql)
        self.assertNotIn('MAX(BATCH_ID)', sql.upper())
        self.assertEqual(
            ['2026-08-11', '2026-08-11', 'amazon', 'flipkart'],
            params,
        )
        self.assertEqual(333, result[0]['actual_count'])
        self.assertEqual(300, result[0]['main_count'])
        self.assertEqual(33, result[0]['bsr_count'])

    def test_mapping_rows_are_supported(self):
        cursor = ScriptedCursor([{
            'fetchall': [{
                'account_name': 'Amazon',
                'batch_id': 'batch-1',
                'actual_count': 240,
                'main_count': 174,
                'bsr_count': 66,
            }],
        }])

        result = self.repo.get_latest_main_batch_counts(
            cursor, 'siel_ldy', '2026-08-11'
        )

        self.assertEqual([{
            'retailer': 'Amazon',
            'batch_id': 'batch-1',
            'actual_count': 240,
            'main_count': 174,
            'bsr_count': 66,
        }], result)


if __name__ == '__main__':
    unittest.main()
