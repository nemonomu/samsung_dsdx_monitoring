import unittest
from datetime import date
from unittest.mock import Mock

from apps.common.sem_retail import get_sem_editable_columns
from apps.dx.dx_layer2.data_edit import services as layer2_services
from apps.dx.dx_layer3.data_edit import services as layer3_services
from tests.unit.support import ScriptedCursor


SEM_TABLE = 'dx_sem.dx_sem_tv_retail_com'


class SemEditableColumnTests(unittest.TestCase):
    def test_validation_columns_are_editable_but_savings_is_not(self):
        editable = get_sem_editable_columns('sem_tv')

        self.assertIn('sku', editable)
        self.assertIn('screen_size', editable)
        self.assertIn('original_sku_price', editable)
        self.assertIn('calendar_week', editable)
        self.assertNotIn('savings', editable)
        self.assertNotIn('batch_id', editable)


class SemLayer2DataEditTests(unittest.TestCase):
    def test_sem_table_is_allowlisted_and_latest_batch_row_can_be_updated(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Liverpool', 'TV-1', 'batch-1')},
            {},
            {},
        ])
        conn = Mock()

        result = layer2_services.update_cell_value(
            cursor, conn, SEM_TABLE, 11, 'sku', 'SKU-1',
            date(2026, 9, 7), 'null', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        self.assertIn(SEM_TABLE, layer2_services.VALID_TABLES_UPDATE)
        self.assertIn("UPPER(BTRIM(source.country)) = %s", cursor.calls[0][0])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', cursor.calls[0][0])
        self.assertIn(f'UPDATE {SEM_TABLE} SET sku = %s', cursor.calls[1][0])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])

    def test_sem_system_column_is_rejected_before_query(self):
        cursor = ScriptedCursor([])

        result = layer2_services.update_cell_value(
            cursor, Mock(), SEM_TABLE, 11, 'batch_id', 'other',
            date(2026, 9, 7), 'null', 'tester', '',
        )

        self.assertEqual(403, result['status'])
        self.assertEqual([], cursor.calls)


class SemLayer3DataEditTests(unittest.TestCase):
    def test_crossfield_cell_update_uses_sem_allowlist_and_latest_batch(self):
        cursor = ScriptedCursor([
            {'fetchone': ('$10.00', 'batch-1', 'Liverpool', 'TV-1')},
            {},
            {},
        ])
        conn = Mock()

        result = layer3_services.update_cell_value(
            cursor, conn, SEM_TABLE, 11, 'final_sku_price', '$9.00',
            date(2026, 9, 7), 'cross_field', 'tester', 'fixed', None,
        )

        self.assertTrue(result['success'])
        self.assertIn(SEM_TABLE, layer3_services.VALID_TABLES_UPDATE)
        self.assertIn("UPPER(BTRIM(source.country)) = %s", cursor.calls[0][0])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', cursor.calls[0][0])
        self.assertIn(
            f'UPDATE {SEM_TABLE} SET final_sku_price = %s',
            cursor.calls[1][0],
        )
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        conn.commit.assert_called_once_with()

    def test_crossfield_system_column_is_rejected_before_query(self):
        cursor = ScriptedCursor([])

        result = layer3_services.update_cell_value(
            cursor, Mock(), SEM_TABLE, 11, 'batch_id', 'other',
            date(2026, 9, 7), 'cross_field', 'tester', '', None,
        )

        self.assertEqual(403, result['status'])
        self.assertEqual([], cursor.calls)


if __name__ == '__main__':
    unittest.main()
