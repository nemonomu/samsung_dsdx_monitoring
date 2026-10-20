import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.dx.dx_layer2 import retail_duplicate_edit as edit
from apps.dx.dx_layer2 import sem_validation, seib_duplicate_validation
from apps.dx.dx_layer2.anomaly_validation import services as detail
from apps.dx.dx_layer2.data_edit import services as saves
from tests.unit.support import ScriptedCursor


CASES = (
    ('SEA', 'public.ref_retail_com', 'Bestbuy', '2026-10-19'),
    ('SEDA', 'dx_seda.dx_seda_ref_retail_com', 'Magalu', '2026-10-19'),
    ('SIEL', 'dx_siel.dx_siel_ref_retail_com', 'Amazon', '2026-10-20'),
    ('TSE', 'dx_tse.dx_tse_ref_retail_com', 'Homepro', '2026-10-20'),
    ('SEM', 'dx_sem.dx_sem_ref_retail_com', 'HomeDepot', '2026-10-20'),
    ('SEIB', 'dx_seib.dx_seib_ref_retail_com', 'MediaMarkt', '2026-10-20'),
)
DAY = date(2026, 10, 20)


class RetailDuplicateEditTests(unittest.TestCase):
    def test_every_country_save_locks_scopes_and_audits(self):
        for country, table, retailer, _day in CASES:
            with self.subTest(country=country):
                cursor = ScriptedCursor([
                    {'fetchone': ('OLD', retailer, 'item')}, {}, {},
                ])
                conn = Mock()
                with patch.object(edit, 'scoped_rows', return_value=[{'id': 42}]) as scoped:
                    result = saves.update_cell_value(
                        cursor, conn, table, 42, 'sku', 'NEW', DAY,
                        'duplicate', 'tester', '상품 옵션 확인',
                    )
                self.assertTrue(result['success'])
                self.assertEqual(country, scoped.call_args.args[2])
                self.assertEqual(DAY, scoped.call_args.args[1])
                self.assertIn('FOR UPDATE', cursor.calls[0][0])
                self.assertEqual(('NEW', 42), cursor.calls[1][1])
                audit = cursor.calls[2][1]
                self.assertEqual((2, 'duplicate_check', table, 42, 'sku', 'OLD', 'NEW'), audit[:7])
                self.assertEqual(DAY, audit[7])
                self.assertEqual(('corrected', '상품 옵션 확인', retailer, 'item'), audit[10:])
                conn.commit.assert_not_called()

    def test_stale_day_batch_or_record_does_not_update(self):
        for country, table, retailer, _ in CASES:
            with self.subTest(country=country):
                cursor = ScriptedCursor([{'fetchone': ('OLD', retailer, 'item')}])
                with patch.object(edit, 'scoped_rows', return_value=[{'id': 99}]):
                    result = edit.update_sku(cursor, Mock(), edit.source_for_table(table),
                                             42, 'sku', 'NEW', DAY, 'tester', '')
                self.assertEqual(404, result['status'])
                self.assertEqual(1, len(cursor.calls))

    def test_sku_only_and_sea_tv_has_no_sku(self):
        context = edit.source_for_table(CASES[0][1])
        for column, value, expected in (('item', 'x', 403), ('sku', '', 400),
                                        ('sku', '  ', 400), ('sku', None, 400)):
            cursor = ScriptedCursor([])
            self.assertEqual(expected, edit.update_sku(
                cursor, Mock(), context, 1, column, value, DAY, 'tester', '')['status'])
            self.assertFalse(cursor.calls)
        for alias in ('tv_retail_com', 'public.tv_retail_com'):
            self.assertEqual(403, saves.update_cell_value(
                ScriptedCursor([]), Mock(), alias, 1, 'sku', 'x', DAY,
                'duplicate', 'tester', '')['status'])
        self.assertIsNone(edit.source_for_table('public.ref_retail_com; DROP TABLE x'))

    def test_audit_error_rolls_back(self):
        cursor, conn = Mock(), Mock()
        cursor.fetchone.return_value = ('OLD', 'Bestbuy', 'item')
        cursor.execute.side_effect = [None, None, RuntimeError('audit failed')]
        with patch.object(edit, 'scoped_rows', return_value=[{'id': 42}]):
            with self.assertRaises(RuntimeError):
                edit.update_sku(cursor, conn, edit.source_for_table(CASES[0][1]),
                                42, 'sku', 'NEW', DAY, 'tester', '')
        conn.rollback.assert_called_once()

    def test_scope_queries_keep_original_day_and_siel_exception(self):
        for country, table, retailer, source_day in CASES:
            with self.subTest(country=country):
                cursor = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
                context = edit.source_for_table(table)
                self.assertEqual([], edit.scoped_rows(cursor, DAY, *context, retailer))
                self.assertEqual(1, len(cursor.calls))
                sql, params = cursor.calls[0]
                self.assertIn(source_day, tuple(str(value) for value in params))
                self.assertIn('batch_id', sql)
                if country == 'SIEL':
                    self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
                else:
                    self.assertNotIn('AT TIME ZONE', sql)

    def test_duplicate_metadata_and_select_sql_on_each_country(self):
        for country, table, _retailer, source_day in CASES:
            with self.subTest(country=country):
                payload = {
                    'actual_table': table, 'readonly': True, 'source_date': source_day,
                    'select_cols': {'record': ['id', 'sku', 'crawl_datetime']},
                    'results': {'duplicates': [{'records': [{'id': 42}, {'id': 43}]}]},
                }
                with patch.object(detail, '_get_anomaly_detail', return_value=payload):
                    result = detail.get_anomaly_detail(Mock(), DAY, '', '', 1, 1, 50)
                self.assertEqual(['sku'], result['editable_cols'])
                self.assertFalse(result['readonly'])
                self.assertFalse(result['allow_cleanup'])
                self.assertEqual(source_day, result['editable_date'])
                self.assertIn(f'FROM {table}', result['query'])
                self.assertIn('id IN (42, 43)', result['query'])

    def test_sem_checks_all_retailers_and_dryer_separately(self):
        def rows(_cursor, _day, source, retailer=None):
            self.assertIn(retailer, source['retailers'])
            # Same item across retailers must never form a duplicate.
            return [{'id': 1, 'item': 'same'}], {'source_date': '2026-10-20'}
        validation = {'tables': []}
        with patch.object(sem_validation, '_latest_rows', side_effect=rows) as fetch:
            self.assertEqual(0, sem_validation.append_duplicate_stats(Mock(), DAY, validation))
        self.assertEqual(8, fetch.call_count)
        self.assertEqual(4, len(validation['tables']))
        self.assertEqual(3, len(validation['tables'][1]['retailers']))
        for source in sem_validation.SEM_SOURCE_CONFIG.values():
            self.assertIn(source['section_code'], detail.VALID_TABLES_ANOMALY)

    def test_seib_details_pagination_and_sql(self):
        rows = [{'id': i, 'item': item, 'sku': 'OLD'} for i, item in
                ((1, 'A'), (2, 'A'), (3, 'B'), (4, 'B'))]
        mapping = {'inspection_date': str(DAY), 'source_date': str(DAY)}
        with patch.object(seib_duplicate_validation, 'latest_rows', return_value=(rows, mapping)):
            result = detail.get_anomaly_detail(Mock(), DAY, 'seib_ref_retail', 'MediaMarkt', 1, 2, 1)
        self.assertEqual(2, result['results']['total_groups'])
        self.assertIn('id IN (3, 4)', result['query'])
        self.assertEqual(['sku'], result['editable_cols'])
        self.assertFalse(result['allow_cleanup'])
        for source in seib_duplicate_validation.SEIB_SOURCE_CONFIG.values():
            self.assertIn(source['section_code'], detail.VALID_TABLES_ANOMALY)
            self.assertNotIn(source['section_code'], detail._DUP_TABLE_CONFIG)


if __name__ == '__main__':
    unittest.main()
