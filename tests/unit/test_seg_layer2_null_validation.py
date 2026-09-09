import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.common.seg_retail import (
    SEG_NULL_COLUMNS,
    get_seg_null_columns,
)
from apps.dx.dx_layer2 import seg_validation
from apps.dx.dx_layer2.data_edit import services as data_edit_services
from apps.dx.dx_layer2.null_validation import services as null_services
from tests.unit.support import ScriptedCursor


SEG_TV_TABLE = 'dx_seg.dx_seg_tv_retail_com'


class SegNullPolicyTests(unittest.TestCase):
    def test_exact_retailer_product_matrix_has_51_checks(self):
        configured = sum(
            len(columns)
            for retailer_columns in SEG_NULL_COLUMNS.values()
            for columns in retailer_columns.values()
        )

        self.assertEqual(51, configured)
        self.assertNotIn('sku', get_seg_null_columns('seg_tv', 'Mediamarkt'))
        self.assertIn('sku', get_seg_null_columns('seg_tv', 'OTTO'))
        self.assertNotIn('count_of_reviews', get_seg_null_columns('seg_tv', 'Amazon'))
        self.assertEqual((), get_seg_null_columns('seg_ldy', 'Amazon'))

    def test_amazon_latest_batch_scope_excludes_redirect_rows(self):
        source = seg_validation.SEG_SOURCE_CONFIG['seg_tv']
        columns = [('id',), ('account_name',), ('redirect',), ('batch_id',)]
        cursor = ScriptedCursor([
            {'fetchone': ('batch-1',)},
            {
                'description': columns,
                'fetchall': [(1, 'Amazon', False, 'batch-1')],
            },
        ])

        rows, mapping = seg_validation._latest_rows(
            cursor, date(2026, 9, 9), source, 'Amazon'
        )

        self.assertEqual([1], [row['id'] for row in rows])
        self.assertEqual('batch-1', mapping['batch_id'])
        self.assertIn('anchor.redirect IS NOT TRUE', cursor.calls[0][0])
        self.assertIn('source.redirect IS NOT TRUE', cursor.calls[1][0])
        self.assertIn("IN ('main', 'bsr')", cursor.calls[1][0])

    @patch('apps.dx.dx_layer2.seg_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.seg_validation._history_rows')
    @patch('apps.dx.dx_layer2.seg_validation._latest_rows')
    def test_detail_defaults_to_three_days_and_only_exposes_retailer_columns(
            self, latest_rows, history_rows, _normal_reviews):
        mapping = {
            'inspection_date': '2026-09-09',
            'source_date': '2026-09-09',
            'offset_days': 0,
            'country': 'SEG',
            'source_key': 'seg_tv',
            'batch_id': 'batch-1',
        }
        latest_rows.return_value = ([{
            'id': 3,
            'item': 'item-1',
            'account_name': 'Mediamarkt',
            'screen_size': None,
            'crawl_strdatetime': '2026-09-09 10:00:00',
        }], mapping)
        history_rows.return_value = [
            {
                'id': day,
                'item': 'item-1',
                'account_name': 'Mediamarkt',
                'screen_size': value,
                'crawl_strdatetime': f'2026-09-0{day} 10:00:00',
            }
            for day, value in ((7, '55'), (8, '55'), (9, None))
        ]

        result = seg_validation.null_detail(
            None, date(2026, 9, 9), 'seg_tv_retail',
            'Mediamarkt', 'screen_size', days=3,
        )

        self.assertEqual(3, result['history_days'])
        self.assertEqual([7, 8, 9], [row['id'] for row in result['results']])
        self.assertTrue(result['supports_day_history'])
        self.assertIn('screen_size', result['editable_cols'])
        self.assertNotIn('sku', result['editable_cols'])
        args = history_rows.call_args.args
        self.assertEqual(date(2026, 9, 7), args[3])
        self.assertEqual(date(2026, 9, 9), args[4])


class SegLayer2DataEditTests(unittest.TestCase):
    def test_null_cell_update_is_scoped_and_retailer_allowlisted(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Amazon', 'item-1', 'batch-1')},
            {},
            {},
        ])
        conn = Mock()

        result = data_edit_services.update_cell_value(
            cursor, conn, SEG_TV_TABLE, 11, 'sku', 'SKU-1',
            date(2026, 9, 9), 'null', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        self.assertIn(SEG_TV_TABLE, data_edit_services.VALID_TABLES_UPDATE)
        self.assertIn('source.redirect IS TRUE', cursor.calls[0][0])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', cursor.calls[0][0])
        self.assertIn(f'UPDATE {SEG_TV_TABLE} SET sku = %s', cursor.calls[1][0])

    def test_column_not_configured_for_actual_retailer_is_rejected(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Mediamarkt', 'item-1', 'batch-1')},
        ])

        result = data_edit_services.update_cell_value(
            cursor, Mock(), SEG_TV_TABLE, 11, 'sku', 'SKU-1',
            date(2026, 9, 9), 'null', 'tester', 'fixed',
        )

        self.assertEqual(403, result['status'])
        self.assertEqual(1, len(cursor.calls))

    def test_normal_review_uses_the_same_seg_scope(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Amazon', 'item-1')},
            {'fetchone': None},
            {},
        ])
        conn = Mock()

        result = null_services.save_null_review(
            cursor, conn, SEG_TV_TABLE, 11, 'sku', 'normal', '',
            '확인 완료', date(2026, 9, 9), 'null', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertIn('source.redirect IS TRUE', cursor.calls[0][0])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', cursor.calls[0][0])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        conn.commit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
