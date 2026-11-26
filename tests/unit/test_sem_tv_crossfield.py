from datetime import date
import unittest
from unittest.mock import patch

from apps.dx.dx_layer3.cross_field import sem_services as services


class SemTvCrossfieldTests(unittest.TestCase):
    day = date(2026, 11, 28)
    rule_id = 'sem_tv:mx_tv_savings_amount_match'
    walmart = {
        'id': 10, 'country': 'SEM', 'account_name': 'walmart ', 'item': '00005381854166',
        'crawl_datetime': '2026-11-28T18:00:00-06:00',
        'original_sku_price': '$3,490.00', 'final_sku_price': '$3,090.00', 'savings': '$399.99',
        'star_rating': '4.6', 'count_of_reviews': '28', 'count_of_star_ratings': '91', 'main_rank': '8',
    }
    sams = {
        **walmart, 'id': 20, 'account_name': "sam's club", 'item': '981052373',
        'original_sku_price': '10331.27', 'final_sku_price': '8383.49', 'savings': '$1,947.78',
    }

    def test_exact_money_and_missing_or_invalid_values(self):
        for retailer, row in [('Walmart', self.walmart), ("Sam's Club", self.sams)]:
            with self.subTest(retailer=retailer):
                for value in (None, '', '30%', 'Ahorra $400.00', '$0.00', '-$400.00'):
                    self.assertEqual([], services._failed_rules({**row, 'savings': value}, retailer, 'sem_tv'))
                self.assertEqual([], services._failed_rules({**row, 'original_sku_price': None}, retailer, 'sem_tv'))
        self.assertEqual(['mx_tv_savings_amount_match'], services._failed_rules(self.walmart, 'Walmart', 'sem_tv'))
        self.assertEqual([], services._failed_rules({**self.walmart, 'savings': '$400.00'}, 'Walmart', 'sem_tv'))
        self.assertEqual([], services._failed_rules(self.sams, "Sam's Club", 'sem_tv'))
        self.assertEqual([], services._failed_rules(
            {**self.sams, 'original_sku_price': '9715', 'final_sku_price': '9714.4', 'savings': '$0.60'},
            "Sam's Club", 'sem_tv'))

    def test_price_dependencies_and_seller_specific_review_rules(self):
        def evaluate(row, seller='Walmart'):
            return services.sem_tv_rules.evaluate(row, seller, services._format_checks('sem_tv', seller))

        reversed_price = evaluate({**self.walmart, 'final_sku_price': '$3,590.00'})
        self.assertEqual('anomaly', reversed_price['mx_tv_price_order'])
        self.assertNotIn('mx_tv_savings_amount_match', reversed_price)
        self.assertEqual('anomaly', evaluate({**self.sams, 'final_sku_price': None}, "Sam's Club")['mx_tv_final_missing'])
        self.assertEqual('review_needed', evaluate({**self.sams, 'original_sku_price': None}, "Sam's Club")['mx_tv_original_missing'])
        self.assertEqual({}, evaluate({'final_sku_price': '8383.49'}, "Sam's Club"))
        self.assertEqual('ok', evaluate({**self.walmart, 'main_rank': None, 'bsr_rank': '100'})['mx_tv_rank_presence'])
        self.assertEqual('anomaly', evaluate({**self.walmart, 'main_rank': None})['mx_tv_rank_presence'])
        self.assertEqual('review_needed', evaluate({**self.walmart, 'star_rating': None})['mx_tv_rating_count'])
        self.assertEqual('review_needed', evaluate({**self.walmart, 'star_rating': '0'})['mx_tv_rating_count'])
        self.assertEqual('review_needed', evaluate({**self.walmart, 'count_of_reviews': '92'})['mx_tv_written_review_count'])
        self.assertEqual('ok', evaluate({**self.walmart, 'count_of_reviews': '0'})['mx_tv_written_review_count'])
        sams = evaluate({**self.sams, 'star_rating': None, 'count_of_reviews': '92'}, "Sam's Club")
        self.assertNotIn('mx_tv_rating_count', sams)
        self.assertNotIn('mx_tv_written_review_count', sams)
        self.assertNotIn('mx_tv_rank_presence', sams)

    def test_date_scope_summary_and_readonly_history(self):
        def latest(_cursor, day, source, retailer='Liverpool'):
            rows = {
                'Walmart': [{**self.walmart, 'star_rating': None}, {**self.walmart, 'id': 11, 'savings': None}],
                "Sam's Club": [self.sams],
            }
            return rows.get(retailer, []), services._mapping(day, source)

        old = {**self.walmart, 'id': 9, 'crawl_datetime': '2026-11-27 09:30:00', 'savings': '$400.00'}
        with patch.object(services, '_latest_rows', side_effect=latest) as loader, \
                patch.object(services, 'exclude_page_absent_records', side_effect=lambda *a, **k: (a[2], [])), \
                patch.object(services, '_history_rows', return_value=[old]) as history:
            prior = services.get_sem_cross_field_summary(None, date(2026, 11, 26), 'sem_tv')
            self.assertNotIn(self.rule_id, [rule['rule_id'] for rule in prior['rule_summary']])
            self.assertEqual(1, loader.call_count)
            summary = services.get_sem_cross_field_summary(None, self.day, 'sem_tv')
            detail = services.get_sem_cross_field_rule_detail(None, self.day, 'sem_tv', self.rule_id, days=3)
        self.assertEqual(3, summary['total_checked'])
        self.assertEqual(1, summary['passed_records'])
        self.assertEqual(1, summary['review_needed_records'])
        self.assertEqual(2, summary['total_review_needed'])
        self.assertEqual({'received': 2, 'checked': 2, 'failed': 1, 'review_count': 1},
                         summary['retailer_checks']['Walmart'])
        rule_map = {row['rule_key']: row for row in summary['rule_summary']}
        self.assertEqual(['Walmart'], rule_map['mx_tv_rating_count']['retailers'])
        self.assertEqual(1, rule_map['mx_tv_savings_missing']['review_count'])
        rule = next(row for row in summary['rule_summary'] if row['rule_id'] == self.rule_id)
        self.assertEqual({'received': 2, 'checked': 1, 'failed': 1, 'review_count': 0}, rule['retailer_checks']['Walmart'])
        self.assertIn("LOWER('Sam''s Club')", rule['query'])
        self.assertIn("BETWEEN '2026-11-27' AND '2026-11-28'", rule['query'])
        self.assertEqual(['Liverpool'], summary['rule_summary'][0]['retailers'])
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual(['comparison_history', 'target'], [row['row_role'] for row in detail['anomalies']])
        self.assertEqual(['Walmart', 'Walmart'], [row['account_name'] for row in detail['anomalies']])
        self.assertTrue(detail['readonly'])
        self.assertFalse(detail['editable_columns'])
        self.assertEqual('Walmart', history.call_args.kwargs['retailer'])
