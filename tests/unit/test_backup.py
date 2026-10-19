import unittest
from apps.common import sea_dates
from apps.common.source_dates import source_date_value
from apps.common.seg_retail import SEG_SOURCE_CONFIG
from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from datetime import date, timedelta

from tests.unit.support import load_module, module_stub, package_stub


class MonitoringDateError(ValueError):
    pass


def resolve_monitoring_date(inspection_date, country, source_key):
    if not isinstance(inspection_date, str):
        raise MonitoringDateError('검수일은 YYYY-MM-DD 형식으로 입력해야 합니다.')
    try:
        parsed_date = date.fromisoformat(inspection_date)
    except ValueError as error:
        raise MonitoringDateError('검수일은 YYYY-MM-DD 형식으로 입력해야 합니다.') from error
    if parsed_date.isoformat() != inspection_date:
        raise MonitoringDateError('검수일은 YYYY-MM-DD 형식으로 입력해야 합니다.')
    offset_days = -1 if country in ('SEA', 'SEDA') else 0
    return {
        'inspection_date': inspection_date,
        'source_date': (parsed_date + timedelta(days=offset_days)).isoformat(),
        'offset_days': offset_days,
        'country': country,
        'source_key': source_key,
    }


SEA_RETAIL_SOURCES = {
    'tv': {
        'key': 'tv', 'source_key': 'sea_tv', 'category': 'TV',
        'product_line': 'tv', 'table_name': 'public.tv_retail_com',
        'backup_table': 'public.tv_retail_com_backup_all',
        'date_column': 'crawl_datetime', 'date_mode': 'timestamp',
    },
    'ref': {
        'key': 'sea_ref', 'source_key': 'sea_ref', 'category': 'REF',
        'product_line': 'sea_ref', 'table_name': 'public.ref_retail_com',
        'backup_table': 'public.ref_retail_com_backup',
        'date_column': 'crawl_strdatetime', 'date_mode': 'text_prefix',
    },
    'ldy': {
        'key': 'sea_ldy', 'source_key': 'sea_ldy', 'category': 'LDY',
        'product_line': 'sea_ldy', 'table_name': 'public.ldy_retail_com',
        'backup_table': 'public.ldy_retail_com_backup',
        'date_column': 'crawl_strdatetime', 'date_mode': 'text_prefix',
    },
}

SIEL_SOURCE_CONFIG = {
    'siel_tv': {
        'source_key': 'siel_tv', 'category': 'TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_tv_retail_com_backup',
        'date_column': 'crawl_datetime',
    },
    'siel_ref': {
        'source_key': 'siel_ref', 'category': 'REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ref_retail_com_backup',
        'date_column': 'crawl_datetime',
    },
    'siel_ldy': {
        'source_key': 'siel_ldy', 'category': 'LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ldy_retail_com_backup',
        'date_column': 'crawl_datetime',
    },
}

SEM_SOURCE_CONFIG = {
    f'sem_{product}': {
        'source_key': f'sem_{product}',
        'category': category,
        'table_name': f'dx_sem.dx_sem_{product}_retail_com',
        'backup_table_name': f'dx_sem.dx_sem_{product}_retail_com_backup',
        'date_column': 'crawl_datetime',
    }
    for product, category in (('tv', 'TV'), ('ref', 'REF'), ('ldy', 'LDY'), ('ldy_dryer', 'LDY_DRYER'))
}

SEIB_SOURCE_CONFIG = {
    f'seib_{product}': {
        'source_key': f'seib_{product}',
        'display_name': f'SEIB {product.upper()}',
        'table_name': f'dx_seib.dx_seib_{product}_retail_com',
    }
    for product in ('tv', 'ref', 'ldy', 'ldy_dryer')
}


