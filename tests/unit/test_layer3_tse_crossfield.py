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


class TseCrossfieldQueryAndSummaryTests(unittest.TestCase):
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

    def test_rule_detail_uses_same_retailer_key_for_summary_and_rows(self):
        cursor = ScriptedCursor([
            {'fetchall': [_rule(1, 'review_count_match')]},
            {'fetchall': [_valid_row(
                account_name='homepro', count_of_reviews='9',
            )]},
            {'fetchall': []},
        ])

        result = tse_services.get_tse_cross_field_rule_detail(
            cursor, date(2026, 8, 10), 'tse_tv', 1,
        )

        self.assertEqual(['Homepro'], list(result['retailer_summary']))
        self.assertEqual('Homepro', result['anomalies'][0]['account_name'])

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
