import unittest
from datetime import time

from apps.common.tse_retail import (
    get_tse_collection_phase,
    get_tse_count_status,
    get_tse_editable_columns,
    get_tse_required_columns,
    get_tse_product_line_for_table,
    resolve_tse_table,
    validate_tse_editable_column,
)


class TseRetailCommonTests(unittest.TestCase):
    def test_resolves_only_known_tse_tables(self):
        table_name = 'dx_tse.dx_tse_tv_retail_com'
        self.assertEqual(resolve_tse_table('tse_tv'), table_name)
        self.assertEqual(resolve_tse_table(table_name), table_name)
        self.assertEqual(get_tse_product_line_for_table(table_name), 'tse_tv')

        with self.assertRaises(ValueError):
            resolve_tse_table('dx_tse.unapproved_table')

    def test_required_columns_are_product_specific(self):
        self.assertIn('screen_size', get_tse_required_columns('tse_tv'))
        self.assertIn('ref_capacity', get_tse_required_columns('tse_ref'))
        self.assertIn('ldy_capacity', get_tse_required_columns('tse_ldy'))
        self.assertNotIn('ref_refrigerator_type', get_tse_required_columns('tse_ref'))
        self.assertNotIn('ldy_loading_type', get_tse_required_columns('tse_ldy'))

    def test_edit_only_price_columns_are_not_null_requirements(self):
        self.assertNotIn('original_sku_price', get_tse_required_columns('tse_tv'))
        self.assertNotIn('savings', get_tse_required_columns('tse_tv'))
        self.assertIn('original_sku_price', get_tse_editable_columns('tse_tv'))
        self.assertIn('savings', get_tse_editable_columns('tse_tv'))

    def test_rejects_system_column_edits(self):
        self.assertEqual(
            validate_tse_editable_column('tse_tv', 'final_sku_price'),
            'final_sku_price',
        )
        for column in ('id', 'batch_id', 'crawl_datetime', 'calendar_week'):
            with self.assertRaises(ValueError):
                validate_tse_editable_column('tse_tv', column)

    def test_collection_phase_uses_rdp_time_boundaries(self):
        self.assertEqual(get_tse_collection_phase(time(8, 59, 59)), 'pending')
        self.assertEqual(get_tse_collection_phase(time(9, 0)), 'collecting')
        self.assertEqual(get_tse_collection_phase(time(9, 30)), 'collecting')
        self.assertEqual(get_tse_collection_phase(time(9, 30, 1)), 'complete')

    def test_count_status_boundaries(self):
        self.assertEqual(get_tse_count_status(300), 'ok')
        self.assertEqual(get_tse_count_status(299), 'warning')
        self.assertEqual(get_tse_count_status(200), 'warning')
        self.assertEqual(get_tse_count_status(199), 'critical')

if __name__ == '__main__':
    unittest.main()
