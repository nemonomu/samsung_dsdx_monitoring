"""SEDA NULL scope, matrix, detail, write permissions, and registration."""

import re
import sqlite3
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common import null_review_evidence as evidence
from apps.common.seda_retail import (
    SEDA_SOURCE_CONFIG, SEDA_NULL_COLUMNS, get_seda_null_columns,
    get_seda_null_select_columns,
)
from apps.dx.dx_layer2 import seda_null_validation as seda
from apps.dx.dx_layer2.common import context
from apps.dx.dx_layer2.data_edit import services as edits
from apps.dx.dx_layer2.null_validation import services as nulls
from tests.unit.support import ScriptedCursor


DAY = date(2026, 9, 14)
SOURCE = SEDA_SOURCE_CONFIG['seda_tv']


class MemoryCursor:
    """Run the production SELECTs in SQLite; omit its unsupported row lock."""
    def __init__(self, db):
        self.db = db
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        self.cursor = self.db.execute(query.replace('%s', '?').replace(' FOR UPDATE OF source', ''), params)
        self.description = self.cursor.description

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()


class SedaNullTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
        # SQLite reserves LEFT as JOIN syntax; use SUBSTR for this one expression.
        self.db.executescript("ATTACH DATABASE ':memory:' AS dx_seda;")
        for product, source in SEDA_SOURCE_CONFIG.items():
            columns = ', '.join(f'{col} {"INTEGER PRIMARY KEY" if col == "id" else "TEXT"}'
                                for col in get_seda_null_select_columns(product))
            self.db.execute(f"CREATE TABLE {source['table_name']} ({columns})")
        self.db.execute('''CREATE TABLE monitoring_corrections (
            id INTEGER PRIMARY KEY, table_name TEXT, crawl_date TEXT,
            correction_type TEXT, status TEXT, record_id INTEGER, column_name TEXT,
            memo TEXT, created_id TEXT, created_at TEXT, reason TEXT)''')
        self.cursor = MemoryCursor(self.db)
        self.evidence_patch = patch.object(evidence, 'load_evidence', return_value=[])
        self.evidence_patch.start()
        self.addCleanup(self.evidence_patch.stop)
        original_execute = self.cursor.execute
        self.cursor.execute = lambda query, params=(): original_execute(
            query.replace('LEFT(BTRIM(anchor.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(anchor.crawl_strdatetime), 1, 10)')
                 .replace('LEFT(BTRIM(source.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(source.crawl_strdatetime), 1, 10)'), params)

    def add(self, product_line='seda_tv', **changes):
        row = {col: 'value' for col in get_seda_null_select_columns(product_line)}
        row.update(country='SEDA', account_name='Magalu', page_type='main',
                   crawl_strdatetime='2026-09-13 20:00:00', batch_id='current',
                   item='001', count_of_reviews='0', count_of_star_ratings='0', star_rating='0')
        row.update(changes)
        columns = ', '.join(row)
        self.db.execute(f"INSERT INTO {SEDA_SOURCE_CONFIG[product_line]['table_name']} ({columns}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))

    def test_exact_34_fields_and_retailer_exceptions(self):
        expected_counts = {'seda_tv': (6, 7), 'seda_ref': (5, 5), 'seda_ldy': (6, 5)}
        self.assertEqual(34, sum(len(fields) for products in SEDA_NULL_COLUMNS.values() for fields in products.values()))
        for product, counts in expected_counts.items():
            self.assertEqual(counts, tuple(len(get_seda_null_columns(product, retailer))
                                          for retailer in ('CasasBahia', 'Magalu')))
        self.assertEqual(get_seda_null_columns('seda_ldy', 'CasasBahia'),
                         get_seda_null_columns('seda_ldy', ' casas bahia '))
        self.assertNotIn('sku', get_seda_null_columns('seda_tv', 'CasasBahia'))
        self.assertNotIn('ldy_color', get_seda_null_columns('seda_ldy', 'Magalu'))
        self.assertEqual((), get_seda_null_columns('seda_tv', 'unknown'))
        for value in (0, '0', '0.0', 'NULL', False):
            self.assertFalse(seda.missing(value))
        for value in (None, '', '  ', '\t\n'):
            self.assertTrue(seda.missing(value))

    def test_latest_main_scope_excludes_other_days_batches_and_retailers(self):
        self.add(id=1, batch_id='old')
        self.add(id=2, batch_id='current')
        self.add(id=3, batch_id='current', page_type='bsr')
        self.add(id=4, batch_id='bsr-only', page_type='bsr')
        self.add(id=5, batch_id='current', account_name='CasasBahia')
        self.add(id=6, batch_id='current', page_type='promotion')
        self.add(id=7, crawl_strdatetime='2026-09-14 00:01:00')
        rows, mapping = seda.latest_rows(self.cursor, DAY, SOURCE, 'Magalu')
        self.assertEqual([2, 3], [row['id'] for row in rows])
        self.assertEqual('2026-09-13', mapping['source_date'])
        self.assertEqual(-1, mapping['offset_days'])
        rows, _ = seda.latest_rows(self.cursor, DAY, SOURCE, ' casas bahia ')
        self.assertEqual([5], [row['id'] for row in rows])
        self.assertEqual([], seda.latest_rows(self.cursor, date(2026, 9, 16), SOURCE, 'Magalu')[0])

    def test_null_batch_requires_a_real_main_anchor(self):
        self.add(id=1, page_type='bsr', batch_id=None)
        self.assertEqual([], seda.latest_rows(self.cursor, DAY, SOURCE, 'Magalu')[0])
        self.add(id=2, batch_id=None)
        self.assertEqual([1, 2], [row['id'] for row in seda.latest_rows(self.cursor, DAY, SOURCE, 'Magalu')[0]])

    def test_summary_uses_only_approved_cells_and_exact_day_confirmations(self):
        self.add(id=1, screen_size=None, sku='', star_rating='0')
        self.add(id=2, account_name='CasasBahia', sku=None)
        self.add('seda_ldy', id=1, account_name='CasasBahia', ldy_color=' ')
        self.add('seda_ldy', id=2, ldy_color=None)
        self.db.execute('''INSERT INTO monitoring_corrections
            (table_name,crawl_date,correction_type,status,record_id,column_name)
            VALUES (?,?, 'null_check','normal',1,'screen_size')''', (SOURCE['table_name'], str(DAY)))
        validation = {'tables': []}
        self.assertEqual(2, seda.append_null_stats(self.cursor, DAY, validation))
        self.assertEqual([1, 0, 1], [table['total_issues'] for table in validation['tables']])
        tv = validation['tables'][0]['retailers']
        self.assertEqual(['Magalu', 'Casas Bahia'], [retailer['retailer'] for retailer in tv])
        self.assertNotIn('sku', tv[1]['fields_detail'])
        self.db.execute("UPDATE monitoring_corrections SET crawl_date = '2026-09-13'")
        self.assertEqual(3, seda.append_null_stats(self.cursor, DAY, {'tables': []}))

    def test_detail_keeps_current_targets_and_reads_history_from_d_minus_one(self):
        self.add(id=1, crawl_strdatetime='2026-09-11 20:00:00', screen_size='55')
        self.add(id=2, crawl_strdatetime='2026-09-12 20:00:00', screen_size=None)
        self.add(id=3, screen_size=None)
        self.add(id=4, screen_size=None, item=None)
        self.add(id=5, screen_size='65', item='001', page_type='bsr')
        result = seda.null_detail(self.cursor, DAY, 'seda_tv_retail', 'Magalu', 'screen_size')
        self.assertEqual([1, 2, 3, 5, 4], [row['id'] for row in result['results']])
        self.assertEqual([], result['results'][0]['null_fields'])
        self.assertEqual([], result['results'][3]['null_fields'])
        self.assertEqual('2026-09-13', self.cursor.calls[-1][1][1])
        self.assertEqual('2026-09-13', result['source_date'])
        self.assertEqual(3, result['history_days'])
        self.assertNotIn('item', result['editable_cols'])
        self.assertIn('screen_size', result['editable_cols'])
        self.assertEqual([], seda.null_detail(self.cursor, DAY, 'seda_tv', 'CasasBahia', 'sku')['results'])
        self.assertEqual([], seda.null_detail(self.cursor, DAY, 'seda_tv', None, 'sku')['results'])

    def test_edit_selector_rejects_history_old_batches_and_wrong_retailer_columns(self):
        self.add(id=1, crawl_strdatetime='2026-09-12 20:00:00', sku=None)
        self.add(id=2, batch_id='old', sku=None)
        self.add(id=3, sku=None)
        self.add(id=4, account_name='CasasBahia', sku=None)
        for record_id in (1, 2, 4):
            self.assertIsNone(seda.select_record(self.cursor, DAY, 'seda_tv', record_id, 'sku'))
        self.assertEqual((None, 'Magalu', '001'), seda.select_record(self.cursor, DAY, 'seda_tv', 3, 'sku'))
        with self.assertRaises(ValueError):
            seda.select_record(self.cursor, DAY, 'seda_tv', 3, 'sku; DROP TABLE x')

    def test_edit_and_normal_confirmation_use_scoped_selector(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Magalu', '001', 'current')},
            {'rowcount': 1}, {'rowcount': 1},
        ])
        result = edits.update_cell_value(cursor, Mock(), SOURCE['table_name'], 3, 'sku', 'SKU', str(DAY), 'null', 'tester', '')
        self.assertTrue(result['success'])
        self.assertIn('FOR UPDATE OF source', cursor.calls[0][0])
        self.assertEqual('2026-09-13', cursor.calls[0][1][0])
        cursor = ScriptedCursor([
            {'fetchone': (None, 'CasasBahia', '001', 'current')},
            {'fetchone': (3, '001', 'Product A', None, 'CasasBahia')},
            {'fetchone': None},
            {'fetchone': (51,)},
            {'fetchone': (101,)},
        ])
        conn = Mock()
        result = nulls.save_null_review(
            cursor, conn, SOURCE['table_name'], 3, 'screen_size', 'normal', '',
            '해당값 정상 확인', str(DAY), 'null', 'tester',
        )
        self.assertTrue(result['success'])
        self.assertEqual('2026-09-13', cursor.calls[0][1][0])
        self.assertEqual((3, '2026-09-13'), cursor.calls[1][1])
        snapshot = dict(zip(evidence._EVIDENCE_COLUMNS[1:], cursor.calls[4][1]))
        self.assertEqual('SEDA', snapshot['country'])
        self.assertEqual('TV', snapshot['product_line'])
        self.assertEqual('Casas Bahia', snapshot['retailer'])
        self.assertEqual('001', snapshot['item'])
        self.assertEqual('Product A', snapshot['product_name'])
        self.assertTrue(result['supports_null_auto_review'])
        conn.commit.assert_called_once()
        cursor = ScriptedCursor([{'fetchone': ('SKU', 'Magalu', '001', 'current')}])
        self.assertEqual(409, nulls.save_null_review(cursor, Mock(), SOURCE['table_name'], 3, 'sku', 'normal', '', 'reason', str(DAY), 'null', 'tester')['status_code'])

    def test_related_price_cells_are_editable_from_price_null_detail(self):
        for column, new_value in (
            ('original_sku_price', '120'),
            ('final_sku_price', '100'),
            ('savings', '20'),
        ):
            with self.subTest(column=column):
                cursor = ScriptedCursor([
                    {'fetchone': (None, 'Magalu', '001', 'current')},
                    {'rowcount': 1},
                    {'rowcount': 1},
                ])
                result = edits.update_cell_value(
                    cursor, Mock(), SOURCE['table_name'], 3, column,
                    new_value, str(DAY), 'null', 'tester', 'price correction',
                )
                self.assertTrue(result['success'])
                self.assertIn(
                    f'UPDATE {SOURCE["table_name"]} SET {column} = %s',
                    cursor.calls[1][0],
                )

    def test_other_validation_writes_are_not_enabled(self):
        for kind in ('format', 'duplicate', 'cross_field'):
            cursor = ScriptedCursor([])
            result = edits.update_cell_value(cursor, Mock(), SOURCE['table_name'], 1, 'sku', 'X', str(DAY), kind, 'tester', '')
            self.assertEqual(403, result['status'])
            result = nulls.save_null_review(cursor, Mock(), SOURCE['table_name'], 1, 'sku', 'normal', '', 'reason', str(DAY), kind, 'tester')
            self.assertEqual(400, result['status_code'])
            self.assertEqual([], cursor.calls)

    def test_seda_sidebar_supports_all_three_validations(self):
        config = {'tv_retail': {'display_name': 'SEA TV'},
                  'seda_tv_retail': {'display_name': 'SEDA TV'},
                  'sem_tv_retail': {'display_name': 'SEM TV'}}
        with patch.object(nulls, 'load_null_check_config', return_value=config), \
                patch.object(nulls, 'get_all_categories', return_value=[*config, 'seda_ref_retail', 'seda_ldy_retail']):
            groups = context.build_sidebar_groups('null_validation', 'SEDA REF')
            menus = context.get_sidebar_items()
        seda_menu = next(item for item in groups[0]['items'] if item['name'] == 'SEDA Retail')
        self.assertTrue(seda_menu['active'])
        self.assertEqual(3, len(seda_menu['children']))
        self.assertTrue(any('SEDA' in item['name'] for item in groups[1]['items']))
        self.assertTrue(any('SEDA' in item['name'] for item in groups[2]['items']))
        self.assertTrue(any(item['key'].startswith('seda_') for item in menus['format']))
        self.assertTrue(any(item['key'].startswith('seda_') for item in menus['anomaly']))

    def test_null_dashboard_and_detail_route_to_seda_without_db_registration(self):
        self.add(id=1, sku=None)
        config = {source['section_code']: {'checks': {}} for source in SEDA_SOURCE_CONFIG.values()}
        with patch.object(nulls, 'load_null_check_config', return_value=config), \
                patch.object(nulls, '_get_tse_runtime', return_value=None), \
                patch.object(nulls, '_append_tse_null_stats', return_value=0), \
                patch.object(nulls.seg_validation, 'append_null_stats', return_value=0):
            result, count = nulls.get_null_stats(self.cursor, DAY, include_youtube=False)
            self.assertEqual(1, count)
            self.assertEqual(['seda_tv_retail', 'seda_ref_retail', 'seda_ldy_retail'],
                             [table['table'] for table in result['tables']])
            detail = nulls.get_null_detail(self.cursor, DAY, 'seda_tv_retail', 'Magalu', 1, 'sku')
            self.assertEqual([1], [row['id'] for row in detail['results']])
        with patch.object(nulls, 'load_null_check_config', return_value={}), \
                patch.object(nulls, '_get_tse_runtime', return_value=None), \
                patch.object(nulls, '_append_tse_null_stats', return_value=0), \
                patch.object(nulls.seg_validation, 'append_null_stats', return_value=0), \
                patch.object(seda, 'append_null_stats', return_value=0) as seda_stats:
            nulls.get_null_stats(self.cursor, DAY, include_youtube=False)
            seda_stats.assert_called_once()

        with patch.object(nulls, 'load_null_check_config', return_value={}), \
                patch.object(nulls, '_get_tse_runtime', return_value=None), \
                patch.object(nulls.seg_validation, 'SEG_SOURCE_CONFIG', {}):
            categories = nulls.get_all_categories()
            sidebar = context.build_sidebar_groups('null_validation')
        self.assertEqual(
            ['seda_tv_retail', 'seda_ref_retail', 'seda_ldy_retail'],
            categories,
        )
        seda_menu = next(
            item for item in sidebar[0]['items']
            if item['name'] == 'SEDA Retail'
        )
        self.assertEqual(3, len(seda_menu['children']))


