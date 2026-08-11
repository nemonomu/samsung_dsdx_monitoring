import unittest

from tests.unit.support import load_module, module_stub, package_stub


class BackupCursor:
    def __init__(self, pending=None, inserted=None, fail_on=''):
        self.pending = pending or {}
        self.inserted = inserted or {}
        self.fail_on = fail_on
        self.calls = []
        self.current = None
        self.closed = False

    def execute(self, sql, params=None):
        normalized = ' '.join(sql.split())
        self.calls.append((normalized, params))
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError('simulated backup failure')
        if 'SELECT COUNT(*)' in normalized:
            self.current = ('one', (self._value_for(normalized, self.pending),))
        elif 'INSERT INTO monitoring_backup_log' in normalized:
            self.current = ('all', [])
        elif normalized.startswith('INSERT INTO'):
            values = [(value,) for value in self._value_for(normalized, self.inserted)]
            self.current = ('all', values)
        else:
            self.current = ('all', [])

    @staticmethod
    def _value_for(sql, values):
        for marker, value in values.items():
            if marker in sql:
                return value
        return 0 if 'SELECT COUNT(*)' in sql else []

    def fetchone(self):
        return self.current[1]

    def fetchall(self):
        return self.current[1]

    def close(self):
        self.closed = True


class BackupConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def load_backup(connection, errors=None):
    errors = errors if errors is not None else []
    return load_module(
        'apps/common/backup.py',
        'tests._backup_under_test',
        {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db', get_dx_connection=lambda: connection,
            ),
            'apps.common.response': module_stub(
                'apps.common.response',
                log_error=lambda error, category='': errors.append((error, category)),
            ),
        },
    )


class BackupTests(unittest.TestCase):
    def test_pending_count_includes_sea_and_all_tse_sources(self):
        cursor = BackupCursor(pending={
            'tv_retail_com_backup_all': 5,
            'dx_tse_tv_retail_com_backup': 4,
            'dx_tse_ref_retail_com_backup': 3,
            'dx_tse_ldy_retail_com_backup': 2,
        })
        connection = BackupConnection(cursor)
        backup = load_backup(connection)

        result = backup.get_backup_count('2026-08-11')

        self.assertEqual(result['tv_count'], 5)
        self.assertEqual(result['tse_tv_count'], 4)
        self.assertEqual(result['tse_ref_count'], 3)
        self.assertEqual(result['tse_ldy_count'], 2)
        self.assertEqual(result['total_count'], 14)
        count_sql = [sql for sql, _ in cursor.calls if 'SELECT COUNT(*)' in sql]
        self.assertEqual(len(count_sql), 4)
        self.assertIn('DATE(a.crawl_datetime::timestamp) = %s', count_sql[0])
        self.assertTrue(all(
            'LEFT(TRIM(a.crawl_datetime), 10) = %s' in sql
            for sql in count_sql[1:]
        ))
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_integrated_backup_commits_once_and_reports_actual_inserts(self):
        cursor = BackupCursor(inserted={
            'tv_retail_com_backup_all': [10, 11],
            'dx_tse_tv_retail_com_backup': [20],
            'dx_tse_ref_retail_com_backup': [],
            'dx_tse_ldy_retail_com_backup': [30, 31, 32],
        })
        connection = BackupConnection(cursor)
        backup = load_backup(connection)

        result = backup.backup_all_retail('tester', '2026-08-11')

        self.assertTrue(result['success'])
        self.assertEqual(result['tv']['count'], 2)
        self.assertEqual(result['tse_tv']['count'], 1)
        self.assertEqual(result['tse_ref']['count'], 0)
        self.assertEqual(result['tse_ldy']['count'], 3)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        insert_sql = [
            sql for sql, _ in cursor.calls
            if sql.startswith('INSERT INTO')
            and 'monitoring_backup_log' not in sql
        ]
        self.assertEqual(len(insert_sql), 4)
        self.assertTrue(all('ON CONFLICT DO NOTHING' in sql for sql in insert_sql))
        self.assertTrue(all('RETURNING id' in sql for sql in insert_sql))
        log_calls = [
            params for sql, params in cursor.calls
            if 'INSERT INTO monitoring_backup_log' in sql
        ]
        self.assertEqual(len(log_calls), 3)
        self.assertEqual([params[0] for params in log_calls], ['tv', 'tse_tv', 'tse_ldy'])
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_any_source_failure_rolls_back_the_whole_backup(self):
        cursor = BackupCursor(
            inserted={
                'tv_retail_com_backup_all': [10],
                'dx_tse_tv_retail_com_backup': [20],
            },
            fail_on='INSERT INTO dx_tse.dx_tse_ref_retail_com_backup',
        )
        connection = BackupConnection(cursor)
        errors = []
        backup = load_backup(connection, errors)

        result = backup.backup_all_retail('tester', '2026-08-11')

        self.assertFalse(result['success'])
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertIn('전체 백업을 취소했습니다', result['error'])
        self.assertFalse(any(
            'INSERT INTO dx_tse.dx_tse_ldy_retail_com_backup' in sql
            for sql, _ in cursor.calls
        ))
        self.assertEqual(errors[0][1], 'backup')
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_backup_status_returns_zero_without_history_query(self):
        cursor = BackupCursor()
        connection = BackupConnection(cursor)
        backup = load_backup(connection)
        backup.get_backup_count = lambda target_date: {
            'success': True,
            'tv_count': 0,
            'hhp_count': 0,
            'tse_tv_count': 0,
            'tse_ref_count': 0,
            'tse_ldy_count': 0,
            'total_count': 0,
        }

        result = backup.get_backup_status('2026-08-11')

        self.assertEqual({
            'success': True,
            'pending_count': 0,
            'has_backup': True,
        }, result)
        self.assertEqual([], cursor.calls)

    def test_backup_status_exposes_each_pending_source_count(self):
        cursor = BackupCursor(pending={'monitoring_backup_log': 1})
        connection = BackupConnection(cursor)
        backup = load_backup(connection)
        backup.get_backup_count = lambda target_date: {
            'success': True,
            'tv_count': 1,
            'hhp_count': 0,
            'tse_tv_count': 2,
            'tse_ref_count': 3,
            'tse_ldy_count': 4,
            'total_count': 10,
        }

        result = backup.get_backup_status('2026-08-11')

        self.assertTrue(result['success'])
        self.assertTrue(result['has_backup'])
        self.assertEqual(result['pending_count'], 10)
        self.assertEqual(result['tv_count'], 1)
        self.assertEqual(result['tse_tv_count'], 2)
        self.assertEqual(result['tse_ref_count'], 3)
        self.assertEqual(result['tse_ldy_count'], 4)
        self.assertEqual(connection.commits, 0)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


if __name__ == '__main__':
    unittest.main()
