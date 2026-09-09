from datetime import date
from pathlib import Path
import unittest

from apps.dx.dx_layer3.cross_field import seg_services


def _amazon_row(**overrides):
    row = {
        'id': 1,
        'country': 'SEG',
        'product': 'TV',
        'account_name': 'Amazon',
        'page_type': 'MAIN',
        'item': 'A-1',
        'main_rank': '1',
        'bsr_rank': None,
        'star_rating': '4.5',
        'count_of_star_ratings': '10',
        'count_of_reviews': None,
        'final_sku_price': '899,99€',
        'original_sku_price': '1.000,00€',
        'savings': '100,01€',
    }
    row.update(overrides)
    return row


class RecordingCursor:
    def __init__(self):
        self.calls = []
        self.description = [('id',), ('account_name',)]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return []


class SegCrossfieldEvaluationTests(unittest.TestCase):
    def test_german_euro_parser_keeps_cents(self):
        self.assertEqual(
            seg_services.Decimal('4700.00'),
            seg_services.parse_seg_money('4.700,00 €'),
        )
        self.assertEqual(
            seg_services.Decimal('9.08'),
            seg_services.parse_seg_money('9,08€'),
        )

    def test_amazon_savings_amount_must_match_through_cents(self):
        self.assertEqual(set(), seg_services.evaluate_seg_row(_amazon_row()))
        errors = seg_services.evaluate_seg_row(_amazon_row(
            savings='100,00€',
        ))
        self.assertIn('savings_amount_match', errors)

    def test_price_presence_rules_only_require_savings_for_discount(self):
        self.assertIn(
            'savings_missing',
            seg_services.evaluate_seg_row(_amazon_row(savings=None)),
        )
        self.assertNotIn(
            'savings_missing',
            seg_services.evaluate_seg_row(_amazon_row(
                final_sku_price='1.000,00€', savings=None,
            )),
        )
        self.assertIn(
            'original_missing',
            seg_services.evaluate_seg_row(_amazon_row(
                original_sku_price=None,
            )),
        )
        self.assertIn(
            'final_missing',
            seg_services.evaluate_seg_row(_amazon_row(
                final_sku_price=None,
            )),
        )

    def test_amazon_status_prices_skip_numeric_price_relationships(self):
        for status in (
            'Höherer Preis als üblich', 'Derzeit nicht verfügbar.',
        ):
            errors = seg_services.evaluate_seg_row(_amazon_row(
                final_sku_price=status, savings=None,
            ))
            self.assertFalse({
                'final_original_price', 'discount_rate_90',
                'savings_missing', 'original_missing', 'final_missing',
                'savings_amount_match',
            } & errors)

    def test_no_customer_reviews_requires_zero_or_missing_rating_count(self):
        errors = seg_services.evaluate_seg_row(_amazon_row(
            star_rating='No customer reviews', count_of_star_ratings='1',
        ))
        self.assertIn('no_review_rating_count', errors)
        normal = seg_services.evaluate_seg_row(_amazon_row(
            star_rating='No customer reviews', count_of_star_ratings='0',
        ))
        self.assertNotIn('no_review_rating_count', normal)


class SegCrossfieldScopeTests(unittest.TestCase):
    def test_tv_latest_batch_scope_excludes_amazon_redirect(self):
        cursor = RecordingCursor()
        seg_services.load_latest_seg_rows(
            cursor, date(2026, 9, 9), 'seg_tv',
        )
        sql, params = cursor.calls[0]
        self.assertIn('ranked_batches', sql)
        self.assertIn("IN ('main', 'bsr')", sql)
        self.assertIn('source.redirect IS NOT TRUE', sql)
        self.assertIn("= 'SEG'", sql)
        self.assertEqual(
            ('2026-09-09', '2026-09-09', '2026-09-09', '2026-09-09'),
            params,
        )

    def test_ldy_scope_does_not_reference_redirect(self):
        cursor = RecordingCursor()
        seg_services.load_latest_seg_rows(
            cursor, date(2026, 9, 9), 'seg_ldy',
        )
        self.assertNotIn('redirect', cursor.calls[0][0].lower())

    def test_seed_registers_all_three_products_and_ten_rules(self):
        sql = Path('sql/seed_seg_layer3_crossfield.sql').read_text(
            encoding='utf-8'
        )
        self.assertIn('Expected 30 active SEG cross-field rules', sql)
        for section in ('seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail'):
            self.assertIn(section, sql)
        for rule_key in seg_services.SEG_RULE_SPECS:
            self.assertIn(f"'{rule_key}'", sql)


if __name__ == '__main__':
    unittest.main()