class SedaNullSqlTests(unittest.TestCase):
    def test_seed_matches_application_matrix_and_repairs_without_duplicates(self):
        with sqlite3.connect(':memory:') as db:
            db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
            db.create_function('NOW', 0, lambda: '2026-09-14 00:00:00')
            db.execute("ATTACH DATABASE ':memory:' AS public")
            audit = 'is_active BOOLEAN, is_del BOOLEAN, created_at TEXT, created_id TEXT, updated_at TEXT, updated_id TEXT'
            definitions = {
                'monitoring_retail_columns': 'product_line TEXT, column_name TEXT, retailer TEXT, duplicate_key BOOLEAN, skip_missing_check BOOLEAN, is_editable BOOLEAN',
                'monitoring_null_category': 'category_name TEXT, display_name TEXT, display_order INTEGER, has_retailer BOOLEAN',
                'monitoring_null_group': 'category_id INTEGER, check_name TEXT, display_name TEXT, table_name TEXT, date_column TEXT, display_order INTEGER',
                'monitoring_null_column': 'group_id INTEGER, check_column TEXT, check_type TEXT, display_columns TEXT, query_columns TEXT, query_days INTEGER',
            }
            for table, columns in definitions.items():
                db.execute(f'CREATE TABLE public.{table} (id INTEGER PRIMARY KEY, {columns}, {audit})')
            sql = (Path(__file__).resolve().parents[2] / 'sql/setup_seda_layer2_null.sql').read_text(encoding='utf-8')
            evidence_migration = re.search(
                r'DO \$seda_evidence\$.*?\$seda_evidence\$;', sql, re.DOTALL,
            )
            self.assertIsNotNone(evidence_migration)
            self.assertIn("'SEDA'", evidence_migration.group(0))
            sqlite_sql = sql[:evidence_migration.start()] + sql[evidence_migration.end():]

            def seed():
                db.executescript(sqlite_sql.replace(' ON COMMIT DROP', ''))
                for table in ('_seda_null_fields', '_seda_null_sources', '_seda_null_groups', '_seda_null_columns'):
                    db.execute('DROP TABLE ' + table)
                db.commit()

            seed()
            first_ids = {table: db.execute(f'SELECT id FROM public.{table} ORDER BY id').fetchall() for table in definitions}
            db.execute("UPDATE public.monitoring_retail_columns SET retailer = 'CasasBahia', is_active = FALSE, is_del = TRUE WHERE retailer = 'Casas Bahia'")
            db.execute("UPDATE public.monitoring_null_column SET is_active = FALSE")
            seed()
            seed()
            for table in definitions:
                self.assertEqual(first_ids[table], db.execute(f'SELECT id FROM public.{table} ORDER BY id').fetchall())
            self.assertEqual(34, db.execute('SELECT COUNT(*) FROM public.monitoring_null_column WHERE is_active AND NOT is_del').fetchone()[0])
            for product, source in SEDA_SOURCE_CONFIG.items():
                for retailer in source['retailers']:
                    rows = db.execute('''SELECT col.check_column, col.display_columns, col.query_columns, col.query_days
                        FROM public.monitoring_null_column col
                        JOIN public.monitoring_null_group g ON g.id = col.group_id
                        JOIN public.monitoring_null_category c ON c.id = g.category_id
                        WHERE c.category_name = ? AND g.display_name = ? AND col.is_active''',
                        (source['section_code'], retailer)).fetchall()
                    self.assertEqual(set(get_seda_null_columns(product, retailer)), {row[0] for row in rows})
                    for column, display, query, days in rows:
                        self.assertEqual(seda.detail_columns(column), display.split('|'))
                        self.assertEqual(display, query)
                        self.assertEqual(0, days)
            self.assertEqual(34, db.execute('''SELECT COUNT(*) FROM public.monitoring_retail_columns
                WHERE is_active AND NOT is_del AND NOT skip_missing_check AND is_editable''').fetchone()[0])

    def test_fresh_evidence_schema_accepts_seda(self):
        sql = (Path(__file__).resolve().parents[2] / 'sql/create_null_review_evidence.sql').read_text(encoding='utf-8')
        country_check = re.search(r"country text NOT NULL CHECK \(country IN \((.*?)\)\)", sql)
        self.assertIsNotNone(country_check)
        countries = {
            value.strip().strip("'")
            for value in country_check.group(1).split(',')
        }
        self.assertEqual({'SEA', 'SEDA', 'SEM', 'SIEL', 'TSE', 'SEG'}, countries)


if __name__ == '__main__':
    unittest.main()
