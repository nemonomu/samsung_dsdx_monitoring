import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class SielLayer1ScheduleSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (
            REPO_ROOT / 'sql' / 'seed_siel_layer1_schedule.sql'
        ).read_text(encoding='utf-8')

    def test_script_is_transactional_and_never_runs_from_application(self):
        self.assertIn('BEGIN;', self.sql)
        self.assertIn('COMMIT;', self.sql)
        self.assertEqual(3, self.sql.count('RAISE EXCEPTION'))
        self.assertNotIn('apps.', self.sql)

    def test_script_has_exact_six_product_retailer_rows(self):
        expected_rows = (
            "('TV',  'Amazon',   'dx_siel.dx_siel_tv_retail_com')",
            "('TV',  'Flipkart', 'dx_siel.dx_siel_tv_retail_com')",
            "('REF', 'Amazon',   'dx_siel.dx_siel_ref_retail_com')",
            "('REF', 'Flipkart', 'dx_siel.dx_siel_ref_retail_com')",
            "('LDY', 'Amazon',   'dx_siel.dx_siel_ldy_retail_com')",
            "('LDY', 'Flipkart', 'dx_siel.dx_siel_ldy_retail_com')",
        )
        for row in expected_rows:
            self.assertEqual(3, self.sql.count(row))

    def test_script_asserts_exact_policy_before_and_after_insert(self):
        self.assertEqual(
            2,
            self.sql.count(
                "COUNT(DISTINCT (schedule.category, schedule.retailer))"
            ),
        )
        self.assertEqual(2, self.sql.count('schedule.expected_count = 300'))
        self.assertEqual(
            2,
            self.sql.count('schedule.collection_duration_min = 540'),
        )
        self.assertIn("schedule.country = 'SIEL'", self.sql)
        self.assertIn("schedule.check_type = 'siel_retail'", self.sql)


if __name__ == '__main__':
    unittest.main()
