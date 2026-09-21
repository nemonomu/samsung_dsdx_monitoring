"""Recommendation boundaries and real latest-batch/history query behavior."""

import re
import sqlite3
import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.dx.dx_layer3.cross_field import seda_services as seda
from tests.unit.support import load_module, module_stub

edits = load_module('apps/dx/dx_layer3/data_edit/services.py', 'seda_recommendation_edits', {
    'apps.common.retail_columns': module_stub(
        'apps.common.retail_columns', get_editable_columns=lambda *_args: ()),
})


DAY = date(2026, 9, 21)
SOURCE = SEDA_SOURCE_CONFIG['seda_tv']


class MemoryCursor:
    def __init__(self, db):
        self.db = db
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        sql = re.sub(r'LEFT\((BTRIM\([^)]+\)), 10\)', r'SUBSTR(\1, 1, 10)', sql)
        sql = sql.replace(' FOR UPDATE OF source', '')
        values = []
        parts = sql.split('%s')
        query = parts[0]
        for value, suffix in zip(params, parts[1:]):
            if isinstance(value, list):
                query = re.sub(r'= ANY\($', 'IN (', query)
                query += ','.join('?' for _ in value) + suffix
                values.extend(value)
            else:
                query += '?' + suffix
                values.append(value)
        self.current = self.db.execute(query, values)
        self.description = self.current.description

    def fetchall(self):
        return self.current.fetchall()

    def fetchone(self):
        return self.current.fetchone()

    def mogrify(self, sql, params):
        # Display SQL is exercised with PostgreSQL in the read-only smoke check.
        return sql.encode('utf-8')


class SedaRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS dx_seda;
            CREATE TABLE monitoring_validation_rules (
                id INTEGER PRIMARY KEY, detail_code TEXT, rule_type TEXT,
                is_active BOOLEAN, section_code TEXT, table_name TEXT, retailer TEXT,
                sort_order INTEGER);
            CREATE TABLE monitoring_corrections (
                record_id INTEGER, layer INTEGER, correction_type TEXT, status TEXT,
                table_name TEXT, crawl_date TEXT, rule_id INTEGER, column_name TEXT,
                memo TEXT, reason TEXT, created_id TEXT, created_at TEXT);
        """)
        for rule_id, (product, source) in enumerate(SEDA_SOURCE_CONFIG.items(), 7):
            fields = ', '.join(f'{col} {"INTEGER PRIMARY KEY" if col == "id" else "TEXT"}'
                               for col in seda.SELECT_COLUMNS)
            self.db.execute(f"CREATE TABLE {source['table_name']} ({fields})")
            self.db.execute('INSERT INTO monitoring_validation_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (rule_id, product + '_recommendation_intent', 'crossfield', True,
                             source['section_code'], source['table_name'], 'CasasBahia', 110))
        self.cursor = MemoryCursor(self.db)
        exclusion = patch.object(seda, 'exclude_page_absent_records',
                                 side_effect=lambda _cursor, _day, rows, **_kwargs: (rows, []))
        exclusion.start()
        self.addCleanup(exclusion.stop)

    def add(self, product='seda_tv', **changes):
        row = dict(id=1, country='SEDA', item='sku-1', account_name='CasasBahia',
                   page_type='MAIN', batch_id='current', crawl_strdatetime='2026-09-20 10:00:00',
                   count_of_reviews='5', recommendation_intent='80% recommend this product')
        row.update(changes)
        table = SEDA_SOURCE_CONFIG[product]['table_name']
        self.db.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                        list(row.values()))

    def test_blank_and_zero_and_boundaries(self):
        for value in (None, '', ' \t ', '0% recommend this product',
                      '100% recommend this product', ' 75% recommend this product '):
            with self.subTest(value=value):
                self.assertTrue(seda.recommendation_valid(value))
        for value in ('101% recommend this product', '-1% recommend this product',
                      '99.5% recommend this product', '80%', '80% Recommend this product',
                      '80% recommend this product extra', '80% would recommend to a friend',
                      'NaN', '１% recommend this product'):
            with self.subTest(value=value):
                self.assertFalse(seda.recommendation_valid(value))

    def test_review_count_does_not_control_recommendation(self):
        for index, reviews in enumerate(('0', '10', None, 'bad'), 1):
            self.add(id=index * 10, count_of_reviews=reviews, recommendation_intent=None)
            self.add(id=index * 10 + 1, count_of_reviews=reviews,
                     recommendation_intent='75% recommend this product')
            self.add(id=index * 10 + 2, count_of_reviews=reviews,
                     recommendation_intent='101% recommend this product')
        result = seda.get_seda_cross_field_summary(self.cursor, DAY, 'seda_tv')
        self.assertEqual((12, 4, 8), (result['total_checked'], result['failed_records'], result['passed_records']))

    def test_latest_main_and_d_minus_one_scope_in_all_products(self):
        for product in SEDA_SOURCE_CONFIG:
            self.add(product, id=1, batch_id='old', recommendation_intent='999% recommend this product')
            self.add(product, id=2, account_name=' Casas Bahia ')
            self.add(product, id=3, page_type='BSR', recommendation_intent='bad')
            self.add(product, id=4, page_type='BSR', batch_id='bsr-only', recommendation_intent='bad')
            self.add(product, id=5, page_type='OTHER', recommendation_intent='bad')
            self.add(product, id=6, account_name='Magalu', recommendation_intent='bad')
            self.add(product, id=7, crawl_strdatetime='2026-09-21 00:01:00', recommendation_intent='bad')
            result = seda.get_seda_cross_field_summary(self.cursor, DAY, product)
            self.assertEqual((2, 1), (result['total_checked'], result['total_anomalies']))
            self.assertEqual(('2026-09-20', -1), (result['source_date'], result['offset_days']))
            self.assertEqual(['Casas Bahia'], result['rule_summary'][0]['retailers'])

    def test_history_is_readonly_and_does_not_count_as_findings(self):
        self.add(id=1, crawl_strdatetime='2026-09-19 10:00:00', recommendation_intent='bad')
        self.add(id=2, crawl_strdatetime='2026-09-18 10:00:00')
        self.add(id=3, recommendation_intent='bad')
        self.add(id=4, item='unrelated')
        detail = seda.get_seda_cross_field_rule_detail(self.cursor, DAY, 'seda_tv', 7, days=3)
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual([(2, 'comparison_history'), (1, 'comparison_history'), (3, 'target')],
                         [(row['id'], row['row_role']) for row in detail['anomalies']])
        self.assertEqual(['recommendation_intent'], detail['editable_columns'])
        self.assertEqual(['sku-1'], detail['retailer_summary']['Casas Bahia']['items'])
        self.assertFalse(seda.get_seda_cross_field_rule_detail(self.cursor, DAY, 'seda_tv', 999)['found'])

    def test_normal_confirmation_is_scoped_to_rule_and_inspection_date(self):
        for row_id in range(1, 4):
            self.add(id=row_id, recommendation_intent='bad')
        for row_id, rule_id, day in ((1, 7, '2026-09-21'), (2, 999, '2026-09-21'), (3, 7, '2026-09-20')):
            self.db.execute('INSERT INTO monitoring_corrections VALUES (?,3,?,?,?, ?,?,?, ?,?,?,?)',
                            (row_id, 'cross_field', 'normal', SOURCE['table_name'], day,
                             rule_id, 'recommendation_intent', 'checked', 'reason', 'user', 'now'))
        result = seda.get_seda_cross_field_summary(self.cursor, DAY, 'seda_tv')
        self.assertEqual(2, result['failed_records'])

    def test_inactive_configuration_does_not_run(self):
        self.db.execute('UPDATE monitoring_validation_rules SET is_active = FALSE')
        result = seda.get_seda_cross_field_summary(self.cursor, DAY, 'seda_tv')
        self.assertFalse(result['configured'])
        self.assertEqual([], result['rule_summary'])
        self.assertEqual(0, result['total_checked'])

    def test_edit_selector_blocks_history_old_batches_magalu_and_other_columns(self):
        self.add(id=1, batch_id='old')
        self.add(id=2)
        self.add(id=3, crawl_strdatetime='2026-09-19 10:00:00')
        self.add(id=4, account_name='Magalu')
        for row_id in (1, 3, 4):
            edits._select_seda_record(self.cursor, SOURCE['table_name'], ('recommendation_intent',), row_id, DAY)
            self.assertIsNone(self.cursor.fetchone())
        edits._select_seda_record(self.cursor, SOURCE['table_name'], ('recommendation_intent',), 2, DAY)
        self.assertIsNotNone(self.cursor.fetchone())
        self.assertEqual(403, edits._validate_edit_target(SOURCE['table_name'], 'savings')['status'])
        cursor = Mock()
        cursor.fetchone.side_effect = [('80%', 'current', 'Casas Bahia', 'sku-1')]
        conn = Mock()
        result = edits.update_cell_value(cursor, conn, SOURCE['table_name'], 2,
                                         'recommendation_intent', '80% recommend this product',
                                         DAY, 'cross_field', 'tester', '', rule_id=7)
        self.assertTrue(result['success'])
        conn.commit.assert_called_once()
        self.assertIn('FOR UPDATE OF source', cursor.execute.call_args_list[0].args[0])


if __name__ == '__main__':
    unittest.main()
