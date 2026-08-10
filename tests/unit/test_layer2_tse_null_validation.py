import unittest
from datetime import date
from unittest.mock import Mock

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


TSE_SOURCES = {
    'tse_tv': {
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
    },
    'tse_ref': {
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
    },
    'tse_ldy': {
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
    },
}


def tse_columns_config():
    return {
        'tse_tv': {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['country', 'account_name', 'sku'],
                'editable_columns': [
                    'country', 'account_name', 'sku',
                    'original_sku_price', 'batch_id',
                ],
            },
        },
        'tse_ref': {},
        'tse_ldy': {},
    }


def common_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', execute_dx_query=lambda _query: [],
            dx_table=lambda table: table,
        ),
        'apps.common.response': module_stub(
            'apps.common.response', log_error=lambda *_: None,
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            load_retail_columns=lambda: {},
            get_editable_columns=lambda *_: [],
            load_tse_retail_columns=tse_columns_config,
        ),
        'apps.common.tse_retail': module_stub(
            'apps.common.tse_retail',
            TSE_SOURCE_CONFIG=TSE_SOURCES,
            TSE_TABLE_TO_PRODUCT_LINE={
                source['table_name']: key
                for key, source in TSE_SOURCES.items()
            },
            get_tse_required_columns=lambda product_line: {
                'tse_tv': ('country', 'account_name', 'sku'),
                'tse_ref': ('country', 'ref_capacity'),
                'tse_ldy': ('country', 'ldy_capacity'),
            }[product_line],
            get_tse_editable_columns=lambda product_line: {
                'tse_tv': (
                    'country', 'account_name', 'sku',
                    'original_sku_price', 'savings',
                ),
                'tse_ref': (
                    'country', 'ref_capacity', 'original_sku_price', 'savings',
                ),
                'tse_ldy': (
                    'country', 'ldy_capacity', 'original_sku_price', 'savings',
                ),
            }[product_line],
            get_tse_product_line_for_table=lambda table: {
                source['table_name']: key for key, source in TSE_SOURCES.items()
            }[table],
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda *_: 'TRUE',
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
        'apps.dx.dx_layer2.common': package_stub(
            'apps.dx.dx_layer2.common'
        ),
        'apps.dx.dx_layer2.common.context': module_stub(
            'apps.dx.dx_layer2.common.context',
            get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
        ),
    }


