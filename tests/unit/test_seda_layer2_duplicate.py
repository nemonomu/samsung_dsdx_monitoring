"""SEDA duplicate grouping, real SELECT scope, routing and read-only boundaries."""
import json
import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.dx.dx_layer2 import seda_duplicate_validation as seda
from apps.dx.dx_layer2.anomaly_validation import api, services
from tests.unit.test_seda_layer2_null import MemoryCursor


DAY = date(2026, 9, 21)


class SedaDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
        self.db.execute("ATTACH DATABASE ':memory:' AS dx_seda")
        for source in SEDA_SOURCE_CONFIG.values():
            columns = ', '.join(f'{col} {"INTEGER PRIMARY KEY" if col == "id" else "TEXT"}'
                                for col in seda.SELECT_COLUMNS)
            self.db.execute(f"CREATE TABLE {source['table_name']} ({columns})")
        self.cursor = MemoryCursor(self.db)
        execute = self.cursor.execute
        self.cursor.execute = lambda sql, params=(): execute(
            sql.replace('LEFT(BTRIM(anchor.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(anchor.crawl_strdatetime), 1, 10)')
               .replace('LEFT(BTRIM(source.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(source.crawl_strdatetime), 1, 10)'), params)

    def add(self, product='seda_tv', **changes):
        row = dict.fromkeys(seda.SELECT_COLUMNS)
        row.update(account_name='Magalu', page_type='main', item='001', sku='TV001',
                   retailer_sku_name='TV', batch_id='current', crawl_strdatetime='2026-09-20 20:00:00')
        row.update(changes)
        self.db.execute(f"INSERT INTO {SEDA_SOURCE_CONFIG[product]['table_name']} ({', '.join(row)})"
                        f" VALUES ({', '.join('?' for _ in row)})", list(row.values()))

    def test_key_does_not_merge_sku_repeats_pages_dates_batches_or_retailers(self):
        base = dict(id=1, account_name='Magalu', page_type='main', item='001', sku='A',
                    retailer_sku_name='Product', batch_id='batch', crawl_strdatetime='2026-09-20')
        rows = [base]
        changes = [dict(item='002'), dict(page_type='bsr'), dict(account_name='CasasBahia'),
                   dict(batch_id='older'), dict(crawl_strdatetime='2026-09-19'), dict(item=None),
                   dict(item=' '), dict(page_type='promotion')]
        rows += [dict(base, id=index + 2, **change) for index, change in enumerate(changes)]
        self.assertEqual([], seda.build_duplicate_groups(rows))
        rows.append(dict(base, id=20, page_type=' MAIN ', item='001 ', account_name=' magalu '))
        group = seda.build_duplicate_groups(rows)[0]
        self.assertEqual('동일 상품 중복', group['duplicate_type'])
        self.assertEqual([1, 20], [row['id'] for row in group['records']])

    def test_aliases_case_and_mapping_conflicts(self):
        for field in ('sku', 'retailer_sku_name'):
            with self.subTest(field=field):
                rows = [dict(id=1, item='abc', page_type='main', account_name='CasasBahia', sku='A', retailer_sku_name='TV'),
                        dict(id=2, item=' ABC ', page_type='MAIN', account_name=' casas bahia ', sku='A', retailer_sku_name='TV')]
                rows[1][field] = 'different'
                self.assertEqual('상품 매핑 충돌', seda.build_duplicate_groups(rows)[0]['duplicate_type'])
        for row in rows:
            row['item'] = 0
        self.assertEqual(2, seda.build_duplicate_groups(rows)[0]['dup_count'])

    def test_scope_is_d_minus_one_latest_main_batch(self):
        self.add(id=1, batch_id='old')
        self.add(id=2, batch_id='old')
        self.add(id=3)
        self.add(id=4)
        self.add(id=5, page_type='bsr')
        self.add(id=6, page_type='bsr', batch_id='bsr-only')
        self.add(id=7, account_name='CasasBahia')
        self.add(id=8, page_type='promotion')
        self.add(id=9, crawl_strdatetime='2026-09-21 00:01:00')
        rows, mapping = seda.latest_rows(self.cursor, DAY, SEDA_SOURCE_CONFIG['seda_tv'], 'Magalu')
        self.assertEqual([3, 4, 5], [row['id'] for row in rows])
        self.assertEqual('2026-09-20', mapping['source_date'])
        groups = seda.build_duplicate_groups(rows)
        self.assertEqual([[3, 4]], [[row['id'] for row in group['records']] for group in groups])

    def test_null_batch_needs_main_anchor(self):
        self.add(id=1, page_type='bsr', batch_id=None)
        self.add(id=2, page_type='bsr', batch_id=None)
        detail = lambda: seda.duplicate_detail(self.cursor, DAY, 'seda_tv_retail', 'Magalu')
        self.assertEqual(0, detail()['results']['total_groups'])
        self.add(id=3, batch_id=None)
        self.assertEqual(1, detail()['results']['total_groups'])

    def test_summary_details_pagination_and_all_six_sources(self):
        for product in SEDA_SOURCE_CONFIG:
            for retailer, start in [('Magalu', 1), ('CasasBahia', 10)]:
                for offset, item in enumerate(('001', '001', '002', '002')):
                    self.add(product, id=start + offset, account_name=retailer, item=item)
        validation = {'tables': []}
        self.assertEqual(12, seda.append_duplicate_stats(self.cursor, DAY, validation))
        self.assertEqual(3, len(validation['tables']))
        for table in validation['tables']:
            self.assertIn(table['table'], services.VALID_TABLES_ANOMALY)
            self.assertNotIn(table['table'], services._DUP_TABLE_CONFIG)
            self.assertEqual((8, 4), (table['total_records'], table['total_issues']))
            for retailer in table['retailers']:
                result = services.get_anomaly_detail(self.cursor, DAY, table['table'], retailer['retailer'], 99, 2, 1)
                self.assertTrue(result['readonly'])
                self.assertEqual([], result['editable_cols'])
                self.assertEqual((2, 2), (result['results']['total_groups'], result['results']['total_pages']))
                self.assertEqual('002', result['results']['duplicates'][0]['item'])
                self.assertEqual(4, retailer['duplicate_records'])
        filtered = {'tables': []}
        self.assertEqual(4, seda.append_duplicate_stats(self.cursor, DAY, filtered, 'seda_ref_retail'))
        self.assertEqual(1, len(filtered['tables']))
        self.assertEqual(1, seda.duplicate_detail(self.cursor, DAY, 'seda_tv', 'Magalu', 0, 0)['results']['page_size'])

    def test_invalid_inputs_and_cleanup_do_not_connect(self):
        with patch.object(api, 'dx_connection') as connect:
            response = api.anomaly_detail(SimpleNamespace(GET={'date': str(DAY), 'table': 'seda_tv_retail', 'retailer': 'unknown'}))
            self.assertEqual(400, response.status_code)
            response = api.duplicate_cleanup(SimpleNamespace(method='POST', body=json.dumps({'table': 'seda_tv_retail', 'ids': [1]})))
            self.assertEqual(400, response.status_code)
            connect.assert_not_called()
        with self.assertRaises(ValueError):
            seda.duplicate_detail(self.cursor, DAY, 'seda_tv', 'unknown')
        self.assertEqual([], self.cursor.calls)


if __name__ == '__main__':
    unittest.main()
