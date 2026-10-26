"""End-to-end service contracts for the newly onboarded dryer retailers."""
import unittest
from datetime import date
from unittest.mock import Mock

from apps.common.null_review_evidence import NON_TARGET_REASON
from apps.dx.dx_layer2.null_validation import services as nulls
from apps.dx.dx_layer2.data_edit import services as edits2
from apps.dx.dx_layer3.data_edit import services as edits3
from tests.unit.support import ScriptedCursor


SOURCES = (
    ('dx_sem.dx_sem_ldy_dryer_retail_com', 'Coppel', '$1.00'),
    ('dx_seg.dx_seg_ldy_dryer_retail', 'Mediamarkt', '1,00 €'),
)
DAY = date(2026, 10, 26)


class DryerReviewWriteTests(unittest.TestCase):
    def test_null_confirmation_persists_dryer_identity_and_evidence(self):
        for table, retailer, _ in SOURCES:
            with self.subTest(retailer=retailer):
                cursor = ScriptedCursor([
                    {'fetchone': (None, retailer, '123')},
                    {'fetchone': (42, '123', 'Dryer A', None, retailer)},
                    {'fetchone': None}, {'fetchone': (101,)}, {'fetchone': (201,)},
                ])
                conn = Mock()
                result = nulls.save_null_review(
                    cursor, conn, table, 42, 'sku', 'normal', '', NON_TARGET_REASON,
                    str(DAY), 'null', 'tester',
                )
                self.assertTrue(result['success'])
                self.assertEqual(201, result['normal_review']['evidence_id'])
                self.assertIn('FOR UPDATE', cursor.calls[1][0])
                self.assertIn('LDY_DRYER', cursor.calls[-1][1])
                self.assertIn(NON_TARGET_REASON, cursor.calls[-1][1])
                self.assertNotIn('UPDATE ' + table, '\n'.join(sql for sql, _ in cursor.calls))
                conn.commit.assert_called_once()

    def test_null_value_edits_write_source_and_audit(self):
        for table, retailer, _ in SOURCES:
            with self.subTest(retailer=retailer):
                cursor = ScriptedCursor([{'fetchone': (None, retailer, '123', 'batch')}, {}, {}])
                result = edits2.update_cell_value(cursor, Mock(), table, 42, 'sku',
                                                 'SKU-1', DAY, 'null', 'tester', 'fixed')
                self.assertTrue(result['success'])
                self.assertIn(f'UPDATE {table} SET sku = %s', cursor.calls[1][0])
                self.assertEqual(('SKU-1', 42), cursor.calls[1][1])
                self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])

    def test_crossfield_edits_and_confirmations_are_audited(self):
        for table, retailer, value in SOURCES:
            with self.subTest(retailer=retailer):
                cursor = ScriptedCursor([{'fetchone': ('old', 'batch', retailer, '123')}, {}, {}])
                conn = Mock()
                result = edits3.update_cell_value(cursor, conn, table, 42,
                                                 'final_sku_price', value, DAY,
                                                 'cross_field', 'tester', 'fixed')
                self.assertTrue(result['success'])
                self.assertIn(f'UPDATE {table} SET final_sku_price = %s', cursor.calls[1][0])
                self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
                conn.commit.assert_called_once()
                cursor = ScriptedCursor([
                    {'fetchone': (value, retailer, '123')}, {'fetchone': None}, {},
                ])
                result = edits3.save_review(cursor, Mock(), table, 42, 'final_sku_price',
                                            'normal', '', 'confirmed', DAY, 'cross_field', 'tester')
                self.assertTrue(result['success'])
                self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])

    def test_out_of_scope_rows_cannot_be_edited_or_confirmed(self):
        for table, _retailer, value in SOURCES:
            for operation in ('null_edit', 'null_review', 'cross_edit', 'cross_review'):
                with self.subTest(table=table, operation=operation):
                    cursor = ScriptedCursor([{'fetchone': None}])
                    conn = Mock()
                    if operation == 'null_edit':
                        result = edits2.update_cell_value(cursor, conn, table, 42, 'sku', 'X', DAY, 'null', 'tester', '')
                    elif operation == 'null_review':
                        result = nulls.save_null_review(cursor, conn, table, 42, 'sku', 'normal', '', NON_TARGET_REASON, str(DAY), 'null', 'tester')
                    elif operation == 'cross_edit':
                        result = edits3.update_cell_value(cursor, conn, table, 42, 'final_sku_price', value, DAY, 'cross_field', 'tester', '')
                    else:
                        result = edits3.save_review(cursor, conn, table, 42, 'final_sku_price', 'normal', '', 'confirmed', DAY, 'cross_field', 'tester')
                    self.assertEqual(404, result.get('status_code', result.get('status')))
                    self.assertEqual(1, len(cursor.calls))
                    conn.commit.assert_not_called()
