import unittest
from datetime import date

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)
from apps.common import tse_retail


tse_services = load_module(
    'apps/dx/dx_layer3/cross_field/tse_services.py',
    'layer3_tse_crossfield_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.tse_retail': tse_retail,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [
                'count_of_reviews', 'star_rating', 'count_of_star_ratings',
                'final_sku_price', 'original_sku_price', 'savings',
            ],
            get_tse_retailer_columns=lambda *_: {
                'Homepro': {
                    'retailer': 'homepro',
                    'required_columns': ['count_of_reviews', 'star_rating'],
                    'editable_columns': ['original_sku_price', 'savings'],
                },
            },
        ),
    },
)


def _valid_row(**overrides):
    row = {
        'id': 10,
        'batch_id': 'batch-new',
        'country': 'TSE',
        'account_name': 'Homepro',
        'item': 'A-1',
        'crawl_datetime': '2026-08-10T09:10:00+09:00',
        'count_of_reviews': '10',
        'star_rating': '4.5',
        'count_of_star_ratings': '10',
        'final_sku_price': '฿7,990',
        'original_sku_price': '฿11,490',
        'savings': '฿3,500 (-30%)',
    }
    row.update(overrides)
    return row


def _rule(rule_id, rule_key):
    spec = tse_services.TSE_RULE_SPECS[rule_key]
    return {
        'id': rule_id,
        'detail_code': f'tse_{rule_key}',
        'detail_name': spec['detail_name'],
        'section_code': 'tse_tv_retail',
        'section_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
        'date_column': 'crawl_datetime',
        'product_line': 'tse_tv',
        'retailer': 'ALL',
        'field1': spec['field1'],
        'field2': spec['field2'],
        'validation_type': rule_key,
        'error_message': spec['error_message'],
        'select_fields': '',
        'query': '',
        'sort_order': rule_id,
    }


class TseCrossfieldEvaluationTests(unittest.TestCase):
    def test_baht_and_negative_floor_percentage_are_valid(self):
        self.assertEqual(tse_services.evaluate_tse_row(_valid_row()), set())
        self.assertEqual(tse_services.parse_tse_money('THB 10,820'), 10820)

    def test_review_and_zero_pair_rules(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            count_of_reviews='9',
            count_of_star_ratings='10',
            star_rating='0.0',
        ))
        self.assertIn('review_count_match', errors)
        self.assertIn('review_zero_pair', errors)

    def test_price_reversal_does_not_cascade_to_savings(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            final_sku_price='฿10,820',
            original_sku_price='฿4,990',
            savings='broken',
        ))
        self.assertEqual(errors, {'savings_format', 'final_original_price'})
        self.assertNotIn('savings_amount_match', errors)
        self.assertNotIn('savings_rate_match', errors)

    def test_missing_original_stops_dependent_savings_rules(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            original_sku_price=None,
            savings='broken',
        ))
        self.assertEqual(errors, {'savings_requires_original'})

    def test_original_zero_stops_dependent_price_rules(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            original_sku_price='฿0',
            final_sku_price='฿100',
            savings='฿20 (-20%)',
        ))
        self.assertEqual(errors, {'original_price_zero'})

    def test_amount_and_floor_rate_mismatches_are_separate(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            savings='฿3,400 (-31%)',
        ))
        self.assertEqual(errors, {'savings_amount_match', 'savings_rate_match'})

    def test_bad_savings_format_is_one_prerequisite_error(self):
        errors = tse_services.evaluate_tse_row(_valid_row(savings='unknown'))
        self.assertEqual(errors, {'savings_format'})

    def test_lazada_percentage_allows_display_price_rounding_tolerance(self):
        errors = tse_services.evaluate_tse_row(_valid_row(
            account_name='Lazada',
            final_sku_price='\u0e3f16,090',
            original_sku_price='\u0e3f28,990',
            savings='-45%',
        ))
        self.assertNotIn('savings_rate_match', errors)


