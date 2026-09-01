import unittest
from datetime import date

from apps.common import inspection_dates, sea_retail
from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


sea_services = load_module(
    'apps/dx/dx_layer3/cross_field/sea_services.py',
    'layer3_sea_crossfield_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.sea_retail': sea_retail,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [
                'count_of_reviews', 'count_of_star_ratings', 'star_rating',
                'final_sku_price', 'original_sku_price', 'savings',
                'detailed_review_content', 'recommendation_intent',
            ],
        ),
    },
)


def _bestbuy_row(**overrides):
    row = {
        'id': 10,
        'batch_id': 'b_260830_180006',
        'country': 'SEA',
        'product': 'REF',
        'account_name': 'Bestbuy',
        'page_type': 'main',
        'item': 'A-1',
        'sku': 'SKU-1',
        'retailer_sku_name': 'Example refrigerator',
        'product_url': 'https://example.com/a-1',
        'crawl_strdatetime': '2026-08-30 18:00:06',
        'count_of_reviews': '2',
        'count_of_star_ratings': '2',
        'star_rating': '4.5',
        'main_rank': '1',
        'bsr_rank': None,
        'final_sku_price': '$900',
        'original_sku_price': '$1,000',
        'savings': '$100',
        'detailed_review_content': 'review1 - good ||| review2 - nice',
        'recommendation_intent': '90% would recommend to a friend',
    }
    row.update(overrides)
    return row


def _lowes_row(**overrides):
    row = _bestbuy_row(
        id=20,
        batch_id='l_260830_185813',
        account_name='Lowes',
        item='L-1',
        product_url='https://example.com/l-1',
        recommendation_intent='90% Recommend this product',
    )
    row.update(overrides)
    return row


def _rule(rule_id, rule_key, retailer='ALL', product_line='sea_ref'):
    spec = sea_services.SEA_RULE_SPECS[rule_key]
    product = 'ref' if product_line == 'sea_ref' else 'ldy'
    return {
        'id': rule_id,
        'detail_code': f'{product_line}_{rule_key}',
        'detail_name': spec['detail_name'],
        'section_code': f'{product_line}_retail',
        'section_name': f'SEA {product.upper()}',
        'table_name': f'public.{product}_retail_com',
        'date_column': 'crawl_strdatetime',
        'product_line': product_line,
        'retailer': retailer,
        'field1': spec['field1'],
        'field2': spec['field2'],
        'validation_type': rule_key,
        'error_message': spec['error_message'],
        'select_fields': '',
        'query': 'DELETE FROM must_not_execute',
        'sort_order': rule_id,
    }


