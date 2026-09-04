import unittest
from datetime import date, timedelta

from apps.common import inspection_dates, retail_validation, siel_retail
from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


siel_services = load_module(
    'apps/dx/dx_layer3/cross_field/siel_services.py',
    'layer3_siel_crossfield_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_validation': retail_validation,
        'apps.common.siel_retail': siel_retail,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [
                'count_of_reviews', 'count_of_star_ratings', 'star_rating',
                'detailed_review_content', 'final_sku_price',
                'original_sku_price', 'savings', 'main_rank', 'bsr_rank',
            ],
        ),
    },
)


def _amazon_row(**overrides):
    row = {
        'id': 10,
        'batch_id': 'amazon_20260902',
        'country': 'SIEL',
        'product': 'TV',
        'account_name': 'Amazon',
        'page_type': 'main',
        'item': 'B000000001',
        'sku': 'SKU-A',
        'retailer_sku_name': 'Amazon TV',
        'product_url': 'https://www.amazon.in/dp/B000000001',
        'crawl_datetime': '2026-09-03T08:00:00+09:00',
        'count_of_reviews': None,
        'star_rating': '4.5',
        'count_of_star_ratings': '10',
        'detailed_review_content': 'review1 - good',
        'main_rank': '1',
        'bsr_rank': None,
        'final_sku_price': '₹900',
        'original_sku_price': '₹1,000',
        'savings': None,
        'redirect': False,
    }
    row.update(overrides)
    return row


def _flipkart_row(**overrides):
    row = _amazon_row(
        id=20,
        batch_id='flipkart_20260902',
        account_name='Flipkart',
        item='TVS0000000000001',
        sku='SKU-F',
        retailer_sku_name='Flipkart TV',
        product_url='https://www.flipkart.com/tv/p/item',
        count_of_reviews='2',
        count_of_star_ratings='20',
        final_sku_price='₹900',
        original_sku_price='₹1,000',
        savings='10%',
    )
    row.update(overrides)
    return row


