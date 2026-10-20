import re
import unittest

from apps.dx.dx_layer2.format_validation import services
from apps.dx.dx_layer2.format_validation.rule_examples import database_examples


class FormatRuleExamplesTests(unittest.TestCase):
    def test_price_examples_match_exact_pattern_and_keep_forbidden_values_out(self):
        pattern = r'^\$[0-9]+(,[0-9]{3})*(\.[0-9]{1,2})?$'
        rule = {'column_name': 'final_sku_price', 'check_type': 'regex', 'pattern': pattern}
        self.assertEqual(['$999', '$1,299', '$1,299.99'], database_examples(rule))
        rule['forbidden_chars'] = ','
        for example in database_examples(rule):
            self.assertRegex(example, pattern)
            self.assertNotIn(',', example)
        rule['extra_allowed'] = 'See price in cart'
        self.assertIn('See price in cart', database_examples(rule))

    def test_ranges_enums_and_regex_clean_use_existing_semantics(self):
        for rule in (
            dict(column_name='rating', check_type='range_float', rule_value='0~5'),
            dict(column_name='page_type', check_type='enum', rule_value='MAIN|BSR'),
            dict(column_name='count', check_type='regex_clean', pattern=r'^\d+$', rule_value='comma'),
        ):
            self.assertTrue(database_examples(rule))
        self.assertEqual([], database_examples(dict(column_name='sku', check_type='fk_check',
                                                   rule_value='source.sku')))

    def test_static_sources_all_have_examples_and_original_rules_stay(self):
        combinations = []
        for registry in (services.SIEL_SOURCE_CONFIG, services.seg_validation.SEG_SOURCE_CONFIG,
                         services.sem_validation.SEM_SOURCE_CONFIG,
                         services.seib_format_validation.SEIB_SOURCE_CONFIG,
                         services.seda_format_validation.SEDA_SOURCE_CONFIG):
            for key, source in registry.items():
                combinations.extend((key, retailer) for retailer in source['retailers'])
        combinations.extend((key, retailer) for key in services.TSE_SOURCE_CONFIG
                            for retailer in ('Homepro', 'Lotuss'))
        for key, retailer in combinations:
            with self.subTest(source=key, retailer=retailer):
                rules = services.get_format_rules(None, key, retailer)['rules']
                self.assertTrue(rules)
                for rule in rules:
                    self.assertTrue(rule['pattern'])
                    self.assertTrue(rule['description'])
                    self.assertTrue(rule['examples'], (key, retailer, rule['field']))
                    self.assertLessEqual(len(rule['examples']), 3)
        originals = services.seib_format_validation.get_format_rule_details('seib_ref', 'MediaMarkt')
        result = services.get_format_rules(None, 'seib_ref', 'MediaMarkt')['rules']
        self.assertEqual(originals, [{k: v for k, v in rule.items() if k != 'examples'}
                                     for rule in result])

    def test_review_section_aliases_use_same_country_rules(self):
        for key, retailer in (('siel_tv', 'Amazon'), ('tse_tv', 'Lotuss')):
            self.assertEqual(services.get_format_rules(None, key, retailer),
                             services.get_format_rules(None, key + '_retail', retailer))


if __name__ == '__main__':
    unittest.main()
