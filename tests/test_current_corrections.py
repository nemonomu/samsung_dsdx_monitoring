"""Execute the current-state list queries against a local SQL fixture, never production."""
import sqlite3
import json
import re
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

from tests import test_collection_statistics_backend
from apps.dx.dx_layer4.corrections import detail, services


class CurrentCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', detect_types=sqlite3.PARSE_DECLTYPES)
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda v: v.strip() if v else v)
        self.db.executescript('''
            CREATE TABLE monitoring_corrections (
                id INTEGER PRIMARY KEY, layer INTEGER DEFAULT 2,
                correction_type TEXT DEFAULT 'null_check',
                table_name TEXT DEFAULT 'dx_seib.dx_seib_ref_retail_com',
                record_id INTEGER DEFAULT 42, column_name TEXT DEFAULT 'ref_capacity',
                old_value TEXT, new_value TEXT, crawl_date DATE DEFAULT '2026-10-23',
                status TEXT, memo TEXT, created_id TEXT, created_at TIMESTAMP,
                reason TEXT, retailer TEXT DEFAULT 'MediaMarkt', item TEXT DEFAULT '186101572',
                rule_id INTEGER, updated_id TEXT, updated_at TIMESTAMP, cancel_memo TEXT
            );
            CREATE TABLE monitoring_validation_rules (id INTEGER PRIMARY KEY, detail_name TEXT);
            INSERT INTO monitoring_validation_rules VALUES (1, 'price'), (2, 'ratings');
        ''')

    def add(self, ident, status, time='17:32:59', **fields):
        fields = dict(id=ident, status=status, created_at='2026-10-23 '+time,
                      created_id='admin', **fields)
        self.db.execute('INSERT INTO monitoring_corrections ('+', '.join(fields)+') VALUES ('+
                        ', '.join('?' for _ in fields)+')', list(fields.values()))

    def read(self, **filters):
        db = self.db

        class Cursor:
            def __init__(self):
                self.cursor = db.cursor()

            def execute(self, sql, params):
                assert sql.lstrip().startswith('SELECT'), sql
                if 'jsonb_to_recordset' in sql:
                    # PostgreSQL expands the bound JSON; emulate only that table
                    # function, then execute the actual union/ranking/filter SQL.
                    params = list(params)
                    payload = json.loads(params.pop(1))
                    db.execute('DROP TABLE IF EXISTS saved_reviews')
                    db.execute('CREATE TEMP TABLE saved_reviews AS SELECT * FROM monitoring_corrections WHERE 0')
                    for row in payload:
                        db.execute('INSERT INTO saved_reviews (' + ','.join(row) + ') VALUES (' +
                                   ','.join('?' for _ in row) + ')', list(row.values()))
                    sql = re.sub(r'jsonb_to_recordset\(%s::jsonb\) AS saved\([^)]*\)', 'saved_reviews', sql)
                self.cursor.execute(sql.replace('%s', '?').replace(' ILIKE ', ' LIKE '), params)

            def fetchall(self):
                names = [column[0] for column in self.cursor.description]
                return [tuple(datetime.fromisoformat(value) if name in ('created_at', 'updated_at')
                              and isinstance(value, str) else value for name, value in zip(names, row))
                        for row in self.cursor.fetchall()]

            def fetchone(self):
                return self.cursor.fetchone()

        @contextmanager
        def connection():
            yield db, Cursor()

        with patch.object(services, 'dx_connection', connection), \
             patch.object(detail, '_sources', return_value={}), \
             patch.object(detail, 'enrich_list', return_value=[]):
            return services.get_corrections(date(2026, 10, 23), **filters)

    def test_cancel_then_correct_counts_only_latest_and_preserves_audit_rows(self):
        self.add(1, 'reverted', '11:08:31', new_value=None,
                 updated_at='2026-10-23 18:00:00')
        self.add(2, 'corrected', new_value='322 L')
        result = self.read()
        self.assertEqual([2], [r['id'] for r in result['items']])
        self.assertEqual({'corrected': 1, 'normal': 0, 'error': 0, 'reverted': 0}, result['status_counts'])
        self.assertEqual({'null_check': 1}, result['type_counts'])
        self.assertEqual(1, result['total'])
        self.assertEqual(2, self.db.execute('SELECT COUNT(*) FROM monitoring_corrections').fetchone()[0])
        # Filtering to an old status/reviewer must never resurrect a superseded event.
        self.assertEqual(0, self.read(status='reverted')['total'])
        self.assertEqual(0, self.read(reviewer='old-reviewer')['total'])

    def test_repeated_corrections_ties_and_new_confirmation_use_latest_event(self):
        self.add(1, 'corrected', new_value='300 L')
        self.add(2, 'corrected', new_value='322 L')
        self.assertEqual('322 L', self.read()['items'][0]['new_value'])
        self.add(3, 'normal', new_value='322 L')
        self.assertEqual(0, self.read(status='corrected')['total'])
        self.assertEqual([3], [r['id'] for r in self.read(status='normal')['items']])

    def test_cancel_without_new_review_remains_cancelled_not_previous_correction(self):
        self.add(1, 'corrected', '10:00:00')
        self.add(2, 'reverted')
        result = self.read()
        self.assertEqual([2], [r['id'] for r in result['items']])
        self.assertEqual(1, result['status_counts']['reverted'])

    def test_different_columns_records_tables_dates_and_validation_rules_stay_separate(self):
        self.add(1, 'corrected')
        self.add(2, 'normal', column_name='sku')
        self.add(3, 'normal', record_id=43)
        self.add(4, 'normal', table_name='dx_seuk.dx_seuk_ref_retail_com')
        self.add(5, 'normal', correction_type='format_check')
        self.add(6, 'normal', correction_type='cross_field', rule_id=1)
        self.add(7, 'normal', correction_type='cross_field', rule_id=2)
        self.add(8, 'corrected', correction_type='cross_field', rule_id=1)
        self.add(9, 'normal', crawl_date='2026-10-22')
        self.assertEqual({1, 2, 3, 4, 5, 7, 8}, {r['id'] for r in self.read()['items']})
        result = self.read(correction_type='cross_field')
        self.assertEqual(2, result['total'])
        self.assertEqual([{'name': 'price'}, {'name': 'ratings'}], result['rule_options'])

    def test_public_aliases_match_but_records_without_ids_are_not_collapsed(self):
        self.add(1, 'reverted', '10:00:00', table_name='public.tv_retail_com')
        self.add(2, 'corrected', table_name='tv_retail_com')
        self.add(3, 'normal', record_id=None)
        self.add(4, 'normal', record_id=None)
        self.assertEqual({2, 3, 4}, {r['id'] for r in self.read()['items']})

    def test_counts_pagination_and_filter_options_use_same_current_subjects(self):
        self.add(1, 'reverted', '10:00:00')
        self.db.execute("UPDATE monitoring_corrections SET created_id='old-reviewer' WHERE id=1")
        self.add(2, 'corrected')
        self.add(3, 'normal', record_id=43)
        result = self.read(page_size=1)
        self.assertEqual(2, result['total'])
        self.assertEqual(2, result['total_pages'])
        self.assertEqual([3], [r['id'] for r in result['items']])
        self.assertEqual(['admin'], result['filter_options']['reviewers'])
        self.assertEqual([2], [r['id'] for r in self.read(page=2, page_size=1)['items']])
        self.assertEqual(0, self.read(reviewer='old-reviewer')['total'])
        self.assertEqual(2, self.read(retailer=' mediamarkt ', search_field='item_column',
                                     search_value='ref_capacity')['total'])

    def review(self, ident=-1, **extra):
        return dict(id=ident, layer=2, correction_type='format_check',
                    table_name='dx_seib.dx_seib_ref_retail_com', record_id=42,
                    column_name='ref_capacity', old_value=None, new_value='322 L',
                    crawl_date='2026-10-23', status='normal', memo='', reason='reviewed',
                    created_id='reviewer', created_at='2026-10-23 20:00:00',
                    _sort_created_at='2026-10-23 11:00:00', retailer='MediaMarkt', item='186101572',
                    country='SEIB', product='REF', review_source='format_review',
                    review_event_id=1, review_target=0, review_record=0, **extra)

    def test_saved_reviews_merge_before_ranking_filtering_and_pagination(self):
        from apps.dx.dx_layer4.corrections import format_reviews
        self.add(1, 'corrected', '10:00:00', correction_type='format_check')
        self.add(2, 'corrected', '12:00:00', record_id=100)
        rows = [self.review(), self.review(-2)]
        rows[1].update(record_id=43, status='error', item='OTHER')
        with patch.object(format_reviews, 'list_rows', return_value=rows):
            result = self.read(page_size=1)
            self.assertEqual(3, result['total'])
            self.assertEqual(3, result['total_pages'])
            self.assertEqual([2], [r['id'] for r in result['items']])
            self.assertEqual({'corrected':1,'normal':1,'error':1,'reverted':0}, result['status_counts'])
            self.assertEqual(1, self.read(status='corrected')['total'])
            self.assertEqual(-1, self.read(status='normal')['items'][0]['id'])
            self.assertEqual('reviewed', self.read(status='error')['items'][0]['reason'])
            self.assertEqual(0, self.read(reviewer='admin', correction_type='format_check')['total'])
            self.assertEqual(1, self.read(search_field='item_column', search_value='OTHER')['total'])
            self.assertEqual({'null_check':1,'format_check':2}, result['type_counts'])
            # A later source correction supersedes the saved confirmation.
            self.add(3, 'corrected', '13:00:00', correction_type='format_check')
            self.assertEqual(0, self.read(status='normal')['total'])

    def test_format_review_ids_cannot_reach_legacy_cancel_updates(self):
        with patch.object(services, 'dx_connection') as connect:
            with self.assertRaises(ValueError):
                services.cancel_corrections([-1], 'cancel', 'reviewer')
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
