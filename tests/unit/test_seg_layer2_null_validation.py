import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.common.seg_retail import (
    SEG_NULL_COLUMNS,
    get_seg_format_columns,
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


class SegDuplicateValidationTests(unittest.TestCase):
    def test_only_otto_separates_option_skus_and_keeps_repeated_skus(self):
        rows = [
            {'id': 1, 'page_type': 'main', 'item': 'item-1',
             'sku': 'SKU-1', 'retailer_sku_name': 'Option 1'},
            {'id': 2, 'page_type': 'main', 'item': 'item-1',
             'sku': 'SKU-2', 'retailer_sku_name': 'Option 2'},
        ]
        self.assertEqual([], seg_validation.build_duplicate_groups(rows, 'OTTO'))
        for retailer in ('Amazon', 'Mediamarkt'):
            with self.subTest(retailer=retailer):
                groups = seg_validation.build_duplicate_groups(rows, retailer)
                self.assertEqual(1, len(groups))
                self.assertEqual('상품 매핑 충돌', groups[0]['duplicate_type'])

        rows.extend([
            {'id': 3, 'page_type': ' MAIN ', 'item': ' ITEM-1 ',
             'sku': ' sku-1 ', 'retailer_sku_name': 'Option 1'},
            {'id': 4, 'page_type': 'bsr', 'item': 'item-1',
             'sku': 'SKU-1', 'retailer_sku_name': 'Option 1'},
        ])
        groups = seg_validation.build_duplicate_groups(rows, ' otto ')
        self.assertEqual(1, len(groups))
        self.assertEqual([1, 3], [row['id'] for row in groups[0]['records']])
        self.assertEqual('완전 중복', groups[0]['duplicate_type'])
        rows[2]['retailer_sku_name'] = 'Changed name'
        groups = seg_validation.build_duplicate_groups(rows, 'OTTO')
        self.assertEqual('상품 매핑 충돌', groups[0]['duplicate_type'])

    @patch('apps.dx.dx_layer2.seg_validation._latest_rows')
    def test_otto_option_policy_is_used_by_stats_and_detail(self, latest_rows):
        rows = [
            {'id': 1, 'page_type': 'main', 'item': 'item-1', 'sku': 'SKU-1'},
            {'id': 2, 'page_type': 'main', 'item': 'item-1', 'sku': 'SKU-2'},
        ]
        latest_rows.return_value = (rows, {'inspection_date': '2026-09-09'})
        for product_line in ('seg_tv', 'seg_ref', 'seg_ldy'):
            with self.subTest(product_line=product_line):
                result = seg_validation.duplicate_detail(
                    None, date(2026, 9, 9), product_line, 'OTTO',
                )
                self.assertEqual(0, result['results']['total_groups'])
                self.assertTrue(result['readonly'])
        validation = {'tables': []}
        seg_validation.append_duplicate_stats(None, date(2026, 9, 9), validation)
        for table in validation['tables']:
            for retailer in table['retailers']:
                with self.subTest(table=table['table'], retailer=retailer['retailer']):
                    is_otto = retailer['retailer'] == 'OTTO'
                    self.assertEqual(0 if is_otto else 1, retailer['duplicate_groups'])
                    self.assertEqual('OK' if is_otto else 'CRITICAL', retailer['status'])
                    self.assertEqual(
                        ['page_type + item + sku' if is_otto else 'page_type + item'],
                        retailer['duplicate_keys'],
                    )

    def test_groups_within_page_type_and_classifies_mapping_conflicts(self):
        rows = [
            {
                'id': 1, 'page_type': 'main', 'item': 'item-1',
                'sku': 'SKU-1', 'retailer_sku_name': 'Name 1',
            },
            {
                'id': 2, 'page_type': 'MAIN', 'item': 'item-1',
                'sku': 'SKU-2', 'retailer_sku_name': 'Name 2',
            },
            {
                'id': 3, 'page_type': 'bsr', 'item': 'item-1',
                'sku': 'SKU-1', 'retailer_sku_name': 'Name 1',
            },
            {
                'id': 4, 'page_type': 'main', 'item': 'item-2',
                'sku': 'SKU-3', 'retailer_sku_name': 'Name 3',
            },
            {
                'id': 5, 'page_type': 'main', 'item': 'item-2',
                'sku': 'SKU-3', 'retailer_sku_name': 'Name 3',
            },
        ]

        groups = seg_validation.build_duplicate_groups(rows)

        self.assertEqual(2, len(groups))
        self.assertEqual('상품 매핑 충돌', groups[0]['duplicate_type'])
        self.assertEqual('MAIN', groups[0]['page_type'])
        self.assertEqual([1, 2], [row['id'] for row in groups[0]['records']])
        self.assertEqual('완전 중복', groups[1]['duplicate_type'])
        self.assertEqual([4, 5], [row['id'] for row in groups[1]['records']])

    @patch('apps.dx.dx_layer2.seg_validation._latest_rows')
    def test_detail_is_latest_batch_readonly_and_uses_page_type_item_key(
            self, latest_rows):
        latest_rows.return_value = ([
            {
                'id': 1, 'page_type': 'main', 'item': 'item-1',
                'sku': 'SKU-1', 'retailer_sku_name': 'Name 1',
            },
            {
                'id': 2, 'page_type': 'main', 'item': 'item-1',
                'sku': 'SKU-1', 'retailer_sku_name': 'Name 1',
            },
        ], {
            'inspection_date': '2026-09-09',
            'source_date': '2026-09-09',
            'offset_days': 0,
            'country': 'SEG',
            'source_key': 'seg_tv',
            'batch_id': 'batch-1',
        })

        result = seg_validation.duplicate_detail(
            None, date(2026, 9, 9), 'seg_tv_retail', 'Amazon'
        )

        self.assertTrue(result['readonly'])
        self.assertEqual([], result['editable_cols'])
        self.assertEqual(1, result['results']['total_groups'])
        self.assertIn('page_type', result['select_cols']['group'])
        self.assertIn('crawl_strdatetime', result['select_cols']['record'])
        source = seg_validation.SEG_SOURCE_CONFIG['seg_tv']
        latest_rows.assert_called_once_with(
            None, date(2026, 9, 9), source, 'Amazon'
        )


class SegFormatValidationTests(unittest.TestCase):
    def test_requested_context_fields_are_not_format_rules(self):
        fields = set(get_seg_format_columns('seg_tv', 'Amazon'))

        self.assertTrue({'final_sku_price', 'screen_size'} <= fields)
        self.assertTrue({
            'product_url', 'redirect', 'crawl_strdatetime', 'batch_id',
            'country', 'product', 'account_name', 'page_type',
        }.isdisjoint(fields))

    def test_approved_amazon_text_values_are_normal(self):
        for price in (
            'Höherer Preis als üblich', 'Derzeit nicht verfügbar.',
            'Derzeit nicht auf Lager.',
        ):
            with self.subTest(price=price):
                errors = seg_validation.evaluate_format_row({
                    'final_sku_price': price,
                    'star_rating': 'No customer reviews',
                    'count_of_star_ratings': '0',
                    'main_rank': '1',
                    'calendar_week': 'w33',
                    'screen_size': '55 inches',
                }, 'seg_tv', 'Amazon')
                self.assertEqual({}, errors)

        self.assertIn(
            'final_sku_price',
            seg_validation.evaluate_format_row({
                'final_sku_price': 'Höherer Preis als üblich',
            }, 'seg_tv', 'Mediamarkt'),
        )

    def test_amazon_unavailable_price_status_scope(self):
        for product_line in ('seg_tv', 'seg_ref', 'seg_ldy'):
            with self.subTest(product_line=product_line):
                self.assertNotIn(
                    'final_sku_price',
                    seg_validation.evaluate_format_row(
                        {'final_sku_price': 'Derzeit nicht auf Lager.'},
                        product_line, 'Amazon',
                    ),
                )
                self.assertIn(
                    'final_sku_price',
                    seg_validation.evaluate_format_row(
                        {'final_sku_price': 'Keine hervorgehobenen Angebote verfügbar'},
                        product_line, 'Amazon',
                    ),
                )

        for retailer in ('Mediamarkt', 'OTTO'):
            with self.subTest(retailer=retailer):
                self.assertIn(
                    'final_sku_price',
                    seg_validation.evaluate_format_row(
                        {'final_sku_price': 'Derzeit nicht auf Lager.'},
                        'seg_ref', retailer,
                    ),
                )
        self.assertIn(
            'original_sku_price',
            seg_validation.evaluate_format_row(
                {'original_sku_price': 'Derzeit nicht auf Lager.'},
                'seg_ref', 'Amazon',
            ),
        )

    def test_ref_capacity_accepts_german_cubic_feet_with_valid_numbers(self):
        for capacity in ('3,1 Kubikfuß', '3.1 Kubikfuß', '3 Kubikfuß', '4,5 Liter', '160.2L'):
            with self.subTest(capacity=capacity):
                self.assertNotIn(
                    'ref_capacity',
                    seg_validation.evaluate_format_row(
                        {'ref_capacity': capacity}, 'seg_ref', 'Amazon',
                    ),
                )
        for capacity in ('Kubikfuß', '3,1,2 Kubikfuß', '-3,1 Kubikfuß', '3,1 Kubikfuß extra'):
            with self.subTest(capacity=capacity):
                self.assertIn(
                    'ref_capacity',
                    seg_validation.evaluate_format_row(
                        {'ref_capacity': capacity}, 'seg_ref', 'Amazon',
                    ),
                )

    def test_savings_is_euro_amount_for_amazon_and_percent_elsewhere(self):
        for savings in ('4,00€', '35,00€', '9,08€', '19,99€', '10,00€'):
            with self.subTest(savings=savings):
                self.assertNotIn(
                    'savings',
                    seg_validation.evaluate_format_row(
                        {'savings': savings}, 'seg_tv', 'Amazon'
                    ),
                )

        self.assertIn(
            'savings',
            seg_validation.evaluate_format_row(
                {'savings': '-10%'}, 'seg_tv', 'Amazon'
            ),
        )
        self.assertNotIn(
            'savings',
            seg_validation.evaluate_format_row(
                {'savings': '-10%'}, 'seg_tv', 'Mediamarkt'
            ),
        )
        amazon_rule = next(
            rule for rule in seg_validation.get_format_rule_details(
                'seg_tv', 'Amazon'
            )
            if rule['field'] == 'savings'
        )
        self.assertIn('4,00€', amazon_rule['pattern'])

    def test_amazon_savings_reports_missing_thousands_separator(self):
        expected_reason = (
            '1,000€ 이상 금액에 천 단위 구분자(.)가 누락되었습니다.'
        )
        for savings in ('4700,00€', '4500,00€', '4498,02€'):
            with self.subTest(savings=savings):
                errors = seg_validation.evaluate_format_row(
                    {'savings': savings}, 'seg_tv', 'Amazon'
                )
                self.assertEqual(expected_reason, errors['savings'])

        for savings in ('999,99€', '1.000,00€', '4.700,00€'):
            with self.subTest(savings=savings):
                self.assertNotIn(
                    'savings',
                    seg_validation.evaluate_format_row(
                        {'savings': savings}, 'seg_tv', 'Amazon'
                    ),
                )

        amazon_rule = next(
            rule for rule in seg_validation.get_format_rule_details(
                'seg_tv', 'Amazon'
            )
            if rule['field'] == 'savings'
        )
        self.assertIn('천 단위 구분자(.) 필수', amazon_rule['description'])
        self.assertIn('4700,00€는 오류', amazon_rule['pattern'])

    def test_csv_variants_are_allowed_and_invalid_values_are_reported(self):
        valid_ref = seg_validation.evaluate_format_row({
            'final_sku_price': '1.099,00 €',
            'original_sku_price': '1.099,– €',
            'star_rating': '4.5',
            'count_of_star_ratings': '1,018',
            'count_of_reviews': '1112',
            'main_rank': '300',
            'bsr_rank': '100',
            'calendar_week': 'w33',
            'ref_capacity': '4,5 Liter',
            'ref_refrigerator_type': 'Multi-Door',
        }, 'seg_ref', 'Amazon')
        invalid_tv = seg_validation.evaluate_format_row({
            'final_sku_price': 'price unknown',
            'star_rating': '6.0',
            'count_of_star_ratings': '-1',
            'main_rank': '0',
            'calendar_week': 'week33',
            'screen_size': 'large',
        }, 'seg_tv', 'Amazon')

        self.assertEqual({}, valid_ref)
        self.assertEqual({
            'final_sku_price', 'star_rating', 'count_of_star_ratings',
            'main_rank', 'calendar_week', 'screen_size',
        }, set(invalid_tv))

    @patch('apps.dx.dx_layer2.seg_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.seg_validation._history_rows')
    @patch('apps.dx.dx_layer2.seg_validation._latest_rows')
    def test_detail_defaults_to_three_days_and_is_editable(
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
            'id': 9, 'item': 'item-1', 'account_name': 'Amazon',
            'final_sku_price': 'bad price',
            'crawl_strdatetime': '2026-09-09 10:00:00',
        }], mapping)
        history_rows.return_value = [
            {
                'id': day, 'item': 'item-1', 'account_name': 'Amazon',
                'final_sku_price': value,
                'crawl_strdatetime': f'2026-09-0{day} 10:00:00',
            }
            for day, value in (
                (7, '99,00 €'), (8, 'Höherer Preis als üblich'),
                (9, 'bad price'),
            )
        ]

        result = seg_validation.format_detail(
            None, date(2026, 9, 9), 'seg_tv_retail', 'Amazon'
        )

        self.assertEqual(3, result['history_days'])
        self.assertEqual([7, 8, 9], [row['id'] for row in result['results']])
        self.assertEqual({'final_sku_price': 1}, result['field_counts'])
        self.assertIn('final_sku_price', result['editable_cols'])
        self.assertNotIn('product_url', result['editable_cols'])
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

    def test_format_cell_update_uses_seg_scope_and_format_allowlist(self):
        cursor = ScriptedCursor([
            {'fetchone': ('bad price', 'Amazon', 'item-1', 'batch-1')},
            {},
            {},
        ])
        conn = Mock()

        result = data_edit_services.update_cell_value(
            cursor, conn, SEG_TV_TABLE, 11, 'final_sku_price', '99,00 €',
            date(2026, 9, 9), 'format', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        self.assertIn('source.redirect IS TRUE', cursor.calls[0][0])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', cursor.calls[0][0])
        self.assertIn('SET final_sku_price = %s', cursor.calls[1][0])
        self.assertEqual('format_check', cursor.calls[2][1][1])

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
