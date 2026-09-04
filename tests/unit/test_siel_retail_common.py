import unittest
from datetime import time

from apps.common.siel_retail import (
    SIEL_SOURCE_CONFIG,
    SIEL_TABLE_TO_PRODUCT_LINE,
    display_siel_retailer,
    get_siel_format_editable_columns,
    get_siel_collection_phase,
    get_siel_count_status,
    get_siel_source,
    get_siel_product_line_for_table,
    resolve_siel_table,
)


class SielRetailCommonTests(unittest.TestCase):
    def test_source_allowlist_contains_three_siel_tables(self):
        self.assertEqual(
            ['siel_tv', 'siel_ref', 'siel_ldy'],
            list(SIEL_SOURCE_CONFIG),
        )
        self.assertEqual(
            'dx_siel.dx_siel_tv_retail_com',
            get_siel_source('SIEL_TV')['table_name'],
        )
        self.assertEqual(
            ('Amazon', 'Flipkart'),
            get_siel_source('siel_ldy')['retailers'],
        )
        self.assertEqual(
            'siel_tv',
            SIEL_TABLE_TO_PRODUCT_LINE[
                'dx_siel.dx_siel_tv_retail_com'
            ],
        )
        self.assertEqual(
            'dx_siel.dx_siel_ref_retail_com',
            resolve_siel_table('siel_ref'),
        )
        self.assertEqual(
            'siel_ldy',
            get_siel_product_line_for_table(
                'dx_siel.dx_siel_ldy_retail_com'
            ),
        )

    def test_unknown_product_line_fails_closed(self):
        with self.assertRaises(ValueError):
            get_siel_source('sea_tv')

    def test_format_edit_allowlist_matches_retailer_and_product(self):
        amazon_tv = get_siel_format_editable_columns('siel_tv', 'Amazon')
        flipkart_ref = get_siel_format_editable_columns(
            'siel_ref', 'Flipkart'
        )

        self.assertIn('screen_size', amazon_tv)
        self.assertIn('product_url', amazon_tv)
        self.assertNotIn('count_of_reviews', amazon_tv)
        self.assertIn('count_of_reviews', flipkart_ref)
        self.assertIn('ref_refrigerator_type', flipkart_ref)
        self.assertNotIn('batch_id', amazon_tv)
        self.assertNotIn('crawl_datetime', flipkart_ref)

    def test_collection_finishes_after_kst_0900(self):
        self.assertEqual('collecting', get_siel_collection_phase(time(8, 59)))
        self.assertEqual('collecting', get_siel_collection_phase(time(9, 0)))
        self.assertEqual('complete', get_siel_collection_phase(time(9, 0, 1)))

    def test_completed_count_threshold_is_200(self):
        self.assertEqual('critical', get_siel_count_status(0))
        self.assertEqual('critical', get_siel_count_status(199))
        self.assertEqual('ok', get_siel_count_status(200))
        self.assertEqual('Amazon', display_siel_retailer('amazon'))


if __name__ == '__main__':
    unittest.main()
