import unittest
from unittest.mock import patch

from tests.unit.support import ScriptedCursor, load_module, module_stub


class AmazonTVSummaryFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_module(
            'apps/common/retail_columns.py', 'amazon_tv_summary_validator', {
                'apps.common.db': module_stub(
                    'apps.common.db', execute_dx_query=lambda *_: [],
                    dx_table=lambda name: name,
                ),
                'apps.common.response': module_stub(
                    'apps.common.response', log_error=lambda *_: None,
                ),
            },
        )

    def setUp(self):
        # A common rule must still apply to other retailers and source tables.
        rule = dict(retailer='ALL', type='regex', rule='^allowed$',
                    allowed=[], forbidden=[], error='invalid format')
        fields = {field: [rule] for field in (
            'summarized_review_content', 'detailed_review_content',
        )}
        cache = {table: {'ALL': fields} for table in (
            'tv_retail_com', 'hhp_retail_com', 'siel_tv', 'ref_retail_com',
        )}
        mock = patch.object(self.validator, 'load_format_rules', return_value=cache)
        mock.start()
        self.addCleanup(mock.stop)

    def test_summary_is_excluded_only_for_sea_amazon_tv(self):
        for retailer in ('Amazon', ' amazon ', 'AMAZON'):
            self.assertIsNone(self.validator.validate_field(
                'tv_retail_com', 'summarized_review_content', 'free text', retailer,
            ))
        for table, field, retailer in (
            ('tv_retail_com', 'summarized_review_content', 'Bestbuy'),
            ('tv_retail_com', 'detailed_review_content', 'Amazon'),
            ('hhp_retail_com', 'summarized_review_content', 'Amazon'),
            ('siel_tv', 'summarized_review_content', 'Amazon'),
            ('ref_retail_com', 'summarized_review_content', 'Amazon'),
        ):
            with self.subTest(table=table, field=field, retailer=retailer):
                self.assertEqual('invalid format: free text', self.validator.validate_field(
                    table, field, 'free text', retailer,
                ))

    def test_error_query_and_review_fields_both_exclude_summary(self):
        sql = self.validator.build_format_error_sql('tv_retail_com', 'TV', 'Amazon')
        self.assertNotIn('summarized_review_content', sql)
        self.assertIn('detailed_review_content', sql)
        fields = self.validator.build_per_field_error_sql('tv_retail_com', 'TV', 'Amazon')
        self.assertEqual(['detailed_review_content'], [row['field'] for row in fields])
        self.assertIn('summarized_review_content',
                      self.validator.build_format_error_sql('tv_retail_com', 'TV', 'Bestbuy'))

    def test_unfiltered_common_rules_skip_amazon_rows_only(self):
        sql = self.validator.build_format_error_sql('tv_retail_com', 'TV')
        self.assertIn("LOWER(TRIM(COALESCE(account_name, ''))) <> 'amazon'", sql)
        fields = self.validator.build_per_field_error_sql('tv_retail_com', 'TV')
        summary = next(row for row in fields if row['field'] == 'summarized_review_content')
        self.assertIn("<> 'amazon'", summary['cond'])

    def test_rule_display_omits_amazon_summary_only(self):
        from apps.dx.dx_layer2.format_validation import services

        for retailer, expected in (('Amazon', []), ('Bestbuy', ['summarized_review_content'])):
            cursor = ScriptedCursor([{
                'description': [(name,) for name in (
                    'column_name', 'check_type', 'pattern', 'rule_value',
                    'extra_allowed', 'error_message', 'forbidden_chars',
                )],
                'fetchall': [('summarized_review_content', 'regex', '^allowed$',
                              '', '', 'invalid format', '')],
            }])
            rules = services.get_format_rules(cursor, 'tv_retail_com', retailer)['rules']
            self.assertEqual(expected, [rule['field'] for rule in rules])


if __name__ == '__main__':
    unittest.main()
