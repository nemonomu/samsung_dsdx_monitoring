import unittest
from pathlib import Path

from apps.common.sem_retail import get_sem_required_columns, get_sem_editable_columns
from tests.unit import test_sem_homedepot_sql as existing


class CoppelConfigurationSqlTests(unittest.TestCase):
    setUp = existing.HomeDepotConfigurationSqlTests.setUp
    snapshot = existing.HomeDepotConfigurationSqlTests.snapshot

    def run_seed(self):
        path = Path(__file__).resolve().parents[2] / 'sql/setup_sem_coppel_monitoring.sql'
        self.db.executescript(path.read_text(encoding='utf-8').replace(' ON COMMIT DROP', ''))
        for table in ('_coppel_sources', '_coppel_columns', '_coppel_null_columns'):
            self.db.execute('DROP TABLE ' + table)
        self.db.commit()

    def test_coppel_seed_matches_code_and_preserves_existing_settings_on_rerun(self):
        existing.HomeDepotConfigurationSqlTests.run_seed(self)
        self.db.executescript("""
            INSERT INTO public.monitoring_retail_columns
                (product_line, column_name, retailer, skip_missing_check, is_editable, is_active, is_del)
            VALUES ('sem_ref', 'sku', 'Liverpool', FALSE, TRUE, TRUE, FALSE);
            INSERT INTO public.monitoring_null_group
                (category_id, check_name, display_name, is_active, is_del)
            SELECT id, 'liverpool_sem_ref', 'Liverpool', TRUE, FALSE
            FROM public.monitoring_null_category WHERE category_name = 'sem_ref_retail';
            INSERT INTO public.monitoring_null_column
                (group_id, check_column, display_columns, is_active, is_del)
            SELECT id, 'sku', 'keep', TRUE, FALSE
            FROM public.monitoring_null_group WHERE check_name = 'liverpool_sem_ref';
        """)
        before = self.snapshot()
        self.run_seed()
        after = self.snapshot()
        for table, rows in before.items():
            self.assertEqual(rows, [row for row in after[table] if row[0] in {r[0] for r in rows}])
        for product in ('sem_ref', 'sem_ldy'):
            rows = self.db.execute("""
                SELECT column_name, skip_missing_check, is_editable
                FROM public.monitoring_retail_columns
                WHERE product_line = ? AND retailer = 'Coppel'
            """, (product,)).fetchall()
            self.assertEqual(18, len(rows))
            self.assertEqual(set(get_sem_required_columns(product, 'Coppel')),
                             {r[0] for r in rows if not r[1]})
            self.assertEqual(set(get_sem_editable_columns(product, 'Coppel')),
                             {r[0] for r in rows if r[2]})
            checks = self.db.execute("""
                SELECT c.check_column FROM public.monitoring_null_column c
                JOIN public.monitoring_null_group g ON g.id = c.group_id
                WHERE g.check_name = ? AND c.is_active = TRUE AND c.is_del = FALSE
            """, ('coppel_' + product,)).fetchall()
            self.assertEqual(8, len(checks))
            self.assertEqual(set(get_sem_required_columns(product, 'Coppel')), {r[0] for r in checks})
        self.run_seed()
        stable = self.snapshot()
        self.run_seed()
        self.assertEqual(stable, self.snapshot())
        for table in after:
            self.assertEqual([r[0] for r in after[table]], [r[0] for r in stable[table]])
