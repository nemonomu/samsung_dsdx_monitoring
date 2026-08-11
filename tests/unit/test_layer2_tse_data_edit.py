import unittest
from datetime import date
from unittest.mock import Mock

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


TSE_TABLE = 'dx_tse.dx_tse_tv_retail_com'
MAX_EDITABLE = {
    'country', 'account_name', 'item', 'sku', 'product_url',
    'retailer_sku_name', 'count_of_reviews', 'star_rating',
    'count_of_star_ratings', 'final_sku_price', 'screen_size',
    'original_sku_price', 'savings',
}


class TSELayer2DataEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.monitoring_exclusions': module_stub(
                'apps.common.monitoring_exclusions',
                DISABLED_SOURCE_TABLES=frozenset(),
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                get_editable_columns=lambda product_line, retailer: (
                    list(MAX_EDITABLE)
                    if product_line == 'tse_tv' and retailer == 'Homepro'
                    else []
                ),
            ),
            'apps.common.tse_retail': module_stub(
                'apps.common.tse_retail',
                TSE_TABLE_TO_PRODUCT_LINE={TSE_TABLE: 'tse_tv'},
                resolve_tse_table=lambda table: (
                    table if table == TSE_TABLE
                    else (_ for _ in ()).throw(ValueError('invalid table'))
                ),
                get_tse_product_line_for_table=lambda table: (
                    'tse_tv' if table == TSE_TABLE
                    else (_ for _ in ()).throw(ValueError('invalid table'))
                ),
                get_tse_editable_columns=lambda product_line: (
                    tuple(MAX_EDITABLE) if product_line == 'tse_tv' else ()
                ),
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer2/data_edit/services.py',
            'layer2_tse_data_edit_service_under_test',
            stubs,
        )

    def test_update_and_history_share_the_same_cursor_transaction(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Homepro', 'TV-1', 'batch-1')},
            {},
            {},
        ])

        result = self.service.update_cell_value(
            cursor, Mock(), TSE_TABLE, 11, 'sku', 'SKU-1',
            date(2026, 8, 10), 'null', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        self.assertIn(
            f'SELECT sku, account_name, item, batch_id FROM {TSE_TABLE}',
            cursor.calls[0][0],
        )
        self.assertIn("country = 'TSE'", cursor.calls[0][0])
        self.assertIn('OR country IS NULL', cursor.calls[0][0])
        self.assertIn('LEFT(TRIM(crawl_datetime), 10) = %s', cursor.calls[0][0])
        self.assertEqual((11, '2026-08-10'), cursor.calls[0][1])
        self.assertIn(f'UPDATE {TSE_TABLE} SET sku = %s', cursor.calls[1][0])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        history = cursor.calls[2][1]
        self.assertEqual('null_check', history[1])
        self.assertEqual(TSE_TABLE, history[2])
        self.assertEqual('corrected', history[10])

    def test_identity_collision_blocks_update_and_history(self):
        cursor = ScriptedCursor([
            {'fetchone': ('TV-1', 'Homepro', 'TV-1', 'batch-1')},
            {'fetchone': (22,)},
        ])

        result = self.service.update_cell_value(
            cursor, Mock(), TSE_TABLE, 11, 'item', 'TV-2',
            date(2026, 8, 10), 'null', 'tester', '',
        )

        self.assertEqual(409, result['status'])
        self.assertEqual(2, len(cursor.calls))
        collision_sql = cursor.calls[1][0]
        self.assertIn('account_name IS NOT DISTINCT FROM %s', collision_sql)
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', collision_sql)
        self.assertIn('item IS NOT DISTINCT FROM %s', collision_sql)
        self.assertNotIn('UPDATE', collision_sql)

    def test_forbidden_column_and_table_are_rejected_before_sql(self):
        for table, column in (
            (TSE_TABLE, 'batch_id'),
            ('dx_tse.dx_tse_tv_retail_com; DROP TABLE x', 'sku'),
            (TSE_TABLE, 'sku; DROP TABLE x'),
        ):
            cursor = ScriptedCursor([])
            result = self.service.update_cell_value(
                cursor, Mock(), table, 11, column, 'x',
                date(2026, 8, 10), 'null', 'tester', '',
            )
            self.assertIn(result['status'], {400, 403})
            self.assertEqual([], cursor.calls)

    def test_history_failure_rolls_back_source_update(self):
        class FailingHistoryCursor(ScriptedCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if 'INSERT INTO monitoring_corrections' in sql:
                    raise RuntimeError('history insert failed')

        cursor = FailingHistoryCursor([
            {'fetchone': (None, 'Homepro', 'TV-1', 'batch-1')},
            {},
            {},
        ])
        conn = Mock()

        with self.assertRaisesRegex(RuntimeError, 'history insert failed'):
            self.service.update_cell_value(
                cursor, conn, TSE_TABLE, 11, 'sku', 'SKU-1',
                date(2026, 8, 10), 'null', 'tester', 'fixed',
            )

        conn.rollback.assert_called_once_with()
        self.assertIn(f'UPDATE {TSE_TABLE} SET sku = %s', cursor.calls[1][0])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])

    def test_missing_account_name_can_be_assigned_to_the_only_configured_retailer(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, None, 'TV-1', 'batch-1')},
            {},
            {},
            {},
        ])

        result = self.service.update_cell_value(
            cursor, Mock(), TSE_TABLE, 11, 'account_name', 'Homepro',
            date(2026, 8, 10), 'null', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        self.assertEqual('Homepro', cursor.calls[3][1][-2])


if __name__ == '__main__':
    unittest.main()
