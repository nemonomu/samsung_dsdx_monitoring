import unittest
from datetime import time

from apps.common.tse_retail import (
    TSE_LOTUSS_CRITICAL_DEVIATION,
    TSE_LOTUSS_HISTORY_DAYS,
    display_tse_retailer,
    get_tse_crossfield_rule_keys,
    get_tse_collection_phase,
    get_tse_count_status,
    get_tse_editable_columns,
    get_tse_format_fields,
    get_tse_required_columns,
    get_tse_product_line_for_table,
    resolve_tse_table,
    tse_crossfield_rule_supported,
    tse_retailer_include_unassigned,
    tse_retailer_supports_column,
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

    def test_collection_phase_uses_kst_1100_completion_boundary(self):
        self.assertEqual(get_tse_collection_phase(time(8, 59, 59)), 'pending')
        self.assertEqual(get_tse_collection_phase(time(9, 0)), 'collecting')
        self.assertEqual(get_tse_collection_phase(time(10, 59, 59)), 'collecting')
        self.assertEqual(get_tse_collection_phase(time(11, 0)), 'collecting')
        self.assertEqual(get_tse_collection_phase(time(11, 0, 1)), 'complete')

    def test_count_status_boundaries(self):
        self.assertEqual(get_tse_count_status(300), 'ok')
        self.assertEqual(get_tse_count_status(299), 'ok')
        self.assertEqual(get_tse_count_status(200), 'ok')
        self.assertEqual(get_tse_count_status(199), 'critical')

    def test_lotuss_history_policy_constants_and_display_name(self):
        self.assertEqual(7, TSE_LOTUSS_HISTORY_DAYS)
        self.assertEqual(20, TSE_LOTUSS_CRITICAL_DEVIATION)
        self.assertEqual('Lotuss', display_tse_retailer('lotuss'))
        self.assertEqual('Lotuss', display_tse_retailer('LOTUSS'))
        self.assertEqual('Lazada', display_tse_retailer('lazada'))
        self.assertEqual('Lazada', display_tse_retailer('LAZADA'))

    def test_retailer_policy_is_not_based_on_config_count(self):
        self.assertFalse(tse_retailer_include_unassigned('Homepro'))
        self.assertFalse(tse_retailer_include_unassigned('Lotuss'))
        self.assertFalse(tse_retailer_include_unassigned('Lazada'))

    def test_lazada_format_and_crossfield_policy_matches_csv_contract(self):
        self.assertNotIn(
            'item', get_tse_format_fields('tse_tv', 'Lazada')
        )
        self.assertIn(
            'screen_size', get_tse_format_fields('tse_tv', 'Lazada')
        )
        self.assertIn(
            'ref_refrigerator_type',
            get_tse_format_fields('tse_ref', 'Lazada'),
        )
        self.assertIn(
            'ldy_loading_type',
            get_tse_format_fields('tse_ldy', 'Lazada'),
        )
        self.assertTrue(tse_crossfield_rule_supported(
            'tse_tv', 'Lazada', 'review_count_match'
        ))
        self.assertTrue(tse_crossfield_rule_supported(
            'tse_tv', 'Lazada', 'review_zero_pair'
        ))
        self.assertTrue(tse_crossfield_rule_supported(
            'tse_tv', 'Lazada', 'savings_rate_match'
        ))

    def test_lotuss_column_and_format_capabilities_are_product_specific(self):
        self.assertFalse(tse_retailer_supports_column(
            'tse_tv', 'Lotuss', 'count_of_reviews'
        ))
        self.assertTrue(tse_retailer_supports_column(
            'tse_tv', 'Lotuss', 'original_sku_price'
        ))
        self.assertFalse(tse_retailer_supports_column(
            'tse_ref', 'Lotuss', 'original_sku_price'
        ))
        self.assertIn(
            'ref_capacity', get_tse_format_fields('tse_ref', 'Lotuss')
        )
        self.assertNotIn(
            'count_of_reviews', get_tse_format_fields('tse_ref', 'Lotuss')
        )

    def test_lotuss_crossfield_capability_excludes_review_rules(self):
        tv_rules = get_tse_crossfield_rule_keys('tse_tv', 'Lotuss')
        self.assertIn('savings_rate_match', tv_rules)
        self.assertNotIn('review_count_match', tv_rules)
        self.assertEqual(
            frozenset(),
            get_tse_crossfield_rule_keys('tse_ref', 'Lotuss'),
        )
        self.assertFalse(tse_crossfield_rule_supported(
            'tse_ldy', 'Lotuss', 'savings_format'
        ))
        self.assertTrue(tse_crossfield_rule_supported(
            'tse_ref', 'Homepro', 'review_count_match'
        ))

if __name__ == '__main__':
    unittest.main()