class TseCrossfieldQueryAndSummaryTests(unittest.TestCase):
    def setUp(self):
        tse_services.get_tse_retailer_columns = lambda *_: {
            'Homepro': {
                'retailer': 'homepro',
                'required_columns': ['count_of_reviews', 'star_rating'],
                'editable_columns': ['original_sku_price', 'savings'],
            },
        }

    def _enable_lotuss(self, product_line='tse_tv'):
        def configured(key):
            retailers = {
                'Homepro': {
                    'retailer': 'homepro',
                    'required_columns': ['count_of_reviews', 'star_rating'],
                    'editable_columns': ['original_sku_price', 'savings'],
                },
            }
            if key == product_line:
                retailers['Lotuss'] = {
                    'retailer': 'lotuss',
                    'required_columns': ['item'],
                    'editable_columns': [],
                }
            return retailers

        tse_services.get_tse_retailer_columns = configured

    def test_display_query_is_compact_edit_scope_and_quotes_literals(self):
        query = tse_services.build_tse_display_query(
            date(2026, 8, 10), 'tse_tv',
            _rule(1, 'review_count_match'), days=3,
            retailer="Homepro's", items=["TV'1", 'TV-2'],
        )

        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com', query)
        self.assertNotIn('WITH batches AS', query)
        self.assertIn('retailer_sku_name', query)
        self.assertIn(
            "DATE(crawl_datetime::timestamp) >= DATE '2026-08-08'", query,
        )
        self.assertIn(
            "DATE(crawl_datetime::timestamp) <= DATE '2026-08-11'", query,
        )
        self.assertIn("country = 'TSE'", query)
        self.assertIn("LOWER(TRIM('Homepro''s'))", query)
        self.assertIn("'TV''1'", query)
        self.assertIn("'TV-2'", query)
        self.assertIn('ORDER BY item, crawl_datetime', query)

    def test_display_query_splits_composite_rule_fields_into_allowlisted_columns(self):
        query = tse_services.build_tse_display_query(
            date(2026, 8, 10), 'tse_tv',
            _rule(1, 'savings_amount_match'),
        )

        self.assertIn('    savings,', query)
        self.assertIn('    original_sku_price,', query)
        self.assertIn('    final_sku_price,', query)
        self.assertNotIn('original_sku_price|final_sku_price', query)

    def test_star_zero_pair_display_includes_review_count(self):
        query = tse_services.build_tse_display_query(
            date(2026, 8, 10), 'tse_tv',
            _rule(1, 'review_zero_pair'),
        )

        self.assertIn('    star_rating,', query)
        self.assertIn('    count_of_star_ratings,', query)
        self.assertIn('    count_of_reviews,', query)

    def test_retailer_cloned_rules_are_merged_by_validation_type(self):
        homepro_rule = _rule(1, 'review_zero_pair')
        homepro_rule.update({
            'retailer': 'Homepro',
            'select_fields': (
                'star_rating|count_of_star_ratings|crawl_datetime'
            ),
        })
        lazada_rule = _rule(2, 'review_zero_pair')
        lazada_rule['retailer'] = 'Lazada'
        cursor = ScriptedCursor([{
            'fetchall': [homepro_rule, lazada_rule],
        }])

        rules = tse_services.load_active_tse_rules(cursor, 'tse_tv')

        self.assertEqual(1, len(rules))
        self.assertEqual([1, 2], rules[0]['_source_rule_ids'])
        self.assertEqual(['Homepro', 'Lazada'], rules[0]['_retailers'])
        self.assertIn(
            'count_of_reviews', rules[0]['select_fields'].split('|')
        )

    def test_merged_retailer_rules_do_not_duplicate_findings(self):
        homepro_rule = _rule(1, 'review_count_match')
        homepro_rule['retailer'] = 'Homepro'
        lazada_rule = _rule(2, 'review_count_match')
        lazada_rule['retailer'] = 'Lazada'
        cursor = ScriptedCursor([
            {'fetchall': [homepro_rule, lazada_rule]},
            {'fetchall': [
                _valid_row(
                    id=10, account_name='Homepro', count_of_reviews='9',
                ),
                _valid_row(
                    id=11, account_name='Lazada', item='L-1',
                    count_of_reviews='9',
                ),
            ]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_summary(
            cursor, date(2026, 8, 10), 'tse_tv',
        )

        self.assertEqual(2, result['total_anomalies'])
        self.assertEqual(1, len(result['rule_summary']))
        self.assertEqual(2, result['rule_summary'][0]['error_count'])
        self.assertIn("LOWER(TRIM('Homepro'))", result['rule_summary'][0]['query'])
        self.assertIn("LOWER(TRIM('Lazada'))", result['rule_summary'][0]['query'])

    def test_latest_batch_query_uses_text_date_and_greatest_id(self):
        cursor = ScriptedCursor([{
            'fetchall': [_valid_row()],
        }])
        rows = tse_services.load_latest_tse_rows(
            cursor, date(2026, 8, 10), 'tse_tv',
        )
        sql, params = cursor.calls[0]
        self.assertIn('LEFT(TRIM(crawl_datetime), 10)', sql)
        self.assertIn('MAX(id) AS max_id', sql)
        self.assertIn('ORDER BY max_id DESC', sql)
        self.assertEqual(params, (
            '2026-08-10', '2026-08-10', 'TSE',
            '2026-08-10', '2026-08-10', 'TSE',
        ))
        self.assertEqual(rows[0]['batch_id'], 'batch-new')

    def test_active_metadata_drives_dynamic_retailer_summary(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [_valid_row(
                account_name='homepro', count_of_reviews='9',
            )]},
            {'fetchall': []},
        ])
        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 10), 'tse_tv',
        )
        self.assertEqual(result['total_checked'], 1)
        self.assertEqual(result['failed_records'], 1)
        self.assertEqual(result['total_anomalies'], 1)
        self.assertEqual(result['retailers'][0]['retailer'], 'Homepro')
        self.assertEqual(result['retailers'][0]['batch_id'], 'batch-new')
        self.assertEqual(result['retailers'][0]['rules'][0]['error_count'], 1)
        self.assertEqual(
            result['rule_results'][0]['error_details'][0]['account_name'],
            'Homepro',
        )

    def test_lotuss_review_rules_are_excluded_but_retailer_card_remains(self):
        self._enable_lotuss()
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [
                _valid_row(
                    id=10, account_name='Homepro', count_of_reviews='9',
                ),
                _valid_row(
                    id=11, account_name='lotuss', item='L-1',
                    count_of_reviews='9',
                ),
            ]},
            {'fetchall': []},
        ])

        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 10), 'tse_tv',
        )

        self.assertEqual(2, result['total_checked'])
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(
            ['Homepro'],
            [row['account_name'] for row in result['rule_results'][0]['error_details']],
        )
        lotuss = next(
            row for row in result['retailers']
            if row['retailer'] == 'Lotuss'
        )
        self.assertEqual(0, lotuss['total_errors'])
        self.assertEqual([], lotuss['rules'])

    def test_lotuss_ref_has_no_unsupported_crossfield_rules(self):
        self._enable_lotuss('tse_ref')
        rule = _rule(1, 'savings_requires_original')
        rule.update({
            'section_code': 'tse_ref_retail',
            'table_name': 'dx_tse.dx_tse_ref_retail_com',
            'product_line': 'tse_ref',
        })
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': [_valid_row(
                account_name='Lotuss', item='REF-1',
                original_sku_price=None, savings='-10%',
            )]},
            {'fetchall': []},
        ])

        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 10), 'tse_ref',
        )

        self.assertEqual(1, result['total_checked'])
        self.assertEqual(0, result['total_anomalies'])
        self.assertEqual([], result['retailers'][0]['rules'])

    def test_summary_query_does_not_scope_review_rule_to_lotuss(self):
        self._enable_lotuss()
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [
                _valid_row(account_name='Homepro'),
                _valid_row(id=11, account_name='Lotuss', item='L-1'),
            ]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_summary(
            cursor, date(2026, 8, 10), 'tse_tv',
        )

        query = result['rule_summary'][0]['query']
        self.assertIn("LOWER(TRIM('Homepro'))", query)
        self.assertNotIn("LOWER(TRIM('Lotuss'))", query)

    def test_summary_omits_explicit_unsupported_lotuss_rule(self):
        self._enable_lotuss()
        rule = _rule(1, 'review_count_match')
        rule['retailer'] = 'Lotuss'
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': [
                _valid_row(account_name='Homepro'),
                _valid_row(id=11, account_name='Lotuss', item='L-1'),
            ]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_summary(
            cursor, date(2026, 8, 10), 'tse_tv',
        )

        self.assertEqual([], result['rule_summary'])

    def test_inactive_lotuss_is_removed_but_unknown_retailer_is_preserved(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'final_original_price')]},
            {'fetchall': [
                _valid_row(
                    account_name='Homepro', final_sku_price='90',
                    original_sku_price='100', savings=None,
                ),
                _valid_row(
                    id=11, account_name='Lotuss', item='L-1',
                    final_sku_price='120', original_sku_price='100',
                    savings=None,
                ),
                _valid_row(
                    id=12, account_name='Future Retail', item='F-1',
                    final_sku_price='120', original_sku_price='100',
                    savings=None,
                ),
            ]},
            {'fetchall': []},
        ])

        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 18), 'tse_tv',
        )

        self.assertEqual(2, result['total_checked'])
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(
            ['Future Retail', 'Homepro'],
            [retailer['retailer'] for retailer in result['retailers']],
        )
        self.assertEqual(
            ['Future Retail'],
            [
                row['account_name']
                for row in result['rule_results'][0]['error_details']
            ],
        )

    def test_inactive_lotuss_specific_rule_is_removed(self):
        rule = _rule(1, 'final_original_price')
        rule['retailer'] = 'Lotuss'
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': [_valid_row(
                account_name='Lotuss', final_sku_price='120',
                original_sku_price='100', savings=None,
            )]},
        ])

        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 18), 'tse_tv',
        )

        self.assertEqual([], result['rule_results'])
        self.assertEqual([], result['retailers'])
        self.assertEqual(0, result['total_checked'])

    def test_summary_replaces_stored_query_with_canonical_display_query(self):
        rule = _rule(1, 'review_count_match')
        rule['query'] = 'DELETE FROM something'
        cursor = ScriptedCursor([
            {'fetchall': [rule]},
            {'fetchall': [_valid_row(count_of_reviews='9')]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_summary(
            cursor, date(2026, 8, 10), 'tse_tv',
        )
        query = result['rule_summary'][0]['query']

        self.assertNotIn('DELETE FROM something', query)
        self.assertNotIn('WITH batches AS', query)
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com', query)
        self.assertIn(
            "DATE(crawl_datetime::timestamp) >= DATE '2026-08-10'", query,
        )
        self.assertIn(
            "DATE(crawl_datetime::timestamp) <= DATE '2026-08-11'", query,
        )
        self.assertIn("LOWER(TRIM('Homepro'))", query)
        self.assertIn("item = 'A-1'", query)

    def test_display_query_supports_multiple_scoped_retailers(self):
        query = tse_services.build_tse_display_query(
            date(2026, 8, 10), 'tse_tv',
            _rule(1, 'review_count_match'),
            retailer_item_pairs=[
                ('Homepro', 'TV-1'), ("Future's Shop", 'TV-2'),
            ],
        )

        self.assertIn("LOWER(TRIM('Future''s Shop'))", query)
        self.assertIn("LOWER(TRIM('Homepro'))", query)
        self.assertIn("item = 'TV-1'", query)
        self.assertIn("item = 'TV-2'", query)
        self.assertNotIn("item IN ('TV-1', 'TV-2')", query)
        self.assertIn(
            "LOWER(TRIM('Homepro')) AND item = 'TV-1'", query,
        )
        self.assertIn(
            "LOWER(TRIM('Future''s Shop')) AND item = 'TV-2'", query,
        )

    def test_rule_detail_uses_same_retailer_key_for_summary_and_rows(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [_valid_row(
                account_name='homepro', count_of_reviews='9',
            )]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_rule_detail(
            cursor, date(2026, 8, 10), 'tse_tv', 1, days=3,
        )

        self.assertEqual(['Homepro'], list(result['retailer_summary']))
        self.assertEqual('Homepro', result['anomalies'][0]['account_name'])
        self.assertNotIn('WITH batches AS', result['query'])
        self.assertIn(
            "DATE(crawl_datetime::timestamp) >= DATE '2026-08-08'",
            result['queries']['Homepro'],
        )
        self.assertIn(
            "item = 'A-1'", result['queries']['Homepro'],
        )

    def test_rule_detail_query_keeps_null_item_anomaly_scope(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [_valid_row(
                account_name='homepro', item=None, count_of_reviews='9',
            )]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_rule_detail(
            cursor, date(2026, 8, 10), 'tse_tv', 1, days=3,
        )
        query = result['queries']['Homepro']

        self.assertIn('item IS NULL', query)
        self.assertIn("LOWER(TRIM('Homepro'))", query)
        self.assertNotIn('item IN (', query)

    def test_normal_history_excludes_same_record_and_rule(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(7, 'review_count_match')]},
            {'fetchall': [_valid_row(count_of_reviews='9')]},
            {'fetchall': [{
                'record_id': 10,
                'column_name': 'count_of_reviews',
                'memo': '확인',
                'reason': '정상 데이터',
                'created_id': 'tester',
                'created_at': '2026-08-10 10:00:00',
                'rule_id': 7,
            }]},
        ])
        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 10), 'tse_tv',
        )
        self.assertEqual(result['failed_records'], 0)
        self.assertEqual(result['total_anomalies'], 0)
        self.assertEqual(result['rule_results'][0]['error_details'], [])

    def test_unknown_metadata_rule_is_not_executed(self):
        unknown = _rule(99, 'review_count_match')
        unknown['validation_type'] = 'run_arbitrary_query'
        unknown['detail_code'] = 'not_supported'
        unknown['query'] = 'DELETE FROM something'
        cursor = ScriptedCursor([{'fetchall': [unknown]}])
        self.assertEqual(
            tse_services.load_active_tse_rules(cursor, 'tse_tv'),
            [],
        )
        self.assertEqual(len(cursor.calls), 1)

    def test_rows_without_active_rules_are_marked_unconfigured(self):
        cursor = ScriptedCursor([
            {'fetchall': []},
            {'fetchall': [_valid_row()]},
        ])

        result = tse_services.build_tse_crossfield_result(
            cursor, date(2026, 8, 10), 'tse_tv',
        )

        self.assertFalse(result['configured'])
        self.assertEqual(result['rule_results'], [])


if __name__ == '__main__':
    unittest.main()
