from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

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
    def test_mediamarkt_discount_boundary_and_other_retailers(self):
        for retailer in ('Mediamarkt', 'OTTO', 'Amazon'):
            for final, missing in (('900,00€', retailer != 'Mediamarkt'), ('899,99€', True)):
                with self.subTest(retailer=retailer, final=final):
                    errors = seg_services.evaluate_seg_row(_amazon_row(
                        account_name=retailer, final_sku_price=final, savings=None,
                    ))
                    self.assertEqual(missing, 'savings_missing' in errors)

    def test_retailer_review_zero_pair_and_count_match(self):
        for retailer in ('Mediamarkt', 'OTTO'):
            for rating, stars, reviews in (('4.5', '10', '0'), ('0', '0', '10')):
                errors = seg_services.evaluate_seg_row(_amazon_row(
                    account_name=retailer, star_rating=rating,
                    count_of_star_ratings=stars, count_of_reviews=reviews,
                ))
                self.assertTrue({'rating_count_presence', 'review_count_match'} <= errors)
            self.assertNotIn('rating_range', seg_services.evaluate_seg_row(_amazon_row(
                account_name=retailer, star_rating='6',
            )))
        self.assertNotIn('rating_count_presence', seg_services.evaluate_seg_row(_amazon_row(count_of_reviews='0')))

    def test_equal_price_is_anomaly_for_every_seg_retailer(self):
        for retailer in ('Mediamarkt', 'OTTO', 'Amazon'):
            self.assertIn('final_original_price', seg_services.evaluate_seg_row(_amazon_row(
                account_name=retailer, final_sku_price='1.000,00€',
            )))

    def test_otto_body_uses_lowes_four_review_cases(self):
        cases = [('1', None), ('0', 'review1 - body'), ('1', 'review2 - body'), ('20', 'review19 - body')]
        for count, body in cases:
            self.assertIsNotNone(seg_services.evaluate_otto_review_body(_amazon_row(
                account_name='OTTO', count_of_reviews=count, detailed_review_content=body,
            )))
        self.assertIsNone(seg_services.evaluate_otto_review_body(_amazon_row(
            account_name='Mediamarkt', count_of_reviews='1', detailed_review_content=None,
        )))
        self.assertIsNone(seg_services.evaluate_otto_review_body(_amazon_row(
            account_name='OTTO', count_of_reviews='20', detailed_review_content='review20 - body',
        )))

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

    def test_seed_registers_all_three_products_and_thirteen_rules(self):
        sql = Path('sql/seed_seg_layer3_crossfield.sql').read_text(
            encoding='utf-8'
        )
        self.assertIn('Expected 39 active SEG cross-field rules', sql)
        for section in ('seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail'):
            self.assertIn(section, sql)
        for rule_key in seg_services.SEG_RULE_SPECS:
            self.assertIn(f"'{rule_key}'", sql)


