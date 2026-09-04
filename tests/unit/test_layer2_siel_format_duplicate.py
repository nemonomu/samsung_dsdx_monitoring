import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SIEL_SOURCES = {
    'siel_tv': {
        'source_key': 'siel_tv',
        'category': 'TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ref': {
        'source_key': 'siel_ref',
        'category': 'REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
    'siel_ldy': {
        'source_key': 'siel_ldy',
        'category': 'LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Flipkart'),
    },
}


def shared_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_table=lambda name: name,
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            validate_field=lambda *_args, **_kwargs: None,
            build_format_error_sql=lambda *_args, **_kwargs: 'FALSE',
            build_per_field_error_sql=lambda *_args, **_kwargs: [],
            get_editable_columns=lambda *_args, **_kwargs: [],
            get_duplicate_key_columns=lambda *_args, **_kwargs: None,
            get_retailer_list=lambda: ['Amazon', 'Bestbuy', 'Walmart'],
            get_retail_duplicate_keys=lambda *_args, **_kwargs: [],
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda alias=None: (
                f"NOT ({alias + '.' if alias else ''}account_name = "
                f"'Amazon' AND {alias + '.' if alias else ''}redirect IS TRUE)"
            ),
        ),
        'apps.common.inspection_dates': module_stub(
            'apps.common.inspection_dates',
            resolve_monitoring_date=lambda inspection, country, source_key: {
                'inspection_date': str(inspection),
                'source_date': str(inspection),
                'offset_days': 0,
                'country': country,
                'source_key': source_key,
            },
        ),
        'apps.common.sea_retail': module_stub(
            'apps.common.sea_retail', SEA_RETAIL_SOURCES={},
        ),
        'apps.common.siel_retail': module_stub(
            'apps.common.siel_retail',
            SIEL_BUSINESS_TIMEZONE='Asia/Seoul',
            SIEL_SOURCE_CONFIG=SIEL_SOURCES,
            get_siel_format_editable_columns=lambda product, retailer: [
                'account_name', 'calendar_week', 'country',
                'detailed_review_content', 'original_sku_price',
                'page_type', 'product', 'product_url', 'star_rating',
                *(
                    ['final_sku_price', 'count_of_star_ratings',
                     'screen_size', 'estimated_annual_electricity_use',
                     'model_year']
                    if product == 'siel_tv'
                    and str(retailer).lower() == 'amazon' else []
                ),
            ],
        ),
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
        'apps.dx.dx_layer2.common': package_stub(
            'apps.dx.dx_layer2.common'
        ),
        'apps.dx.dx_layer2.common.context': module_stub(
            'apps.dx.dx_layer2.common.context',
            get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
        ),
    }


class SIELFormatValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'layer2_siel_format_service_under_test',
            stubs=shared_stubs(),
        )

    def test_siel_rules_include_common_fields_without_rank_fields(self):
        result = self.service.get_format_rules(
            None, 'siel_tv', 'Amazon'
        )
        fields = {rule['field'] for rule in result['rules']}

        self.assertIn('siel_tv_retail', self.service.VALID_TABLES_FORMAT)
        self.assertIn('siel_tv', self.service.VALID_TABLES_RULES)
        self.assertIn('screen_size', fields)
        self.assertTrue({
            'account_name', 'calendar_week', 'country',
            'detailed_review_content', 'original_sku_price', 'page_type',
            'product', 'product_url', 'star_rating',
        }.issubset(fields))
        self.assertFalse({
            'sku', 'retailer_sku_name',
            'rank_1', 'rank_2', 'main_rank', 'bsr_rank',
        } & fields)

    def test_flipkart_rules_are_present_without_sea_rank_fields(self):
        for source_key in ('siel_tv', 'siel_ref', 'siel_ldy'):
            with self.subTest(source_key=source_key):
                result = self.service.get_format_rules(
                    None, source_key, 'Flipkart'
                )
                fields = {rule['field'] for rule in result['rules']}
                self.assertTrue(fields)
                self.assertFalse({
                    'rank_1', 'rank_2', 'main_rank', 'bsr_rank',
                } & fields)

    def test_amazon_price_statuses_are_valid_but_bad_rupee_is_not(self):
        for price in (
            '₹10,999', 'Currently unavailable.',
            'No featured offers available',
        ):
            with self.subTest(price=price):
                errors = self.service.evaluate_siel_format_row(
                    {'final_sku_price': price}, 'siel_tv', 'Amazon'
                )
                self.assertNotIn('final_sku_price', errors)

        errors = self.service.evaluate_siel_format_row(
            {'final_sku_price': '₹10,99'}, 'siel_tv', 'Amazon'
        )
        self.assertIn('final_sku_price', errors)

    def test_flipkart_price_does_not_accept_amazon_status(self):
        errors = self.service.evaluate_siel_format_row(
            {'final_sku_price': 'Currently unavailable.'},
            'siel_tv', 'Flipkart',
        )
        self.assertIn('final_sku_price', errors)

    def test_rating_shape_is_layer2_but_range_and_counts_stay_layer3(self):
        for rating in ('No customer reviews', '5.5'):
            with self.subTest(rating=rating):
                errors = self.service.evaluate_siel_format_row(
                    {
                        'star_rating': rating,
                        'count_of_star_ratings': '1',
                    },
                    'siel_tv', 'Amazon',
                )
                self.assertNotIn('star_rating', errors)

        errors = self.service.evaluate_siel_format_row(
            {'star_rating': 'unexpected text'}, 'siel_tv', 'Amazon'
        )
        self.assertIn('star_rating', errors)

    def test_common_fields_follow_siel_csv_shapes(self):
        amazon_valid = self.service.evaluate_siel_format_row({
            'account_name': 'Amazon',
            'calendar_week': 'w33',
            'country': 'SIEL',
            'detailed_review_content': 'review1 - Good picture',
            'original_sku_price': '₹12,999',
            'page_type': 'main',
            'product': 'TV',
            'product_url': 'https://www.amazon.in/dp/B0FNCLVRW5',
            'star_rating': 'No customer reviews',
        }, 'siel_tv', 'Amazon')
        flipkart_valid = self.service.evaluate_siel_format_row({
            'account_name': 'Flipkart',
            'calendar_week': 'w28',
            'country': 'SIEL',
            'detailed_review_content': 'review1 - Clear display',
            'original_sku_price': '₹89,999',
            'page_type': 'bsr',
            'product': 'TV',
            'product_url': (
                'https://www.flipkart.com/tv/p/itmf2fd16e9d1284'
                '?pid=TVSHM58EGYMZKGF2'
            ),
            'star_rating': '4.3',
        }, 'siel_tv', 'Flipkart')
        self.assertEqual({}, amazon_valid)
        self.assertEqual({}, flipkart_valid)

        invalid = self.service.evaluate_siel_format_row({
            'account_name': 'Other',
            'calendar_week': 'W54',
            'country': 'SEA',
            'detailed_review_content': 'Good picture',
            'original_sku_price': '12,999',
            'page_type': 'search',
            'product': 'REF',
            'product_url': 'https://example.com/product',
            'star_rating': 'great',
        }, 'siel_tv', 'Amazon')
        self.assertEqual({
            'account_name', 'calendar_week', 'country',
            'detailed_review_content', 'original_sku_price', 'page_type',
            'product', 'product_url', 'star_rating',
        }, set(invalid))

    def test_retailer_specific_screen_size_formats(self):
        amazon_valid = self.service.evaluate_siel_format_row(
            {'screen_size': '43 Inches'}, 'siel_tv', 'Amazon'
        )
        amazon_invalid = self.service.evaluate_siel_format_row(
            {'screen_size': '109.22 Centimetres'}, 'siel_tv', 'Amazon'
        )
        flipkart_valid = self.service.evaluate_siel_format_row(
            {'screen_size': '163.83 cm (65 inch)'},
            'siel_tv', 'Flipkart',
        )

        self.assertNotIn('screen_size', amazon_valid)
        self.assertIn('screen_size', amazon_invalid)
        self.assertNotIn('screen_size', flipkart_valid)

    def test_capacity_rules_follow_confirmed_siel_units(self):
        amazon_ref = self.service.evaluate_siel_format_row(
            {'ref_capacity': '3.3 cubic feet'}, 'siel_ref', 'Amazon'
        )
        amazon_ref_csv = self.service.evaluate_siel_format_row(
            {'ref_capacity': '4.4 cubic feet'}, 'siel_ref', 'Amazon'
        )
        amazon_ref_invalid = self.service.evaluate_siel_format_row(
            {'ref_capacity': 'Standard'}, 'siel_ref', 'Amazon'
        )
        flipkart_ref = self.service.evaluate_siel_format_row(
            {'ref_capacity': '192 L'}, 'siel_ref', 'Flipkart'
        )
        amazon_ldy = self.service.evaluate_siel_format_row(
            {'ldy_capacity': '800 g'}, 'siel_ldy', 'Amazon'
        )

        self.assertNotIn('ref_capacity', amazon_ref)
        self.assertNotIn('ref_capacity', amazon_ref_csv)
        self.assertIn('ref_capacity', amazon_ref_invalid)
        self.assertNotIn('ref_capacity', flipkart_ref)
        self.assertNotIn('ldy_capacity', amazon_ldy)

    def test_amazon_kilowatts_value_from_csv_is_valid(self):
        errors = self.service.evaluate_siel_format_row(
            {'estimated_annual_electricity_use': '141 Kilowatts'},
            'siel_tv', 'Amazon',
        )
        self.assertNotIn('estimated_annual_electricity_use', errors)

    def test_counts_energy_and_year_validate_shape_only(self):
        errors = self.service.evaluate_siel_format_row(
            {
                'count_of_reviews': '1.5K',
                'count_of_star_ratings': '1,23',
                'estimated_annual_electricity_use': (
                    '200 W, 0.5, 0.5 W (Standby)'
                ),
                'model_year': '2026년',
            },
            'siel_tv', 'Flipkart',
        )
        self.assertEqual({
            'count_of_reviews', 'count_of_star_ratings',
            'estimated_annual_electricity_use', 'model_year',
        }, set(errors))

    def test_query_uses_kst_day_latest_main_batch_and_redirect_scope(self):
        row = (
            1, 'a_20260902_203000', 'SIEL', 'TV', 'Amazon', 'main',
            'B001', 'SKU-1', 'TV 1', 'w36', 'review1 - Good',
            '₹12,999', 'https://www.amazon.in/dp/B0FNCLVRW5', '4.3',
            '₹10,999', '10', '43 Inches', '164.25 Kilowatt Hours', '2026',
            datetime(2026, 9, 2, 23, 10, tzinfo=timezone.utc),
        )
        cursor = ScriptedCursor([{'fetchall': [row]}])
        result = self.service._fetch_siel_format_rows(
            cursor, date(2026, 9, 3), date(2026, 9, 3),
            SIEL_SOURCES['siel_tv'], 'Amazon',
        )
        sql, params = cursor.calls[0]

        self.assertIn('WITH latest_batches AS', sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
        self.assertIn("= 'main'", sql)
        self.assertNotIn("IN ('main', 'bsr')", sql)
        self.assertEqual(
            1,
            sql.count('LOWER(BTRIM(CAST(source.account_name AS TEXT)))'),
        )
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertIn('source.redirect IS TRUE', sql)
        self.assertEqual(5, len(params))
        self.assertEqual('2026-09-03', params[0])
        self.assertEqual('B001', result[0]['item'])

    def test_detail_displays_timestamptz_in_kst(self):
        row = {
            'id': 1,
            'item': 'B001',
            'screen_size': '109.22 Centimetres',
            'crawl_datetime': datetime(
                2026, 9, 2, 23, 10, tzinfo=timezone.utc
            ),
            'product_url': 'https://www.amazon.in/dp/B0FNCLVRW5',
        }
        with patch.object(
            self.service, '_fetch_siel_format_rows', return_value=[row]
        ), patch.object(
            self.service, '_load_siel_format_normal_reviews', return_value={}
        ):
            result = self.service._get_siel_format_detail(
                ScriptedCursor([]), date(2026, 9, 3),
                'siel_tv_retail', 'Amazon', 1,
            )

        self.assertEqual('2026-09-03 08:10:00', result['results'][0][
            'crawl_datetime'
        ])
        self.assertEqual({'screen_size': 1}, result['field_counts'])
        self.assertIn('screen_size', result['editable_cols'])
        self.assertIn('product_url', result['editable_cols'])
        self.assertNotIn('batch_id', result['editable_cols'])

    def test_stats_append_all_three_siel_cards(self):
        validation = {'tables': [{'table': 'tv_retail'}]}
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, '_fetch_siel_format_rows', return_value=[]
        ), patch.object(
            self.service, '_load_siel_format_normal_reviews', return_value={}
        ):
            total = self.service._append_siel_format_stats(
                cursor, date(2026, 9, 3), validation
            )

        self.assertEqual(0, total)
        self.assertEqual(
            ['siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'],
            [table['table'] for table in validation['tables'][1:]],
        )


class SIELDuplicateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/anomaly_validation/services.py',
            'layer2_siel_duplicate_service_under_test',
            stubs=shared_stubs(),
        )

    @staticmethod
    def row(row_id, page_type, item, sku='SKU-1', name='Product 1'):
        return {
            'id': row_id,
            'page_type': page_type,
            'item': item,
            'sku': sku,
            'retailer_sku_name': name,
            'final_sku_price': '₹10,999',
            'crawl_datetime': datetime(
                2026, 9, 2, 23, 10 + row_id, tzinfo=timezone.utc
            ),
            'product_url': f'https://example/{row_id}',
        }

    def test_page_type_and_item_define_duplicate_groups(self):
        groups = self.service.build_siel_duplicate_groups([
            self.row(1, 'main', 'A'),
            self.row(2, 'MAIN', 'A'),
            self.row(3, 'bsr', 'A'),
        ])

        self.assertEqual(1, len(groups))
        self.assertEqual('완전 중복', groups[0]['duplicate_type'])
        self.assertEqual('MAIN', groups[0]['page_type'])

    def test_sku_or_name_difference_is_mapping_conflict(self):
        groups = self.service.build_siel_duplicate_groups([
            self.row(1, 'main', 'A'),
            self.row(2, 'main', 'A', sku='SKU-2'),
        ])
        self.assertEqual('상품 매핑 충돌', groups[0]['duplicate_type'])

    def test_blank_item_is_left_to_null_validation(self):
        groups = self.service.build_siel_duplicate_groups([
            self.row(1, 'main', ''),
            self.row(2, 'main', None),
        ])
        self.assertEqual([], groups)

    def test_detail_is_read_only_and_uses_kst_latest_batch(self):
        rows = [
            (
                1, 'a_20260902_203000', 'SIEL', 'Amazon', 'main', 'A',
                'SKU-1', 'Product 1', '₹10,999',
                datetime(2026, 9, 2, 23, 10, tzinfo=timezone.utc),
                'https://example/1',
            ),
            (
                2, 'a_20260902_203000', 'SIEL', 'Amazon', 'MAIN', 'A',
                'SKU-1', 'Product 1', '₹10,999',
                datetime(2026, 9, 2, 23, 11, tzinfo=timezone.utc),
                'https://example/2',
            ),
        ]
        cursor = ScriptedCursor([{'fetchall': rows}])
        result = self.service._get_siel_anomaly_detail(
            cursor, date(2026, 9, 3), 'siel_tv_retail',
            'Amazon', 1, 50,
        )
        sql, params = cursor.calls[0]

        self.assertIn('WITH latest_batch AS', sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
        self.assertIn('source.redirect IS TRUE', sql)
        self.assertEqual('2026-09-03', params[0])
        self.assertTrue(result['readonly'])
        self.assertEqual(1, result['results']['total_groups'])
        self.assertEqual(
            '2026-09-03 08:10:00',
            result['results']['duplicates'][0]['records'][0][
                'crawl_datetime'
            ],
        )
        self.assertNotIn('siel_tv_retail', self.service._DUP_TABLE_CONFIG)

    def test_stats_append_all_three_siel_cards(self):
        validation = {'tables': [{'table': 'tv_retail'}]}
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, '_fetch_siel_duplicate_rows', return_value=[]
        ):
            total = self.service._append_siel_anomaly_stats(
                cursor, date(2026, 9, 3), validation
            )

        self.assertEqual(0, total)
        self.assertEqual(
            ['siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'],
            [table['table'] for table in validation['tables'][1:]],
        )


if __name__ == '__main__':
    unittest.main()
