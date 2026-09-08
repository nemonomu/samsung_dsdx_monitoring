import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from apps.common.sem_retail import (
    SEM_SOURCE_CONFIG,
    get_sem_collection_phase,
    get_sem_count_status,
    get_sem_required_columns,
    get_sem_table_columns,
)
from apps.dx.dx_layer2.sem_validation import (
    _load_normal_reviews,
    append_null_stats,
    duplicate_detail,
    evaluate_format,
    format_detail,
    get_format_rule_details,
    get_review_allowed_columns,
    null_detail,
    product_line_for,
)
from apps.dx.dx_layer2.format_validation.services import (
    VALID_TABLES_RULES,
    get_format_rules,
)
from apps.dx.dx_layer3.cross_field.sem_services import (
    _failed_rules,
    get_sem_cross_field_rule_detail,
    get_sem_cross_field_summary,
)
from apps.dx.dx_layer1.sem_retail import sem_retail_services
from tests.unit.support import ScriptedCursor


class SemRetailConfigurationTests(unittest.TestCase):
    def test_collection_uses_kst_0900_to_1100_window(self):
        self.assertEqual('pending', get_sem_collection_phase(time(8, 59, 59)))
        self.assertEqual('collecting', get_sem_collection_phase(time(9, 0)))
        self.assertEqual('collecting', get_sem_collection_phase(time(11, 0)))
        self.assertEqual('complete', get_sem_collection_phase(time(11, 0, 1)))

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

    def test_table_columns_include_full_schema_and_product_fields(self):
        for product_line, extra_column in (
            ('sem_tv', 'screen_size'),
            ('sem_ref', 'ref_refrigerator_type'),
            ('sem_ldy', 'ldy_loading_type'),
        ):
            columns = get_sem_table_columns(product_line)
            self.assertIn('batch_id', columns)
            self.assertIn('main_rank', columns)
            self.assertIn('bsr_rank', columns)
            self.assertIn('savings', columns)
            self.assertIn(extra_column, columns)

    def test_null_columns_match_homepro_style_without_savings(self):
        required = get_sem_required_columns('sem_tv')
        self.assertIn('sku', required)
        self.assertIn('count_of_reviews', required)
        self.assertIn('star_rating', required)
        self.assertIn('count_of_star_ratings', required)
        self.assertNotIn('savings', required)

    def test_format_rule_popup_uses_exact_sem_validation_fields(self):
        product_extras = {
            'sem_tv': {'screen_size'},
            'sem_ref': {'ref_capacity', 'ref_refrigerator_type'},
            'sem_ldy': {'ldy_capacity', 'ldy_loading_type'},
        }
        for product_line, extras in product_extras.items():
            with self.subTest(product_line=product_line):
                expected = set(get_review_allowed_columns(
                    product_line, 'format_check'
                ))
                direct_rules = get_format_rule_details(product_line)
                api_rules = get_format_rules(
                    None, product_line, 'Liverpool'
                )['rules']
                self.assertIn(product_line, VALID_TABLES_RULES)
                self.assertEqual(
                    expected, {rule['field'] for rule in direct_rules}
                )
                self.assertEqual(direct_rules, api_rules)
                self.assertTrue(extras.issubset(expected))

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
            'SEM 멕시코 TV/REF/LDY 일일 수집 현황',
            result['check']['description'],
        )
        self.assertEqual('KST 09:00~11:00', result['check']['collection_window'])

    def test_layer1_truncates_display_average_but_keeps_precise_rate(self):
        current = {
            'retailer': 'Liverpool', 'batch_id': 'batch',
            'actual_count': 196, 'main_count': 196, 'bsr_count': 0,
        }
        with patch.object(
            sem_retail_services.repo,
            'get_latest_batch_counts',
            return_value=current,
        ), patch.object(
            sem_retail_services.repo,
            'get_previous_main_counts',
            return_value=[{'main_count': 196}, {'main_count': 197}],
        ):
            result = sem_retail_services.get_layer1_stats(
                object(), date(2026, 9, 7), datetime(2026, 9, 7, 12, 0)
            )

        self.assertTrue(all(
            category['expected'] == 196
            for category in result['check']['categories']
        ))
        self.assertTrue(all(
            category['expected_precise'] == 196.5
            for category in result['check']['categories']
        ))
        self.assertTrue(all(
            category['rate'] == 99.7
            for category in result['check']['categories']
        ))
        self.assertEqual(588, result['check']['expected'])
        self.assertEqual(99.7, result['check']['rate'])

    def test_layer1_marks_completed_product_ok_during_collection(self):
        def current_counts(_cursor, product_line, _target_date):
            count = 200 if product_line == 'sem_tv' else 0
            return {
                'retailer': 'Liverpool', 'batch_id': product_line,
                'actual_count': count, 'main_count': count, 'bsr_count': 0,
            }

        with patch.object(
            sem_retail_services.repo,
            'get_latest_batch_counts',
            side_effect=current_counts,
        ), patch.object(
            sem_retail_services.repo,
            'get_previous_main_counts',
            return_value=[{'main_count': 200}],
        ):
            check = sem_retail_services.get_layer1_stats(
                object(), date(2026, 9, 7), datetime(2026, 9, 7, 10, 0)
            )['check']

        self.assertEqual('OK', check['categories'][0]['status'])
        self.assertEqual('COLLECTING', check['categories'][1]['status'])
        self.assertEqual('COLLECTING', check['categories'][2]['status'])
        self.assertEqual('COLLECTING', check['status'])


class SemRetailValidationTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            'country': 'SEM',
            'account_name': 'Liverpool',
            'item': '1097076932',
            'crawl_datetime': '2026-09-07 13:32:00',
            'calendar_week': 'W37',
            'product_url': 'https://www.liverpool.com.mx/tienda/pdp/example/123',
            'final_sku_price': '$13,759.20',
            'original_sku_price': '$15,000.00',
            'star_rating': '4.8',
            'count_of_star_ratings': '20',
            'count_of_reviews': '20',
            'screen_size': '55 inch',
            'ref_capacity': '31 cu ft',
            'ref_refrigerator_type': 'French Door',
            'ldy_capacity': '22 kg',
            'ldy_loading_type': 'Front Load',
            'main_rank': 1,
            'bsr_rank': 2,
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

    def test_identity_date_rank_and_product_type_formats_are_reported(self):
        row = {
            **self.row,
            'item': 'item-1',
            'crawl_datetime': 'not-a-date',
            'main_rank': 0,
            'bsr_rank': '-1',
            'ref_refrigerator_type': 'Bottom Freezer',
        }
        self.assertEqual(
            {
                'item', 'crawl_datetime', 'main_rank', 'bsr_rank',
                'ref_refrigerator_type',
            },
            set(evaluate_format(row, 'sem_ref')),
        )

        ldy_row = {**self.row, 'ldy_loading_type': 'Stacked'}
        self.assertEqual(
            ['ldy_loading_type'], evaluate_format(ldy_row, 'sem_ldy')
        )

    def test_normal_review_metadata_is_loaded_for_reload_badge(self):
        cursor = ScriptedCursor([{'fetchall': [(
            404, 'sku', '확인 메모', 'tester',
            datetime(2026, 9, 7, 14, 30), '항목 부재',
        )]}])

        reviews = _load_normal_reviews(
            cursor, date(2026, 9, 7), 'sem_ref', 'null_check', 'sku'
        )

        self.assertEqual('항목 부재', reviews['404_sku']['reason'])
        self.assertEqual('확인 메모', reviews['404_sku']['memo'])
        self.assertEqual(
            '2026-09-07 14:30:00', reviews['404_sku']['created_at']
        )
        self.assertEqual(
            [
                'dx_sem.dx_sem_ref_retail_com', '2026-09-07',
                'null_check', 'sku',
            ],
            cursor.calls[0][1],
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

    @patch('apps.dx.dx_layer2.sem_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.sem_validation._latest_rows')
    def test_null_stats_use_existing_retailer_ui_contract(
            self, latest_rows, _normal_reviews):
        latest_rows.return_value = ([{
            'country': 'SEM',
            'account_name': 'Liverpool',
            'item': 'item-1',
            'sku': None,
            'product_url': 'https://example.com',
            'retailer_sku_name': 'TV',
            'count_of_reviews': None,
            'star_rating': '4.8',
            'count_of_star_ratings': '20',
            'final_sku_price': '$10.00',
            'screen_size': '55 inch',
            'ref_capacity': '20 cu ft',
            'ldy_capacity': '20 kg',
        }], {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })
        validation = {'tables': []}

        total = append_null_stats(None, date(2026, 9, 7), validation)

        self.assertEqual(6, total)
        retailer = validation['tables'][0]['retailers'][0]
        self.assertEqual(2, retailer['total_null_count'])
        self.assertEqual(1, retailer['fields_detail']['sku'])
        self.assertEqual(1, retailer['fields_detail']['count_of_reviews'])
        self.assertNotIn('issue_count', retailer)
        self.assertNotIn('field_counts', retailer)
        self.assertNotIn('savings', retailer['fields_detail'])

    @patch('apps.dx.dx_layer2.sem_validation._load_normal_reviews')
    @patch('apps.dx.dx_layer2.sem_validation._latest_rows')
    def test_all_layer2_details_are_editable(
            self, latest_rows, normal_reviews):
        normal_reviews.return_value = {
            '1_sku': {
                'reason': '항목 부재', 'memo': '', 'created_id': 'tester',
                'created_at': '2026-09-07 14:00:00',
            },
        }
        rows = [{
            **self.row,
            'id': 1,
            'item': 'item-1',
            'sku': None,
            'retailer_sku_name': 'TV',
            'crawl_datetime': '2026-09-07 10:00:00',
        }, {
            **self.row,
            'id': 2,
            'item': 'item-1',
            'sku': 'sku-2',
            'retailer_sku_name': 'TV',
            'crawl_datetime': '2026-09-07 10:00:00',
        }]
        latest_rows.return_value = (rows, {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })

        null_result = null_detail(
            None, date(2026, 9, 7), 'sem_tv', 'sku'
        )
        format_result = format_detail(
            None, date(2026, 9, 7), 'sem_tv'
        )
        duplicate_result = duplicate_detail(
            None, date(2026, 9, 7), 'sem_tv'
        )

        for result in (null_result, format_result, duplicate_result):
            self.assertFalse(result['readonly'])
            self.assertIn('sku', result['editable_cols'])
            self.assertNotIn('savings', result['editable_cols'])
            self.assertEqual(
                'dx_sem.dx_sem_tv_retail_com', result['actual_table']
            )

        self.assertIn('batch_id', null_result['select_cols'])
        self.assertIn('main_rank', null_result['select_cols'])
        self.assertIn('bsr_rank', null_result['select_cols'])
        self.assertEqual(
            '항목 부재', null_result['normal_reviews']['1_sku']['reason']
        )
        self.assertEqual(
            '항목 부재', format_result['normal_reviews']['1_sku']['reason']
        )

        rating_result = null_detail(
            None, date(2026, 9, 7), 'sem_tv', 'star_rating'
        )
        rating_columns = rating_result['display_config']['star_rating'][
            'select_columns'
        ]
        self.assertIn('star_rating', rating_columns)
        self.assertIn('count_of_star_ratings', rating_columns)
        self.assertIn('count_of_reviews', rating_columns)

    @patch('apps.dx.dx_layer2.sem_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.sem_validation._history_rows')
    @patch('apps.dx.dx_layer2.sem_validation._latest_rows')
    def test_null_detail_expands_target_items_to_daily_history(
            self, latest_rows, history_rows, _normal_reviews):
        latest_rows.return_value = ([{
            **self.row,
            'id': 3,
            'item': 'item-1',
            'sku': None,
            'crawl_datetime': '2026-09-07 10:00:00',
        }], {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })
        history_rows.return_value = [
            {**self.row, 'id': day, 'item': 'item-1', 'sku': value,
             'crawl_datetime': f'2026-09-0{day} 10:00:00'}
            for day, value in ((5, 'old-1'), (6, 'old-2'), (7, None))
        ]

        result = null_detail(
            None, date(2026, 9, 7), 'sem_tv', 'sku', days=3
        )

        self.assertEqual([5, 6, 7], [row['id'] for row in result['results']])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(3, result['history_days'])
        history_rows.assert_called_once()
        args = history_rows.call_args.args
        self.assertEqual(date(2026, 9, 5), args[2])
        self.assertEqual(date(2026, 9, 7), args[3])
        self.assertEqual(['item-1'], args[4])

    @patch('apps.dx.dx_layer2.sem_validation._load_normal_reviews', return_value={})
    @patch('apps.dx.dx_layer2.sem_validation._history_rows')
    @patch('apps.dx.dx_layer2.sem_validation._latest_rows')
    def test_format_detail_expands_history_and_exposes_all_table_columns(
            self, latest_rows, history_rows, _normal_reviews):
        latest_rows.return_value = ([{
            **self.row,
            'id': 3,
            'item': '1097076932',
            'screen_size': '55',
        }], {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })
        history_rows.return_value = [
            {
                **self.row,
                'id': day,
                'item': '1097076932',
                'screen_size': value,
                'crawl_datetime': f'2026-09-0{day} 10:00:00',
            }
            for day, value in ((5, '55 inch'), (6, '55 inch'), (7, '55'))
        ]

        result = format_detail(
            None, date(2026, 9, 7), 'sem_tv', days=3
        )

        self.assertEqual([5, 6, 7], [row['id'] for row in result['results']])
        self.assertEqual({'screen_size': 1}, result['field_counts'])
        self.assertTrue(result['supports_day_history'])
        self.assertEqual(3, result['history_days'])
        self.assertIn('batch_id', result['select_cols'])
        self.assertIn('savings', result['select_cols'])
        self.assertIn('main_rank', result['select_cols'])
        self.assertIn('bsr_rank', result['select_cols'])
        history_rows.assert_called_once()

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

    def test_rating_and_review_presence_mismatch_uses_rating_rule(self):
        rating_only = _failed_rules({
            **self.row,
            'count_of_reviews': None,
        })
        review_only = _failed_rules({
            **self.row,
            'star_rating': None,
        })

        self.assertIn('rating_count_consistency', rating_only)
        self.assertIn('rating_count_consistency', review_only)

    def test_original_price_zero_is_reported_without_price_reversal(self):
        errors = set(_failed_rules({
            **self.row,
            'final_sku_price': '$100.00',
            'original_sku_price': '$0.00',
        }))

        self.assertIn('original_price_zero', errors)
        self.assertNotIn('final_original_price', errors)

    @patch('apps.dx.dx_layer3.cross_field.sem_services._latest_rows')
    def test_cross_field_summary_exposes_only_agreed_rules(self, latest_rows):
        latest_rows.return_value = ([], {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })

        result = get_sem_cross_field_summary(
            None, date(2026, 9, 7), 'sem_tv'
        )

        self.assertEqual(
            [
                'rating_count_consistency',
                'review_rating_count',
                'final_original_price',
                'original_price_zero',
            ],
            [rule['rule_key'] for rule in result['rule_summary']],
        )
        self.assertNotIn(
            'savings',
            '|'.join(rule['select_fields'] for rule in result['rule_summary']),
        )
        rating_rules = result['rule_summary'][:2]
        self.assertTrue(all(
            rule['select_fields'] == (
                'star_rating|count_of_star_ratings|count_of_reviews'
            )
            for rule in rating_rules
        ))

    @patch('apps.dx.dx_layer3.cross_field.sem_services._latest_rows')
    def test_cross_field_detail_is_editable(self, latest_rows):
        latest_rows.return_value = ([{
            **self.row,
            'id': 1,
            'item': 'item-1',
            'final_sku_price': '$100.00',
            'original_sku_price': '$0.00',
        }], {
            'inspection_date': '2026-09-07',
            'source_date': '2026-09-07',
            'offset_days': 0,
        })

        result = get_sem_cross_field_rule_detail(
            None,
            date(2026, 9, 7),
            'sem_tv',
            'sem_tv:original_price_zero',
        )

        self.assertTrue(result['found'])
        self.assertIn('original_sku_price', result['editable_columns'])
        self.assertNotIn('savings', result['editable_columns'])
        selector_columns = result['retailer_columns']['Liverpool']
        self.assertIn('batch_id', selector_columns)
        self.assertIn('main_rank', selector_columns)
        self.assertIn('bsr_rank', selector_columns)
        self.assertIn('savings', selector_columns)
        self.assertNotIn('savings', result['editable_columns'])

    def test_main_count_uses_previous_valid_average(self):
        self.assertEqual(('ok', 100.0), get_sem_count_status(85, [90, 110]))
        self.assertEqual(
            ('critical', 100.0),
            get_sem_count_status(80, [90, 110]),
        )


if __name__ == '__main__':
    unittest.main()
