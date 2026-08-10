import unittest

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class TseLayer1RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.tse_retail': module_stub(
                'apps.common.tse_retail',
                get_tse_source=lambda product_line: {
                    'table_name': {
                        'tse_tv': 'dx_tse.dx_tse_tv_retail_com',
                        'tse_ref': 'dx_tse.dx_tse_ref_retail_com',
                        'tse_ldy': 'dx_tse.dx_tse_ldy_retail_com',
                    }[product_line],
                },
            ),
        }
        cls.repo = load_module(
            'apps/dx/dx_layer1/tse_retail/tse_retail_repositories.py',
            'tse_layer1_repository_under_test',
            stubs,
        )

    def test_latest_batch_is_selected_by_greatest_id(self):
        cursor = ScriptedCursor([{
            'fetchall': [
                ('Homepro', 'h20260810_095803', 300),
                ('Future Retailer', 'future-batch', 245),
            ],
        }])

        result = self.repo.get_latest_batch_counts(
            cursor, 'tse_tv', '2026-08-10'
        )

        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com', sql)
        self.assertIn('LEFT(TRIM(crawl_datetime), 10) = %s', sql)
        self.assertIn('DISTINCT ON (LOWER(TRIM(account_name)))', sql)
        self.assertIn('ORDER BY LOWER(TRIM(account_name)), id DESC', sql)
        self.assertNotIn('MAX(BATCH_ID)', sql.upper())
        self.assertEqual(('2026-08-10',), params)
        self.assertEqual(300, result[0]['actual_count'])
        self.assertEqual('Future Retailer', result[1]['retailer'])

    def test_mapping_rows_are_supported(self):
        cursor = ScriptedCursor([{
            'fetchall': [{
                'account_name': 'Homepro',
                'batch_id': 'batch-1',
                'actual_count': 287,
            }],
        }])

        result = self.repo.get_latest_batch_counts(
            cursor, 'tse_ldy', '2026-08-10'
        )

        self.assertEqual([{
            'retailer': 'Homepro',
            'batch_id': 'batch-1',
            'actual_count': 287,
        }], result)


if __name__ == '__main__':
    unittest.main()
