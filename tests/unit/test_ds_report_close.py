"""Exercise save-and-close atomically without importing production settings."""
import ast
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]


def load_functions(relative_path, names, namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)


class ReportCloseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS ssd_crawl_db")
        self.db.executescript('''
            CREATE TABLE ssd_crawl_db.ds_monitoring_targets (retailer_id INTEGER, is_active INTEGER);
            INSERT INTO ssd_crawl_db.ds_monitoring_targets VALUES (1, 1), (2, 1);
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_daily (
                retailer_id INTEGER, crawl_date TEXT, anomaly_total INTEGER, memo TEXT, is_del INTEGER);
            INSERT INTO ssd_crawl_db.ds_monitoring_report_daily VALUES
                (1, '2026-10-01', 2, 'Reviewed', 0), (2, '2026-10-01', 0, '', 0);
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_close (
                crawl_date TEXT PRIMARY KEY, is_closed INTEGER, closed_at TEXT, closed_id TEXT,
                created_at TEXT, updated_at TEXT);
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_close_history (
                crawl_date TEXT, action TEXT, action_at TEXT, action_id TEXT);
            CREATE TABLE ssd_crawl_db.ds_monitoring_documents (
                document_id TEXT PRIMARY KEY, category_id TEXT, title TEXT, content TEXT,
                object_document_id TEXT, crawl_date TEXT, created_id TEXT, created_at TEXT,
                updated_id TEXT, updated_at TEXT, is_del INTEGER DEFAULT 0);
        ''')

        class Cursor:
            def __init__(self, db):
                self.cursor = db.cursor()

            def execute(self, sql, params=()):
                sql = sql.replace('%s', '?').replace(' FOR UPDATE', '').replace('NOW()', 'CURRENT_TIMESTAMP')
                sql = sql.replace('ON DUPLICATE KEY UPDATE crawl_date = VALUES(crawl_date)',
                                  'ON CONFLICT(crawl_date) DO NOTHING')
                sql = sql.replace('ON DUPLICATE KEY UPDATE', 'ON CONFLICT(crawl_date) DO UPDATE SET')
                self.cursor.execute(sql, params)

            def fetchone(self):
                return self.cursor.fetchone()

            def fetchall(self):
                return self.cursor.fetchall()

        @contextmanager
        def connection():
            try:
                yield self.db, Cursor(self.db)
            except Exception:
                self.db.rollback()
                raise

        doc_namespace = {}
        load_functions('apps/ds/ds_document/document/document_repositories.py',
                       {'get_document_by_crawl_date', 'update_document_record', 'insert_document_record'},
                       doc_namespace)
        namespace = {'datetime': datetime, 'ds_connection': connection,
                     'REPORT_CATEGORY_ID': '20260212-0001',
                     'document_repositories': SimpleNamespace(**doc_namespace),
                     'generate_ds_id': lambda *args: '20261002-0001'}
        load_functions('apps/ds/ds_layer4/report/report_repositories.py', {'execute_close_report'}, namespace)
        self.close = namespace['execute_close_report']

    def rows(self, table):
        return self.db.execute(f'SELECT * FROM ssd_crawl_db.ds_monitoring_{table}').fetchall()

    def test_first_close_saves_document_and_history(self):
        result = self.close('2026-10-01', 'tester', '<p>Reviewed report</p>')
        self.assertTrue(result['success'])
        self.assertEqual(result['document_id'], '20261002-0001')
        self.assertEqual(self.rows('documents')[0][2:4], ('2026-10-01 DS 검수 보고서', '<p>Reviewed report</p>'))
        self.assertEqual(self.rows('report_close')[0][1], 1)
        self.assertEqual(self.rows('report_close_history')[0][1], 'close')

    def test_reclose_updates_same_document(self):
        first = self.close('2026-10-01', 'tester', 'first')
        self.db.execute('UPDATE ssd_crawl_db.ds_monitoring_report_close SET is_closed = 0')
        self.db.commit()
        second = self.close('2026-10-01', 'tester', 'revised')
        self.assertEqual(first['document_id'], second['document_id'])
        self.assertEqual(len(self.rows('documents')), 1)
        self.assertEqual(self.rows('documents')[0][3], 'revised')
        self.assertEqual(len(self.rows('report_close_history')), 2)

    def test_duplicate_close_does_not_overwrite_document_or_history(self):
        self.close('2026-10-01', 'tester', 'first')
        self.assertFalse(self.close('2026-10-01', 'tester', 'duplicate')['success'])
        self.assertEqual(self.rows('documents')[0][3], 'first')
        self.assertEqual(len(self.rows('report_close_history')), 1)

    def test_incomplete_targets_and_missing_memo_do_not_save(self):
        for sql in [
            'UPDATE ssd_crawl_db.ds_monitoring_report_daily SET retailer_id = 99 WHERE retailer_id = 2',
            "UPDATE ssd_crawl_db.ds_monitoring_report_daily SET memo = '  ' WHERE retailer_id = 1",
        ]:
            with self.subTest(sql=sql):
                self.db.execute(sql)
                self.db.commit()
                self.assertFalse(self.close('2026-10-01', 'tester', 'report')['success'])
                self.assertEqual(self.rows('documents'), [])
                self.assertEqual(self.rows('report_close'), [])
                self.db.execute('UPDATE ssd_crawl_db.ds_monitoring_report_daily SET retailer_id = 2 WHERE retailer_id = 99')
                self.db.commit()

    def fail_history(self):
        self.db.executescript('''
            CREATE TRIGGER ssd_crawl_db.fail_history BEFORE INSERT ON ds_monitoring_report_close_history
            BEGIN SELECT RAISE(ABORT, 'simulated history failure'); END;
        ''')

    def test_failure_after_document_insert_rolls_back_entire_close(self):
        self.fail_history()
        with self.assertRaises(sqlite3.IntegrityError):
            self.close('2026-10-01', 'tester', 'report')
        self.assertEqual(self.rows('documents'), [])
        self.assertEqual(self.rows('report_close'), [])

    def test_failure_after_document_update_preserves_previous_report(self):
        self.close('2026-10-01', 'tester', 'first')
        self.db.execute('UPDATE ssd_crawl_db.ds_monitoring_report_close SET is_closed = 0')
        self.db.commit()
        self.fail_history()
        with self.assertRaises(sqlite3.IntegrityError):
            self.close('2026-10-01', 'tester', 'revised')
        self.assertEqual(self.rows('documents')[0][3], 'first')
        self.assertEqual(self.rows('report_close')[0][1], 0)
        self.assertEqual(len(self.rows('report_close_history')), 1)

    def test_service_requires_content_and_valid_date(self):
        calls = []
        namespace = {'datetime': datetime, 'log_error': lambda error: None,
                     'report_repositories': SimpleNamespace(execute_close_report=lambda *args: calls.append(args))}
        load_functions('apps/ds/ds_layer4/report/report_services.py', {'close_report'}, namespace)
        for date, content in [('2026-10-01', ''), ('2026-10-01', None), ('invalid', 'report')]:
            self.assertFalse(namespace['close_report'](date, 'tester', content)['success'])
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
