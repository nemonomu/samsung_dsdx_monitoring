"""Representative source formats and collection-date boundaries."""

import unittest
from unittest.mock import Mock, patch

from apps.common.source_dates import source_date_value
from apps.dx.dx_layer2 import seib_format_validation as seib
from apps.dx.dx_layer2 import sem_validation as sem


class NewRetailFormatTests(unittest.TestCase):
    def test_seib_product_shapes_and_invalid_present_values(self):
        common = {
            'country': 'SEIB', 'account_name': 'MediaMarkt', 'item': '141692482',
            'product_url': 'https://www.mediamarkt.es/es/product/_tv-141692482.html',
            'crawl_datetime': '2026-10-18T01:09:37.945005+09:00',
            'calendar_week': 'W42', 'count_of_reviews': '160',
            'count_of_star_ratings': '160', 'star_rating': '4.7',
            'final_sku_price': '2.070,00 €', 'original_sku_price': None,
            'savings': None,
        }
        products = {
            'seib_tv': {'screen_size': '65 inches'},
            'seib_ref': {'ref_capacity': '231 L', 'ref_refrigerator_type': 'Single Door'},
            'seib_ldy': {'capacity': '10.5kg, 6kg', 'loading_type': 'Front Load'},
            'seib_ldy_dryer': {'capacity': '8 kg', 'loading_type': None},
        }
        for product, extra in products.items():
            with self.subTest(product=product):
                self.assertEqual([], seib.evaluate_format({**common, **extra}, product))
        invalid = {**common, 'final_sku_price': '2,070.00 €', 'star_rating': '5.1',
                   'count_of_reviews': '-1', 'savings': '101%'}
        self.assertEqual(
            {'final_sku_price', 'star_rating', 'count_of_reviews', 'savings'},
            set(seib.evaluate_format(invalid, 'seib_tv')),
        )

    def test_seib_detail_uses_original_source_day_and_latest_rows(self):
        row = {
            'id': 7, 'batch_id': 'b1', 'item': '141692482',
            'country': 'SEIB', 'account_name': 'MediaMarkt',
            'crawl_datetime': '2026-10-18T23:37:34-04:00',
            'final_sku_price': '2,070.00 €',
        }
        cursor = Mock()
        cursor.fetchall.return_value = []
        mapping = {'inspection_date': '2026-10-18', 'source_date': '2026-10-18',
                   'offset_days': 0}
        with patch.object(seib.seib_null_validation, 'latest_rows', return_value=([row], mapping)) as latest:
            result = seib.format_detail(cursor, '2026-10-18', 'seib_tv_retail', 'MediaMarkt')
        self.assertEqual('2026-10-18', source_date_value(row['crawl_datetime']))
        self.assertEqual('2026-10-18', result['results'][0]['_source_date'])
        self.assertEqual({'final_sku_price': 1}, result['field_counts'])
        self.assertEqual('b1', result['batch_id'])
        latest.assert_called_once()

    def test_sem_homedepot_dryer_reuses_prices_with_kg_capacity(self):
        row = {
            'country': 'SEM', 'account_name': 'HomeDepot', 'item': '126443',
            'crawl_datetime': '2026-10-19T01:00:46+00:00',
            'calendar_week': '2026-W43',
            'product_url': 'https://www.homedepot.com.mx/p/secadora-126443',
            'final_sku_price': '$9,599.00', 'original_sku_price': '$15,479.00',
            'savings': '-37%', 'star_rating': '4.3',
            'count_of_reviews': '378', 'count_of_star_ratings': '378',
            'capacity': '22 kg', 'loading_type': None,
        }
        self.assertEqual([], sem.evaluate_format(row, 'sem_ldy_dryer', 'HomeDepot'))
        self.assertEqual(['capacity'], sem.evaluate_format(
            {**row, 'capacity': '22 L'}, 'sem_ldy_dryer', 'HomeDepot'))
        self.assertIn('loading_type', sem.evaluate_format(
            {**row, 'loading_type': 'Other'}, 'sem_ldy_dryer', 'HomeDepot'))
        fields = {rule['field'] for rule in sem.get_format_rule_details('sem_ldy_dryer', 'HomeDepot')}
        self.assertTrue({'capacity', 'loading_type', 'savings'} <= fields)


if __name__ == '__main__':
    unittest.main()