class SeaCrossfieldEvaluationTests(unittest.TestCase):
    def test_rating_zero_pair_is_bidirectional_for_both_retailers(self):
        for row_factory in (_bestbuy_row, _lowes_row):
            with self.subTest(retailer=row_factory.__name__, direction='rating_zero'):
                errors = sea_services.evaluate_sea_row(row_factory(
                    star_rating='0', count_of_star_ratings='2',
                    count_of_reviews='2',
                ))
                self.assertIn('rating_count_presence', errors)

            with self.subTest(retailer=row_factory.__name__, direction='count_zero'):
                errors = sea_services.evaluate_sea_row(row_factory(
                    star_rating='4.5', count_of_star_ratings='0',
                    count_of_reviews='0',
                ))
                self.assertIn('rating_count_presence', errors)

            with self.subTest(retailer=row_factory.__name__, state='both_zero'):
                errors = sea_services.evaluate_sea_row(row_factory(
                    star_rating='0', count_of_star_ratings='0',
                    count_of_reviews='0', detailed_review_content=None,
                    recommendation_intent=None,
                ))
                self.assertNotIn('rating_count_presence', errors)

    def test_bestbuy_tv_style_rules(self):
        self.assertEqual(set(), sea_services.evaluate_sea_row(_bestbuy_row()))

        errors = sea_services.evaluate_sea_row(_bestbuy_row(
            count_of_reviews='3',
            count_of_star_ratings='2',
            main_rank=None,
            final_sku_price='$1,100',
            detailed_review_content='review1 - only one',
            recommendation_intent='90% Recommend this product',
        ))

        self.assertTrue({
            'review_count_match', 'rank_page_type',
            'final_original_price', 'review_body_count',
            'recommendation_intent',
        }.issubset(errors))

    def test_lowes_review_body_cases_are_review_candidates_not_anomalies(self):
        cases = (
            ('body_missing', {
                'count_of_reviews': '3',
                'count_of_star_ratings': '3',
                'detailed_review_content': None,
            }),
            ('body_without_reviews', {
                'count_of_reviews': '0',
                'count_of_star_ratings': '0',
                'star_rating': '0',
                'detailed_review_content': 'review1 - a',
                'recommendation_intent': None,
            }),
            ('body_over_review_count', {
                'count_of_reviews': '1',
                'count_of_star_ratings': '1',
                'detailed_review_content': 'review1 - a ||| review2 - b',
            }),
            ('review20_missing', {
                'count_of_reviews': '25',
                'count_of_star_ratings': '25',
                'detailed_review_content': ' ||| '.join(
                    f'review{i} - body' for i in range(1, 20)
                ),
            }),
        )
        for expected, overrides in cases:
            with self.subTest(expected=expected):
                row = _lowes_row(**overrides)
                self.assertEqual(
                    expected, sea_services.evaluate_lowes_review_body(row),
                )
                self.assertNotIn(
                    'review_body_count', sea_services.evaluate_sea_row(row),
                )

        self.assertIsNone(sea_services.evaluate_lowes_review_body(_lowes_row(
            count_of_reviews='3',
            count_of_star_ratings='3',
            detailed_review_content='review1 - a ||| review2 - b',
        )))

    def test_lowes_price_and_four_savings_cases(self):
        self.assertIn(
            'final_original_price',
            sea_services.evaluate_sea_row(_lowes_row(
                final_sku_price='$1,000', original_sku_price='$1,000',
                savings='$0',
            )),
        )
        cases = (
            ('savings_missing', {
                'final_sku_price': '$900', 'original_sku_price': '$1,000',
                'savings': None,
            }),
            ('original_missing', {
                'final_sku_price': '$900', 'original_sku_price': None,
                'savings': '$100',
            }),
            ('savings_amount_match', {
                'final_sku_price': '$900', 'original_sku_price': '$1,000',
                'savings': '$50',
            }),
            ('final_missing', {
                'final_sku_price': None, 'original_sku_price': '$1,000',
                'savings': '$100',
            }),
        )
        for expected, overrides in cases:
            with self.subTest(expected=expected):
                self.assertIn(
                    expected,
                    sea_services.evaluate_sea_row(_lowes_row(**overrides)),
                )

    def test_recommendation_format_is_retailer_specific(self):
        self.assertNotIn(
            'recommendation_intent',
            sea_services.evaluate_sea_row(_bestbuy_row()),
        )
        self.assertNotIn(
            'recommendation_intent',
            sea_services.evaluate_sea_row(_lowes_row()),
        )
        self.assertIn(
            'recommendation_intent',
            sea_services.evaluate_sea_row(_lowes_row(
                recommendation_intent='90% would recommend to a friend',
            )),
        )


