import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from apps.common.sem_retail import (
    SEM_SOURCE_CONFIG,
    get_sem_count_status,
    get_sem_required_columns,
)
from apps.dx.dx_layer2.sem_validation import evaluate_format, product_line_for
from apps.dx.dx_layer3.cross_field.sem_services import _failed_rules
from apps.dx.dx_layer1.sem_retail import sem_retail_services


class SemRetailConfigurationTests(unittest.TestCase):
    def test_all_liverpool_product_lines_are_schema_qualified(self):
        self.assertEqual(
            {'sem_tv', 'sem_ref', 'sem_ldy'},
            set(SEM_SOURCE_CONFIG),
        )
        for key, source in SEM_SOURCE_CONFIG.items():
            self.assertEqual('Liverpool', source['retailers'][0])
            self.assertTrue(source['table_name'].startswith('dx_sem.'))
            self.assertEqual(key, product_line_for(source['section_code']))
            self.assertEqual(key, product_line_for(source['table_name']))

    def test_product_specific_required_columns_are_included(self):
        self.assertIn('screen_size', get_sem_required_columns('sem_tv'))
        self.assertIn('ref_capacity', get_sem_required_columns('sem_ref'))
        self.assertIn('ldy_capacity', get_sem_required_columns('sem_ldy'))

    def test_layer1_description_uses_korean_country_name(self):
        current = {
            'retailer': 'Liverpool',
            'batch_id': 'batch',
            'actual_count': 1,
            'main_count': 1,
            'bsr_count': 0,
        }
        with patch.object(
            sem_retail_services.repo,
            'get_latest_batch_counts',
            return_value=current,
        ), patch.object(
            sem_retail_services.repo,
            'get_previous_main_counts',
            return_value=[{'main_count': 1}],
        ):
            result = sem_retail_services.get_layer1_stats(
                object(),
                date(2026, 9, 7),
                datetime(
                    2026, 9, 7, 13, 0,
                    tzinfo=timezone(timedelta(hours=9)),
                ),
            )

        self.assertEqual(
            'SEM 멕시코 Liverpool TV/REF/LDY 일일 수집 현황',
            result['check']['description'],
        )


class SemRetailValidationTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            'country': 'SEM',
            'account_name': 'Liverpool',
            'calendar_week': 'W37',
            'product_url': 'https://www.liverpool.com.mx/tienda/pdp/example/123',
            'final_sku_price': '$13,759.20',
            'original_sku_price': '$15,000.00',
            'star_rating': '4.8',
            'count_of_star_ratings': '20',
            'count_of_reviews': '20',
            'screen_size': '55 inch',
            'ref_capacity': '31 cu ft',
            'ldy_capacity': '22 kg',
        }

    def test_exported_mexico_formats_are_accepted(self):
        for product_line in SEM_SOURCE_CONFIG:
            self.assertEqual([], evaluate_format(self.row, product_line))

    def test_liverpool_bundle_values_and_liter_capacity_are_accepted(self):
        tv_row = {
            **self.row,
            'screen_size': '65 inch / 55 inch / 43 inch',
            'final_sku_price': '$12,999.00 / $7,499.00 / $9,999.00',
        }
        ref_row = {**self.row, 'ref_capacity': '4.5 L'}
        self.assertEqual([], evaluate_format(tv_row, 'sem_tv'))
        self.assertEqual([], evaluate_format(ref_row, 'sem_ref'))

    def test_bad_price_url_and_product_dimension_are_reported(self):
        row = {
            **self.row,
            'final_sku_price': '13759.20',
            'product_url': 'https://example.com/item',
            'screen_size': '55',
        }
        self.assertEqual(
            {'final_sku_price', 'product_url', 'screen_size'},
            set(evaluate_format(row, 'sem_tv')),
        )

    def test_optional_rating_fields_may_all_be_blank(self):
        row = {
            **self.row,
            'star_rating': '',
            'count_of_star_ratings': '',
            'count_of_reviews': '',
            'original_sku_price': '',
        }
        self.assertEqual([], evaluate_format(row, 'sem_tv'))
        self.assertEqual([], _failed_rules(row))

    def test_cross_field_failures_are_classified(self):
        row = {
            **self.row,
            'star_rating': '0',
            'count_of_star_ratings': '5',
            'count_of_reviews': '4',
            'final_sku_price': '$16,000.00',
        }
        self.assertEqual(
            {
                'rating_count_consistency',
                'review_rating_count',
                'final_original_price',
            },
            set(_failed_rules(row)),
        )

    def test_main_count_uses_previous_valid_average(self):
        self.assertEqual(('ok', 100.0), get_sem_count_status(85, [90, 110]))
        self.assertEqual(
            ('critical', 100.0),
            get_sem_count_status(80, [90, 110]),
        )


if __name__ == '__main__':
    unittest.main()
