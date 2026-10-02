"""Cause saves must persist daily memo counts in the same transaction."""
import ast
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import unittest


class CauseMemoSyncTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS ssd_crawl_db")
        self.db.executescript('''
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_daily (
                id INTEGER PRIMARY KEY, crawl_date TEXT, retailer_id INTEGER, memo TEXT,
                file_memo TEXT, updated_at TEXT, updated_id TEXT, is_del INTEGER DEFAULT 0);
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_anomaly (
                id INTEGER PRIMARY KEY, crawl_date TEXT, retailer_id INTEGER, cause TEXT,
                memo TEXT, screenshot_id INTEGER, updated_at TEXT, updated_id TEXT, is_del INTEGER DEFAULT 0);
            CREATE TABLE ssd_crawl_db.ds_monitoring_report_close (crawl_date TEXT PRIMARY KEY, is_closed INTEGER);
        ''')
        self.db.executemany('INSERT INTO ssd_crawl_db.ds_monitoring_report_daily '
                            '(id, crawl_date, retailer_id, memo, file_memo) VALUES (?, ?, ?, ?, ?)', [
            (1, '2026-10-01', 1, '항목 부재(3건)', '파일 메모 유지'),
            (2, '2026-10-01', 2, '다른 리테일러 메모', '다른 파일 메모'),
            (3, '2026-09-30', 1, '과거 날짜 메모', ''),
        ])
        self.db.executemany('INSERT INTO ssd_crawl_db.ds_monitoring_report_anomaly '
                            '(id, crawl_date, retailer_id, cause, is_del) VALUES (?, ?, ?, ?, ?)', [
            (1, '2026-10-01', 1, '항목 부재', 0), (2, '2026-10-01', 1, '항목 부재', 0),
            (3, '2026-10-01', 1, '항목 부재', 0), (4, '2026-10-01', 1, '', 0),
            (5, '2026-10-01', 1, 'crawler_null_capture', 0),
            (6, '2026-10-01', 1, '항목 부재', 1),
            (7, '2026-10-01', 2, '항목 부재', 0), (8, '2026-09-30', 1, '항목 부재', 0),
        ])
        self.db.commit()

        class Cursor:
            def __init__(self, db):
                self.cursor = db.cursor()

            def execute(self, sql, params=()):
                self.cursor.execute(sql.replace('%s', '?').replace(' FOR UPDATE', ''), params)

            def fetchone(self):
                return self.cursor.fetchone()

            def fetchall(self):
                return self.cursor.fetchall()

            @property
            def rowcount(self):
                return self.cursor.rowcount

        @contextmanager
        def connection():
            try:
                yield self.db, Cursor(self.db)
            except Exception:
                self.db.rollback()
                raise

        namespace = {'datetime': datetime, 're': re, 'ds_connection': connection,
                     '_SYSTEM_CAUSE_MARKERS': {'crawler_null_capture'},
                     'record_cause_application': lambda *args: None,
                     'fetch_cause_applications': lambda *args: {}}
        path = Path(__file__).resolve().parents[2] / 'apps/ds/ds_layer4/report/report_repositories.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = {'_user_cause', '_cause_counts', '_merge_cause_memo', '_prepare_cause_memos',
                 '_save_cause_memos', 'update_anomaly_report'}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
        self.update = namespace['update_anomaly_report']
        self.merge = namespace['_merge_cause_memo']

    def memo(self, daily_id=1):
        return self.db.execute('SELECT memo FROM ssd_crawl_db.ds_monitoring_report_daily WHERE id = ?',
                               (daily_id,)).fetchone()[0]

    def set_memo(self, value):
        self.db.execute('UPDATE ssd_crawl_db.ds_monitoring_report_daily SET memo = ? WHERE id = 1', (value,))
        self.db.commit()

    def test_two_new_causes_change_three_to_five_without_second_save(self):
        result = self.update({'updates': [{'anomaly_id': 4, 'cause': '항목 부재'},
                                         {'anomaly_id': 5, 'cause': '항목 부재'}]}, 'tester')
        self.assertTrue(result['success'])
        self.assertEqual(result['updated_count'], 2)
        self.assertEqual(self.memo(), '항목 부재(5건)')
        self.assertEqual(result['daily_memos'], [
            {'daily_id': 1, 'memo': '항목 부재(5건)', 'cause_summary': {'항목 부재': 5}}])
        self.assertEqual(self.memo(2), '다른 리테일러 메모')
        self.assertEqual(self.memo(3), '과거 날짜 메모')
        self.assertEqual(self.db.execute('SELECT file_memo FROM ssd_crawl_db.ds_monitoring_report_daily WHERE id = 1')
                         .fetchone()[0], '파일 메모 유지')

    def test_single_cause_change_decreases_old_and_adds_new_count(self):
        result = self.update({'anomaly_id': 1, 'cause': '404페이지'}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(2건), 404페이지(1건)')
        self.assertEqual(result['daily_memos'][0]['cause_summary'], {'항목 부재': 2, '404페이지': 1})

    def test_zero_count_cause_is_removed_and_notes_remain(self):
        self.set_memo('항목 부재(3건), 담당자 확인 예정')
        self.update({'updates': [{'anomaly_id': id, 'cause': '404페이지'} for id in (1, 2, 3)]}, 'tester')
        self.assertEqual(self.memo(), '404페이지(3건), 담당자 확인 예정')

    def test_empty_or_custom_memo_gains_summary_without_losing_notes(self):
        for before, after in [('', '항목 부재(4건)'),
                              ('담당자 확인 예정', '항목 부재(4건), 담당자 확인 예정')]:
            self.set_memo(before)
            self.update({'anomaly_id': 4, 'cause': '항목 부재'}, 'tester')
            self.assertEqual(self.memo(), after)

    def test_cause_removal_and_internal_marker_are_not_counted(self):
        self.update({'anomaly_id': 1, 'cause': ''}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(2건)')
        self.update({'anomaly_id': 2, 'cause': 'crawler_null_capture'}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(1건)')

    def test_repeated_save_does_not_duplicate_summary_or_notes(self):
        self.set_memo('항목 부재(3건), 확인 요청(2건)')
        for _ in range(2):
            self.update({'anomaly_id': 4, 'cause': '항목 부재'}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(4건), 확인 요청(2건)')

    def test_batch_can_update_multiple_retailers(self):
        result = self.update({'updates': [{'anomaly_id': 4, 'cause': '항목 부재'},
                                         {'anomaly_id': 7, 'cause': '404페이지'}]}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(4건)')
        self.assertEqual(self.memo(2), '404페이지(1건), 다른 리테일러 메모')
        self.assertEqual(len(result['daily_memos']), 2)

    def test_memo_or_screenshot_only_update_does_not_rewrite_daily_memo(self):
        self.set_memo('수동으로 작성한 내용')
        for patch in [{'memo': '개별 메모'}, {'screenshot_id': 10}]:
            result = self.update({'anomaly_id': 1, **patch}, 'tester')
            self.assertEqual(result['daily_memos'], [])
            self.assertEqual(self.memo(), '수동으로 작성한 내용')

    def test_deleted_or_unknown_anomalies_do_not_sync(self):
        for id in (6, 999):
            result = self.update({'updates': [{'anomaly_id': id, 'cause': '404페이지'}]}, 'tester')
            self.assertEqual(result['updated_count'], 0)
            self.assertEqual(result['daily_memos'], [])
        self.assertEqual(self.memo(), '항목 부재(3건)')

    def test_memo_write_failure_rolls_back_cause_update(self):
        self.db.executescript('''
            CREATE TRIGGER ssd_crawl_db.reject_memo BEFORE UPDATE ON ds_monitoring_report_daily
            BEGIN SELECT RAISE(ABORT, 'simulated memo failure'); END;
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.update({'anomaly_id': 4, 'cause': '항목 부재'}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(3건)')
        self.assertEqual(self.db.execute('SELECT cause FROM ssd_crawl_db.ds_monitoring_report_anomaly WHERE id = 4')
                         .fetchone()[0], '')

    def test_closed_report_rejects_cause_and_memo_changes(self):
        self.db.execute("INSERT INTO ssd_crawl_db.ds_monitoring_report_close VALUES ('2026-10-01', 1)")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, '마감'):
            self.update({'anomaly_id': 4, 'cause': '항목 부재'}, 'tester')
        self.assertEqual(self.memo(), '항목 부재(3건)')

    def test_summary_labels_with_punctuation_and_multiple_notes(self):
        before = '판매자(공식, 직영)(2건), 404페이지(1건), 담당자 확인, 재확인 예정'
        self.assertEqual(self.merge(before, {'판매자(공식, 직영)': 2, '404페이지': 1}, {'404페이지': 3}),
                         '404페이지(3건), 담당자 확인, 재확인 예정')


if __name__ == '__main__':
    unittest.main()
