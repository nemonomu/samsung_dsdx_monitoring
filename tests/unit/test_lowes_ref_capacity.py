import unittest
from pathlib import Path

from tests.unit.support import load_module, module_stub


class LowesRefCapacityTests(unittest.TestCase):
    def test_liter_template_works_with_the_db_rule_validator(self):
        root = Path(__file__).resolve().parents[2]
        migration = (root / 'sql/update_lowes_ref_capacity_liter.sql').read_text(encoding='utf-8')
        seed = (root / 'sql/seed_sea_ref_ldy_format.sql').read_text(encoding='utf-8')
        pattern = migration.split('$capacity$')[1]
        self.assertEqual(pattern, seed.split('$capacity$')[1])
        old_pattern = r'^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+) Cu\.Feet$'
        rows = [
            dict(table_name=table, column_name=column, account_name=retailer,
                 check_type='regex', pattern=rule, error_message='invalid capacity')
            for table, column, retailer, rule in (
                ('ref_retail_com', 'ref_capacity', 'Lowes', pattern),
                ('ldy_retail_com', 'ldy_capacity', 'Lowes', old_pattern),
                ('ref_retail_com', 'ref_capacity', 'Bestbuy',
                 r'^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+) cubic feet$'),
            )
        ]
        validator = load_module('apps/common/retail_columns.py', 'lowes_capacity_validator', {
            'apps.common.db': module_stub('apps.common.db',
                execute_dx_query=lambda *_: rows, dx_table=lambda name: name),
            'apps.common.response': module_stub('apps.common.response', log_error=lambda *_: None),
        })
        for value in ('4 Liter', '6 Liter', '12 Liter', '4liter', '4 liters',
                      '4 LITER', '22.9 Cu.Feet', '.5 Cu.Feet', '4.5 Liter'):
            with self.subTest(value=value):
                self.assertIsNone(validator.validate_field('ref_retail_com', 'ref_capacity', value, 'Lowes'))
        for value in ('4', 'Liter', '4 kg', '4..5 Liter', '4 Liter extra'):
            with self.subTest(invalid=value):
                self.assertIsNotNone(validator.validate_field('ref_retail_com', 'ref_capacity', value, 'Lowes'))
        self.assertIsNotNone(validator.validate_field('ldy_retail_com', 'ldy_capacity', '4 Liter', 'Lowes'))
        self.assertIsNotNone(validator.validate_field('ref_retail_com', 'ref_capacity', '4 Liter', 'Bestbuy'))
