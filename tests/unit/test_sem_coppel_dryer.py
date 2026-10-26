import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from apps.common import sem_retail as config
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer1.sem_retail import sem_retail_repositories as repo, sem_retail_services as l1
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import attach_comparisons
from apps.dx.dx_layer1.collection_issues.services import coverage_start
from apps.dx.dx_layer1.collection_statistics import automatic
from apps.dx.dx_layer1.collection_statistics.calculations import normalize_check
from apps.dx.dx_layer1.common.retail_batches import fetch_batch_details
from apps.dx.dx_layer2 import sem_validation as l2
from apps.dx.dx_layer2.data_edit import services as edit2
from apps.dx.dx_layer3.cross_field import sem_services as l3
from apps.dx.dx_layer3.data_edit import services as edit3

KEY = 'sem_ldy_dryer'
DAY = date(2026, 10, 25)
FIELDS = {'country', 'account_name', 'item', 'sku', 'product_url',
          'retailer_sku_name', 'final_sku_price', 'capacity'}


class CoppelDryerTests(unittest.TestCase):
    def row(self, **changes):
        return dict(dict(id=1, country='SEM', account_name='Coppel', item='I1', sku='S1',
                         retailer_sku_name='Dryer', product_url='https://www.coppel.com/pdp/dryer',
                         final_sku_price='$11,649', original_sku_price='$14,559', savings='$2,910 (19%)',
                         capacity='20kg', loading_type=None, star_rating=None, count_of_reviews=None,
                         count_of_star_ratings=None, main_rank=1, bsr_rank=1,
                         crawl_datetime='2026-10-25T23:59:59-04:00', batch_id='c1'), **changes)

    def test_date_key_and_launch_are_independent_of_timestamp_order(self):
        self.assertEqual('2026-10-25', source_date_value(self.row()['crawl_datetime']))
        self.assertEqual(('HomeDepot',), config.active_sem_retailers(KEY, '2026-10-24'))
        self.assertEqual(('HomeDepot', 'Coppel'), config.active_sem_retailers(KEY, DAY))
        order = config.sem_batch_order(KEY, 'Coppel')
        self.assertTrue(order.endswith('DESC NULLS LAST, id DESC'))
        self.assertIn('crawl_datetime', order)
        self.assertEqual('id DESC', config.sem_batch_order(KEY, 'HomeDepot'))
        self.assertEqual('id DESC', config.sem_batch_order('sem_ldy', 'Coppel'))

    def test_all_batch_queries_use_timestamp_first_and_actual_columns(self):
        cursor = Mock(description=[('id',)])
        cursor.fetchall.return_value = []
        source = config.get_sem_source(KEY)
        repo.get_latest_batch_counts(cursor, KEY, 'Coppel', DAY)
        repo.get_previous_main_counts(cursor, KEY, 'Coppel', DAY)
        l2._latest_rows(cursor, DAY, source, 'Coppel')
        l2._history_rows(cursor, source, DAY, DAY, ['I1'], retailer='Coppel')
        fetch_batch_details(cursor, 'sem_retail', KEY, str(DAY), 'Coppel')
        for call in cursor.execute.call_args_list:
            sql = call.args[0]
            self.assertIn(config.sem_batch_order(KEY, 'Coppel'), sql)
            self.assertIn('LEFT(BTRIM(CAST(', sql)
            self.assertNotIn('page_type', sql)
        cursor.reset_mock()
        l2.fetch_review_record(cursor, DAY, KEY, 1, 'sku')
        edit2._select_sem_edit_record(cursor, {'source': source, 'table_name': source['table_name']}, 'sku, account_name, item', 1, DAY)
        edit3._select_sem_record(cursor, source, 'sku, account_name, item', 1, DAY)
        for call in cursor.execute.call_args_list:
            self.assertIn('CASE WHEN LOWER(BTRIM(', call.args[0])
            self.assertIn('crawl_datetime', call.args[0])
        cursor.reset_mock()
        self.assertEqual([], l2._latest_rows(cursor, date(2026, 10, 24), source, 'Coppel')[0])
        cursor.execute.assert_not_called()

    def test_layer1_and_saved_statistics_include_coppel_without_adding_ranks(self):
        with patch.object(repo, 'get_latest_batch_counts', return_value=dict(
                retailer='Coppel', actual_count=29, main_count=29, bsr_count=28, batch_id='c1')), \
                patch.object(repo, 'get_previous_main_counts', return_value=[]):
            check = l1.get_layer1_stats(None, DAY, datetime(2026, 10, 26, 15))['check']
        row = next(r for r in normalize_check(check, 'SEM', DAY)
                   if r['product'] == 'LDY_DRYER' and r['retailer'] == 'Coppel')
        self.assertEqual((29, 28, 29), (row['main'], row['bsr'], row['total']))
        self.assertEqual(str(DAY), row['active_from'])
        self.assertEqual('db_original', row['source_date_basis'])

    def test_nulls_and_duplicates_follow_existing_coppel_policy(self):
        self.assertEqual(FIELDS, set(config.get_sem_required_columns(KEY, 'Coppel')))
        mapping = dict(source_date=str(DAY), inspection_date=str(DAY), offset_days=0)
        rows = [self.row(sku=None), self.row(id=2, item='I2', capacity=' ')]
        with patch.object(l2, '_latest_rows', side_effect=lambda c,d,s,retailer=None: (rows if retailer=='Coppel' else [],mapping)), \
                patch.object(l2, '_load_normal_reviews', return_value={}), \
                patch.object(l2, 'uses_new_policy', return_value=False):
            stats={'tables': []}
            self.assertEqual(2, l2.append_null_stats(None, DAY, stats, KEY+'_retail'))
            coppel=next(r for r in stats['tables'][0]['retailers'] if r['retailer']=='Coppel')
            self.assertEqual(FIELDS,set(coppel['fields_detail']))
        self.assertEqual([],l2._duplicate_groups([self.row(),self.row(id=2,item='I2')]))
        self.assertEqual(1,len(l2._duplicate_groups([self.row(),self.row(id=2)])))

    def test_seven_price_rules_exclude_reviews_and_handle_floor_boundaries(self):
        self.assertEqual([],l3._failed_rules(self.row(), 'Coppel', KEY))
        cases=[({'original_sku_price':'$0'},'original_price_zero'),
               ({'final_sku_price':'$14,559'},'final_original_price'),
               ({'savings':None},'coppel_savings_missing'),
               ({'original_sku_price':None},'coppel_original_missing'),
               ({'final_sku_price':None},'coppel_final_missing'),
               ({'savings':'$2,900 (19%)'},'coppel_savings_amount_match'),
               ({'savings':'$2,910 (20%)'},'coppel_savings_rate_match')]
        for changes,rule in cases:
            self.assertIn(rule,l3._failed_rules(self.row(**changes),'Coppel',KEY))
        mapping=dict(source_date=str(DAY),inspection_date=str(DAY),offset_days=0)
        with patch.object(l3,'_latest_rows',side_effect=lambda c,d,s,retailer=None: ([self.row()] if retailer=='Coppel' else [],mapping)), \
                patch.object(l3,'exclude_page_absent_records',side_effect=lambda c,d,rows,**kw:(rows,[])):
            summary=l3.get_sem_cross_field_summary(None,DAY,KEY)
        applicable=[r for r in summary['rule_summary'] if 'Coppel' in r['retailers']]
        self.assertEqual(7,len(applicable))
        self.assertFalse(any('rating' in r['rule_key'] or 'review' in r['rule_key'] for r in applicable))
        self.assertEqual(0,summary['total_anomalies'])

    def test_columns_use_actual_schema_and_crawl_order(self):
        cursor=Mock();cursor.fetchall.return_value=[]
        @contextmanager
        def connection():
            yield None,cursor
        with patch.object(columns,'dx_connection',connection),patch.object(columns,'_configured_retailers',side_effect=AssertionError('Use dryer columns')):
            data=columns.daily_counts('SEM','LDY_DRYER','Coppel',DAY,29)
        self.assertIn('capacity',data['columns'])
        self.assertIn('loading_type',data['columns'])
        self.assertNotIn('ldy_capacity',data['columns'])
        self.assertEqual(str(DAY),data['active_from'])
        self.assertIn(config.sem_batch_order(KEY,'Coppel','source'),cursor.execute.call_args.args[0])
        self.assertEqual((DAY, 'registered'), coverage_start('SEM', 'LDY_DRYER', 'Coppel'))

    def test_column_alerts_wait_for_history_and_respect_launch(self):
        data = dict(country='SEM', product='LDY_DRYER', retailer='Coppel',
                    active_from=str(DAY), columns=['sku'], daily=[
                        dict(date=str(DAY-timedelta(days=1)), total=0, counts={'sku': 0}),
                        dict(date=str(DAY), total=29, counts={'sku': 18}),
                        dict(date=str(DAY+timedelta(days=1)), total=30, counts={'sku': 19}),
                    ])
        now = datetime.fromisoformat('2026-10-27T15:00:00+09:00')
        current = attach_comparisons(data, DAY+timedelta(days=1), now)
        self.assertEqual('insufficient', current['comparisons'][0]['status'])
        self.assertEqual(1, current['comparisons'][0]['history_days'])
        before = attach_comparisons(data, DAY-timedelta(days=1), now)
        self.assertEqual('not_scheduled', before['comparisons'][0]['status'])

    def test_history_refresh_fills_coppel_but_not_before_launch(self):
        last_due=DAY+timedelta(days=3)
        days=[last_due-timedelta(days=i) for i in range(3,112)]
        rows=[dict(product='LDY_DRYER',retailer='HomeDepot',bsr=0,source_date_basis='db_original')]
        with patch.object(automatic.Daily,'objects') as manager:
            manager.filter.return_value.values_list.return_value=[(d,rows) for d in days]
            self.assertEqual((DAY,DAY),automatic.history_range('SEM',last_due))

    def test_format_uses_coppel_rules_and_actual_dryer_columns(self):
        expected = {'country', 'account_name', 'item', 'crawl_datetime', 'calendar_week',
                    'product_url', 'final_sku_price', 'original_sku_price', 'savings',
                    'main_rank', 'bsr_rank', 'capacity', 'loading_type'}
        self.assertEqual(expected, set(l2.get_review_allowed_columns(KEY, 'format_check', 'Coppel')))
        rules = l2.get_format_rule_details(KEY, 'Coppel')
        self.assertEqual(expected, {r['field'] for r in rules})
        self.assertIn('20kg', next(r['pattern'] for r in rules if r['field'] == 'capacity'))
        row = self.row(item='123', calendar_week='W44', loading_type='Front Load')
        self.assertEqual([], l2.evaluate_format(row, KEY, 'Coppel'))
        for value in ('20kg', '20 kg', '20.5 KG', '20kg / 22 kg'):
            self.assertEqual([], l2.evaluate_format(dict(row, capacity=value), KEY, 'Coppel'))
        for field, value in (
            ('capacity', '20lb'), ('capacity', '20'), ('capacity', '-2kg'),
            ('loading_type', 'Unknown'), ('calendar_week', 'W54'),
            ('item', 'I1'), ('crawl_datetime', '2026-02-30T12:00:00'),
            ('final_sku_price', '$11649'), ('savings', '-19%'),
            ('product_url', 'https://www.homedepot.com.mx/p/dryer'), ('bsr_rank', 0),
        ):
            with self.subTest(field=field, value=value):
                self.assertEqual([field], l2.evaluate_format(dict(row, **{field: value}), KEY, 'Coppel'))
        self.assertEqual([], l2.evaluate_format(dict(row, capacity=None, loading_type=' ',
                            original_sku_price=None, savings=None, star_rating='invalid'), KEY, 'Coppel'))
        # The source-specific unit spacing exception must not broaden other retailers/products.
        self.assertFalse(l2._format_checks(KEY, 'HomeDepot')['capacity']('20kg'))
        self.assertFalse(l2._format_checks('sem_ldy', 'Coppel')['ldy_capacity']('20kg'))

    def test_format_summary_detail_history_and_review_agree(self):
        mapping = dict(source_date=str(DAY), inspection_date=str(DAY), offset_days=0)
        rows = [self.row(item='123', capacity='20lb'), self.row(id=2, item='456')]
        with patch.object(l2, '_latest_rows', side_effect=lambda c,d,s,retailer=None: (rows if retailer=='Coppel' else [], mapping)), \
                patch.object(l2, '_load_normal_reviews', return_value={}), \
                patch.object(l2, '_history_rows', return_value=rows) as history:
            summary = {'tables': []}
            self.assertEqual(1, l2.append_format_stats(None, DAY, summary, KEY+'_retail'))
            coppel = next(r for r in summary['tables'][0]['retailers'] if r['retailer']=='Coppel')
            self.assertEqual((2, 1), (coppel['total'], coppel['issue_count']))
            detail = l2.format_detail(None, DAY, KEY, days=3, retailer='Coppel')
            self.assertEqual({'capacity': 1}, detail['field_counts'])
            self.assertEqual([1], detail['target_ids'])
            self.assertIn('capacity', detail['editable_cols'])
            self.assertNotIn('ldy_capacity', detail['column_names'])
            self.assertEqual('Coppel', history.call_args.kwargs['retailer'])
        with patch.object(l2, '_latest_rows', return_value=(rows, mapping)), \
                patch.object(l2, '_load_normal_reviews', return_value={'1_capacity': {'reason': 'reviewed'}}):
            detail = l2.format_detail(None, DAY, KEY, retailer='Coppel')
            self.assertEqual(0, detail['total_format_count'])

    def test_format_does_not_show_coppel_before_launch(self):
        before = DAY-timedelta(days=1)
        mapping = dict(source_date=str(before), inspection_date=str(before), offset_days=0)
        with patch.object(l2, '_latest_rows', return_value=([], mapping)), \
                patch.object(l2, '_load_normal_reviews', return_value={}):
            summary = {'tables': []}
            l2.append_format_stats(None, before, summary, KEY+'_retail')
        self.assertEqual(['HomeDepot'], [r['retailer'] for r in summary['tables'][0]['retailers']])

    def test_duplicate_summary_and_detail_group_items_not_skus(self):
        mapping = dict(source_date=str(DAY), inspection_date=str(DAY), offset_days=0)
        rows = [self.row(item='123'), self.row(id=2, item=' 123 ', sku='different'),
                self.row(id=3, item='456'), self.row(id=4, item=None), self.row(id=5, item=' ')]
        with patch.object(l2, '_latest_rows', side_effect=lambda c,d,s,retailer=None: (rows if retailer=='Coppel' else [], mapping)):
            summary = {'tables': []}
            self.assertEqual(1, l2.append_duplicate_stats(None, DAY, summary, KEY+'_retail'))
            detail = l2.duplicate_detail(None, DAY, KEY, retailer='Coppel')
        self.assertEqual(['item'], summary['tables'][0]['duplicate_keys'])
        self.assertEqual(1, detail['results']['total_groups'])
        group = detail['results']['duplicates'][0]
        self.assertEqual(('123', 2), (group['item'], group['dup_count']))
        self.assertEqual({1, 2}, {r['id'] for r in group['records']})
        self.assertFalse(detail['allow_cleanup'])