def backup_date_payload():
    source_dates = {
        'sea_tv': '2026-08-10',
        'sea_ref': '2026-08-10',
        'sea_ldy': '2026-08-10',
        'seda_tv': '2026-08-10',
        'seda_ref': '2026-08-10',
        'seda_ldy': '2026-08-10',
        'siel_tv': '2026-08-11',
        'siel_ref': '2026-08-11',
        'siel_ldy': '2026-08-11',
        'tse_tv': '2026-08-11',
        'tse_ref': '2026-08-11',
        'tse_ldy': '2026-08-11',
        'sem_tv': '2026-08-11',
        'sem_ref': '2026-08-11',
        'sem_ldy': '2026-08-11',
    }
    return {
        'inspection_date': '2026-08-11',
        'source_dates': source_dates,
        'date_mappings': {
            source_key: {
                'inspection_date': '2026-08-11',
                'source_date': source_date,
            }
            for source_key, source_date in source_dates.items()
        },
    }


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
            'apps.common.inspection_dates': module_stub(
                'apps.common.inspection_dates',
                MonitoringDateError=MonitoringDateError,
                resolve_monitoring_date=resolve_monitoring_date,
            ),
            'apps.common.response': module_stub(
                'apps.common.response',
                log_error=lambda error, category='': errors.append((error, category)),
            ),
            'apps.common.sea_dates': sea_dates,
            'apps.common.sea_retail': module_stub(
                'apps.common.sea_retail',
                SEA_RETAIL_SOURCES=SEA_RETAIL_SOURCES,
            ),
            'apps.common.siel_retail': module_stub(
                'apps.common.siel_retail',
                SIEL_BUSINESS_TIMEZONE='Asia/Seoul',
                SIEL_SOURCE_CONFIG=SIEL_SOURCE_CONFIG,
            ),
            'apps.common.sem_retail': module_stub(
                'apps.common.sem_retail',
                SEM_SOURCE_CONFIG=SEM_SOURCE_CONFIG,
            ),
            'apps.common.seg_retail': module_stub(
                'apps.common.seg_retail', SEG_SOURCE_CONFIG=SEG_SOURCE_CONFIG,
            ),
            'apps.common.seda_retail': module_stub(
                'apps.common.seda_retail', SEDA_SOURCE_CONFIG=SEDA_SOURCE_CONFIG,
            ),
            'apps.common.seib_retail': module_stub(
                'apps.common.seib_retail', SEIB_SOURCE_CONFIG=SEIB_SOURCE_CONFIG,
            ),
            'apps.common.source_dates': module_stub(
                'apps.common.source_dates',
                source_date_sql=lambda column: f'LEFT(BTRIM(CAST({column} AS TEXT)), 10)',
            ),
        },
    )


