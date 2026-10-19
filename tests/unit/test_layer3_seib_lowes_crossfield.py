import unittest
from datetime import date
from unittest.mock import patch

from apps.common.seib_retail import get_seib_source, latest_scope
from apps.dx.dx_layer3.cross_field import sea_services, seib_services


def seib_row(**overrides):
    row = {
        'count_of_reviews': '12', 'count_of_star_ratings': '12',
        'star_rating': '4,5', 'final_sku_price': '2.070,00 \u20ac',
        'original_sku_price': '2.691,00 \u20ac', 'savings': '23%',
    }
    row.update(overrides)
    return row


class SeibCrossfieldTests(unittest.TestCase):
    def test_discount_rate_uses_floored_european_prices(self):
        self.assertEqual(seib_services.evaluate_seib_row(seib_row()), set())
        self.assertEqual(seib_services._money('2.070,00 \u20ac'), 2070)
        self.assertIn('savings_rate_match', seib_services.evaluate_seib_row(
            seib_row(savings='24%')))
        self.assertNotIn('savings_missing', seib_services.evaluate_seib_row(
            seib_row(final_sku_price='999,99 \u20ac',
                     original_sku_price='1.000,00 \u20ac', savings=None)))
        self.assertIn('savings_missing', seib_services.evaluate_seib_row(
            seib_row(savings=None)))

    def test_all_seven_rules_and_invalid_format_is_not_crossfield(self):
        cases = {
            'review_count_match': {'count_of_reviews': '11'},
            'rating_count_presence': {'star_rating': '0'},
            'final_original_price': {'final_sku_price': '2.691,00 \u20ac'},
            'original_missing': {'original_sku_price': None},
            'final_missing': {'final_sku_price': None},
        }
        for expected, values in cases.items():
            with self.subTest(rule=expected):
                self.assertIn(expected, seib_services.evaluate_seib_row(seib_row(**values)))
        invalid = seib_services.evaluate_seib_row(seib_row(savings='not a percentage'))
        self.assertNotIn('savings_rate_match', invalid)

    def test_all_products_use_raw_date_and_latest_batch(self):
        for product in ('tv', 'ref', 'ldy', 'ldy_dryer'):
            with self.subTest(product=product):
                source = get_seib_source('seib_' + product)
                cte, scope, params = latest_scope(source, '2026-10-14', '2026-10-19')
                self.assertIn('crawl_datetime', cte)
                self.assertIn('batch_id IS NOT DISTINCT FROM', scope)
                self.assertEqual(params[0], '2026-10-18')
                query = seib_services.display_query(source, date(2026, 10, 19))
                self.assertIn("'2026-10-18'", query)
                self.assertIn('batch_id IS NOT DISTINCT FROM', query)
                self.assertNotIn('batch_id::date', query)

    def test_summary_and_detail_use_inspection_day_and_show_prior_history(self):
        class Cursor:
            def execute(self, query, params=None):
                self.query = query

            def fetchall(self):
                if 'FROM public.monitoring_validation_rules' in self.query:
                    return [(i, 'seib_tv_' + key, key, 'MediaMarkt')
                            for i, key in enumerate(seib_services.RULES, 1)]
                if 'SELECT source.*' in self.query:
                    return [
                        dict(seib_row(), id=1, item='A', account_name='MediaMarkt',
                             crawl_datetime='2026-10-18T21:37:34-04:00'),
                        dict(seib_row(savings='24%'), id=2, item='A',
                             account_name='MediaMarkt',
                             crawl_datetime='2026-10-19T21:37:34-04:00'),
                    ]
                return []

        cursor = Cursor()
        with patch.object(seib_services, 'exclude_page_absent_records',
                          side_effect=lambda _, __, rows, **kwargs: (rows, [])):
            summary = seib_services.get_seib_cross_field_summary(
                cursor, date(2026, 10, 19), 'seib_tv')
            detail = seib_services.get_seib_cross_field_rule_detail(
                cursor, date(2026, 10, 19), 'seib_tv', 7, 2)
        self.assertEqual(summary['source_date'], '2026-10-19')
        self.assertEqual(summary['total_checked'], 1)
        self.assertEqual(summary['total_anomalies'], 1)
        self.assertEqual(detail['total_findings'], 1)
        self.assertEqual([row['row_role'] for row in detail['anomalies']],
                         ['comparison_history', 'target'])


class LowesDryerCrossfieldTests(unittest.TestCase):
    def test_dryer_source_and_rules_include_lowes(self):
        source = sea_services._source_for_product_line('sea_ldy_dryer')
        self.assertIn('lowes', tuple(name.lower() for name in source['retailers']))
        self.assertEqual(sea_services._resolve_rule_key({
            'detail_code': 'sea_ldy_dryer_lowes_savings_amount_match',
        }), 'savings_amount_match')

    def test_seven_dryer_rules_match_existing_evaluator(self):
        row = {
            'account_name': 'Lowes', 'star_rating': '4.5',
            'count_of_reviews': '3', 'count_of_star_ratings': '3',
            'final_sku_price': '$900', 'original_sku_price': '$1,000',
            'savings': '$100',
        }
        self.assertEqual(
            sea_services.evaluate_sea_row(row, 'sea_ldy_dryer')
            & sea_services.HOMEDEPOT_RULE_KEYS,
            set(),
        )
        row['savings'] = '$90'
        self.assertIn('savings_amount_match', sea_services.evaluate_sea_row(
            row, 'sea_ldy_dryer'))


if __name__ == '__main__':
    unittest.main()
