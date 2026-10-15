import unittest
from pathlib import Path

from tests.unit.support import load_module, module_stub


class LowesPickupPatternTests(unittest.TestCase):
    def test_shared_patterns_with_real_validator_and_sql_builder(self):
        root = Path(__file__).resolve().parents[2]
        sql = (root / 'sql/update_lowes_pickup_patterns.sql').read_text(encoding='utf-8')
        pattern = sql.split('$pattern$')[1]
        seed = (root / 'sql/seed_sea_ref_ldy_format.sql').read_text(encoding='utf-8')
        for tag in ('lowespickup', 'refpickup', 'ldypickup'):
            self.assertEqual(pattern, seed.split(f'${tag}$')[1])
        rows = [dict(table_name=f'{product}_retail_com', column_name='pick_up_availability',
                     account_name=retailer, check_type='regex', pattern=rule, error_message='Invalid pickup')
                for product in ('ref', 'ldy') for retailer, rule in (
                    ('Lowes', pattern), ('Bestbuy', r'^Pick up today$'))]
        validator = load_module('apps/common/retail_columns.py', 'lowes_pickup_validator', {
            'apps.common.db': module_stub('apps.common.db',
                execute_dx_query=lambda *_: rows, dx_table=lambda name: name),
            'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
        })
        valid = ('Pickup Thu, Nov 19', 'Pickup Wed, Oct 21 (Est.)',
                 'Pickup Ready by 9am Tomorrow', 'Pickup 9am Tomorrow',
                 'Pickup Ready by 12:30pm Tomorrow', 'Pickup Ready Today',
                 'Pickup Today', 'Pickup Tomorrow', 'Pickup Ready Tomorrow',
                 'Pickup Ready by Tue, Dec 1', 'Pickup Ready by Tue, Oct 20 (Est.)')
        invalid = ('Pickup', 'Pickup anything', 'Pickup Ready by 0am Tomorrow',
                   'Pickup Ready by 13am Tomorrow', 'Pickup Ready by 9:60am Tomorrow',
                   'Pickup Thu, Nov 32', 'Pickup Thu, Nov 0', 'Pickup Thu, Xxx 19',
                   'Pickup Unknown, Nov 19', 'Pickup Thu, Nov 19 garbage', '<div>Pickup Today</div>')
        for product in ('ref', 'ldy'):
            table = f'{product}_retail_com'
            for value in valid:
                with self.subTest(product=product, valid=value):
                    self.assertIsNone(validator.validate_field(table, 'pick_up_availability', value, 'Lowes'))
            for value in invalid:
                with self.subTest(product=product, invalid=value):
                    self.assertIsNotNone(validator.validate_field(table, 'pick_up_availability', value, 'Lowes'))
            self.assertIsNotNone(validator.validate_field(table, 'pick_up_availability', valid[0], 'Bestbuy'))
            sql_rule = validator.build_format_error_sql(table, account_name='Lowes')
            self.assertIn(pattern.replace("'", "''"), sql_rule)