def _rule(rule_id, rule_key, retailer, product_line='siel_tv'):
    spec = siel_services.SIEL_RULE_SPECS[rule_key]
    source = siel_retail.get_siel_source(product_line)
    return {
        'id': rule_id,
        'detail_code': f'{product_line}_{rule_key}',
        'detail_name': spec['detail_name'],
        'section_code': source['section_code'],
        'section_name': source['display_name'],
        'table_name': source['table_name'],
        'date_column': source['date_column'],
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


class SielCrossfieldEvaluationTests(unittest.TestCase):
    def test_valid_amazon_and_flipkart_rows_have_no_findings(self):
        self.assertEqual(set(), siel_services.evaluate_siel_row(_amazon_row()))
        self.assertEqual(set(), siel_services.evaluate_siel_row(_flipkart_row()))

    def test_amazon_rating_rank_and_price_rules(self):
        no_review = siel_services.evaluate_siel_row(_amazon_row(
            star_rating='No customer reviews',
            count_of_star_ratings='1',
        ))
        self.assertIn('no_review_rating_count', no_review)

        errors = siel_services.evaluate_siel_row(_amazon_row(
            star_rating='5.5',
            count_of_star_ratings=None,
            main_rank=None,
            final_sku_price='₹100',
            original_sku_price='₹1,000',
        ))
        self.assertTrue({
            'rating_count_presence', 'rating_range', 'rank_page_type',
            'discount_rate_90',
        }.issubset(errors))

        sentence = siel_services.evaluate_siel_row(_amazon_row(
            star_rating='Excellent television',
        ))
        self.assertIn('rating_range', sentence)

        allowed_no_review = siel_services.evaluate_siel_row(_amazon_row(
            star_rating='No customer reviews',
            count_of_star_ratings='0',
        ))
        self.assertNotIn('rating_range', allowed_no_review)

    def test_flipkart_review_body_both_directions(self):
        errors = siel_services.evaluate_siel_row(_flipkart_row(
            count_of_reviews='2', detailed_review_content=None,
        ))
        self.assertIn('review_body_missing', errors)

        errors = siel_services.evaluate_siel_row(_flipkart_row(
            count_of_reviews='0', detailed_review_content='review1 - text',
        ))
        self.assertIn('review_count_missing', errors)

    def test_flipkart_review_count_requires_star_count(self):
        for missing_star_count in (None, '', '0'):
            with self.subTest(star_count=missing_star_count):
                errors = siel_services.evaluate_siel_row(_flipkart_row(
                    count_of_reviews='3',
                    count_of_star_ratings=missing_star_count,
                ))
                self.assertIn('review_star_count_missing', errors)
                self.assertIn('rating_count_presence', errors)

        errors = siel_services.evaluate_siel_row(_flipkart_row(
            count_of_reviews='21', count_of_star_ratings='20',
        ))
        self.assertIn('review_gt_star_count', errors)

    def test_flipkart_price_presence_and_order_rules(self):
        self.assertIn(
            'savings_missing',
            siel_services.evaluate_siel_row(_flipkart_row(savings=None)),
        )
        self.assertIn(
            'original_missing',
            siel_services.evaluate_siel_row(_flipkart_row(
                original_sku_price=None, savings='10%',
            )),
        )
        self.assertIn(
            'final_original_price',
            siel_services.evaluate_siel_row(_flipkart_row(
                final_sku_price='₹1,100', original_sku_price='₹1,000',
                savings='10%',
            )),
        )

    def test_flipkart_discount_rate_allows_one_percentage_point(self):
        normal = siel_services.evaluate_siel_row(_flipkart_row(
            final_sku_price='₹14,000',
            original_sku_price='₹14,050',
            savings='1%',
        ))
        self.assertNotIn('savings_rate_match', normal)

        bad = siel_services.evaluate_siel_row(_flipkart_row(
            final_sku_price='₹14,000',
            original_sku_price='₹14,050',
            savings='5%',
        ))
        self.assertIn('savings_rate_match', bad)


class SielCrossfieldQueryAndSummaryTests(unittest.TestCase):
    def test_latest_batch_query_uses_kst_same_day_and_redirect_scope(self):
        cursor = ScriptedCursor([{'fetchall': [_amazon_row()]}])

        rows = siel_services.load_latest_siel_rows(
            cursor, date(2026, 9, 3), 'siel_tv'
        )

        self.assertEqual(1, len(rows))
        sql, params = cursor.calls[0]
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
        self.assertIn("= 'main'", sql)
        self.assertIn("IN ('main', 'bsr')", sql)
        self.assertIn(
            'latest.batch_id IS NOT DISTINCT FROM source.batch_id', sql
        )
        self.assertIn(
            "NOT (source.account_name = 'Amazon' AND source.redirect IS TRUE)",
            sql,
        )
        self.assertEqual(
            ('2026-09-03', '2026-09-03', '2026-09-03', '2026-09-03'),
            params,
        )

    def test_retailer_specific_rows_merge_only_for_same_rule_key(self):
        cursor = ScriptedCursor([{'fetchall': [
            _rule(1, 'rating_range', 'Amazon'),
            _rule(2, 'rating_range', 'Flipkart'),
        ]}])

        rules = siel_services.load_active_siel_rules(cursor, 'siel_tv')

        self.assertEqual(1, len(rules))
        self.assertEqual(['Amazon', 'Flipkart'], rules[0]['_retailers'])
        self.assertEqual([1, 2], rules[0]['_source_rule_ids'])

    def test_summary_uses_static_rules_not_stored_query(self):
        cursor = ScriptedCursor([
            {'fetchall': [
                _rule(1, 'no_review_rating_count', 'Amazon'),
                _rule(2, 'review_star_count_missing', 'Flipkart'),
            ]},
            {'fetchall': [
                _amazon_row(
                    star_rating='No customer reviews',
                    count_of_star_ratings='3',
                ),
                _flipkart_row(count_of_star_ratings=None),
            ]},
            {'fetchall': []},
        ])

        result = siel_services.get_siel_cross_field_summary(
            cursor, date(2026, 9, 3), 'siel_tv'
        )

        self.assertEqual('2026-09-03', result['source_date'])
        self.assertEqual(0, result['offset_days'])
        self.assertEqual(2, result['failed_records'])
        self.assertEqual(2, result['total_anomalies'])
        self.assertEqual(2, len(result['rule_summary']))
        for rule in result['rule_summary']:
            self.assertNotIn('DELETE FROM must_not_execute', rule['query'])
            self.assertNotIn('WITH main_batches AS', rule['query'])
            self.assertNotIn('    batch_id', rule['query'])
            self.assertIn(
                "crawl_datetime >= CURRENT_DATE "
                "- INTERVAL '2 days'",
                rule['query'],
            )
            self.assertIn(
                "crawl_datetime < CURRENT_DATE + INTERVAL '1 day'",
                rule['query'],
            )
            self.assertNotIn('AT TIME ZONE', rule['query'])

    def test_detail_marks_same_day_target_and_previous_day_history(self):
        rule = _rule(1, 'review_gt_star_count', 'Flipkart')
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': [
                _flipkart_row(
                    id=19, crawl_datetime='2026-09-02T08:00:00+09:00',
                    count_of_reviews='21', count_of_star_ratings='20',
                ),
                _flipkart_row(
                    id=20, crawl_datetime='2026-09-03T08:00:00+09:00',
                    count_of_reviews='21', count_of_star_ratings='20',
                ),
            ]},
            {'fetchall': []},
        ])

        result = siel_services.get_siel_cross_field_rule_detail(
            cursor, date(2026, 9, 3), 'siel_tv', 1, days=3
        )

        self.assertTrue(result['found'])
        self.assertEqual('2026-09-03', result['source_date'])
        self.assertEqual(
            ['target', 'comparison_history'],
            [row['row_role'] for row in result['anomalies']],
        )
        self.assertEqual(1, result['total_anomalies'])
        self.assertIn('count_of_reviews', result['editable_columns'])
        self.assertIn(
            'detailed_review_content', result['editable_columns']
        )
        self.assertNotIn('main_rank', result['editable_columns'])
        self.assertIn(
            "crawl_datetime >= CURRENT_DATE - INTERVAL '2 days'",
            result['query'],
        )
        self.assertIn('    count_of_reviews', result['query'])
        self.assertIn('    count_of_star_ratings', result['query'])

    def test_thirty_day_detail_keeps_target_rows_at_the_front(self):
        rule = _rule(1, 'review_gt_star_count', 'Flipkart')
        rows = []
        row_id = 1
        for item_index in range(4):
            for day in range(29, -1, -1):
                rows.append(_flipkart_row(
                    id=row_id,
                    item=f'ITEM-{item_index}',
                    crawl_datetime=(
                        date(2026, 9, 3) - timedelta(days=day)
                    ).isoformat() + 'T08:00:00+09:00',
                    count_of_reviews='21',
                    count_of_star_ratings='20',
                ))
                row_id += 1
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': rows},
            {'fetchall': []},
        ])

        result = siel_services.get_siel_cross_field_rule_detail(
            cursor, date(2026, 9, 3), 'siel_tv', 1, days=30
        )

        self.assertEqual(
            ['target'] * 4,
            [row['row_role'] for row in result['anomalies'][:4]],
        )
        self.assertEqual(
            {'ITEM-0', 'ITEM-1', 'ITEM-2', 'ITEM-3'},
            {row['item'] for row in result['anomalies'][:4]},
        )


class SielCrossfieldSeedTests(unittest.TestCase):
    def test_seed_contains_three_sources_and_sixteen_rules_each(self):
        from pathlib import Path

        sql = Path('sql/seed_siel_layer3_crossfield.sql').read_text(
            encoding='utf-8'
        )
        self.assertIn('Expected 48 active SIEL cross-field rules', sql)
        for section in (
            'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
        ):
            self.assertIn(section, sql)
        for rule_key in siel_services.SIEL_RULE_SPECS:
            self.assertIn(f"'{rule_key}'", sql)


if __name__ == '__main__':
    unittest.main()
