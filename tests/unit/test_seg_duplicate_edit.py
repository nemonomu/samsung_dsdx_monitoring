import unittest
from datetime import date
from unittest.mock import Mock

from apps.dx.dx_layer2.data_edit import services
from apps.dx.dx_layer2.seg_validation import build_duplicate_groups
from tests.unit.support import ScriptedCursor


TABLE = 'dx_seg.dx_seg_ref_retail_com'
DAY = date(2026, 10, 20)


class SegDuplicateEditTests(unittest.TestCase):
    def edit(self, cursor, column='sku', value='CORRECT-SKU', conn=None):
        return services.update_cell_value(
            cursor, conn or Mock(), TABLE, 108558, column, value,
            DAY, 'duplicate', 'tester', '상품 옵션 SKU 수정',
        )

    def test_latest_source_day_sku_update_has_audit_history(self):
        cursor = ScriptedCursor([
            {'fetchone': ('OLD-SKU', 'OTTO', 'item-1', 'batch-1')}, {}, {},
        ])
        conn = Mock()
        self.assertTrue(self.edit(cursor, conn=conn)['success'])
        sql, params = cursor.calls[0]
        self.assertIn('FOR UPDATE OF source', sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', sql)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_strdatetime AS TEXT)), 10) = %s', sql)
        self.assertEqual((108558, '2026-10-20', 'SEG', '2026-10-20'), params)
        self.assertEqual(('CORRECT-SKU', 108558), cursor.calls[1][1])
        audit = cursor.calls[2][1]
        self.assertEqual((2, 'duplicate_check', TABLE, 108558, 'sku', 'OLD-SKU', 'CORRECT-SKU'), audit[:7])
        self.assertEqual(DAY, audit[7])
        self.assertEqual('tester', audit[8])
        self.assertEqual(('corrected', '상품 옵션 SKU 수정', 'OTTO', 'item-1'), audit[10:])
        conn.commit.assert_not_called()

    def test_other_columns_and_empty_sku_rejected_without_query(self):
        for column, value, expected in (
            ('item', 'other', 403), ('retailer_sku_name', 'other', 403),
            ('batch_id', 'other', 403), ('final_sku_price', '10', 403),
            ('sku', '', 400), ('sku', '  ', 400), ('sku', None, 400),
        ):
            with self.subTest(column=column, value=value):
                cursor = ScriptedCursor([])
                self.assertEqual(expected, self.edit(cursor, column, value)['status'])
                self.assertEqual([], cursor.calls)

    def test_row_outside_selected_day_or_latest_batch_cannot_be_updated(self):
        cursor = ScriptedCursor([{'fetchone': None}])
        self.assertEqual(404, self.edit(cursor)['status'])
        self.assertEqual(1, len(cursor.calls))

    def test_unchanged_value_does_not_add_history(self):
        cursor = ScriptedCursor([{'fetchone': ('CORRECT-SKU', 'OTTO', 'item-1', 'batch-1')}])
        self.assertTrue(self.edit(cursor)['success'])
        self.assertEqual(1, len(cursor.calls))

    def test_audit_failure_rolls_back_the_update(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('OLD-SKU', 'OTTO', 'item-1', 'batch-1')
        cursor.execute.side_effect = [None, None, RuntimeError('audit unavailable')]
        conn = Mock()
        with self.assertRaises(RuntimeError):
            self.edit(cursor, conn=conn)
        conn.rollback.assert_called_once()

    def test_otto_option_sku_correction_recomputes_duplicate_group(self):
        rows = [
            dict(id=1, page_type='main', item='same', sku='OLD', retailer_sku_name='Option A'),
            dict(id=2, page_type='main', item='same', sku='OLD', retailer_sku_name='Option B'),
        ]
        self.assertEqual(1, len(build_duplicate_groups(rows, 'OTTO')))
        rows[1]['sku'] = 'CORRECT'
        self.assertEqual([], build_duplicate_groups(rows, 'OTTO'))
        self.assertEqual(1, len(build_duplicate_groups(rows, 'Mediamarkt')))