class BackupTests(unittest.TestCase):
    def test_sea_and_sem_dryer_backup_use_original_source_dates(self):
        cursor = BackupCursor(
            pending={'public.ldy_dryer_retail_backup': 2,
                     'dx_sem_ldy_dryer_retail_com_backup': 3},
            inserted={'public.ldy_dryer_retail_backup': [1, 2],
                      'dx_sem_ldy_dryer_retail_com_backup': [3, 4, 5]},
        )
        connection = BackupConnection(cursor)
        backup = load_backup(connection)
        counts = backup.get_backup_count('2026-10-19')
        self.assertEqual(2, counts['sea_ldy_dryer_count'])
        self.assertEqual(3, counts['sem_ldy_dryer_count'])
        self.assertEqual('2026-10-18', counts['source_dates']['sea_ldy_dryer'])
        self.assertEqual('2026-10-19', counts['source_dates']['sem_ldy_dryer'])
        result = backup.backup_all_retail('tester', '2026-10-19')
        self.assertEqual(2, result['sea_ldy_dryer']['count'])
        self.assertEqual(3, result['sem_ldy_dryer']['count'])
        self.assertEqual(1, connection.commits)
        for table, day in (('public.ldy_dryer_retail', '2026-10-18'),
                           ('dx_sem.dx_sem_ldy_dryer_retail_com', '2026-10-19')):
            scoped = [(sql, params) for sql, params in cursor.calls if table + ' a' in sql]
            self.assertEqual(2, len(scoped))
            for sql, params in scoped:
                self.assertIn('LEFT(BTRIM(CAST(a.crawl_datetime AS TEXT)), 10) = %s', sql)
                self.assertEqual((day,), params)

    def test_sea_appliance_pending_and_insert_share_recorded_source_date(self):
        cursor = BackupCursor()
        backup = load_backup(BackupConnection(cursor))
        for product in ('ref', 'ldy'):
            source = backup._sea_backup_source(product)
            mapping = {'inspection_date': '2026-09-18', 'source_date': '2026-09-17',
                       'offset_days': -1, 'source_key': source['source_key']}
            backup._count_pending_source(cursor, source, mapping['source_date'])
            backup._backup_source(cursor, source, 'tester', mapping)
            predicate, params = backup._date_condition(
                source['date_column'], mapping['source_date'], source['date_mode'])
            scoped_calls = [(sql, bound) for sql, bound in cursor.calls
                            if source['source_table'] + ' a' in sql]
            self.assertEqual(2, len(scoped_calls))
            for sql, bound in scoped_calls:
                self.assertIn(' '.join(predicate.split()), sql)
                self.assertEqual(('2026-09-17',), bound)
            self.assertIn('LEFT(BTRIM(CAST(a.crawl_strdatetime AS TEXT)), 10)', predicate)
            self.assertEqual(('2026-09-17',), params)

    def test_seg_backup_uses_existing_tables_and_same_day_ids(self):
        cursor = BackupCursor(
            pending={'dx_seg_tv_retail_com_backup': 2},
            inserted={'dx_seg_tv_retail_com_backup': [10, 11]},
        )
        backup = load_backup(BackupConnection(cursor))
        counts = backup.get_backup_count('2026-08-11')
        self.assertEqual(2, counts['seg_tv_count'])
        self.assertEqual(2, counts['total_count'])
        self.assertEqual('2026-08-11', counts['source_dates']['seg_ldy'])
        result = backup.backup_all_retail('tester', '2026-08-11')
        self.assertEqual(2, result['seg_tv']['count'])
        inserts = [(sql, params) for sql, params in cursor.calls
                   if sql.startswith('INSERT INTO dx_seg.')]
        self.assertEqual(3, len(inserts))
        for sql, params in inserts:
            self.assertIn('ON a.id = b.id', sql)
            self.assertIn('WHERE b.id IS NULL', sql)
            self.assertNotIn('redirect', sql)
            self.assertEqual(('2026-08-11',), params)

    def test_seib_backup_covers_four_sources_on_original_same_day(self):
        self.assertEqual(
            '2026-10-18', source_date_value('2026-10-18T23:37:34-04:00'),
        )
        cursor = BackupCursor(
            pending={'dx_seib_ldy_dryer_retail_com_backup': 2},
            inserted={'dx_seib_ldy_dryer_retail_com_backup': [11, 12]},
        )
        connection = BackupConnection(cursor)
        backup = load_backup(connection)

        counts = backup.get_backup_count('2026-10-18')
        self.assertEqual(2, counts['seib_ldy_dryer_count'])
        self.assertEqual('2026-10-18', counts['source_dates']['seib_ldy_dryer'])
        self.assertEqual(2, counts['total_count'])

        result = backup.backup_all_retail('tester', '2026-10-18')
        self.assertTrue(result['success'])
        self.assertEqual(2, result['seib_ldy_dryer']['count'])
        self.assertEqual(1, connection.commits)
        for product in ('tv', 'ref', 'ldy', 'ldy_dryer'):
            source_table = f'dx_seib.dx_seib_{product}_retail_com'
            backup_table = source_table + '_backup'
            scoped = [(sql, params) for sql, params in cursor.calls
                      if source_table + ' a' in sql]
            self.assertEqual(2, len(scoped))
            for sql, params in scoped:
                self.assertIn(backup_table, sql)
                self.assertIn('LEFT(BTRIM(CAST(a.crawl_datetime AS TEXT)), 10) = %s', sql)
                self.assertEqual(('2026-10-18',), params)


    def test_pending_count_includes_all_retail_sources(self):
        cursor = BackupCursor(pending={
            'tv_retail_com_backup_all': 5,
            'public.ref_retail_com_backup': 6,
            'public.ldy_retail_com_backup': 7,
            'dx_seda_tv_retail_com_backup': 14,
            'dx_seda_ref_retail_com_backup': 15,
            'dx_seda_ldy_retail_com_backup': 16,
            'dx_tse_tv_retail_com_backup': 4,
            'dx_tse_ref_retail_com_backup': 3,
            'dx_tse_ldy_retail_com_backup': 2,
            'dx_siel_tv_retail_com_backup': 8,
            'dx_siel_ref_retail_com_backup': 9,
            'dx_siel_ldy_retail_com_backup': 10,
            'dx_sem_tv_retail_com_backup': 11,
            'dx_sem_ref_retail_com_backup': 12,
            'dx_sem_ldy_retail_com_backup': 13,
        })
        connection = BackupConnection(cursor)
        backup = load_backup(connection)

        result = backup.get_backup_count('2026-08-11')

        self.assertEqual(result['tv_count'], 5)
        self.assertEqual(result['sea_ref_count'], 6)
        self.assertEqual(result['sea_ldy_count'], 7)
        self.assertEqual(result['seda_tv_count'], 14)
        self.assertEqual(result['seda_ref_count'], 15)
        self.assertEqual(result['seda_ldy_count'], 16)
        self.assertEqual(result['siel_tv_count'], 8)
        self.assertEqual(result['siel_ref_count'], 9)
        self.assertEqual(result['siel_ldy_count'], 10)
        self.assertEqual(result['tse_tv_count'], 4)
        self.assertEqual(result['tse_ref_count'], 3)
        self.assertEqual(result['tse_ldy_count'], 2)
        self.assertEqual(result['sem_tv_count'], 11)
        self.assertEqual(result['sem_ref_count'], 12)
        self.assertEqual(result['sem_ldy_count'], 13)
        self.assertEqual(result['total_count'], 135)
        self.assertEqual(result['inspection_date'], '2026-08-11')
        self.assertEqual(result['source_dates']['sea_tv'], '2026-08-10')
        self.assertEqual(result['source_dates']['sea_ref'], '2026-08-10')
        self.assertEqual(result['source_dates']['sea_ldy'], '2026-08-10')
        self.assertEqual(result['source_dates']['seda_tv'], '2026-08-10')
        self.assertEqual(result['source_dates']['siel_tv'], '2026-08-11')
        self.assertEqual(result['source_dates']['tse_tv'], '2026-08-11')
        count_calls = [
            (sql, params)
            for sql, params in cursor.calls
            if 'SELECT COUNT(*)' in sql
        ]
        self.assertEqual(len(count_calls), 24)
        self.assertIn(
            'FROM public.tv_retail_com a',
            count_calls[0][0],
        )
        self.assertIn(
            'DATE(a.crawl_datetime::timestamp) = %s',
            count_calls[0][0],
        )
        self.assertIn('FROM public.ref_retail_com a', count_calls[1][0])
        self.assertIn('FROM public.ldy_retail_com a', count_calls[2][0])
        self.assertIn('FROM public.ldy_dryer_retail a', count_calls[3][0])
        self.assertTrue(all(
            'LEFT(BTRIM(CAST(a.crawl_strdatetime AS TEXT)), 10)' in sql
            and "AT TIME ZONE 'America/New_York'" not in sql
            for sql, _ in count_calls[1:3]
        ))
        self.assertTrue(all(
            'LEFT(TRIM(a.crawl_strdatetime), 10) = %s' in sql
            for sql, _ in count_calls[4:7]
        ))
        self.assertIn(
            'FROM dx_seda.dx_seda_tv_retail_com a', count_calls[4][0],
        )
        self.assertTrue(all(
            'LEFT(TRIM(a.crawl_datetime), 10) = %s' in sql
            for sql, _ in count_calls[7:10]
        ))
        self.assertIn(
            'FROM dx_siel.dx_siel_tv_retail_com a', count_calls[10][0],
        )
        self.assertTrue(all(
            "AT TIME ZONE 'Asia/Seoul'" in sql
            for sql, _ in count_calls[10:13]
        ))
        self.assertTrue(all(
            'LEFT(TRIM(a.crawl_datetime), 10) = %s' in sql
            for sql, _ in count_calls[13:16]
        ))
        self.assertTrue(all(
            'LEFT(TRIM(a.crawl_strdatetime), 10) = %s' in sql
            and 'redirect' not in sql
            for sql, _ in count_calls[17:20]
        ))
        self.assertTrue(all(
            'LEFT(BTRIM(CAST(a.crawl_datetime AS TEXT)), 10) = %s' in sql
            for sql, _ in count_calls[20:]
        ))
        self.assertTrue(all(
            'batch_id' not in sql and 'page_type' not in sql
            for sql, _ in count_calls[:3]
        ))
        self.assertEqual(
            [params for _, params in count_calls],
            [('2026-08-10',)] * 7 +
            [('2026-08-11',)] * 3 +
            [('2026-08-11', '2026-08-11')] * 3 +
            [('2026-08-11',)] * 11,
        )
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_missing_or_invalid_inspection_date_fails_before_database_access(self):
        for inspection_date in (None, '', '20260811', '2026-02-30'):
            with self.subTest(inspection_date=inspection_date):
                cursor = BackupCursor()
                connection = BackupConnection(cursor)
                backup = load_backup(connection)

                count_result = backup.get_backup_count(inspection_date)
                backup_result = backup.backup_all_retail(
                    'tester', inspection_date,
                )

                self.assertFalse(count_result['success'])
                self.assertFalse(backup_result['success'])
                self.assertEqual(
                    count_result['error_code'],
                    'invalid_inspection_date',
                )
                self.assertEqual([], cursor.calls)
                self.assertEqual(connection.commits, 0)
                self.assertEqual(connection.rollbacks, 0)

    def test_integrated_backup_commits_once_and_reports_actual_inserts(self):
        cursor = BackupCursor(inserted={
            'tv_retail_com_backup_all': [10, 11],
            'public.ref_retail_com_backup': [12, 13],
            'public.ldy_retail_com_backup': [14],
            'dx_seda_tv_retail_com_backup': [15],
            'dx_seda_ref_retail_com_backup': [],
            'dx_seda_ldy_retail_com_backup': [16],
            'dx_tse_tv_retail_com_backup': [20],
            'dx_tse_ref_retail_com_backup': [],
            'dx_tse_ldy_retail_com_backup': [30, 31, 32],
            'dx_siel_tv_retail_com_backup': [40],
            'dx_siel_ref_retail_com_backup': [50, 51],
            'dx_siel_ldy_retail_com_backup': [],
            'dx_sem_tv_retail_com_backup': [60, 61],
            'dx_sem_ref_retail_com_backup': [],
            'dx_sem_ldy_retail_com_backup': [70],
        })
        connection = BackupConnection(cursor)
        backup = load_backup(connection)

        result = backup.backup_all_retail('tester', '2026-08-11')

        self.assertTrue(result['success'])
        self.assertEqual(result['tv']['count'], 2)
        self.assertEqual(result['sea_ref']['count'], 2)
        self.assertEqual(result['sea_ldy']['count'], 1)
        self.assertEqual(result['seda_tv']['count'], 1)
        self.assertEqual(result['seda_ref']['count'], 0)
        self.assertEqual(result['seda_ldy']['count'], 1)
        self.assertEqual(result['siel_tv']['count'], 1)
        self.assertEqual(result['siel_ref']['count'], 2)
        self.assertEqual(result['siel_ldy']['count'], 0)
        self.assertEqual(result['tse_tv']['count'], 1)
        self.assertEqual(result['tse_ref']['count'], 0)
        self.assertEqual(result['tse_ldy']['count'], 3)
        self.assertEqual(result['sem_tv']['count'], 2)
        self.assertEqual(result['sem_ref']['count'], 0)
        self.assertEqual(result['sem_ldy']['count'], 1)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        insert_calls = [
            (sql, params) for sql, params in cursor.calls
            if sql.startswith('INSERT INTO')
            and 'monitoring_backup_log' not in sql
        ]
        self.assertEqual(len(insert_calls), 24)
        self.assertTrue(all(
            'ON CONFLICT DO NOTHING' in sql
            for sql, _ in insert_calls
        ))
        self.assertTrue(all('RETURNING id' in sql for sql, _ in insert_calls))
        self.assertEqual(
            [params for _, params in insert_calls],
            [('2026-08-10',)] * 7 +
            [('2026-08-11',)] * 3 +
            [('2026-08-11', '2026-08-11')] * 3 +
            [('2026-08-11',)] * 11,
        )
        log_calls = [
            params for sql, params in cursor.calls
            if 'INSERT INTO monitoring_backup_log' in sql
        ]
        self.assertEqual(len(log_calls), 11)
        self.assertEqual(
            [params[0] for params in log_calls],
            [
                'tv', 'sea_ref', 'sea_ldy', 'seda_tv', 'seda_ldy',
                'tse_tv', 'tse_ldy',
                'siel_tv', 'siel_ref',
                'sem_tv', 'sem_ldy',
            ],
        )
        self.assertEqual(
            [params[2] for params in log_calls],
            ['2026-08-10'] * 5 + ['2026-08-11'] * 6,
        )
        self.assertEqual(result['inspection_date'], '2026-08-11')
        self.assertEqual(result['tv']['source_date'], '2026-08-10')
        self.assertEqual(result['seda_tv']['source_date'], '2026-08-10')
        self.assertEqual(result['siel_tv']['source_date'], '2026-08-11')
        self.assertEqual(result['tse_tv']['source_date'], '2026-08-11')
        self.assertEqual(result['sem_tv']['source_date'], '2026-08-11')
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
        self.assertEqual(result['failed_source'], 'tse_ref')
        self.assertIn('TSE REF', result['error'])
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
            'sea_ref_count': 0,
            'sea_ldy_count': 0,
            'seda_tv_count': 0,
            'seda_ref_count': 0,
            'seda_ldy_count': 0,
            'siel_tv_count': 0,
            'siel_ref_count': 0,
            'siel_ldy_count': 0,
            'hhp_count': 0,
            'tse_tv_count': 0,
            'tse_ref_count': 0,
            'tse_ldy_count': 0,
            'total_count': 0,
            **backup_date_payload(),
        }

        result = backup.get_backup_status('2026-08-11')

        self.assertTrue(result['success'])
        self.assertEqual(result['pending_count'], 0)
        self.assertTrue(result['has_backup'])
        self.assertEqual(result['sea_ref_count'], 0)
        self.assertEqual(result['sea_ldy_count'], 0)
        self.assertEqual(result['siel_tv_count'], 0)
        self.assertEqual(result['inspection_date'], '2026-08-11')
        self.assertEqual(result['source_dates']['sea_tv'], '2026-08-10')
        self.assertEqual([], cursor.calls)

    def test_backup_status_exposes_each_pending_source_count(self):
        cursor = BackupCursor(pending={'monitoring_backup_log': 1})
        connection = BackupConnection(cursor)
        backup = load_backup(connection)
        backup.get_backup_count = lambda target_date: {
            'success': True,
            'tv_count': 1,
            'sea_ref_count': 5,
            'sea_ldy_count': 6,
            'seda_tv_count': 10,
            'seda_ref_count': 11,
            'seda_ldy_count': 12,
            'siel_tv_count': 7,
            'siel_ref_count': 8,
            'siel_ldy_count': 9,
            'hhp_count': 0,
            'tse_tv_count': 2,
            'tse_ref_count': 3,
            'tse_ldy_count': 4,
            'total_count': 78,
            **backup_date_payload(),
        }

        result = backup.get_backup_status('2026-08-11')

        self.assertTrue(result['success'])
        self.assertTrue(result['has_backup'])
        self.assertEqual(result['pending_count'], 78)
        self.assertEqual(result['tv_count'], 1)
        self.assertEqual(result['sea_ref_count'], 5)
        self.assertEqual(result['sea_ldy_count'], 6)
        self.assertEqual(result['seda_tv_count'], 10)
        self.assertEqual(result['seda_ref_count'], 11)
        self.assertEqual(result['seda_ldy_count'], 12)
        self.assertEqual(result['siel_tv_count'], 7)
        self.assertEqual(result['siel_ref_count'], 8)
        self.assertEqual(result['siel_ldy_count'], 9)
        self.assertEqual(result['tse_tv_count'], 2)
        self.assertEqual(result['tse_ref_count'], 3)
        self.assertEqual(result['tse_ldy_count'], 4)
        history_calls = [
            (sql, params)
            for sql, params in cursor.calls
            if 'monitoring_backup_log' in sql
        ]
        self.assertEqual(len(history_calls), 1)
        self.assertIn('target_date IN (%s, %s)', history_calls[0][0])
        self.assertEqual(
            history_calls[0][1],
            ('2026-08-10', '2026-08-11'),
        )
        self.assertEqual(connection.commits, 0)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


if __name__ == '__main__':
    unittest.main()
