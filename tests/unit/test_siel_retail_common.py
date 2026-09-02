import unittest
from datetime import time

from apps.common.siel_retail import (
    SIEL_SOURCE_CONFIG,
    display_siel_retailer,
    get_siel_collection_phase,
    get_siel_count_status,
    get_siel_source,
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

    def test_unknown_product_line_fails_closed(self):
        with self.assertRaises(ValueError):
            get_siel_source('sea_tv')

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