class TSELayer2NullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'layer2_tse_null_service_under_test',
            common_stubs(),
        )
        cls.runtime = cls.service._get_tse_runtime()

    def test_summary_uses_latest_batch_and_active_required_columns(self):
        cursor = ScriptedCursor([
            {'fetchone': ('h20260810_095803', 300, 0, 0, 1)},
            {'fetchall': []},
        ])

        tables, issue_count = self.service._get_tse_null_tables(
            cursor, date(2026, 8, 10), self.runtime,
            tse_columns_config(),
        )

        self.assertEqual(1, issue_count)
        self.assertEqual('TSE TV', tables[0]['table_name'])
        self.assertEqual(300, tables[0]['retailers'][0]['total'])
        self.assertEqual(
            {'country': 0, 'account_name': 0, 'sku': 1},
            tables[0]['retailers'][0]['fields_detail'],
        )
        summary_sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com source', summary_sql)
        self.assertIn('LEFT(TRIM(source.crawl_datetime), 10) = %s', summary_sql)
        self.assertIn('ORDER BY source.id DESC LIMIT 1', summary_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', summary_sql)
        self.assertIn('OR source.account_name IS NULL', summary_sql)
        self.assertNotIn('batch_id AS null_batch_id', summary_sql)
        self.assertEqual(
            ('2026-08-10', 'homepro', '2026-08-10', 'homepro'),
            params,
        )

    def test_tse_query_failure_rolls_back_only_tse_savepoint(self):
        class FailingCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=None):
                normalized = ' '.join(sql.split())
                self.calls.append((normalized, params))
                if normalized.startswith('WITH latest_batch AS'):
                    raise RuntimeError('TSE table unavailable')

        cursor = FailingCursor()
        validation = {'tables': [{'table': 'tv_retail'}]}

        issue_count = self.service._append_tse_null_stats(
            cursor, date(2026, 8, 10), validation
        )

        self.assertEqual(0, issue_count)
        self.assertEqual([{'table': 'tv_retail'}], validation['tables'])
        sql_calls = [sql for sql, _params in cursor.calls]
        self.assertEqual('SAVEPOINT layer2_tse_null_stats', sql_calls[0])
        self.assertIn('WITH latest_batch AS', sql_calls[1])
        self.assertEqual(
            'ROLLBACK TO SAVEPOINT layer2_tse_null_stats', sql_calls[2]
        )
        self.assertEqual(
            'RELEASE SAVEPOINT layer2_tse_null_stats', sql_calls[3]
        )

    def test_detail_rejects_unconfigured_or_injected_column_before_sql(self):
        cursor = ScriptedCursor([])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku; DROP TABLE x', self.runtime, tse_columns_config(),
        )

        self.assertEqual([], result['results'])
        self.assertEqual([], cursor.calls)

    def test_detail_returns_only_latest_batch_rows_and_db_editable_allowlist(self):
        description = [
            ('id',), ('batch_id',), ('country',), ('account_name',),
            ('item',), ('crawl_datetime',), ('sku',),
            ('original_sku_price',),
        ]
        cursor = ScriptedCursor([
            {
                'description': description,
                'fetchall': [(
                    11, 'h20260810_095803', 'TSE', 'Homepro', 'TV-1',
                    '2026-08-10T09:58:03+09:00', None, '฿10,000',
                )],
            },
            {'fetchall': []},
        ])

        result = self.service._get_tse_null_detail(
            cursor, date(2026, 8, 10), 'tse_tv_retail', 'Homepro',
            'sku', self.runtime, tse_columns_config(),
        )

        self.assertEqual([11], [row['id'] for row in result['results']])
        self.assertEqual(['sku'], result['results'][0]['null_fields'])
        self.assertEqual(
            ['country', 'account_name', 'sku', 'original_sku_price'],
            result['editable_cols'],
        )
        self.assertNotIn('batch_id', result['editable_cols'])
        self.assertEqual(
            'dx_tse.dx_tse_tv_retail_com', result['actual_table']
        )
        detail_sql = cursor.calls[0][0]
        self.assertIn('CROSS JOIN latest_batch', detail_sql)
        self.assertIn('source.sku IS NULL', detail_sql)
        self.assertIn('OR source.account_name IS NULL', detail_sql)

    def test_normal_review_is_recorded_for_active_required_column(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Homepro', 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11, 'sku',
            'normal', 'checked', 'source_issue', date(2026, 8, 10),
            'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertIn(
            'SELECT sku, account_name, item FROM dx_tse.dx_tse_tv_retail_com',
            cursor.calls[0][0],
        )
        self.assertIn("country = 'TSE'", cursor.calls[0][0])
        self.assertIn('LEFT(TRIM(crawl_datetime), 10) = %s', cursor.calls[0][0])
        self.assertEqual((11, '2026-08-10'), cursor.calls[0][1])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        insert_params = cursor.calls[2][1]
        self.assertEqual('null_check', insert_params[1])
        self.assertEqual('dx_tse.dx_tse_tv_retail_com', insert_params[2])
        self.assertEqual('normal', insert_params[10])
        conn.commit.assert_called_once_with()

    def test_normal_review_rejects_edit_only_column(self):
        cursor = ScriptedCursor([])

        result = self.service.save_null_review(
            cursor, Mock(), 'dx_tse.dx_tse_tv_retail_com', 11,
            'original_sku_price', 'normal', '', 'source_issue',
            date(2026, 8, 10), 'null', 'tester',
        )

        self.assertEqual(400, result['status_code'])
        self.assertEqual([], cursor.calls)

    def test_single_retailer_config_can_review_missing_account_name(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, None, 'TV-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = self.service.save_null_review(
            cursor, conn, 'dx_tse.dx_tse_tv_retail_com', 11,
            'account_name', 'normal', 'checked', 'source_issue',
            date(2026, 8, 10), 'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual('homepro', cursor.calls[2][1][-2])

if __name__ == '__main__':
    unittest.main()
