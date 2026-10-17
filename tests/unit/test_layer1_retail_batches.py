import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.source_dates import source_date_sql
from apps.dx.dx_layer1.common import retail_batches as batches


class RetailBatchTests(unittest.TestCase):
    def test_copy_sql_uses_direct_values_for_all_eighteen_sources(self):
        for country in ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE'):
            for product in ('tv', 'ref', 'ldy'):
                with self.subTest(country=country, product=product):
                    check = 'retail' if country == 'SEA' else country.lower() + '_retail'
                    key = product if country == 'SEA' else country.lower() + '_' + product
                    cursor = Mock()
                    cursor.fetchall.return_value = [{'batch_id': "batch'1"}]
                    cursor.mogrify.return_value = b'SELECT *;'
                    batches.fetch_batch_details(cursor, check, key, '2026-09-21', 'Lowes')
                    sql, params = cursor.mogrify.call_args.args
                    self.assertEqual(('2026-09-21', 'Lowes', "batch'1"), params)
                    self.assertNotRegex(sql, r'LOWER|UPPER|TRIM|CAST|CASE|AT TIME ZONE|IS NOT DISTINCT')
                    self.assertIn('AND account_name = %s\n  AND batch_id = %s', sql)
                    column = 'crawl_strdatetime' if country in ('SEDA', 'SEG') or (country == 'SEA' and product != 'tv') else 'crawl_datetime'
                    self.assertIn(f'WHERE {column} >= %s', sql)
                    self.assertTrue(sql.endswith(f'ORDER BY item, {column};'))
                    if country == 'SEA' and product == 'ref':
                        self.assertEqual(
                            'SELECT *\nFROM public.ref_retail_com\n'
                            'WHERE crawl_strdatetime >= %s\n'
                            '  AND account_name = %s\n  AND batch_id = %s\n'
                            'ORDER BY item, crawl_strdatetime;', sql,
                        )

    def test_missing_batch_uses_is_null_without_changing_case(self):
        cursor = Mock()
        cursor.fetchall.return_value = [{'batch_id': None}]
        cursor.mogrify.return_value = b'SELECT *;'
        batches.fetch_batch_details(cursor, 'retail', 'ref', '2026-09-21', 'Lowes')
        sql, params = cursor.mogrify.call_args.args
        self.assertEqual(('2026-09-21', 'Lowes'), params)
        self.assertIn('AND batch_id IS NULL', sql)

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
            ('retail', 'ref', 'public.ref_retail_com', 'crawl_strdatetime'),
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
                else:
                    self.assertNotIn('AT TIME ZONE', sql)
                    self.assertNotIn('timestamptz', sql)

    def test_sea_batch_membership_uses_original_day_for_every_product(self):
        for product in ('tv', 'ref', 'ldy', 'ldy_dryer'):
            for inspection_day, source_day in (
                ('2026-10-15', '2026-10-14'),
                ('2027-01-01', '2026-12-31'),
            ):
                with self.subTest(product=product, inspection_day=inspection_day):
                    contract = resolve_monitoring_date(inspection_day, 'SEA', 'sea_' + product)
                    self.assertEqual(source_day, contract['source_date'])
                    source, _, condition, params = batches._scope(
                        'retail', product, contract['source_date'])
                    self.assertIn(source_date_sql(source['date_column']), condition)
                    self.assertNotRegex(condition, r'AT TIME ZONE|timestamptz|batch_id')
                    self.assertEqual(source_day, params[0])

    def test_costco_and_homedepot_details_and_copy_sql_share_original_date(self):
        for retailer, products in (
            ('Costco', ('tv', 'ref', 'ldy', 'ldy_dryer')),
            ('HomeDepot', ('ref', 'ldy', 'ldy_dryer')),
        ):
            for product in products:
                with self.subTest(retailer=retailer, product=product):
                    cursor = Mock()
                    # A batch ID may retain a different day after a source correction.
                    cursor.fetchall.return_value = [{'batch_id': 'c20261016_203216'}]
                    cursor.mogrify.return_value = b'SELECT *;'
                    result = batches.fetch_batch_details(
                        cursor, 'retail', product, '2026-10-14', retailer)
                    sql, params = cursor.execute.call_args.args
                    membership = sql.split('), latest AS')[0]
                    self.assertNotRegex(membership, r'AT TIME ZONE|timestamptz')
                    self.assertEqual('2026-10-14', params[0])
                    self.assertEqual('2026-10-14', result['source_date'])
                    # Display-time conversion remains independent of membership.
                    zone = 'Asia/Seoul' if retailer == 'Costco' else 'America/New_York'
                    self.assertIn(zone, sql)
                    copy_sql, copy_params = cursor.mogrify.call_args.args
                    column = 'crawl_datetime' if product in ('tv', 'ldy_dryer') else 'crawl_strdatetime'
                    self.assertIn(f'WHERE {source_date_sql(column)} = %s', copy_sql)
                    self.assertNotRegex(copy_sql, r'AT TIME ZONE|timestamptz')
                    self.assertEqual(('2026-10-14', retailer, 'c20261016_203216'), copy_params)

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
        contexts = [row.pop('batch_context') for row in rows]
        self.assertEqual('2026-09-20', contexts[0]['source_date'])
        self.assertEqual('Amazon', contexts[0]['retailer'])
        self.assertEqual('sea_ref', contexts[2]['product_line'])
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

    def test_details_use_latest_main_anchor_and_parameterized_exact_batch_sql(self):
        cursor = Mock()
        cursor.fetchall.return_value = [("b'1,2", '2026-09-21 09:00', '2026-09-21 09:30', 280, 100, False, 300)]
        cursor.mogrify.return_value = b'SELECT * FROM exact_batch;'
        result = batches.fetch_batch_details(cursor, 'seg_retail', 'seg_tv', '2026-09-21', 'Amazon')
        sql, params = cursor.execute.call_args.args
        self.assertIn("WHERE LOWER(BTRIM(CAST(page_type AS TEXT))) = 'main' ORDER BY id DESC", sql)
        self.assertIn("FILTER (WHERE LOWER(BTRIM(CAST(page_type AS TEXT))) IN ('main', 'bsr'))", sql)
        self.assertEqual(('2026-09-21', 'amazon'), params)
        self.assertEqual(('2026-09-21', 'Amazon', "b'1,2"), cursor.mogrify.call_args.args[1])
        self.assertIn('batch_id = %s', cursor.mogrify.call_args.args[0])
        self.assertEqual(False, result['batches'][0]['applied'])
        self.assertEqual("b'1,2", result['batches'][0]['batch_id'])
        self.assertEqual('SELECT * FROM exact_batch;', result['batches'][0]['sql'])

    def test_sea_tv_details_apply_all_batches_but_appliances_use_an_anchor(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        batches.fetch_batch_details(cursor, 'retail', 'tv', '2026-09-20', 'Amazon')
        sql, params = cursor.execute.call_args.args
        self.assertIn('BOOL_OR(TRUE)', sql)
        self.assertEqual(('2026-09-20', '2026-09-21', 'amazon'), params)
        batches.fetch_batch_details(cursor, 'retail', 'ref', '2026-09-20', 'HomeDepot')
        sql = cursor.execute.call_args.args[0]
        self.assertIn('WHERE TRUE ORDER BY id DESC', sql)
        self.assertIn('America/New_York', sql)
        self.assertIn('(SELECT batch_id FROM latest) IS NOT NULL', sql)


if __name__ == '__main__':
    unittest.main()
