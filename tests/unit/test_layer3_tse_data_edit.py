import unittest
from unittest.mock import patch

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub
from apps.common import inspection_dates, sea_retail, tse_retail


services = load_module(
    'apps/dx/dx_layer3/data_edit/services.py',
    'layer3_tse_data_edit_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [],
        ),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.sea_retail': sea_retail,
        'apps.common.tse_retail': tse_retail,
    },
)


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FailingHistoryCursor(ScriptedCursor):
    def execute(self, sql, params=None):
        if 'INSERT INTO monitoring_corrections' in sql:
            raise RuntimeError('history insert failed')
        super().execute(sql, params)


class TseLayer3DataEditTests(unittest.TestCase):
    table_name = 'dx_tse.dx_tse_tv_retail_com'

    def test_tse_tables_are_exactly_allowlisted(self):
        self.assertIn(self.table_name, services.VALID_TABLES_UPDATE)
        self.assertNotIn('dx_tse.any_table', services.VALID_TABLES_UPDATE)

    def test_forbidden_system_column_is_rejected_before_query(self):
        cursor = ScriptedCursor([])
        result = services.update_cell_value(
            cursor, FakeConnection(), self.table_name, 1, 'batch_id', 'new',
            '2026-08-10', 'cross_field', 'tester', '', 11,
        )
        self.assertEqual(result['status'], 403)
        self.assertEqual(cursor.calls, [])

    def test_service_rejects_unknown_table_and_injected_column_before_query(self):
        for table_name, column_name in (
            ('dx_tse.unknown_table', 'item'),
            (self.table_name, 'item; DROP TABLE x'),
        ):
            cursor = ScriptedCursor([])
            result = services.update_cell_value(
                cursor, FakeConnection(), table_name, 1, column_name, 'x',
                '2026-08-10', 'cross_field', 'tester', '', 11,
            )
            self.assertEqual(result['status'], 400)
            self.assertEqual(cursor.calls, [])

    @patch.object(services, 'get_editable_columns', return_value=['final_sku_price'])
    def test_update_and_history_commit_together(self, _editable):
        cursor = ScriptedCursor([
            {'fetchone': ('฿7,990', 'batch-1', 'Homepro', 'A-1')},
            {},
            {},
        ])
        conn = FakeConnection()
        result = services.update_cell_value(
            cursor, conn, self.table_name, 10, 'final_sku_price', '฿7,900',
            '2026-08-10', 'cross_field', 'tester', '가격 확인', 21,
        )
        self.assertTrue(result['success'])
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertIn('UPDATE dx_tse.dx_tse_tv_retail_com', cursor.calls[1][0])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        self.assertEqual(cursor.calls[2][1][-1], 21)

    @patch.object(services, 'get_editable_columns', return_value=['final_sku_price'])
    def test_history_failure_rolls_back_source_update(self, _editable):
        cursor = FailingHistoryCursor([
            {'fetchone': ('฿7,990', 'batch-1', 'Homepro', 'A-1')},
            {},
        ])
        conn = FakeConnection()
        with self.assertRaises(RuntimeError):
            services.update_cell_value(
                cursor, conn, self.table_name, 10, 'final_sku_price', '฿7,900',
                '2026-08-10', 'cross_field', 'tester', '', 21,
            )
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    @patch.object(services, 'get_editable_columns', return_value=['item'])
    def test_unique_key_conflict_blocks_item_update(self, _editable):
        cursor = ScriptedCursor([
            {'fetchone': ('A-1', 'batch-1', 'Homepro', 'A-1')},
            {'fetchone': (99,)},
        ])
        conn = FakeConnection()
        result = services.update_cell_value(
            cursor, conn, self.table_name, 10, 'item', 'A-2',
            '2026-08-10', 'cross_field', 'tester', '', 21,
        )
        self.assertEqual(result['status'], 409)
        self.assertEqual(conn.commits, 0)
        self.assertFalse(any('UPDATE ' in sql for sql, _ in cursor.calls))
        self.assertIn('account_name IS NOT DISTINCT FROM %s', cursor.calls[1][0])
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', cursor.calls[1][0])
        self.assertIn('item IS NOT DISTINCT FROM %s', cursor.calls[1][0])

    @patch.object(services, 'get_editable_columns', return_value=['star_rating'])
    def test_normal_review_keeps_rule_and_audit_fields(self, _editable):
        cursor = ScriptedCursor([
            {'fetchone': ('0.0', 'Homepro', 'A-1')},
            {'fetchone': None},
            {},
        ])
        conn = FakeConnection()
        result = services.save_review(
            cursor, conn, self.table_name, 10, 'star_rating', 'normal',
            '실제 정상', '사이트 표시 기준', '2026-08-10',
            'cross_field', 'tester', 31,
        )
        self.assertTrue(result['success'])
        self.assertEqual(conn.commits, 1)
        insert_params = cursor.calls[2][1]
        self.assertEqual(insert_params[1], 'cross_field')
        self.assertEqual(insert_params[10], 'normal')
        self.assertEqual(insert_params[-1], 31)


if __name__ == '__main__':
    unittest.main()