class SeaCrossfieldScopeTests(unittest.TestCase):
    def test_latest_anchor_scope_uses_exact_d_minus_one(self):
        cursor = ScriptedCursor([{'fetchall': [_bestbuy_row()]}])

        rows = sea_services.load_latest_sea_rows(
            cursor, date(2026, 8, 31), 'sea_ref',
        )

        sql, params = cursor.calls[0]
        self.assertIn('FROM public.ref_retail_com', sql)
        self.assertIn("= 'MAIN'", sql)
        self.assertIn("IN ('MAIN', 'BSR')", sql)
        self.assertIn('ROW_NUMBER() OVER', sql)
        self.assertIn('ORDER BY max_id DESC', sql)
        self.assertEqual(
            ('2026-08-30', '2026-08-30',
             '2026-08-30', '2026-08-30'),
            params,
        )
        self.assertEqual('b_260830_180006', rows[0]['batch_id'])

    def test_summary_ignores_stored_query_and_keeps_product_url(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [_bestbuy_row(count_of_reviews='3')]},
            {'fetchall': []},
        ])

        result = sea_services.get_sea_cross_field_summary(
            cursor, date(2026, 8, 31), 'sea_ref',
        )

        self.assertEqual('2026-08-31', result['date'])
        self.assertEqual('2026-08-30', result['source_date'])
        self.assertEqual(-1, result['offset_days'])
        self.assertEqual(1, result['total_anomalies'])
        query = result['rule_summary'][0]['query']
        self.assertNotIn('DELETE FROM must_not_execute', query)
        self.assertIn('source.product_url', query)
        self.assertIn('ranked_batches', query)
        self.assertIn("'2026-08-30'", query)

    def test_lowes_review_candidates_are_separate_from_anomalies(self):
        rows = [
            _lowes_row(
                id=21, item='L-21', count_of_reviews='3',
                count_of_star_ratings='3', detailed_review_content=None,
            ),
            _lowes_row(
                id=22, item='L-22', count_of_reviews='0',
                count_of_star_ratings='0', star_rating='0',
                detailed_review_content='review1 - a',
                recommendation_intent=None,
            ),
            _lowes_row(
                id=23, item='L-23', count_of_reviews='1',
                count_of_star_ratings='1',
                detailed_review_content='review1 - a ||| review2 - b',
            ),
            _lowes_row(
                id=24, item='L-24', count_of_reviews='25',
                count_of_star_ratings='25',
                detailed_review_content=' ||| '.join(
                    f'review{i} - body' for i in range(1, 20)
                ),
            ),
        ]
        cursor = ScriptedCursor([
            {'fetchall': [_rule(7, 'review_body_count', retailer='Lowes')]},
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = sea_services.get_sea_cross_field_summary(
            cursor, date(2026, 8, 31), 'sea_ref',
        )

        self.assertEqual(0, result['total_anomalies'])
        self.assertEqual(4, result['total_review_needed'])
        self.assertEqual(4, result['review_needed_records'])
        self.assertEqual(0, result['passed_records'])
        rule = result['rule_summary'][0]
        self.assertEqual(0, rule['error_count'])
        self.assertEqual(4, rule['review_count'])
        self.assertEqual(
            set(sea_services.LOWES_REVIEW_ISSUES.values()),
            {label for label, count in rule['review_type_summary'].items()
             if count == 1},
        )

        detail_cursor = ScriptedCursor([
            {'fetchall': [_rule(7, 'review_body_count', retailer='Lowes')]},
            {'fetchall': rows},
            {'fetchall': []},
        ])
        detail = sea_services.get_sea_cross_field_rule_detail(
            detail_cursor, date(2026, 8, 31), 'sea_ref', 7,
        )
        self.assertEqual(0, detail['total_anomalies'])
        self.assertEqual(4, detail['total_review_needed'])
        self.assertEqual(4, detail['total_findings'])
        self.assertTrue(all(
            row['finding_level'] == 'review_needed'
            and row.get('issue_type')
            for row in detail['anomalies']
        ))
        detail_by_id = {row['id']: row for row in detail['anomalies']}
        self.assertEqual(0, detail_by_id[21]['review_body_count'])
        self.assertEqual(2, detail_by_id[23]['review_body_count'])
        self.assertNotIn('max_review_number', detail_by_id[23])
        self.assertNotIn('review_body_criterion', detail_by_id[24])

    def test_bestbuy_review_detail_includes_body_metrics(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(7, 'review_body_count', retailer='Bestbuy')]},
            {'fetchall': [_bestbuy_row(
                count_of_reviews='3', count_of_star_ratings='3',
                detailed_review_content='review1 - a ||| review2 - b',
            )]},
            {'fetchall': []},
        ])

        detail = sea_services.get_sea_cross_field_rule_detail(
            cursor, date(2026, 8, 31), 'sea_ref', 7,
        )

        row = detail['anomalies'][0]
        self.assertEqual('anomaly', row['finding_level'])
        self.assertEqual('review3 없음', row['issue_type'])
        self.assertEqual(2, row['review_body_count'])
        self.assertNotIn('max_review_number', row)
        self.assertNotIn('review_body_criterion', row)

    def test_detail_returns_full_source_row_and_inspection_date(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(7, 'review_count_match')]},
            {'fetchall': [_bestbuy_row(count_of_reviews='3')]},
            {'fetchall': []},
        ])

        result = sea_services.get_sea_cross_field_rule_detail(
            cursor, date(2026, 8, 31), 'sea_ref', 7,
        )

        self.assertTrue(result['found'])
        self.assertEqual('2026-08-31', result['inspection_date'])
        self.assertEqual('2026-08-30', result['source_date'])
        self.assertEqual(
            'https://example.com/a-1', result['anomalies'][0]['product_url'],
        )


if __name__ == '__main__':
    unittest.main()
