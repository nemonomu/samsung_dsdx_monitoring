"""Amazon savings syntax and the exact half-percent missing-value boundary."""
from pathlib import Path
import re
import unittest

from apps.dx.dx_layer2 import seg_validation
from apps.dx.dx_layer3.cross_field import seg_services
from tests.unit.test_layer3_siel_crossfield import siel_services
from tests.unit.test_layer2_siel_format_duplicate import shared_stubs
from tests.unit.support import load_module, module_stub


class AmazonSavingsPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.formats = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'amazon_savings_formats_under_test', shared_stubs(),
        )
        cls.sql = Path('sql/update_amazon_savings_percent.sql').read_text(encoding='utf-8')
        pattern = re.search(r"'regex', '([^']+)'", cls.sql).group(1)
        rows = [dict(table_name='tv_retail_com', column_name='savings',
                     account_name='Amazon', check_type='regex', pattern=pattern,
                     rule_value=None, extra_allowed=None,
                     forbidden_chars=None, error_message='Invalid Amazon percent')]
        cls.sea_formats = load_module(
            'apps/common/retail_columns.py', 'amazon_savings_sea_formats_under_test',
            {'apps.common.db': module_stub('apps.common.db',
                execute_dx_query=lambda *_a, **_kw: rows, dx_table=lambda name: name),
             'apps.common.response': module_stub('apps.common.response', log_error=lambda *_a: None)},
        )

    def test_percent_syntax_is_consistent_across_amazon_sources(self):
        cases = [(value, False) for value in ('1%', '10%', '100%', ' 10% ', None, '')]
        cases += [(value, True) for value in ('0%', '101%', '-1%', '10.5%', '10', '$10', '₹109', '10,00€', '-')]
        for value, invalid in cases:
            with self.subTest(value=value):
                self.assertEqual(invalid, self.sea_formats.validate_field(
                    'tv_retail_com', 'savings', value, 'Amazon') is not None)
                self.assertEqual(invalid, 'savings' in seg_validation.evaluate_format_row(
                    {'savings': value}, 'seg_tv', 'Amazon'))
                for product in ('siel_tv', 'siel_ref', 'siel_ldy'):
                    self.assertEqual(invalid, 'savings' in self.formats.evaluate_siel_format_row(
                        {'savings': value}, product, 'Amazon'))
        self.assertNotIn('savings', self.formats.evaluate_siel_format_row(
            {'savings': '0%'}, 'siel_tv', 'Flipkart'))
        self.assertIn('savings', self.sea_formats.build_format_error_sql('tv_retail_com', 'TV', 'Amazon'))
        self.assertEqual([], self.sea_formats.build_per_field_error_sql('tv_retail_com', 'TV', 'Bestbuy'))

    def test_missing_boundary_is_exact_and_independent_of_displayed_percent(self):
        cases = [('995.01', False), ('995.00', True), ('994.99', True), ('800.00', True),
                 ('1000.00', False), ('1100.00', False)]
        for final_price, expected in cases:
            for missing in (None, '', ' ', '-', 'null', 'none', 'n/a'):
                with self.subTest(final_price=final_price, missing=missing):
                    seg = dict(account_name='Amazon', final_sku_price=final_price.replace('.', ',') + '€',
                               original_sku_price='1.000,00€', savings=missing)
                    siel = dict(account_name='Amazon', final_sku_price='₹' + final_price,
                                original_sku_price='₹1,000', savings=missing)
                    self.assertEqual(expected, 'savings_missing' in seg_services.evaluate_seg_row(seg))
                    self.assertEqual(expected, 'savings_missing' in siel_services.evaluate_siel_row(siel))
                    for row, evaluate in ((seg, seg_services.evaluate_seg_row), (siel, siel_services.evaluate_siel_row)):
                        errors = evaluate(dict(row, savings='1%'))
                        self.assertFalse({'savings_missing', 'savings_amount_match', 'savings_rate_match'} & errors)

    def test_screenshot_small_discount_and_unparseable_prices(self):
        self.assertNotIn('savings_missing', siel_services.evaluate_siel_row({
            'account_name': 'Amazon', 'original_sku_price': '₹53,999',
            'final_sku_price': '₹53,890', 'savings': None,
        }))
        for evaluate in (seg_services.evaluate_seg_row, siel_services.evaluate_siel_row):
            for original, final in ((None, '100'), ('bad', '100'), ('0', '0'), ('100', 'bad')):
                self.assertNotIn('savings_missing', evaluate(dict(
                    account_name='Amazon', original_sku_price=original, final_sku_price=final, savings=None)))

    def test_other_retailer_missing_policies_are_preserved(self):
        self.assertIn('savings_missing', seg_services.evaluate_seg_row(dict(
            account_name='OTTO', original_sku_price='1.000,00€', final_sku_price='999,00€', savings=None)))
        self.assertNotIn('savings_missing', seg_services.evaluate_seg_row(dict(
            account_name='Mediamarkt', original_sku_price='1.000,00€', final_sku_price='900,00€', savings=None)))
        self.assertIn('savings_missing', siel_services.evaluate_siel_row(dict(
            account_name='Flipkart', original_sku_price='₹1,000', final_sku_price='₹999', savings=None)))
