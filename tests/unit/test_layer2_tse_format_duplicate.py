import unittest
from datetime import date
from unittest.mock import patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


TSE_SOURCES = {
    'tse_tv': {
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
    },
    'tse_ref': {
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
    },
    'tse_ldy': {
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
    },
}


def tse_columns(product_line):
    if product_line != 'tse_tv':
        return {}
    return {
        'Homepro': {
            'retailer': 'homepro',
            'required_columns': [],
            'editable_columns': [
                'final_sku_price', 'original_sku_price', 'savings',
                'count_of_reviews', 'count_of_star_ratings', 'star_rating',
            ],
        },
    }


def shared_stubs():
    retail_columns = module_stub(
        'apps.common.retail_columns',
        validate_field=lambda *_args, **_kwargs: None,
        build_format_error_sql=lambda *_args, **_kwargs: 'FALSE',
        build_per_field_error_sql=lambda *_args, **_kwargs: [],
        get_editable_columns=lambda *_args, **_kwargs: [],
        get_duplicate_key_columns=lambda *_args, **_kwargs: None,
        get_retailer_list=lambda: ['Amazon', 'Bestbuy', 'Walmart'],
        get_retail_duplicate_keys=lambda *_args, **_kwargs: [],
        get_tse_retailer_columns=tse_columns,
    )
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_table=lambda name: name,
        ),
        'apps.common.retail_columns': retail_columns,
        'apps.common.tse_retail': module_stub(
            'apps.common.tse_retail',
            TSE_COUNTRY='TSE',
            TSE_SOURCE_CONFIG=TSE_SOURCES,
            get_tse_editable_columns=lambda _product_line: (
                'final_sku_price', 'original_sku_price', 'savings',
                'count_of_reviews', 'count_of_star_ratings', 'star_rating',
            ),
            get_tse_format_fields=lambda product_line, retailer: {
                'tse_tv': (
                    'product_url', 'final_sku_price',
                    'original_sku_price', 'savings', 'count_of_reviews',
                    'count_of_star_ratings', 'star_rating', 'screen_size',
                ),
                'tse_ref': (
                    'product_url', 'final_sku_price',
                    'original_sku_price', 'savings', 'count_of_reviews',
                    'count_of_star_ratings', 'star_rating', 'ref_capacity',
                    'ref_refrigerator_type',
                ),
                'tse_ldy': (
                    'product_url', 'final_sku_price',
                    'original_sku_price', 'savings', 'count_of_reviews',
                    'count_of_star_ratings', 'star_rating', 'ldy_capacity',
                    'ldy_loading_type',
                ),
            }[product_line] if str(retailer).lower() == 'lazada' else (),
            tse_retailer_include_unassigned=lambda _retailer: False,
            tse_retailer_supports_column=lambda *_args: True,
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda *_args: 'TRUE',
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


class TSEFormatValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'layer2_tse_format_service_under_test',
            stubs=shared_stubs(),
        )

    def valid_row(self, **overrides):
        row = {
            'final_sku_price': '฿10,820',
            'original_sku_price': '฿13,820',
            'savings': '฿3,000 (-3%)',
            'count_of_reviews': '128',
            'count_of_star_ratings': '128',
            'star_rating': '4.5',
            'item': 'not-validated',
            'product_url': 'not a url',
            'account_name': 'not-homepro',
            'country': 'not-tse',
        }
        row.update(overrides)
        return row

    def test_valid_baht_savings_counts_and_rating(self):
        self.assertEqual(
            {}, self.service.evaluate_tse_format_row(self.valid_row())
        )
        self.assertEqual(
            {}, self.service.evaluate_tse_format_row(self.valid_row(
                count_of_reviews='1,234',
                count_of_star_ratings='1,234',
            ))
        )

    def test_requested_identity_and_url_fields_are_not_format_rules(self):
        errors = self.service.evaluate_tse_format_row(self.valid_row())
        self.assertFalse({'item', 'product_url', 'account_name', 'country'} & set(errors))
        rule_fields = {rule['field'] for rule in self.service.TSE_FORMAT_RULES}
        self.assertFalse({'item', 'product_url', 'account_name', 'country'} & rule_fields)

    def test_prices_require_baht_and_grouped_thousands(self):
        errors = self.service.evaluate_tse_format_row(self.valid_row(
            final_sku_price='10,820',
            original_sku_price='฿13820',
        ))
        self.assertEqual(
            {'final_sku_price', 'original_sku_price'}, set(errors)
        )

    def test_out_of_stock_final_price_and_zero_percent_savings_are_valid(self):
        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(self.valid_row(
                final_sku_price='สินค้าหมด',
            )),
        )
        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(self.valid_row(
                final_sku_price='฿6,490',
                original_sku_price='฿6,499',
                savings='฿9 (-0%)',
            )),
        )

    def test_original_and_savings_are_one_way_optional_pair(self):
        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(self.valid_row(
                original_sku_price=None, savings=None,
            )),
        )
        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(self.valid_row(
                original_sku_price='-', savings='-',
            )),
        )
        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(self.valid_row(
                final_sku_price='฿5,990',
                original_sku_price='฿6,290',
                savings='-',
            )),
        )
        self.assertIn(
            'original_sku_price',
            self.service.evaluate_tse_format_row(self.valid_row(
                original_sku_price=None,
            )),
        )

    def test_savings_counts_and_rating_are_strict(self):
        errors = self.service.evaluate_tse_format_row(self.valid_row(
            savings='฿3,000 (3%)',
            count_of_reviews='1.5',
            count_of_star_ratings='-1',
            star_rating='5.5',
        ))
        self.assertEqual({
            'savings', 'count_of_reviews', 'count_of_star_ratings',
            'star_rating',
        }, set(errors))

    def test_lotuss_tv_uses_percentage_savings_and_ignores_reviews(self):
        row = {
            'account_name': 'Lotuss',
            'item': '51397644',
            'product_url': (
                'https://www.lotuss.com/th/product/'
                'hisense32a3100g32-51397644'
            ),
            'final_sku_price': '฿3,790',
            'original_sku_price': '฿8,990',
            'savings': '-57%',
            'screen_size': '32 inch',
            'count_of_reviews': 'not-supported',
            'count_of_star_ratings': 'not-supported',
            'star_rating': 'not-supported',
        }

        self.assertEqual(
            {},
            self.service.evaluate_tse_format_row(
                row, 'tse_tv', 'Lotuss'
            ),
        )

    def test_lotuss_out_of_stock_is_exact_and_null_pair_is_not_format_error(self):
        base = {
            'account_name': 'Lotuss',
            'item': '50173824',
            'product_url': (
                'https://www.lotuss.com/th/product/50173824'
            ),
            'final_sku_price': 'Out of stock',
            'screen_size': '32 inch',
        }
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            base, 'tse_tv', 'Lotuss'
        ))
        errors = self.service.evaluate_tse_format_row(
            {
                **base,
                'final_sku_price': 'out of stock',
                'original_sku_price': '฿8,990',
            },
            'tse_tv', 'Lotuss',
        )
        self.assertEqual({'final_sku_price'}, set(errors))
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            {
                **base,
                'original_sku_price': None,
                'savings': '-57%',
            },
            'tse_tv', 'Lotuss',
        ))

    def test_lotuss_ref_capacity_accepts_cu_ft_l_and_liter(self):
        base = {
            'account_name': 'Lotuss',
            'item': '50840542',
            'product_url': (
                'https://www.lotuss.com/th/product/50840542'
            ),
            'final_sku_price': '฿6,790',
            'ref_refrigerator_type': 'Freezer-on-Top (Top Mount)',
        }
        for capacity in ('5.2 cu ft', '300 l', '300 L', '300 liter'):
            with self.subTest(capacity=capacity):
                self.assertEqual({}, self.service.evaluate_tse_format_row(
                    {**base, 'ref_capacity': capacity},
                    'tse_ref', 'Lotuss',
                ))
        errors = self.service.evaluate_tse_format_row(
            {**base, 'ref_capacity': '300 kg'},
            'tse_ref', 'Lotuss',
        )
        self.assertIn('ref_capacity', errors)

    def test_lotuss_ldy_optional_loading_type_validates_when_present(self):
        base = {
            'account_name': 'Lotuss',
            'item': '50548802',
            'product_url': (
                'https://www.lotuss.com/th/product/50548802'
            ),
            'final_sku_price': '฿9,990',
            'ldy_capacity': '10 kg',
        }
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            base, 'tse_ldy', 'Lotuss'
        ))
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            {**base, 'ldy_loading_type': 'Twin Tub'},
            'tse_ldy', 'Lotuss'
        ))
        self.assertIn(
            'ldy_loading_type',
            self.service.evaluate_tse_format_row(
                {**base, 'ldy_loading_type': 'Unknown'},
                'tse_ldy', 'Lotuss',
            ),
        )

    def test_lazada_accepts_integer_one_and_two_decimal_prices(self):
        base = {
            'account_name': 'Lazada',
            'item': '1000366675',
            'product_url': (
                'https://www.lazada.co.th/products/'
                'pdp-i1000366675.html'
            ),
            'savings': '-54%',
            'count_of_reviews': '585',
            'count_of_star_ratings': '585',
            'star_rating': '4.9',
            'screen_size': '32 inch',
        }
        price_pairs = (
            ('\u0e3f1,390', '\u0e3f2,999'),
            ('\u0e3f3,288.3', '\u0e3f4,699.9'),
            ('\u0e3f2,656.83', '\u0e3f3,590.00'),
        )
        for final_price, original_price in price_pairs:
            with self.subTest(final_price=final_price):
                self.assertEqual({}, self.service.evaluate_tse_format_row(
                    {
                        **base,
                        'final_sku_price': final_price,
                        'original_sku_price': original_price,
                    },
                    'tse_tv', 'Lazada',
                ))

    def test_lazada_item_is_not_a_format_validation_field(self):
        row = {
            'account_name': 'Lazada',
            'item': 'LAZ-ITEM-A_01',
            'product_url': (
                'https://www.lazada.co.th/products/'
                'pdp-i1000366675.html'
            ),
            'final_sku_price': '\u0e3f1,390',
            'original_sku_price': '\u0e3f2,999',
            'savings': '-54%',
            'count_of_reviews': '585',
            'count_of_star_ratings': '585',
            'star_rating': '4.9',
            'screen_size': '32 inch',
        }
        errors = self.service.evaluate_tse_format_row(
            row, 'tse_tv', 'Lazada'
        )
        self.assertNotIn('item', errors)
        self.assertNotIn(
            'item',
            {
                rule['field']
                for rule in self.service._get_tse_static_format_rules(
                    'tse_tv', 'Lazada'
                )
            },
        )

    def test_lazada_product_specific_values_follow_csv_formats(self):
        common = {
            'account_name': 'Lazada',
            'item': '1024616655',
            'product_url': (
                'https://www.lazada.co.th/products/'
                'pdp-i1024616655.html'
            ),
            'final_sku_price': '\u0e3f599',
            'original_sku_price': '\u0e3f1,990',
            'savings': '-70%',
            'count_of_reviews': '16',
            'count_of_star_ratings': '16',
            'star_rating': '4.6',
        }
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            {
                **common,
                'ldy_capacity': '8.5 L',
                'ldy_loading_type': 'Top Load',
            },
            'tse_ldy', 'Lazada',
        ))
        self.assertEqual({}, self.service.evaluate_tse_format_row(
            {
                **common,
                'ref_capacity': '7.3 cu ft',
                'ref_refrigerator_type': 'Multi Door',
            },
            'tse_ref', 'Lazada',
        ))

    def test_static_tse_rule_api_does_not_require_database_rows(self):
        result = self.service.get_format_rules(None, 'tse_tv', 'Homepro')
        self.assertEqual(
            len(self.service.TSE_FORMAT_RULES), len(result['rules'])
        )
        self.assertIn('tse_tv_retail', self.service.VALID_TABLES_FORMAT)
        self.assertIn('tse_tv', self.service.VALID_TABLES_RULES)

    def test_history_query_uses_each_days_latest_retailer_batch(self):
        row = (
            1, 'batch-1', 'TSE', 'Homepro', '1104098', 'SKU-1',
            'MODEL-1', '฿10,820', '฿13,820', '฿3,000 (-3%)',
            '10', '10', '4.5', '2026-08-11 09:10:00', 'https://x',
        )
        cursor = ScriptedCursor([{'fetchall': [row]}])
        result = self.service._fetch_tse_format_rows(
            cursor, date(2026, 8, 10), date(2026, 8, 11),
            TSE_SOURCES['tse_tv'], 'homepro', True,
        )
        sql, params = cursor.calls[0]
        self.assertIn('WITH latest_batches AS', sql)
        self.assertIn('DISTINCT ON', sql)
        self.assertIn('dx_tse.dx_tse_tv_retail_com', sql)
        self.assertEqual('homepro', params[2])
        self.assertEqual('TSE', params[3])
        self.assertEqual('1104098', result[0]['item'])

    def test_stats_append_tse_card_without_changing_legacy_tables(self):
        validation = {'tables': [{'table': 'tv_retail'}]}
        row = self.valid_row(final_sku_price='10,820')
        row['id'] = 1
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, '_fetch_tse_format_rows', return_value=[row]
        ), patch.object(
            self.service, '_load_tse_format_normal_reviews', return_value={}
        ):
            total = self.service._append_tse_format_stats(
                cursor, date(2026, 8, 11), validation
            )

        self.assertEqual(1, total)
        self.assertEqual('tv_retail', validation['tables'][0]['table'])
        self.assertEqual('tse_tv_retail', validation['tables'][1]['table'])
        self.assertEqual(1, validation['tables'][1]['total_issues'])
        self.assertEqual('SAVEPOINT layer2_tse_format_stats', cursor.calls[0][0])
        self.assertEqual('RELEASE SAVEPOINT layer2_tse_format_stats', cursor.calls[1][0])

    def test_stats_apply_unassigned_scope_per_retailer(self):
        configs = {
            'Homepro': {
                'retailer': 'homepro', 'editable_columns': [],
            },
            'Lotuss': {
                'retailer': 'lotuss', 'editable_columns': [],
            },
        }
        validation = {'tables': []}
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, 'get_tse_retailer_columns',
            side_effect=lambda product: configs if product == 'tse_tv' else {},
        ), patch.object(
            self.service, '_fetch_tse_format_rows', return_value=[]
        ) as fetch_rows, patch.object(
            self.service, '_load_tse_format_normal_reviews', return_value={}
        ):
            self.service._append_tse_format_stats(
                cursor, date(2026, 8, 14), validation
            )

        self.assertEqual(False, fetch_rows.call_args_list[0].args[-1])
        self.assertEqual(False, fetch_rows.call_args_list[1].args[-1])
        self.assertEqual(
            ['Homepro', 'Lotuss'],
            [row['retailer'] for row in validation['tables'][0]['retailers']],
        )


class TSEDuplicateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/anomaly_validation/services.py',
            'layer2_tse_duplicate_service_under_test',
            stubs=shared_stubs(),
        )

    @staticmethod
    def row(row_id, item, retailer_sku_name):
        return {
            'id': row_id,
            'item': item,
            'retailer_sku_name': retailer_sku_name,
            'sku': f'SKU-{row_id}',
            'final_sku_price': '฿10,820',
            'crawl_datetime': f'2026-08-11 09:10:0{row_id}',
            'product_url': f'https://example/{row_id}',
        }

    def test_exact_and_item_mapping_conflicts_are_separate_groups(self):
        groups = self.service.build_tse_duplicate_groups([
            self.row(1, 'A', 'MODEL-1'),
            self.row(2, 'A', 'MODEL-1'),
            self.row(3, 'A', 'MODEL-2'),
            self.row(4, 'B', 'MODEL-2'),
        ])
        self.assertEqual({
            '완전 중복', 'Item 매핑 충돌',
        }, {group['duplicate_type'] for group in groups})
        self.assertTrue(all(group['records'] for group in groups))

    def test_retailer_sku_mapped_to_multiple_items_is_not_a_conflict(self):
        groups = self.service.build_tse_duplicate_groups([
            self.row(1, 'A', 'MODEL-1'),
            self.row(2, 'B', 'MODEL-1'),
        ])

        self.assertEqual([], groups)

    def test_blank_item_or_retailer_sku_is_left_to_null_validation(self):
        groups = self.service.build_tse_duplicate_groups([
            self.row(1, None, 'MODEL-1'),
            self.row(2, None, 'MODEL-1'),
            self.row(3, 'A', None),
            self.row(4, 'A', ''),
        ])
        self.assertEqual([], groups)

    def test_tse_detail_is_read_only_and_uses_latest_batch(self):
        rows = [
            (
                1, 'batch-1', 'TSE', 'Homepro', 'A', 'SKU-1',
                'MODEL-1', '฿10,820', '2026-08-11 09:10:01', 'https://x/1',
            ),
            (
                2, 'batch-1', 'TSE', 'Homepro', 'A', 'SKU-2',
                'MODEL-1', '฿10,820', '2026-08-11 09:10:02', 'https://x/2',
            ),
        ]
        cursor = ScriptedCursor([{'fetchall': rows}])
        result = self.service._get_tse_anomaly_detail(
            cursor, date(2026, 8, 11), 'tse_tv_retail',
            'Homepro', 1, 50,
        )
        sql, params = cursor.calls[0]
        self.assertIn('WITH latest_batch AS', sql)
        self.assertIn('dx_tse.dx_tse_tv_retail_com', sql)
        self.assertEqual('TSE', params[2])
        self.assertTrue(result['readonly'])
        self.assertEqual(1, result['results']['total_groups'])
        self.assertNotIn('tse_tv_retail', self.service._DUP_TABLE_CONFIG)
        self.assertIn('tse_tv_retail', self.service.VALID_TABLES_ANOMALY)

    def test_stats_append_read_only_tse_duplicate_card(self):
        rows = [
            self.row(1, 'A', 'MODEL-1'),
            self.row(2, 'A', 'MODEL-1'),
        ]
        validation = {'tables': [{'table': 'tv_retail'}]}
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, '_fetch_tse_duplicate_rows', return_value=rows
        ):
            total = self.service._append_tse_anomaly_stats(
                cursor, date(2026, 8, 11), validation
            )

        self.assertEqual(1, total)
        self.assertEqual('tv_retail', validation['tables'][0]['table'])
        self.assertEqual('tse_tv_retail', validation['tables'][1]['table'])
        self.assertEqual(1, validation['tables'][1]['total_issues'])
        self.assertEqual(
            'SAVEPOINT layer2_tse_duplicate_stats', cursor.calls[0][0]
        )
        self.assertEqual(
            'RELEASE SAVEPOINT layer2_tse_duplicate_stats', cursor.calls[1][0]
        )

    def test_duplicate_stats_apply_unassigned_scope_per_retailer(self):
        configs = {
            'Homepro': {'retailer': 'homepro'},
            'Lotuss': {'retailer': 'lotuss'},
        }
        validation = {'tables': []}
        cursor = ScriptedCursor([{}, {}])
        with patch.object(
            self.service, 'get_tse_retailer_columns',
            side_effect=lambda product: configs if product == 'tse_tv' else {},
        ), patch.object(
            self.service, '_fetch_tse_duplicate_rows', return_value=[]
        ) as fetch_rows:
            self.service._append_tse_anomaly_stats(
                cursor, date(2026, 8, 14), validation
            )

        self.assertEqual(False, fetch_rows.call_args_list[0].args[-1])
        self.assertEqual(False, fetch_rows.call_args_list[1].args[-1])
        self.assertEqual(
            ['Homepro', 'Lotuss'],
            [row['retailer'] for row in validation['tables'][0]['retailers']],
        )


if __name__ == '__main__':
    unittest.main()
