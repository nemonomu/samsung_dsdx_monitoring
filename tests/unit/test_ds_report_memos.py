"""Exercise memo updates against an isolated in-memory database."""
import ast
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
import unittest


REPOSITORY = Path(__file__).resolve().parents[2] / 'apps/ds/ds_layer4/report/report_repositories.py'


class ReportMemoTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.execute("ATTACH DATABASE ':memory:' AS ssd_crawl_db")
        self.connection.execute('''
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_daily (
                id INTEGER PRIMARY KEY, memo TEXT, file_memo TEXT,
                updated_at TEXT, updated_id TEXT, is_del INTEGER DEFAULT 0
            )
        ''')
        self.connection.executemany('''
            INSERT INTO ssd_crawl_db.ds_monitoring_report_daily
                (id, memo, file_memo, updated_id, is_del) VALUES (?, ?, ?, ?, ?)
        ''', [(1, '상품페이지 내 항목 부재(3건)', '기존 파일 메모', 'original', 0),
              (2, '404페이지(1건)', '두 번째 파일 메모', 'original', 0),
              (3, '삭제된 보고서 메모', '삭제된 파일 메모', 'original', 1)])
        self.connection.commit()

        class Cursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def execute(self, sql, values):
                self.cursor.execute(sql.replace('%s', '?'), values)

            @property
            def rowcount(self):
                return self.cursor.rowcount

        @contextmanager
        def ds_connection():
            yield self.connection, Cursor(self.connection.cursor())

        # Load just this function; never import production connections or settings.
        tree = ast.parse(REPOSITORY.read_text(encoding='utf-8'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'update_daily_memo_db')
        namespace = {'datetime': datetime, 'ds_connection': ds_connection}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(REPOSITORY), 'exec'), namespace)
        self.update = namespace['update_daily_memo_db']

    def row(self, daily_id=1):
        return self.connection.execute('''
            SELECT memo, file_memo, updated_id
            FROM ssd_crawl_db.ds_monitoring_report_daily WHERE id = ?
        ''', (daily_id,)).fetchone()

    def test_file_batch_preserves_status_memo(self):
        result = self.update({'memos': [{'daily_id': 1, 'file_memo': '새 파일 메모'}]}, 'tester')
        self.assertTrue(result['success'])
        self.assertEqual(result['updated_count'], 1)
        self.assertEqual(self.row(), ('상품페이지 내 항목 부재(3건)', '새 파일 메모', 'tester'))
        self.assertEqual(self.row(2), ('404페이지(1건)', '두 번째 파일 메모', 'original'))

    def test_status_batch_preserves_file_memo(self):
        self.update({'memos': [{'daily_id': 1, 'memo': '새 현황 메모'}]}, 'tester')
        self.assertEqual(self.row(), ('새 현황 메모', '기존 파일 메모', 'tester'))

    def test_explicit_empty_values_clear_only_requested_field(self):
        result = self.update({'memos': [
            {'daily_id': 1, 'file_memo': ''}, {'daily_id': 2, 'memo': ''},
        ]}, 'tester')
        self.assertEqual(result['updated_count'], 2)
        self.assertEqual(self.row(), ('상품페이지 내 항목 부재(3건)', '', 'tester'))
        self.assertEqual(self.row(2), ('', '두 번째 파일 메모', 'tester'))

    def test_both_fields_are_updated_when_supplied(self):
        self.update({'memos': [{'daily_id': 1, 'memo': '현황', 'file_memo': '파일'}]}, 'tester')
        self.assertEqual(self.row(), ('현황', '파일', 'tester'))

    def test_missing_fields_or_id_cannot_erase_memos(self):
        result = self.update({'memos': [{'daily_id': 1}, {'file_memo': '파일'}]}, 'tester')
        self.assertEqual(result['updated_count'], 0)
        self.assertEqual(self.row(), ('상품페이지 내 항목 부재(3건)', '기존 파일 메모', 'original'))

    def test_deleted_and_unknown_reports_remain_untouched(self):
        result = self.update({'memos': [
            {'daily_id': 3, 'file_memo': '변경'}, {'daily_id': 999, 'memo': '변경'},
        ]}, 'tester')
        self.assertEqual(result['updated_count'], 0)
        self.assertEqual(self.row(3), ('삭제된 보고서 메모', '삭제된 파일 메모', 'original'))

    def test_single_item_updates_still_preserve_other_field(self):
        self.update({'daily_id': 1, 'file_memo': '자동 저장'}, 'tester')
        self.assertEqual(self.row(), ('상품페이지 내 항목 부재(3건)', '자동 저장', 'tester'))
        self.update({'daily_id': 1, 'memo': ''}, 'tester')
        self.assertEqual(self.row(), ('', '자동 저장', 'tester'))


if __name__ == '__main__':
    unittest.main()
