import re
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_format_duplicate import SEA_SOURCES, common_stubs


FIELDS = (
    'offer', 'sku_status', 'pick_up_availability',
    'delivery_availability', 'recommendation_intent',
)
LOWES_EXTRA_FIELDS = (
    'available_quantity_for_purchase_pickup',
    'available_quantity_for_purchase_delivery',
    'available_quantity_for_purchase_fastdelivery',
    'fastest_delivery', 'discount_type', 'sku_popularity',
)
LOWES_FIELDS = FIELDS[1:] + LOWES_EXTRA_FIELDS


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
        (seed.split('), bestbuy_seed AS (')[1].split('), lowes_seed AS (')[0],
         ('Bestbuy',)),
        (seed.split('), lowes_seed AS (')[1].split('), rule_seed AS (')[0],
         ('Lowes',)),
    ):
        for field, template, rest in re.findall(
            r"\('([^']+)', '(SEA_APPLIANCE_[A-Z_]+)',\s*([^)]*)\)", block,
        ):
            if field not in FIELDS + LOWES_EXTRA_FIELDS:
                continue
            is_enum = template == 'SEA_APPLIANCE_ENUM'
            for table in ('ref_retail_com', 'ldy_retail_com'):
                for retailer in retailers:
                    selected_template = template
                    if retailer == 'Lowes':
                        product = table.split('_')[0].upper()
                        selected_template = {
                            'pick_up_availability': f'SEA_APPLIANCE_LOWES_{product}_PICKUP',
                            'discount_type': f'SEA_APPLIANCE_LOWES_{product}_DISCOUNT',
                        }.get(field, template)
                    rows.append(dict(
                        table_name=table, column_name=field, account_name=retailer,
                        check_type='enum' if is_enum else 'regex',
                        pattern=None if is_enum else templates[selected_template],
                        rule_value=rest.split("'")[1] if is_enum else None,
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
        self.assertEqual(30, len(self.rules))
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for retailer, expected in (
                ('Bestbuy', set(FIELDS)), ('Lowes', set(LOWES_FIELDS)),
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
                ('Pick up Sat, Sep 19', 'Pick up Tue, Jan 5', 'Pick up today',
                 'Pick up tomorrow'),
                ('Pick up', 'Pick up abc', 'Pick up today extra',
                 'Pick up tomorrow extra', 'Pick up Tomorrow',
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
                retailers = ('Bestbuy', 'Lowes') if field == 'sku_status' else ('Bestbuy',)
                for retailer in retailers:
                    for values, expected_valid in ((valid, True), (invalid, False)):
                        for value in values:
                            with self.subTest(table=table, field=field, retailer=retailer, value=value):
                                error = self.validator.validate_field(table, field, value, retailer)
                                self.assertEqual(expected_valid, error is None)

    def test_empty_values_and_other_markets_are_not_new_format_errors(self):
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for field in FIELDS + LOWES_EXTRA_FIELDS:
                for value in (None, '', '   '):
                    self.assertIsNone(self.validator.validate_field(table, field, value, 'Bestbuy'))
                    self.assertIsNone(self.validator.validate_field(table, field, value, 'Lowes'))
                self.assertIsNone(self.validator.validate_field('tv_retail_com', field, 'bad', 'Bestbuy'))
                self.assertIsNone(self.validator.validate_field(table, field, 'bad', 'Amazon'))
            self.assertIsNone(self.validator.validate_field(table, 'offer', 'ignored', 'Lowes'))
            for field in LOWES_EXTRA_FIELDS:
                self.assertIsNone(self.validator.validate_field(table, field, 'not applicable', 'Bestbuy'))
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

    def test_lowes_ref_ldy_new_discount_and_pickup_values_are_scoped_and_bounded(self):
        cases = {
            'discount_type': (
                ('Buy More, Save More', 'Buy 1 And Get 1', 'Buy 2 And Get 3', 'Buy 12 And Get 10'),
                ('Buy More Save More', 'buy More, Save More', 'Buy 1 and Get 1',
                 'Buy 0 And Get 1', 'Buy 1 And Get 0', 'Buy -1 And Get 1',
                 'Buy 1.5 And Get 1', 'Buy 1 And Get 1 extra', 'Buy 01 And Get 1'),
            ),
            'pick_up_availability': (
                ('Pickup Ready Tomorrow',),
                ('Pickup Ready tomorrow', 'Pickup Ready Tomorrow extra'),
            ),
        }
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for field, (allowed, invalid) in cases.items():
                for value in allowed:
                    with self.subTest(table=table, field=field, value=value):
                        self.assertIsNone(self.validator.validate_field(table, field, value, 'Lowes'))
                for value in invalid:
                    with self.subTest(table=table, field=field, value=value):
                        self.assertIsNotNone(self.validator.validate_field(table, field, value, 'Lowes'))
            self.assertIsNotNone(self.validator.validate_field(
                table, 'pick_up_availability', 'Pickup Ready Tomorrow', 'Bestbuy'))

        root = Path(__file__).resolve().parents[2]
        seed = (root / 'sql/seed_sea_ref_ldy_format.sql').read_text(encoding='utf-8')
        for product in ('ref', 'ldy'):
            table = f'{product}_retail_com'
            migration = (root / f'sql/update_lowes_{product}_discount_pickup.sql').read_text(encoding='utf-8')
            patterns = re.findall(r'\$pattern\$(.*?)\$pattern\$', migration, re.S)
            expected = [row['pattern'] for row in self.rules
                        if row['table_name'] == table and row['account_name'] == 'Lowes'
                        and row['column_name'] in cases]
            self.assertEqual(set(expected), set(patterns))
            for field in cases:
                self.assertIn(f"product.table_name = '{table}' AND rule.column_name = '{field}'", seed)
            self.assertIn(f"WHERE table_name = '{table}' AND account_name = 'Lowes'", migration)

    def test_lowes_text_and_quantity_values(self):
        cases = {
            'pick_up_availability': (
                ('Pickup Ready Today', 'Pickup Ready by Tue, Sep 22', 'Pickup Ready by Wed, Oct 1'),
                ('Pick up today', 'Pick up tomorrow', 'Pickup Ready today', 'Pickup Ready by Tue, Sep 0',
                 'Pickup Ready by Tue, Sep 32', 'Pickup Ready by Tue, 9 22',
                 'Pickup Ready by XXX, Sep 22', 'Pickup Ready Today extra'),
            ),
            'delivery_availability': (
                ('Delivery Sat, Sep 19', 'Shipping Mon, Sep 21', 'Delivery w/FREE Installation',
                 'Delivery Tomorrow', ' Delivery Tomorrow '),
                ('Delivery as soon as Sat, Sep 19', 'Shipping today',
                 'Delivery w/free Installation', 'Delivery Sat, Sep 32',
                 'Shipping Mon, Bad 21', 'Delivery Sat, Sep 19 extra',
                 'Delivery tomorrow', 'Delivery Tomorrow extra'),
            ),
            'recommendation_intent': (
                ('0% Recommend this product', '83% Recommend this product', '100% Recommend this product'),
                ('-1% Recommend this product', '101% Recommend this product',
                 '83.5% Recommend this product', '83% would recommend to a friend',
                 '83% recommend this product', '83% Recommend this product extra'),
            ),
            'fastest_delivery': (
                ('Get it Tomorrow', ' Get it Tomorrow '),
                ('Get it tomorrow', 'Get it Today', 'Tomorrow', 'Get it Tomorrow extra'),
            ),
            'sku_popularity': (
                ('Top Deal', 'trending now', 'best seller', 'luxury'),
                ('top deal', 'Trending Now', 'Best Seller', 'sale', 'Top Deal extra'),
            ),
            'discount_type': (
                ('Exclusive Appliance Bundle', 'Unlock Member Deal',
                 'Get $50 Off In Cart On Purchase Of 2 Items',
                 'Get $175 Off In Cart On Purchase Of 3 Items', '$200 Instant Savings',
                 '$1234 Instant Savings', 'Buy 3+ Get 10% Off', 'Buy 4+ Get 100% Off'),
                ('Exclusive appliance bundle', 'Sale', '$0 Instant Savings',
                 '$-50 Instant Savings', '$2.5 Instant Savings', '$1,000 Instant Savings',
                 'Get $50 Off In Cart On Purchase Of 0 Items',
                 'Get $50 Off In Cart On Purchase Of 2.5 Items',
                 'Buy 0+ Get 10% Off', 'Buy 3+ Get 0% Off', 'Buy 3+ Get 101% Off',
                 'Buy 3+ Get 10.5% Off', 'Unlock Member Deal extra'),
            ),
        }
        for field in LOWES_EXTRA_FIELDS[:3]:
            cases[field] = (
                (0, '1', '3273', ' 2 '),
                ('-1', '+1', '1.0', '1.5', '1,000', '10 units', '1e3', 'abc', '１２', '1\n2'),
            )
        for table in ('ref_retail_com', 'ldy_retail_com'):
            for field, (valid, invalid) in cases.items():
                for values, expected_valid in ((valid, True), (invalid, False)):
                    for value in values:
                        with self.subTest(table=table, field=field, value=value):
                            error = self.validator.validate_field(table, field, value, 'Lowes')
                            self.assertEqual(expected_valid, error is None)

    def test_lowes_query_excludes_offer_and_selects_new_fields(self):
        for product in ('ref', 'ldy'):
            cursor = ScriptedCursor([{'fetchall': []}])
            self.service._fetch_sea_format_rows(
                cursor, date(2026, 9, 15), date(2026, 9, 15), SEA_SOURCES[product], 'Lowes',
            )
            sql, _ = cursor.calls[0]
            self.assertNotIn('source.offer', sql)
            for field in LOWES_FIELDS:
                self.assertIn(f'source.{field}', sql)

    def test_lowes_summary_and_detail_ignore_stale_offer_rule(self):
        row = dict.fromkeys(LOWES_FIELDS, 'invalid')
        row.update(id=1, item='A1', offer='bad offer')
        def validate(table, field, value, *args, **kwargs):
            if field == 'offer':
                self.fail('Lowes offer must not be evaluated even with a stale DB rule')
            return self.validator.validate_field(table, field, value, *args, **kwargs)

        for product in ('ref', 'ldy'):
            section = f'sea_{product}_retail'
            def fetch(_cursor, _start, _end, _source, retailer):
                return [row] if retailer == 'Lowes' else []

            with patch.object(self.service, 'validate_field', validate), \
                 patch.object(self.service, '_fetch_sea_format_rows', side_effect=fetch), \
                 patch.object(self.service, '_load_sea_format_normal_reviews', return_value={}):
                cursor = ScriptedCursor([{}, {}])
                validation = {'tables': []}
                total = self.service._append_sea_format_stats(cursor, '2026-09-01', validation, section)
                detail = self.service._get_sea_format_detail(cursor, '2026-09-01', section, 'Lowes', 1)
            self.assertEqual(10, total)
            self.assertEqual(total, detail['total_format_count'])
            self.assertEqual({field: 1 for field in LOWES_FIELDS}, detail['field_counts'])
            self.assertEqual(set(LOWES_FIELDS), set(detail['results'][0]['error_fields']))
            self.assertTrue(set(LOWES_FIELDS).issubset(detail['column_names']))
            self.assertNotIn('offer', detail['column_names'])

    def test_rule_popup_excludes_lowes_offer_even_before_db_update(self):
        columns = ('column_name', 'check_type', 'pattern', 'rule_value', 'extra_allowed', 'error_message')
        for product in ('ref', 'ldy'):
            for retailer, expected in (('Lowes', {'sku_status'}), ('Bestbuy', {'offer', 'sku_status'})):
                cursor = ScriptedCursor([{
                    'description': [(column,) for column in columns],
                    'fetchall': [('offer', 'regex', '^[0-9]+$', None, None, 'count'),
                                 ('sku_status', 'enum', None, 'Sponsored|Rollback', None, 'status')],
                }])
                rules = self.service.get_format_rules(cursor, f'{product}_retail_com', retailer)
                self.assertEqual(expected, {rule['field'] for rule in rules['rules']})

    def test_retiring_offer_is_idempotent_and_scoped_to_lowes_ref_ldy(self):
        root = Path(__file__).resolve().parents[2]
        seed = (root / 'sql/seed_sea_ref_ldy_format.sql').read_text(encoding='utf-8')
        statement = seed.split('-- Lowes does not collect offer;')[1]
        statement = statement[statement.index('UPDATE '):].split(';')[0]
        statement = statement.replace('public.monitoring_format_rules', 'monitoring_format_rules')
        with closing(sqlite3.connect(':memory:')) as db:
            db.create_function('NOW', 0, lambda: '2026-09-16')
            db.execute('CREATE TABLE monitoring_format_rules ('
                       'id INTEGER, table_name TEXT, account_name TEXT, column_name TEXT, '
                       'is_active BOOLEAN, updated_id TEXT, updated_at TEXT)')
            db.executemany('INSERT INTO monitoring_format_rules VALUES (?, ?, ?, ?, TRUE, NULL, NULL)', [
                (1, 'ref_retail_com', 'Lowes', 'offer'),
                (2, 'ldy_retail_com', ' lowes ', 'offer'),
                (3, 'ref_retail_com', 'Bestbuy', 'offer'),
                (4, 'ldy_retail_com', 'Bestbuy', 'offer'),
                (5, 'tv_retail_com', 'Lowes', 'offer'),
                (6, 'ref_retail_com', 'Lowes', 'sku_status'),
                (7, 'ldy_retail_com', 'Lowes', 'discount_type'),
            ])
            self.assertEqual(2, db.execute(statement).rowcount)
            self.assertEqual(0, db.execute(statement).rowcount)
            self.assertEqual([(1, 0), (2, 0), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1)],
                             db.execute('SELECT id, is_active FROM monitoring_format_rules ORDER BY id').fetchall())


if __name__ == '__main__':
    unittest.main()
