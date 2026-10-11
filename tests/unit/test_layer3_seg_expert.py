from datetime import date
import unittest
from unittest.mock import Mock, patch

from apps.dx.dx_layer3.cross_field import seg_services as service
from apps.dx.dx_layer3.cross_field import seg_sources as sources
from apps.dx.dx_layer3.data_edit import services as edits


class ExpertCrossfieldTests(unittest.TestCase):
    def test_dryer_summary_and_detail_show_expert_and_allow_existing_review_flow(self):
        keys = ('rating_count_presence', 'review_count_match', 'final_original_price',
                'savings_missing', 'original_missing', 'final_missing', 'savings_rate_match')
        rules = [dict(service.SEG_RULE_SPECS[key], rule_id=i, rule_key=key,
                      detail_code='seg_ldy_dryer_expert_' + key, _retailers=['Expert'],
                      _all_retailers=False) for i, key in enumerate(keys, 1)]
        row = self.row(id=1, item='I1', sku='S1', retailer_sku_name='Dryer',
                       crawl_datetime='2026-10-11T11:00:00+09:00', batch_id='e1',
                       final_sku_price='999,00 €', original_sku_price='1.000,00 €', savings=None)
        with patch.object(service, 'load_active_seg_rules', return_value=rules), \
                patch.object(service, 'load_latest_seg_rows', return_value=[row]), \
                patch.object(service, '_load_normal_corrections', return_value=[]), \
                patch.object(service, 'exclude_page_absent_records', side_effect=lambda c, d, rows, **kw: (rows, [])):
            summary = service.get_seg_cross_field_summary(None, date(2026, 10, 11), 'seg_ldy_dryer')
            self.assertTrue(summary['configured'])
            self.assertEqual('Expert', summary['retailers'][0]['retailer'])
            self.assertEqual(7, len(summary['rule_summary']))
            self.assertEqual(1, summary['total_anomalies'])
            detail = service.get_seg_cross_field_rule_detail(None, date(2026, 10, 11), 'seg_ldy_dryer', 4)
            self.assertIn('savings', detail['editable_columns'])
            self.assertEqual('crawl_datetime', detail['date_col'])
            self.assertIn('Expert', detail['retailer_columns'])

    def row(self, **values):
        return dict(account_name='expert', **values)

    def test_discount_floor_and_missing_without_ten_percent_threshold(self):
        for savings, mismatch in [('18%', False), ('19%', True), ('18.5%', True)]:
            errors = service.evaluate_seg_row(self.row(final_sku_price='589,00 €',
                original_sku_price='719,00 €', savings=savings))
            self.assertEqual(mismatch, 'savings_rate_match' in errors)
        for final in ('999,00 €', '900,00 €', '1.000,00 €', '1.100,00 €'):
            errors = service.evaluate_seg_row(self.row(final_sku_price=final,
                original_sku_price='1.000,00 €', savings=None))
            self.assertIn('savings_missing', errors)
        self.assertNotIn('savings_rate_match', service.evaluate_seg_row(self.row(
            final_sku_price='0,00 €', original_sku_price='0,00 €', savings='0%')))

    def test_review_counts_and_zero_pairs(self):
        errors = service.evaluate_seg_row(self.row(star_rating='4.5', count_of_star_ratings='2', count_of_reviews='0'))
        self.assertTrue({'review_count_match', 'rating_count_presence'} <= errors)
        self.assertEqual(set(), service.evaluate_seg_row(self.row(
            star_rating='0', count_of_star_ratings='0', count_of_reviews='0')))

    def test_dryer_latest_batch_uses_actual_columns_and_start_date(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        service.load_latest_seg_rows(cursor, date(2026, 10, 11), 'seg_ldy_dryer')
        sql = cursor.execute.call_args.args[0]
        self.assertIn('crawl_datetime', sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('crawl_strdatetime', sql)
        self.assertIn('2026-10-11', sql)
        self.assertIn('latest.batch_id IS NOT DISTINCT FROM source.batch_id', sql)
        cursor.reset_mock()
        self.assertEqual([], service.load_latest_seg_rows(cursor, date(2026, 10, 10), 'seg_ldy_dryer'))
        cursor.execute.assert_not_called()

    def test_edit_scope_and_columns_use_expert_contract(self):
        columns = sources.get_seg_crossfield_editable_columns('seg_ldy_dryer', 'expert')
        self.assertIn('count_of_reviews', columns)
        self.assertNotIn('page_type', columns)
        self.assertNotIn('detailed_review_content', columns)
        cursor = Mock()
        edits._select_seg_record(cursor, sources.get_seg_source('seg_ldy_dryer'),
                                 'final_sku_price, account_name, item', 1, date(2026, 10, 11))
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])

    def test_expert_copy_query_preserves_item_case_and_uses_lowercase_account(self):
        sql = service.build_seg_display_query(date(2026, 10, 11), 'seg_ldy_dryer',
                {'rule_key': 'final_original_price'}, retailer_item_pairs=[('Expert', 'Expert')])
        self.assertIn("account_name = 'expert'", sql)
        self.assertIn("item IN ('Expert')", sql)
        self.assertIn('crawl_datetime', sql)

    def test_expert_no_page_or_review_body_rules(self):
        for rule in ('rank_page_type', 'review_body_count', 'review_body_decrease', 'rating_range'):
            self.assertFalse(service._retailer_supported(rule, 'Expert'))
        for rule in ('rating_count_presence', 'review_count_match', 'final_original_price'):
            self.assertTrue(service._retailer_supported(rule, 'expert'))
