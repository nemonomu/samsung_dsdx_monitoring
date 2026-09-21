import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from apps.dx.dx_layer1.common import retail_batches as batches


class RetailBatchTests(unittest.TestCase):
    def test_counts_are_daily_distinct_nonblank_ids_not_latest_batch_rows(self):
        cursor = Mock()
        cursor.fetchall.return_value = [('amazon', 2), ('bestbuy', 1), ('walmart', 0)]
        result = batches.fetch_batch_counts(cursor, 'retail', 'tv', '2026-09-20')
        self.assertEqual({'amazon': 2, 'bestbuy': 1, 'walmart': 0}, result)
        sql, params = cursor.execute.call_args.args
        self.assertIn("COUNT(DISTINCT NULLIF(BTRIM(CAST(batch_id AS TEXT)), ''))", sql)
        self.assertIn('public.tv_retail_com', sql)
        self.assertNotIn('LIMIT 1', sql)
        self.assertNotIn('page_type', sql)
        self.assertEqual(('2026-09-20', '2026-09-21'), params)

    def test_country_date_rules_and_sources(self):
        cases = [
            ('siel_retail', 'siel_tv', 'dx_siel.dx_siel_tv_retail_com', 'AT TIME ZONE'),
            ('seda_retail', 'seda_ref', 'dx_seda.dx_seda_ref_retail_com', 'crawl_strdatetime'),
            ('seg_retail', 'seg_ldy', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime'),
            ('sem_retail', 'sem_ref', 'dx_sem.dx_sem_ref_retail_com', 'crawl_datetime'),
            ('tse_retail', 'tse_tv', 'dx_tse.dx_tse_tv_retail_com', 'crawl_datetime'),
            ('retail', 'ref', 'public.ref_retail_com', 'America/New_York'),
        ]
        for check_type, product, table, date_rule in cases:
            with self.subTest(check_type=check_type):
                cursor = Mock()
                cursor.fetchall.return_value = [{'retailer_key': 'retailer', 'batch_count': 3}]
                self.assertEqual({'retailer': 3}, batches.fetch_batch_counts(
                    cursor, check_type, product, '2026-09-20',
                ))
                sql, params = cursor.execute.call_args.args
                self.assertIn(table, sql)
                self.assertIn(date_rule, sql)
                self.assertEqual('2026-09-20', params[0])
                if check_type == 'siel_retail':
                    self.assertEqual(('2026-09-20', 'Asia/Seoul', '2026-09-20', 'Asia/Seoul'), params)

    def test_metadata_uses_category_source_date_and_preserves_validation(self):
        check = {'check_type': 'retail', 'source_date': '2026-09-21', 'status': 'OK', 'categories': [
            {'product_line': 'tv', 'source_date': '2026-09-20', 'time_slots': [{'retailers': [
                {'retailer': 'Amazon', 'count': 300, 'batch_id': 'latest', 'status': 'OK'},
                {'retailer': 'Walmart', 'count': 0, 'status': 'CRITICAL'},
            ]}]},
            {'product_line': 'sea_ref', 'source_date': '2026-09-19', 'time_slots': [{'retailers': [
                {'retailer': 'Amazon', 'count': 300, 'status': 'OK'},
            ]}]},
        ]}
        before = deepcopy(check)
        cursor = Mock()
        with patch.object(batches, 'fetch_batch_counts', side_effect=[{'amazon': 2}, {'amazon': 1}]) as fetch:
            batches.add_batch_counts(cursor, check, '2026-09-21')
        self.assertEqual(['2026-09-20', '2026-09-19'], [call.args[3] for call in fetch.call_args_list])
        rows = [row for cat in check['categories'] for slot in cat['time_slots'] for row in slot['retailers']]
        self.assertEqual([2, 0, 1], [row.pop('batch_count') for row in rows])
        self.assertEqual(before, check)

    def test_seda_names_match_and_tse_uses_selected_date(self):
        for check_type, name, key in [('seda_retail', 'Casas Bahia', 'casasbahia'), ('tse_retail', 'Homepro', 'homepro')]:
            row = {'retailer': name}
            check = {'check_type': check_type, 'categories': [{'product_line': 'unused', 'retailers': [row]}]}
            with patch.object(batches, 'fetch_batch_counts', return_value={key: 3}) as fetch:
                batches.add_batch_counts(Mock(), check, '2026-09-21')
            self.assertEqual(3, row['batch_count'])
            self.assertEqual('2026-09-21', fetch.call_args.args[3])

    def test_query_failure_rolls_back_without_partial_metadata(self):
        check = {'check_type': 'retail', 'categories': [
            {'product_line': product, 'retailers': [{'retailer': 'Bestbuy'}]}
            for product in ['tv', 'ref']
        ]}
        before = deepcopy(check)
        cursor = Mock()
        with patch.object(batches, 'fetch_batch_counts', side_effect=[{'bestbuy': 2}, RuntimeError('failed')]):
            with self.assertRaises(RuntimeError):
                batches.add_batch_counts(cursor, check, '2026-09-21')
        self.assertEqual(before, check)
        self.assertEqual([
            'SAVEPOINT layer1_retail_batch_counts',
            'ROLLBACK TO SAVEPOINT layer1_retail_batch_counts',
            'RELEASE SAVEPOINT layer1_retail_batch_counts',
        ], [call.args[0] for call in cursor.execute.call_args_list])

    def test_other_checks_do_not_query_batches(self):
        cursor = Mock()
        batches.add_batch_counts(cursor, {'check_type': 'youtube', 'categories': [{}]}, '2026-09-21')
        cursor.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
