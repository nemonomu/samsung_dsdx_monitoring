import sqlite3
import unittest
from unittest.mock import Mock, patch

from tests.unit.support import load_module
from tests.unit.test_layer2_sea_format_duplicate import common_stubs


class DuplicateLookupQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/anomaly_validation/services.py',
            'duplicate_lookup_under_test', common_stubs())

    def result(self, table='public.ref_retail_com', ids=(10, 11)):
        return {'actual_table': table, 'readonly': True, 'results': {
            'duplicates': [{'item': "x'); DROP TABLE t; --", 'records': [
                {'id': value} for value in ids]}],
            'page': 2, 'total_pages': 3,
        }}

    def test_lookup_selects_only_returned_rows_for_all_country_schemas(self):
        for schema in ('public', 'dx_seda', 'dx_siel', 'dx_seg', 'dx_sem', 'dx_tse', 'dx_seib'):
            with self.subTest(schema=schema), sqlite3.connect(':memory:') as db:
                db.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
                table = schema + '.retail'
                db.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, item TEXT)')
                db.executemany(f'INSERT INTO {table} VALUES (?, ?)', [(10, 'a'), (11, 'a'), (12, 'unrelated')])
                result = self.service._duplicate_lookup_query(self.result(table, (11, 10, 11)), '')
                self.assertEqual([(10, 'a'), (11, 'a')], db.execute(result['query']).fetchall())
                self.assertEqual(2, result['query_record_count'])
                self.assertNotIn('DROP', result['query'])
                self.assertNotIn('AT TIME ZONE', result['query'])

    def test_missing_or_invalid_ids_never_widen_the_query(self):
        for ids in ((), (None,), (True,), (1.5,), ("1); DELETE FROM t; --",), (1, 'bad')):
            self.assertEqual({'query': '', 'query_record_count': 0},
                             self.service._duplicate_lookup_query(self.result(ids=ids), ''))
        for table in ('', 'x; DROP TABLE y', 'x.y.z', None, 123):
            self.assertEqual('', self.service._duplicate_lookup_query(self.result(table), '')['query'])

    def test_bigint_ids_are_preserved_before_browser_json_parsing(self):
        result = self.service._duplicate_lookup_query(self.result(ids=(9007199254740993, '9007199254740995')), '')
        self.assertIn('id IN (9007199254740993, 9007199254740995)', result['query'])

    def test_market_tables_use_existing_registry_without_a_new_query(self):
        for key in ('market_trend', 'market_product', 'market_event'):
            result = self.service._duplicate_lookup_query(self.result(''), key)
            self.assertIn('FROM public.' + self.service._DUP_TABLE_CONFIG[key]['actual'], result['query'])

    def test_wrapper_adds_query_to_readonly_results_without_executing_it(self):
        cursor = Mock()
        payload = self.result('dx_tse.dx_tse_ref_retail_com')
        with patch.object(self.service, '_get_anomaly_detail', return_value=payload) as detail:
            result = self.service.get_anomaly_detail(cursor, '2026-10-15', 'tse_ref_retail', 'Homepro', 1, 2, 50)
        detail.assert_called_once_with(cursor, '2026-10-15', 'tse_ref_retail', 'Homepro', 1, 2, 50)
        cursor.execute.assert_not_called()
        self.assertTrue(result['readonly'])
        self.assertEqual(2, result['query_record_count'])
        self.assertEqual(2, result['results']['page'])

    def test_real_sea_pagination_updates_ids_without_changing_source_date(self):
        rows = [dict(id=i, page_type='main', item=item, sku='sku')
                for i, item in ((1, 'A'), (2, 'A'), (3, 'B'), (4, 'B'))]
        cursor = Mock()
        with patch.object(self.service, '_fetch_sea_duplicate_rows', return_value=rows) as fetch:
            for page, ids in ((1, '1, 2'), (2, '3, 4')):
                result = self.service.get_anomaly_detail(cursor, '2026-10-15', 'sea_ref_retail', 'Lowes', 1, page, 1)
                self.assertIn('id IN (' + ids + ')', result['query'])
                self.assertEqual('2026-10-14', result['source_date'])
                self.assertEqual(2, result['query_record_count'])
            result = self.service.get_anomaly_detail(cursor, '2026-10-15', 'sea_ref_retail', 'Lowes', 1, 3, 1)
            self.assertEqual('', result['query'])
        self.assertEqual(3, fetch.call_count)
        cursor.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
