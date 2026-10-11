import unittest
from datetime import date
from unittest.mock import patch

from apps.dx.dx_layer2 import seg_expert_format as rules, seg_validation as seg
from apps.dx.dx_layer2.seg_sources import get_seg_format_columns
from apps.dx.dx_layer2.data_edit.services import _get_seg_edit_context


class ExpertFormatTests(unittest.TestCase):
    def test_populated_formats_and_null_separation(self):
        row = dict(final_sku_price='1.299,00 €', original_sku_price=None,
                   savings='4%', star_rating='0.0', count_of_reviews='0',
                   count_of_star_ratings='1234', product_url='https://www.expert.de/a',
                   capacity='2.5 kg', loading_type='Front Load')
        self.assertEqual({}, seg.evaluate_format_row(row, 'seg_ldy_dryer', 'Expert'))
        for field, value in dict(final_sku_price='1,299.00 €', savings='4.6%',
                                 star_rating='5.1', count_of_reviews='-1',
                                 product_url='https://', capacity='8 L',
                                 loading_type='invalid').items():
            with self.subTest(field=field):
                self.assertIn(field, seg.evaluate_format_row(
                    {**row, field: value}, 'seg_ldy_dryer', 'expert'))
        self.assertEqual({}, rules.evaluate(dict.fromkeys(row, ' '), 'seg_ldy_dryer'))
        self.assertEqual({}, rules.evaluate({'item': 'any', 'sku': 'abc'}, 'seg_tv'))
        unavailable = 'Artikel ist derzeit nicht verfügbar'
        self.assertEqual({'original_sku_price'}, set(rules.evaluate(
            {'final_sku_price': unavailable, 'original_sku_price': unavailable}, 'seg_ldy')))

    def test_product_rules_and_editable_columns(self):
        samples = {'seg_tv': {'screen_size': '55 inch'},
                   'seg_ref': {'ref_capacity': '136 L', 'ref_refrigerator_type': 'Mini Refrigerator'},
                   'seg_ldy': {'ldy_capacity': '7.5 kg', 'ldy_loading_type': 'Top Load'},
                   'seg_ldy_dryer': {'capacity': '8 kg', 'loading_type': 'Front Load'}}
        for product, row in samples.items():
            self.assertEqual({}, rules.evaluate(row, product))
            self.assertEqual(set(get_seg_format_columns(product, 'Expert')),
                             {r['field'] for r in seg.get_format_rule_details(product, 'Expert')})
        editable = _get_seg_edit_context('dx_seg.dx_seg_ldy_dryer_retail')['max_editable']
        self.assertTrue({'original_sku_price', 'savings', 'capacity', 'loading_type'} <= editable)

    def test_dryer_detail_stats_and_start_date(self):
        row = {'id': 1, 'item': 'I1', 'account_name': 'expert', 'capacity': '8 L'}
        mapping = {'inspection_date': '2026-10-11', 'source_date': '2026-10-11', 'batch_id': 'e1'}
        with patch.object(seg, '_latest_rows', return_value=([row], mapping)), \
                patch.object(seg, '_load_normal_reviews', return_value={}):
            detail = seg.format_detail(None, date(2026, 10, 11), 'seg_ldy_dryer_retail', 'Expert', 1)
            self.assertEqual({'capacity': 1}, detail['field_counts'])
            self.assertEqual('crawl_datetime', detail['date_column'])
            self.assertFalse(detail['readonly'])
            stats = {'tables': []}
            self.assertEqual(1, seg.append_format_stats(None, date(2026, 10, 11), stats, 'seg_ldy_dryer_retail'))
            self.assertEqual('Expert', stats['tables'][0]['retailers'][0]['retailer'])
            stats = {'tables': []}
            self.assertEqual(0, seg.append_format_stats(None, date(2026, 10, 10), stats, 'seg_ldy_dryer_retail'))
            self.assertEqual([], stats['tables'])
