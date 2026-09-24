import unittest
from datetime import date
from unittest.mock import patch

from apps.common import seg_tv_format
from apps.common.seg_retail import get_seg_format_columns
from apps.dx.dx_layer2 import seg_validation


class SegTvTextFormatTests(unittest.TestCase):
    def check_values(self, retailer, field, valid, invalid):
        for value, expected in [(v, False) for v in valid] + [(v, True) for v in invalid]:
            with self.subTest(retailer=retailer, field=field, value=value):
                errors = seg_validation.evaluate_format_row({field: value}, 'seg_tv', retailer)
                self.assertEqual(expected, field in errors)

    def test_mediamarkt_all_fields(self):
        self.check_values('Mediamarkt', 'sku_status', ['Sponsored'], ['sponsored', 'Sponsorrr'])
        self.check_values('Mediamarkt', 'discount_type',
            ['Incl. streaming content', 'Our own brand', 'Price champion', 'Also for business customers',
             'Our own brand ||| Also for business customers'],
            ['Our own brand ||| unknown', 'Our own brand ||| ', 'Deal & Win', 'Our own brand | Price champion'])
        self.check_values('Mediamarkt', 'delivery_availability',
            ['Home delivery from 24.09.2026', 'Home delivery from 29.02.2028', 'Not available for delivery'],
            ['Home delivery from 31.02.2026', 'Home delivery from 29.02.2026',
             'Home delivery from 00.09.2026', 'Home delivery from 24.13.2026',
             'Home delivery from 2026-09-24', 'Home delivery from 24.09.2026 product details'])
        self.check_values('Mediamarkt', 'pick_up_availability',
            ['Available for store pickup', 'Not available for store pickup'], ['Available', 'Pickup tomorrow'])

    def test_otto_all_fields(self):
        self.check_values('OTTO', 'sku_popularity', ['Very popular'], ['Popular', 'Bestseller'])
        self.check_values('OTTO', 'sku_status', ['Sponsored'], ['Sponsored product'])
        self.check_values('OTTO', 'discount_type',
            ['Deal & Win', 'Deal of the week', 'Deal of the month'], ['Limited Time Offer', 'Our own brand'])
        self.check_values('OTTO', 'delivery_availability',
            ['Available - at your door the next working day', 'Available - at your door in 2-3 working days',
             'Available in 2 weeks', 'Available - at your door in 10-12 working days'],
            ['Available - at your door in 5-2 working days', 'Available in 0 weeks',
             'Available - at your door in 0-3 working days', 'Available in -2 weeks', 'Available soon'])

    def test_amazon_quantities_and_inventory_contamination(self):
        self.check_values('Amazon', 'sku_popularity', ['Bestseller', 'Amazons Tipp'], ['Very popular', 'Popular'])
        self.check_values('Amazon', 'number_of_units_purchased_past_month',
            ['50+ gekauft Mal im letzten Monat', '2500+ gekauft Mal im letzten Monat'],
            ['0+ gekauft Mal im letzten Monat', '-5+ gekauft Mal im letzten Monat',
             '50 gekauft Mal im letzten Monat', '50+ bought in past month'])
        self.check_values('Amazon', 'available_quantity_for_purchase',
            ['Nur noch 25 auf Lager', 'Nur noch 3 auf Lager (mehr ist unterwegs).'],
            ['Nur noch 0 auf Lager', 'Nur noch -1 auf Lager', 'Nur noch abc auf Lager', '3'])
        self.check_values('Amazon', 'inventory_status',
            ['In Stock', 'Currently unavailable.', 'Currently out of stock.', 'Only 1 left in stock',
             'Only 20 left in stock (more on the way).', 'Usually ready to ship in 2 to 3 days',
             'Usually ready to ship in 3 to 7 months', 'Gewoehnlich versandfertig in 2 bis 5 Wochen'],
            ['Only 0 left in stock', 'Usually ready to ship in 5 to 2 days',
             'Gewoehnlich versandfertig in 0 bis 5 Wochen',
             'PHILIPS Smart TV 399,00€ FREE delivery Only 1 left in stock In den Einkaufswagen',
             'In Stock product description', 'Currently out of stock. product description'])

    def test_amazon_delivery_variants_and_invalid_dates(self):
        self.check_values('Amazon', 'delivery_availability',
            ['FREE delivery Saturday, September 26th',
             'FREE delivery tomorrow, September 24th. Order within 6 hrs. 44 mins.',
             'FREE delivery September 30th - October 1st for qualifying first order. Order within 12 hrs. 41 mins..',
             'FREE delivery by appointment to a location of your choice October 2nd - October 12th.',
             'delivery for 3€ September 26th - September 29th.',
             'delivery for 5,99 € September 25th - September 26th. Order within 11 hrs. 35 mins..',
             'delivery by appointment to a location of your choice for 19,90 € October 2nd - October 12th.',
             'FREE delivery December 30th - January 2nd', 'FREE delivery February 29th, 2028',
             'delivery Friday, September 25th'],
            ['FREE delivery February 31st', 'FREE delivery February 29th, 2026',
             'FREE delivery September 32nd', 'FREE delivery September 21th',
             'FREE delivery Friday, September 25th. Order within 2 hrs. 60 mins.',
             'FREE delivery soon', 'product name FREE delivery Friday, September 25th',
             'delivery for -3€ September 26th - September 29th.',
             'FREE delivery Friday, September 25th trailing garbage'])
        self.check_values('Amazon', 'fastest_delivery',
            ['Or fastest delivery tomorrow 14:00 - 18:00. Order within 7 hrs.',
             'Or earliest delivery Wednesday, September 30th, 11:00 - 15:00',
             'Or fastest delivery Friday, September 25th',
             'Or fastest delivery September 25th - September 26th. Order within 11 hrs. 41 mins..'],
            ['Or fastest delivery tomorrow 24:00 - 25:00', 'Or fastest delivery tomorrow 18:00 - 14:00',
             'Or fastest delivery tomorrow 14:60 - 18:00', 'Or earliest delivery February 30th',
             'FREE delivery Friday, September 25th', 'Or fastest delivery tomorrow 14:00 - 18:00 extra'])

    def test_empty_fields_and_exact_scope(self):
        for retailer, rules in seg_tv_format.RULES.items():
            for empty in (None, '', '   '):
                row = dict.fromkeys(rules, empty)
                self.assertEqual({}, seg_validation.evaluate_format_row(row, 'seg_tv', retailer))
            fields = set(get_seg_format_columns('seg_tv', retailer))
            self.assertTrue(set(rules) <= fields)
            details = seg_validation.get_format_rule_details('seg_tv', retailer)
            self.assertEqual(len(details), len({r['field'] for r in details}))
            for field in rules:
                self.assertEqual(1, sum(r['field'] == field for r in details))
            for product in ('seg_ref', 'seg_ldy'):
                self.assertEqual({}, seg_tv_format.evaluate(dict.fromkeys(rules, 'bad'), product, retailer))
        self.assertNotIn('sku_status', get_seg_format_columns('seg_tv', 'Amazon'))
        self.assertEqual({}, seg_validation.evaluate_format_row({'sku_status': 'unconfirmed'}, 'seg_tv', 'Amazon'))
        self.assertNotIn('pick_up_availability', get_seg_format_columns('seg_tv', 'OTTO'))
        union = set(get_seg_format_columns('seg_tv'))
        self.assertTrue(all(set(rules) <= union for rules in seg_tv_format.RULES.values()))

    @patch('apps.dx.dx_layer2.seg_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.seg_validation._latest_rows')
    def test_findings_detail_fields_and_review_suppression(self, latest, reviews):
        mapping = {'inspection_date': '2026-09-23', 'source_date': '2026-09-23'}
        row = {'id': 11, 'inventory_status': 'TV price 399 euro Only 1 left in stock'}
        latest.side_effect = lambda _cursor, _day, _source, retailer: ([row] if retailer == 'Amazon' else [], mapping)
        validation = {'tables': []}
        self.assertEqual(1, seg_validation.append_format_stats(None, date(2026, 9, 23), validation, category='seg_tv_retail'))
        detail = seg_validation.format_detail(None, date(2026, 9, 23), 'seg_tv', 'Amazon', days=1)
        self.assertEqual({'inventory_status': 1}, detail['field_counts'])
        self.assertIn('inventory_status', detail['column_names'])
        self.assertIn('inventory_status', detail['editable_cols'])
        self.assertIn('inventory_status', detail['results'][0]['error_details'])
        reviews.return_value = {'11_inventory_status': {'status': 'normal'}}
        self.assertEqual(0, seg_validation.append_format_stats(None, date(2026, 9, 23), {'tables': []}, category='seg_tv_retail'))


if __name__ == '__main__':
    unittest.main()
