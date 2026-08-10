import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


class DummyConnection:
    def commit(self):
        return None


def load_service(cursor, retailer_columns):
    @contextmanager
    def dx_connection():
        yield DummyConnection(), cursor

    return load_module(
        'apps/dx/dx_layer4/collection_status/services.py',
        'layer4_tse_collection_status_under_test',
        stubs={
            'apps.common.db': module_stub(
                'apps.common.db',
                dx_connection=dx_connection,
                dx_table=lambda name: name,
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                load_retail_columns=lambda: {},
                get_tse_retailer_columns=lambda product_line: retailer_columns,
            ),
            'apps.common.retail_validation': module_stub(
                'apps.common.retail_validation',
                get_tv_validation_condition=lambda: 'TRUE',
            ),
            'config': package_stub('config'),
            'config.config': module_stub(
                'config.config',
                EMAIL_CONFIG={},
            ),
        },
    )


class Layer4TseCollectionStatusTests(unittest.TestCase):
    def test_latest_batch_null_counts_use_allowlisted_columns(self):
        cursor = ScriptedCursor([
            {'fetchone': (287, 0, 6)},
        ])
        service = load_service(cursor, {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['country', 'ldy_capacity', 'bad;column'],
                'editable_columns': [],
            }
        })

        result = service.get_collection_status(date(2026, 8, 10), 'tse_ldy')

        self.assertTrue(result['success'])
        self.assertEqual(result['retailers'][0]['total_count'], 287)
        self.assertEqual(
            result['retailers'][0]['columns'],
            [
                {'column': 'country', 'total_count': 287, 'null_count': 0},
                {'column': 'ldy_capacity', 'total_count': 287, 'null_count': 6},
            ],
        )
        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_ldy_retail_com t', sql)
        self.assertIn('LEFT(TRIM(crawl_datetime), 10) = %s', sql)
        self.assertIn('ORDER BY id DESC LIMIT 1', sql)
        self.assertNotIn('bad;column', sql)
        self.assertIn('LEFT(TRIM(t.crawl_datetime), 10) = %s', sql)
        self.assertIn('OR t.account_name IS NULL', sql)
        self.assertEqual(
            params,
            ['homepro', '2026-08-10', 'homepro', '2026-08-10'],
        )

    def test_null_detail_is_latest_batch_and_read_only(self):
        cursor = ScriptedCursor([
            {
                'fetchall': [
                    (7, '2026-08-10T09:58:03+09:00', 'Homepro', 'A1', None, 'https://example.invalid'),
                ]
            },
        ])
        service = load_service(cursor, {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['ldy_capacity'],
                'editable_columns': ['ldy_capacity'],
            }
        })

        result = service.get_null_detail(
            date(2026, 8, 10), 'tse_ldy', 'Homepro', 'ldy_capacity'
        )

        self.assertTrue(result['read_only'])
        self.assertEqual(result['actual_table'], 'dx_tse.dx_tse_ldy_retail_com')
        self.assertEqual(result['rows'][0]['ldy_capacity'], '')
        sql, params = cursor.calls[0]
        self.assertIn('ORDER BY id DESC LIMIT 1', sql)
        self.assertIn('LEFT(TRIM(t.crawl_datetime), 10) = %s', sql)
        self.assertIn('OR t.account_name IS NULL', sql)
        self.assertEqual(
            params,
            ['homepro', '2026-08-10', 'homepro', '2026-08-10'],
        )

    def test_rejects_unconfigured_detail_column(self):
        service = load_service(ScriptedCursor([]), {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['country'],
                'editable_columns': [],
            }
        })
        with self.assertRaises(ValueError):
            service.get_null_detail(
                date(2026, 8, 10), 'tse_tv', 'Homepro', 'batch_id'
            )


if __name__ == '__main__':
    unittest.main()
