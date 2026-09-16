import re
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_format_duplicate import common_stubs


FIELDS = (
    'offer', 'sku_status', 'pick_up_availability',
    'delivery_availability', 'recommendation_intent',
)


def load_seed_validator():
    """Exercise the shipped SQL's patterns, bindings and retailer scopes."""
    root = Path(__file__).resolve().parents[2]
    seed = (root / 'sql/seed_sea_ref_ldy_format.sql').read_text(encoding='utf-8')
    templates = dict(re.findall(
        r"\('(SEA_APPLIANCE_[A-Z_]+)',\s*'[^']*', 'regex',\s*"
        r"\$[a-z]+\$(.*?)\$[a-z]+\$\)", seed, re.S,
    ))
    rows = []
    for block, retailers in (
        (seed.split('), common_seed AS (')[1].split('), retailer_seed AS (')[0],
         ('Bestbuy', 'Lowes')),
        (seed.split('), bestbuy_seed AS (')[1].split('), rule_seed AS (')[0],
         ('Bestbuy',)),
    ):
        for field, template, rest in re.findall(
            r"\('([^']+)', '(SEA_APPLIANCE_[A-Z_]+)',\s*([^)]*)\)", block,
        ):
            if field not in FIELDS:
                continue
            for table in ('ref_retail_com', 'ldy_retail_com'):
                for retailer in retailers:
                    rows.append(dict(
                        table_name=table, column_name=field, account_name=retailer,
                        check_type='enum' if field == 'sku_status' else 'regex',
                        pattern=templates.get(template),
                        rule_value=rest.split("'")[1] if field == 'sku_status' else None,
                        error_message=f'{field} 형식 오류',
                    ))
    validator = load_module('apps/common/retail_columns.py', 'sea_appliance_validator', {
        'apps.common.db': module_stub('apps.common.db',
            execute_dx_query=lambda *_: rows, dx_table=lambda name: name),
        'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
    })
    return validator, rows


class SeaApplianceFormatRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator, cls.rules = load_seed_validator()
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'sea_appliance_format_service', common_stubs(),
        )

    def test_seed_has_exactly_the_approved_field_and_retailer_bindings(self):
        self.assertEqual(14, len(self.rules))
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for retailer, expected in (
                ('Bestbuy', set(FIELDS)), ('Lowes', {'offer', 'sku_status'}),
            ):
                actual = {row['column_name'] for row in self.rules
                          if row['table_name'] == table and row['account_name'] == retailer}
                self.assertEqual(expected, actual)

    def test_valid_and_invalid_values_through_real_db_rule_loader(self):
        cases = {
            'offer': (
                (0, 1, '2', '1000', ' 2 '),
                ('-1', '-0', '1.0', '1.5', '+1', '1,000', '2 offers',
                 'abc', '1e3', '1\n2', '１２', 'NULL', 'N/A'),
            ),
            'sku_status': (
                ('Sponsored', 'Rollback', ' Sponsored '),
                ('Sale', 'sponsored', 'ROLLBACK', 'Sponsored products',
                 'Sponsored|Rollback', 'NULL'),
            ),
            'pick_up_availability': (
                ('Pick up Sat, Sep 19', 'Pick up Tue, Jan 5', 'Pick up today'),
                ('Pick up', 'Pick up abc', 'Pick up today extra',
                 'Pick up Foo, Sep 19', 'Pick up Sat, Foo 19',
                 'Pick up Sat, Sep 0', 'Pick up Sat, Sep 32'),
            ),
            'delivery_availability': (
                ('Delivery as soon as Thu, Sep 17', 'Delivery as soon as Tue, Jan 5'),
                ('Delivery abc', 'Delivery as soon as', 'Delivery as soon as today',
                 'Delivery as soon as Thu, Sep 32', 'Delivery as soon as Thu, Sep 17 extra'),
            ),
            'recommendation_intent': (
                ('0% would recommend to a friend', '93% would recommend to a friend',
                 '100% would recommend to a friend'),
                ('101% would recommend to a friend', '-1% would recommend to a friend',
                 '93.5% would recommend to a friend', '93',
                 '93% would recommend to a friend extra'),
            ),
        }
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for field, (valid, invalid) in cases.items():
                retailers = ('Bestbuy', 'Lowes') if field in FIELDS[:2] else ('Bestbuy',)
                for retailer in retailers:
                    for values, expected_valid in ((valid, True), (invalid, False)):
                        for value in values:
                            with self.subTest(table=table, field=field, retailer=retailer, value=value):
                                error = self.validator.validate_field(table, field, value, retailer)
                                self.assertEqual(expected_valid, error is None)

    def test_empty_values_and_other_markets_are_not_new_format_errors(self):
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for field in FIELDS:
                for value in (None, '', '   '):
                    self.assertIsNone(self.validator.validate_field(table, field, value, 'Bestbuy'))
                self.assertIsNone(self.validator.validate_field('tv_retail_com', field, 'bad', 'Bestbuy'))
                self.assertIsNone(self.validator.validate_field(table, field, 'bad', 'Amazon'))
            for field in FIELDS[2:]:
                self.assertIsNone(self.validator.validate_field(table, field, 'different wording', 'Lowes'))
            self.assertIsNone(self.validator.validate_field(table, 'retailer_sku_name_similar', '|||', 'Bestbuy'))

    def test_new_errors_match_summary_and_detail_for_both_products(self):
        row = dict(id=1, item='A1', offer='-1', sku_status='Sale',
                   pick_up_availability='bad', delivery_availability='bad',
                   recommendation_intent='101% would recommend to a friend',
                   retailer_sku_name_similar='|||')
        for product in ('ref', 'ldy'):
            section = f'sea_{product}_retail'
            def fetch(_cursor, _start, _end, _source, retailer):
                return [row] if retailer == 'Bestbuy' else []

            with patch.object(self.service, 'validate_field', self.validator.validate_field), \
                 patch.object(self.service, '_fetch_sea_format_rows', side_effect=fetch), \
                 patch.object(self.service, '_load_sea_format_normal_reviews', return_value={}):
                self.assertEqual(set(FIELDS), set(self.service.evaluate_sea_format_row(row, product, 'Bestbuy')))
                validation = {'tables': []}
                cursor = ScriptedCursor([{}, {}])
                total = self.service._append_sea_format_stats(cursor, '2026-09-01', validation, section)
                detail = self.service._get_sea_format_detail(cursor, '2026-09-01', section, 'Bestbuy', 1)

            self.assertEqual(5, total)
            self.assertEqual(total, detail['total_format_count'])
            self.assertEqual({field: 1 for field in FIELDS}, detail['field_counts'])
            self.assertEqual(set(FIELDS), set(detail['results'][0]['error_fields']))
            self.assertTrue(set(FIELDS).issubset(detail['column_names']))
            self.assertNotIn('retailer_sku_name_similar', detail['column_names'])


if __name__ == '__main__':
    unittest.main()
