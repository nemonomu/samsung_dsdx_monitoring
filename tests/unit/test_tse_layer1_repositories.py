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
                ('Homepro', 'h20260810_095803', 300, 180, 100),
                ('Future Retailer', 'future-batch', 245, 150, 80),
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
        self.assertIn('COUNT(rows.main_rank) AS main_count', sql)
        self.assertIn('COUNT(rows.bsr_rank) AS bsr_count', sql)
        self.assertEqual(('2026-08-10',), params)
        self.assertEqual(300, result[0]['actual_count'])
        self.assertEqual(180, result[0]['main_count'])
        self.assertEqual(100, result[0]['bsr_count'])
        self.assertEqual('Future Retailer', result[1]['retailer'])

    def test_mapping_rows_are_supported(self):
        cursor = ScriptedCursor([{
            'fetchall': [{
                'account_name': 'Homepro',
                'batch_id': 'batch-1',
                'actual_count': 287,
                'main_count': 200,
                'bsr_count': 90,
            }],
        }])

        result = self.repo.get_latest_batch_counts(
            cursor, 'tse_ldy', '2026-08-10'
        )

        self.assertEqual([{
            'retailer': 'Homepro',
            'batch_id': 'batch-1',
            'actual_count': 287,
            'main_count': 200,
            'bsr_count': 90,
        }], result)

    def test_previous_main_counts_use_latest_batch_and_prior_valid_days(self):
        cursor = ScriptedCursor([{
            'fetchall': [
                ('2026-08-13', 84),
                ('2026-08-12', 86),
                ('2026-08-11', 82),
            ],
        }])

        result = self.repo.get_previous_main_counts(
            cursor,
            'tse_tv',
            'Lotuss',
            '2026-08-14',
            limit=7,
        )

        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com', sql)
        self.assertIn('LOWER(TRIM(account_name)) = LOWER(TRIM(%s))', sql)
        self.assertIn("LEFT(TRIM(crawl_datetime), 10) < %s", sql)
        self.assertIn('DISTINCT ON (collection_date)', sql)
        self.assertIn('ORDER BY collection_date, id DESC', sql)
        self.assertIn('COUNT(rows.main_rank) AS main_count', sql)
        self.assertIn('HAVING COUNT(rows.main_rank) > 0', sql)
        self.assertIn('ORDER BY latest.collection_date DESC', sql)
        self.assertIn('LIMIT %s', sql)
        self.assertEqual(('Lotuss', '2026-08-14', 7), params)
        self.assertEqual([
            {'collection_date': '2026-08-13', 'main_count': 84},
            {'collection_date': '2026-08-12', 'main_count': 86},
            {'collection_date': '2026-08-11', 'main_count': 82},
        ], result)

    def test_previous_main_counts_support_mapping_rows(self):
        cursor = ScriptedCursor([{
            'fetchall': [{
                'collection_date': '2026-08-13',
                'main_count': 39,
            }],
        }])

        result = self.repo.get_previous_main_counts(
            cursor, 'tse_ldy', 'lotuss', '2026-08-14'
        )

        self.assertEqual([
            {'collection_date': '2026-08-13', 'main_count': 39},
        ], result)


if __name__ == '__main__':
    unittest.main()