class SegReviewHistoryTests(unittest.TestCase):
    def result(self, key, rows, corrections=None, detail=False):
        spec = seg_services.SEG_RULE_SPECS[key]
        rule = dict(spec, rule_key=key, rule_id=1, detail_code='seg_tv_' + key,
                    _all_retailers=True, select_fields='|'.join(spec['display_fields']))
        with patch.object(seg_services, 'load_active_seg_rules', return_value=[rule]), \
                patch.object(seg_services, 'load_latest_seg_rows', return_value=rows) as load, \
                patch.object(seg_services, '_load_normal_corrections', return_value=corrections or []):
            if detail:
                result = seg_services.get_seg_cross_field_rule_detail(None, date(2026, 9, 9), 'seg_tv', 1, 3)
            else:
                result = seg_services.build_seg_crossfield_result(None, date(2026, 9, 9), 'seg_tv')
        return result, load

    def row(self, row_id, day, count, **overrides):
        body = ' ||| '.join(f'review{i} - body' for i in range(1, count + 1))
        values = dict(id=row_id, account_name='Mediamarkt',
                      crawl_strdatetime=day, detailed_review_content=body,
                      count_of_reviews='50', count_of_star_ratings='50')
        values.update(overrides)
        return _amazon_row(**values)

    def test_decrease_accounts_for_counts_and_twenty_review_limit(self):
        cases = [
            # Previous counts/body, current counts/body, anomaly.
            ('50', '50', 20, '50', '50', 15, True),
            ('50', '50', 20, '60', '60', 15, True),
            ('50', '50', 20, '0', '0', 0, False),
            ('50', '50', 20, '30', '30', 15, True),
            ('50', '50', 20, '10', '10', 10, False),
            ('50', '50', 20, '10', '10', 5, True),
            ('50', '50', 20, '1', '1', 1, False),
            ('50', '50', 20, '1', '1', 0, True),
            ('50', '50', 20, '0', '10', 10, True),
            ('50', '50', 20, '10', '0', 10, True),
            ('50', '50', 20, '60', '60', 20, False),
            ('50', '50', 15, '60', '60', 20, False),
        ]
        for retailer in ('Mediamarkt', 'OTTO'):
            for pr, ps, pb, cr, cs, cb, expected in cases:
                with self.subTest(retailer=retailer, counts=(pr, ps, cr, cs), body=(pb, cb)):
                    previous = self.row(1, '2026-09-08', pb, account_name=retailer,
                                        count_of_reviews=pr, count_of_star_ratings=ps)
                    current = self.row(2, '2026-09-09', cb, account_name=retailer,
                                       count_of_reviews=cr, count_of_star_ratings=cs)
                    result, _ = self.result('review_body_decrease', [previous, current])
                    self.assertEqual(int(expected), result['failed_records'])

    def test_invalid_counts_are_not_treated_as_zero_on_either_day(self):
        for column in ('count_of_reviews', 'count_of_star_ratings'):
            for invalid in (None, '', '-', 'unknown', '-1', '1.5'):
                for index in (0, 1):
                    rows = [self.row(1, '2026-09-08', 20), self.row(2, '2026-09-09', 0)]
                    rows[index][column] = invalid
                    result, _ = self.result('review_body_decrease', rows)
                    self.assertEqual(0, result['failed_records'])

    def test_zero_counts_with_remaining_body_is_separate_review_finding(self):
        for retailer in ('Mediamarkt', 'OTTO'):
            current = self.row(2, '2026-09-09', 5, account_name=retailer,
                               count_of_reviews='0', count_of_star_ratings='0')
            result, _ = self.result('review_body_count', [current])
            self.assertEqual(1, result['review_needed_records'])
            result, _ = self.result('review_body_decrease', [
                self.row(1, '2026-09-08', 20, account_name=retailer), current,
            ])
            self.assertEqual(0, result['failed_records'])
            current['detailed_review_content'] = None
            result, _ = self.result('review_body_count', [current])
            self.assertEqual(0, result['review_needed_records'])

    def test_collection_cutoff_uses_kst_noon_and_defers_future_dates(self):
        before = datetime(2026, 9, 9, 2, 59, 59, tzinfo=timezone.utc)
        noon = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)
        self.assertFalse(seg_services._review_collection_complete('2026-09-09', before))
        self.assertTrue(seg_services._review_collection_complete('2026-09-09', noon))
        self.assertTrue(seg_services._review_collection_complete('2026-09-08', before))
        self.assertFalse(seg_services._review_collection_complete('2026-09-10', noon))
        with patch.object(seg_services, '_review_collection_complete', return_value=False):
            result, _ = self.result('review_body_decrease', [
                self.row(1, '2026-09-08', 20), self.row(2, '2026-09-09', 0),
            ])
        self.assertEqual(0, result['failed_records'])

    def test_drop_compares_exact_previous_day_and_not_other_retailer(self):
        rows = [self.row(1, '2026-09-08', 20), self.row(2, '2026-09-09', 15),
                self.row(3, '2026-09-09', 10, item='new')]
        result, load = self.result('review_body_decrease', rows)
        self.assertEqual(date(2026, 9, 8), load.call_args.kwargs['from_date'])
        self.assertEqual(2, result['total_checked'])
        self.assertEqual(1, result['failed_records'])
        detail = result['rule_results'][0]['error_details'][0]
        self.assertEqual((20, 15), (detail['previous_review_body_count'], detail['review_body_count']))
        for previous in (self.row(1, '2026-09-07', 20), dict(rows[0], account_name='OTTO')):
            result, _ = self.result('review_body_decrease', [previous, rows[1]])
            self.assertEqual(0, result['failed_records'])

    def test_drop_detail_includes_non_anomalous_previous_row(self):
        result, _ = self.result('review_body_decrease', [
            self.row(1, '2026-09-08', 20), self.row(2, '2026-09-09', 15),
        ], detail=True)
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(['comparison_history', 'target'], [r['row_role'] for r in result['anomalies']])

    def test_normal_confirmation_excludes_drop(self):
        result, _ = self.result('review_body_decrease', [
            self.row(1, '2026-09-08', 20), self.row(2, '2026-09-09', 15),
        ], corrections=[{'record_id': 2, 'rule_id': 1}])
        self.assertEqual(0, result['failed_records'])

    def test_otto_body_counts_as_review_needed_only(self):
        row = dict(self.row(2, '2026-09-09', 0), account_name='OTTO', count_of_reviews='10')
        result, _ = self.result('review_body_count', [row])
        self.assertEqual((0, 1, 0), (result['failed_records'], result['review_needed_records'], result['passed_records']))
        detail, _ = self.result('review_body_count', [row], detail=True)
        self.assertEqual((0, 1), (detail['total_anomalies'], detail['total_review_needed']))

    def test_unrecognized_body_does_not_mean_zero_and_main_is_preferred(self):
        rows = [self.row(1, '2026-09-08', 15),
                dict(self.row(3, '2026-09-08', 20), page_type='BSR'),
                self.row(4, '2026-09-09', 15)]
        result, _ = self.result('review_body_decrease', rows)
        self.assertEqual(0, result['failed_records'])
        rows[-1]['detailed_review_content'] = 'unrecognized text'
        result, _ = self.result('review_body_decrease', rows)
        self.assertEqual(0, result['failed_records'])

    def test_body_review_and_decrease_do_not_double_count_dashboard_records(self):
        rules = []
        for rule_id, key in enumerate(('review_body_count', 'review_body_decrease'), 1):
            spec = seg_services.SEG_RULE_SPECS[key]
            rules.append(dict(spec, rule_id=rule_id, rule_key=key,
                              detail_code='seg_tv_' + key, _all_retailers=True))
        rows = [dict(self.row(1, '2026-09-08', 20), account_name='OTTO'),
                dict(self.row(2, '2026-09-09', 0), account_name='OTTO', count_of_reviews='20')]
        with patch.object(seg_services, 'load_active_seg_rules', return_value=rules), \
                patch.object(seg_services, 'load_latest_seg_rows', return_value=rows), \
                patch.object(seg_services, '_load_normal_corrections', return_value=[]):
            result = seg_services.build_seg_crossfield_result(None, date(2026, 9, 9), 'seg_tv')
        self.assertEqual((1, 0, 0), (result['failed_records'], result['review_needed_records'], result['passed_records']))
        self.assertEqual((1, 1), (result['total_anomalies'], result['total_review_needed']))


if __name__ == '__main__':
    unittest.main()
