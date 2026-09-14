"""Exercise configuration upserts in memory without a production connection.

SQLite supports the seed's UPDATE FROM, CTEs and INSERT SELECT statements.
Only PostgreSQL's ON COMMIT DROP clause is removed; temporary tables are
cleaned up explicitly after each execution.
"""

import sqlite3
import unittest
from pathlib import Path

from apps.common.sem_retail import (
    SEM_SOURCE_CONFIG, get_sem_editable_columns, get_sem_required_columns,
    get_sem_table_columns,
)
from apps.dx.dx_layer2.sem_validation import _null_detail_columns


SQL_PATH = Path(__file__).resolve().parents[2] / 'sql/setup_sem_homedepot_monitoring.sql'


class HomeDepotConfigurationSqlTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
        self.db.create_function('NOW', 0, lambda: '2026-09-14 00:00:00')
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS public;
            CREATE TABLE public.monitoring_retail_columns (
                id INTEGER PRIMARY KEY,
                product_line TEXT, column_name TEXT, retailer TEXT,
                duplicate_key BOOLEAN, skip_missing_check BOOLEAN,
                is_editable BOOLEAN, is_active BOOLEAN, is_del BOOLEAN,
                created_at TEXT, created_id TEXT, updated_at TEXT, updated_id TEXT,
                UNIQUE(product_line, column_name, retailer)
            );
            CREATE TABLE public.monitoring_null_category (
                id INTEGER PRIMARY KEY,
                category_name TEXT UNIQUE, display_name TEXT, display_order INTEGER,
                has_retailer BOOLEAN, is_active BOOLEAN, is_del BOOLEAN,
                created_at TEXT, created_id TEXT, updated_at TEXT, updated_id TEXT
            );
            CREATE TABLE public.monitoring_null_group (
                id INTEGER PRIMARY KEY,
                category_id INTEGER, check_name TEXT, display_name TEXT,
                table_name TEXT, date_column TEXT, display_order INTEGER,
                is_active BOOLEAN, is_del BOOLEAN,
                created_at TEXT, created_id TEXT, updated_at TEXT, updated_id TEXT,
                UNIQUE(category_id, check_name)
            );
            CREATE TABLE public.monitoring_null_column (
                id INTEGER PRIMARY KEY,
                group_id INTEGER, check_column TEXT, check_type TEXT,
                display_columns TEXT, query_columns TEXT, query_days INTEGER,
                is_active BOOLEAN, is_del BOOLEAN,
                created_at TEXT, created_id TEXT, updated_at TEXT, updated_id TEXT,
                UNIQUE(group_id, check_column)
            );
        """)

    def run_seed(self):
        sql = SQL_PATH.read_text(encoding='utf-8')
        self.db.executescript(sql.replace(' ON COMMIT DROP', ''))
        for table in ('_hd_sources', '_hd_columns', '_hd_null_columns'):
            self.db.execute('DROP TABLE ' + table)
        self.db.commit()

    def snapshot(self):
        return {
            name: self.db.execute('SELECT * FROM public.' + name + ' ORDER BY id').fetchall()
            for name in ('monitoring_retail_columns', 'monitoring_null_category',
                         'monitoring_null_group', 'monitoring_null_column')
        }

    def test_fresh_registration_matches_all_application_columns(self):
        self.run_seed()
        for product in ('sem_ref', 'sem_ldy'):
            rows = self.db.execute("""
                SELECT column_name, skip_missing_check, is_editable
                FROM public.monitoring_retail_columns
                WHERE product_line = ? AND retailer = 'HomeDepot'
                  AND is_active = TRUE AND is_del = FALSE
            """, (product,)).fetchall()
            self.assertEqual(18, len(rows))
            self.assertEqual(set(get_sem_table_columns(product)) - {'id', 'batch_id'},
                             {row[0] for row in rows})
            self.assertEqual(set(get_sem_required_columns(product)),
                             {row[0] for row in rows if not row[1]})
            self.assertEqual(set(get_sem_editable_columns(product, 'HomeDepot')),
                             {row[0] for row in rows if row[2]})
            group = self.db.execute("""
                SELECT g.id, g.table_name, g.date_column
                FROM public.monitoring_null_group g
                JOIN public.monitoring_null_category c ON c.id = g.category_id
                WHERE c.category_name = ? AND g.check_name = ?
            """, (product + '_retail', 'homedepot_' + product)).fetchone()
            self.assertEqual(SEM_SOURCE_CONFIG[product]['table_name'], group[1])
            self.assertEqual('crawl_datetime', group[2])
            checks = self.db.execute("""
                SELECT check_column, check_type, display_columns, query_columns, query_days
                FROM public.monitoring_null_column
                WHERE group_id = ? AND is_active = TRUE AND is_del = FALSE
            """, (group[0],)).fetchall()
            self.assertEqual(11, len(checks))
            self.assertEqual(set(get_sem_required_columns(product)), {row[0] for row in checks})
            for column, check_type, display, query, days in checks:
                self.assertEqual('both', check_type)
                self.assertEqual(_null_detail_columns(column), display.split('|'))
                self.assertEqual(display, query)
                self.assertEqual(0, days)
        self.assertEqual(2, self.db.execute('SELECT COUNT(*) FROM public.monitoring_null_group').fetchone()[0])

    def test_rerunning_preserves_ids_and_does_not_duplicate_rows(self):
        self.run_seed()
        first = self.snapshot()
        self.run_seed()
        second = self.snapshot()
        self.run_seed()
        self.assertEqual(second, self.snapshot())
        for table in first:
            self.assertEqual([row[0] for row in first[table]], [row[0] for row in second[table]])

    def test_existing_homedepot_settings_are_repaired_without_changing_liverpool(self):
        self.run_seed()
        self.db.executescript("""
            INSERT INTO public.monitoring_retail_columns
                (product_line, column_name, retailer, skip_missing_check, is_editable, is_active, is_del)
            VALUES ('sem_ref', 'savings', 'Liverpool', TRUE, FALSE, TRUE, FALSE);
            INSERT INTO public.monitoring_null_group
                (category_id, check_name, display_name, table_name, date_column, is_active, is_del)
            SELECT id, 'liverpool_sem_ref', 'Liverpool', 'dx_sem.dx_sem_ref_retail_com',
                   'crawl_datetime', TRUE, FALSE
            FROM public.monitoring_null_category WHERE category_name = 'sem_ref_retail';
            INSERT INTO public.monitoring_null_column
                (group_id, check_column, check_type, display_columns, query_columns, query_days, is_active, is_del)
            SELECT id, 'sku', 'both', 'keep', 'keep', 3, TRUE, FALSE
            FROM public.monitoring_null_group WHERE check_name = 'liverpool_sem_ref';
            UPDATE public.monitoring_null_category
            SET display_name = 'Existing REF label', display_order = 42
            WHERE category_name = 'sem_ref_retail';
            UPDATE public.monitoring_retail_columns
            SET skip_missing_check = TRUE, is_editable = FALSE, is_active = FALSE, is_del = TRUE
            WHERE retailer = 'HomeDepot' AND column_name = 'sku';
            INSERT INTO public.monitoring_null_column
                (group_id, check_column, check_type, is_active, is_del)
            SELECT id, 'savings', 'both', TRUE, FALSE
            FROM public.monitoring_null_group WHERE check_name = 'homedepot_sem_ref';
        """)
        before = self.db.execute("SELECT * FROM public.monitoring_retail_columns WHERE retailer = 'Liverpool'").fetchall()
        before_checks = self.db.execute("""
            SELECT col.* FROM public.monitoring_null_column col
            JOIN public.monitoring_null_group g ON g.id = col.group_id
            WHERE g.check_name = 'liverpool_sem_ref'
        """).fetchall()
        self.run_seed()
        self.assertEqual(before, self.db.execute("SELECT * FROM public.monitoring_retail_columns WHERE retailer = 'Liverpool'").fetchall())
        self.assertEqual(before_checks, self.db.execute("""
            SELECT col.* FROM public.monitoring_null_column col
            JOIN public.monitoring_null_group g ON g.id = col.group_id
            WHERE g.check_name = 'liverpool_sem_ref'
        """).fetchall())
        self.assertEqual(('Existing REF label', 42), self.db.execute("""
            SELECT display_name, display_order FROM public.monitoring_null_category
            WHERE category_name = 'sem_ref_retail'
        """).fetchone())
        self.assertEqual([(0, 1, 1, 0), (0, 1, 1, 0)], self.db.execute("""
            SELECT skip_missing_check, is_editable, is_active, is_del
            FROM public.monitoring_retail_columns WHERE retailer = 'HomeDepot' AND column_name = 'sku'
        """).fetchall())
        self.assertEqual((0,), self.db.execute("""
            SELECT col.is_active FROM public.monitoring_null_column col
            JOIN public.monitoring_null_group g ON g.id = col.group_id
            WHERE g.check_name = 'homedepot_sem_ref' AND col.check_column = 'savings'
        """).fetchone())


if __name__ == '__main__':
    unittest.main()
