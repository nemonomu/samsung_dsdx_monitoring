import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class DummyConnection:
    pass


def load_service(cursor):
    @contextmanager
    def dx_connection():
        yield DummyConnection(), cursor

    registry = load_module(
        'apps/dx/dx_layer4/collection_status/email_registry.py',
        'layer4_email_registry_under_test',
    )
    package_name = 'apps.dx.dx_layer4.collection_status'
    return load_module(
        'apps/dx/dx_layer4/collection_status/email_services.py',
        f'{package_name}.email_services_under_test',
        stubs={
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=dx_connection,
            ),
            package_name: package_stub(package_name),
            f'{package_name}.email_registry': registry,
        },
    )


def source(key='siel_tv', date_mode='timestamp'):
    return {
        'key': key,
        'country': 'SIEL',
        'product': 'TV',
        'label': 'SIEL TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'date_column': 'crawl_datetime',
        'date_mode': date_mode,
        'id_column': 'id',
        'batch_column': 'batch_id',
        'account_column': 'account_name',
        'has_page_type': True,
        'include_unassigned': False,
        'retailers': ({
            'name': 'Amazon',
            'aliases': ('Amazon',),
            'columns': ('sku', 'final_sku_price'),
            'expected_count': 300,
            'exclude_redirect': False,
        },),
    }


class EmailReportDataTests(unittest.TestCase):
    def test_latest_batch_and_whitespace_missing_counts(self):
        cursor = ScriptedCursor([
            {'fetchone': ('a_20260811_000011',)},
            {'fetchone': (287, 2, 5)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(),)
        )

        self.assertTrue(result['complete'])
        row = result['sources'][0]
        self.assertEqual(row['column_order'], ['sku', 'final_sku_price'])
        self.assertEqual(row['total_count'], 287)
        self.assertEqual(row['retailers'][0]['batch_id'], 'a_20260811_000011')
        self.assertEqual(row['retailers'][0]['columns'][1]['null_count'], 5)
        latest_sql, params = cursor.calls[0]
        count_sql, count_params = cursor.calls[1]
        self.assertIn('DATE(source.crawl_datetime::timestamp) = %s', latest_sql)
        self.assertIn('ORDER BY source.id DESC LIMIT 1', latest_sql)
        self.assertIn('BTRIM(CAST(source.final_sku_price AS TEXT))', count_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM %s', count_sql)
        self.assertEqual(params, ['amazon', '2026-08-11'])
        self.assertEqual(count_params[-1], 'a_20260811_000011')

    def test_missing_batch_returns_zero_without_second_query(self):
        cursor = ScriptedCursor([{'fetchone': None}])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(date_mode='text'),)
        )

        retailer = result['sources'][0]['retailers'][0]
        self.assertFalse(retailer['has_data'])
        self.assertEqual(retailer['total_count'], 0)
        self.assertEqual(len(cursor.calls), 1)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)', cursor.calls[0][0])

    def test_partial_failure_is_not_reported_as_complete(self):
        cursor = ScriptedCursor([])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(key='broken'),)
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['errors'][0]['source'], 'broken')


if __name__ == '__main__':
    unittest.main()
