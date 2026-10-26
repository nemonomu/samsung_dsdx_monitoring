import unittest
from datetime import date
from unittest.mock import Mock, patch

from django.test import override_settings
from apps.dx.dx_layer2 import seg_sources as config, seg_validation as layer2
from apps.dx.dx_layer3.cross_field import seg_services as cross, seg_sources
from apps.dx.dx_layer3.data_edit import services as edits
from apps.dx.dx_layer1.management.commands.setup_seg_mediamarkt_dryer_validation import register_rules, RULE_KEYS

KEY = 'seg_ldy_dryer'
DAY = date(2026, 10, 25)


class MediamarktDryerValidationTests(unittest.TestCase):
    def row(self, **values):
        return dict(dict(id=1, account_name='Mediamarkt', item='I1', sku='S1',
                         retailer_sku_name='Dryer', final_sku_price='899,– €',
                         original_sku_price='1.000,– €', savings='10%',
                         star_rating='4.8', count_of_reviews='27', count_of_star_ratings='27',
                         main_rank=1, bsr_rank=1, calendar_week='w43', capacity='8kg',
                         loading_type='Front load', crawl_datetime='2026-10-25T23:59:59-04:00',
                         batch_id='m1'), **values)

    def test_format_has_exactly_eleven_actual_columns_and_existing_boundaries(self):
        fields = {'final_sku_price', 'original_sku_price', 'savings', 'star_rating',
                  'count_of_reviews', 'count_of_star_ratings', 'main_rank', 'bsr_rank',
                  'calendar_week', 'capacity', 'loading_type'}
        self.assertEqual(fields, set(config.get_seg_format_columns(KEY, 'Mediamarkt')))
        self.assertEqual(fields, {r['field'] for r in layer2.get_format_rule_details(KEY, 'Mediamarkt')})
        cases = {'capacity': ('10,5 kg', '8 lb'), 'loading_type': ('TOP LOAD', 'Side load'),
                 'calendar_week': ('w53', 'w54'), 'star_rating': ('5.0', '5.1'),
                 'count_of_reviews': ('1,018', '-1'), 'bsr_rank': (100, 0),
                 'savings': ('-10%', '10.5%')}
        for field, (good, bad) in cases.items():
            self.assertEqual({}, layer2.evaluate_format_row(self.row(**{field: good}), KEY, 'Mediamarkt'))
            self.assertEqual({field}, set(layer2.evaluate_format_row(self.row(**{field: bad}), KEY, 'Mediamarkt')))
        self.assertEqual({}, layer2.evaluate_format_row(dict.fromkeys(fields, ' '), KEY, 'Mediamarkt'))
        self.assertEqual({'final_sku_price'}, set(layer2.evaluate_format_row(
            self.row(final_sku_price='Artikel ist derzeit nicht verfügbar'), KEY, 'Mediamarkt')))

    def test_duplicate_item_not_sku_and_legacy_page_scope_unchanged(self):
        first = self.row()
        self.assertEqual([], layer2.build_duplicate_groups([first], 'Mediamarkt', KEY))
        self.assertEqual([], layer2.build_duplicate_groups([first, self.row(id=2, item='I2')], 'Mediamarkt', KEY))
        groups = layer2.build_duplicate_groups([first, self.row(id=2, final_sku_price='799,99 €')], 'Mediamarkt', KEY)
        self.assertEqual('동일 상품 중복', groups[0]['duplicate_type'])
        conflict = layer2.build_duplicate_groups([first, self.row(id=2, sku='S2')], 'Mediamarkt', KEY)
        self.assertEqual('상품 매핑 충돌', conflict[0]['duplicate_type'])
        self.assertEqual([], layer2.build_duplicate_groups([first, self.row(id=2)], 'Mediamarkt', 'seg_ldy'))
        self.assertEqual([], layer2.build_duplicate_groups([self.row(item=None), self.row(item=' ')], 'Mediamarkt', KEY))
        mapping = dict(source_date=str(DAY), inspection_date=str(DAY), batch_id='m1')
        with patch.object(layer2, '_latest_rows', return_value=([first, self.row(id=2)], mapping)):
            detail = layer2.duplicate_detail(None, DAY, KEY, 'Mediamarkt')
        self.assertEqual(1, detail['results']['total_groups'])
        self.assertNotIn('page_type', detail['select_cols']['group'])
        self.assertFalse(detail['allow_cleanup'])

    def test_six_crossfield_rules_and_ten_percent_boundary(self):
        self.assertEqual(set(), cross.evaluate_seg_row(self.row(), KEY))
        cases = [({'star_rating': '0'}, {'rating_count_presence'}),
                 ({'count_of_reviews': '26'}, {'review_count_match'}),
                 ({'final_sku_price': '1.000,– €'}, {'final_original_price'}),
                 ({'final_sku_price': '900,– €', 'savings': None}, set()),
                 ({'final_sku_price': '899,99 €', 'savings': None}, {'savings_missing'}),
                 ({'original_sku_price': None}, {'original_missing'}),
                 ({'final_sku_price': None}, {'final_missing'}),
                 ({'star_rating': '0', 'count_of_reviews': '0', 'count_of_star_ratings': '0'}, set())]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(expected, cross.evaluate_seg_row(self.row(**values), KEY))
        self.assertIsNone(cross.parse_seg_money('1.000,– €'))  # Existing products unchanged.

    def test_rule_loader_rejects_absent_columns_and_retains_six_rules(self):
        cursor = Mock()
        cursor.fetchall.return_value = [dict(id=i, detail_code='seg_ldy_dryer_mediamarkt_' + key,
            validation_type=key, retailer='Mediamarkt', select_fields='')
            for i, key in enumerate((*RULE_KEYS, 'review_body_count', 'review_body_decrease', 'rank_page_type'), 1)]
        rules = cross.load_active_seg_rules(cursor, KEY)
        self.assertEqual(set(RULE_KEYS), {r['rule_key'] for r in rules})
        with patch.object(cross, 'load_active_seg_rules', return_value=rules), \
                patch.object(cross, 'load_latest_seg_rows', return_value=[self.row()]), \
                patch.object(cross, 'load_seg_review_history', side_effect=AssertionError('No dryer review bodies')), \
                patch.object(cross, '_load_normal_corrections', return_value=[]), \
                patch.object(cross, 'exclude_page_absent_records', side_effect=lambda c, d, rows, **kw: (rows, [])):
            summary = cross.get_seg_cross_field_summary(None, DAY, KEY)
            detail = cross.get_seg_cross_field_rule_detail(None, DAY, KEY, rules[0]['rule_id'])
        self.assertEqual(6, len(summary['rule_summary']))
        self.assertEqual(0, summary['total_anomalies'])
        self.assertTrue(detail['found'])

    def test_crossfield_date_and_edit_scopes_use_real_schema(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        cross.load_latest_seg_rows(cursor, DAY, KEY, from_date=date(2026, 10, 24))
        sql = cursor.execute.call_args.args[0]
        self.assertIn("<> 'mediamarkt'", sql)
        self.assertIn("'2026-10-25'", sql)
        self.assertNotIn('page_type', sql)
        self.assertNotIn('detailed_review_content', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertEqual([*seg_sources.EXPERT_EDITABLE, 'savings'],
                         seg_sources.get_seg_crossfield_editable_columns(KEY, 'Mediamarkt'))
        edits._select_seg_record(cursor, seg_sources.get_seg_source(KEY), 'savings, account_name, item', 1, DAY)
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])

    def test_registration_matches_seg_metadata_registry_and_is_retailer_scoped(self):
        for debug in (True, False):
            cursor = Mock()
            cursor.fetchall.return_value = [(key, 1) for key in RULE_KEYS]
            with override_settings(DEBUG=debug):
                self.assertEqual(dict.fromkeys(RULE_KEYS, 1), register_rules(cursor))
            for call in cursor.execute.call_args_list:
                sql = call.args[0]
                self.assertIn('public.monitoring_validation_rules', sql)
                self.assertIn("LOWER(BTRIM(retailer))='mediamarkt'", sql)
                self.assertNotIn('UPDATE dx_seg.', sql)
