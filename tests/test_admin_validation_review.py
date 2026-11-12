"""Administrator review regression tests; isolated settings, no production DB."""
import json
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend  # isolated Django settings
from django.test import RequestFactory, SimpleTestCase
from django.test import override_settings
from django.template import Engine, Context
from django.urls import path, include
from apps.common import validation_review as service, validation_review_views as views

SOURCE = dict(table_name='public.dx_test_retail', country='SEIB', product='LDY',
              key='seib_ldy', date_column='crawl_datetime')
REGISTRY = {'dx_test_retail': SOURCE}


def log(**kwargs):
    return dict(dict(id=1, table_name=SOURCE['table_name'], record_id=57,
                     column_name='sku', retailer='MediaMarkt', item='A001',
                     old_value=None, new_value='WW90T554DAX', status='corrected',
                     rule_id=None, rule_name='', created_id='reviewer',
                     created_at='2026-11-06 10:10:24', reason='', memo='모델명 확인',
                     crawl_date='2026-11-06', correction_type='null_check',
                     source_date='2026-11-06', value_known=True, context_available=False), **kwargs)


class Cursor:
    def __init__(self, *batches):
        self.batches = list(batches)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.lstrip().startswith('SELECT'), sql
        batch = self.batches.pop(0)
        if batch and isinstance(batch[0], dict):
            keys = list(batch[0])
            self.description = [(k,) for k in keys]
            self.rows = [tuple(r.get(k) for k in keys) for r in batch]
        else:
            self.rows = batch
            self.description = []

    def fetchall(self):
        return self.rows

    def mogrify(self, sql, params):
        from psycopg2.extensions import adapt
        self.display_query = (sql, params)
        return (sql % tuple(adapt(p).getquoted().decode('utf-8') for p in params)).encode('utf-8')


@contextmanager
def connection(cursor):
    yield None, cursor


class AuthorizationTests(unittest.TestCase):
    def request(self, method='get', **query):
        request = getattr(RequestFactory(), method)('/dx/layer2/api/admin-review/', query)
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False, is_superuser=False)
        return request

    def test_denied_before_reading_any_audit_store_or_page_context(self):
        for authenticated in (True, False):
            for endpoint in (views.data, views.page):
                request = self.request(date='2026-11-06', type='null_check')
                request.user.is_authenticated = authenticated
                with patch.object(service, 'summary') as read, patch.object(views, 'render') as render:
                    response = endpoint(request)
                self.assertEqual(403, response.status_code)
                self.assertIn('no-store', response['Cache-Control'])
                read.assert_not_called()
                render.assert_not_called()

    def test_admin_types_get_only_and_no_store(self):
        for role in ('is_staff', 'is_superuser'):
            for kind in service.KINDS:
                request = self.request(date='2026-11-06', type=kind)
                setattr(request.user, role, True)
                with patch.object(service, 'summary', return_value={'success': True}) as read:
                    response = views.data(request)
                self.assertEqual(200, response.status_code)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(kind, read.call_args.args[1])
        request = self.request('post', date='2026-11-06', type='null_check')
        request.user.is_staff = True
        with patch.object(service, 'summary') as read:
            self.assertEqual(405, views.data(request).status_code)
        read.assert_not_called()

    def test_bad_parameters_do_not_reach_database(self):
        base = dict(date='2026-11-06', type='null_check', view='records',
                    table=SOURCE['table_name'], retailer='MediaMarkt', field='sku')
        for changed in ({'date':'2026-13-06'}, {'type':'duplicate_check'}, {'days':'31'},
                        {'days':'0'}, {'page':'0'}, {'rule':'not-a-number'}, {'status':'delete'},
                        {'columns':'sku;DROP TABLE t'}, {'q_field':'other'},
                        {'sort_by':'created_id;DROP TABLE t'}, {'sort_order':'invalid'}):
            request = self.request(**{**base, **changed})
            request.user.is_staff = True
            with patch.object(service, 'records') as read:
                self.assertEqual(400, views.data(request).status_code)
            read.assert_not_called()

    def test_null_and_cross_field_accept_column_search_and_sort_options(self):
        for kind in ('null_check', 'cross_field'):
            request = self.request(date='2026-11-06', type=kind, view='records',
                                   table=SOURCE['table_name'], retailer='MediaMarkt', field='sku',
                                   columns='count_of_reviews,star_rating', days='7',
                                   q_field='item', q='A001', sort_by='id', sort_order='desc')
            request.user.is_staff = True
            with patch.object(service, 'records', return_value={'success':True}) as read:
                self.assertEqual(200, views.data(request).status_code)
            self.assertEqual({'extra_columns':['count_of_reviews','star_rating'],
                              'q_field':'item','sort_by':'id','sort_order':'desc'}, read.call_args.kwargs)
            self.assertEqual((7, 'A001'), read.call_args.args[7:9])


@override_settings(MONITORING_CACHE_ENABLED=False)
class AuditValueTests(SimpleTestCase):
    def test_incomplete_automatic_validation_is_not_accepted_for_caching(self):
        from apps.dx.dx_layer2.null_validation import services as null_service
        with patch.object(null_service, 'uses_new_policy', return_value=True), \
                patch.object(null_service, 'get_null_stats', return_value=(
                    {'tables':[{'status':'ERROR'}], 'auto_null_reviews':[]}, 0)):
            with self.assertRaises(RuntimeError):
                null_service.get_auto_applied_null_reviews(None, date(2026,11,6), strict=True)
            # Existing callers retain their original behavior.
            self.assertEqual([], null_service.get_auto_applied_null_reviews(None, date(2026,11,6)))

    def test_cold_detail_binds_filters_after_latest_decision_selection(self):
        cursor = Cursor([log(correction_type='cross_field', rule_id=346)])
        with patch.object(service.audit, '_sources', return_value=REGISTRY), \
                patch.object(service.saved, '_current_source') as format_source:
            result = service._load(cursor, date(2026,11,6), 'cross_field',
                                   SOURCE['table_name'], ' MediaMarkt ', 'sku', 346)
        format_source.assert_not_called()
        sql, params = cursor.calls[0]
        self.assertIn('current_rank = 1', sql)
        self.assertIn('c.column_name = %s', sql)
        self.assertIn('c.rule_id IS NOT DISTINCT FROM %s', sql)
        self.assertEqual(['mediamarkt', 'sku', 346], params[-3:])
        self.assertEqual(1, len(result))

    def test_manual_null_decision_still_suppresses_auto_before_rule_filter(self):
        cursor = Cursor([log(status='normal', rule_id=3)], [])
        with patch.object(service.audit, '_sources', return_value=REGISTRY), \
                patch('apps.dx.dx_layer2.null_validation.services.get_auto_applied_null_reviews',
                      return_value=[log(id='auto:57')]):
            result = service._load(cursor, date(2026,11,6), 'null_check',
                                   SOURCE['table_name'], 'MediaMarkt', 'sku', None)
        self.assertEqual([], result)

    def test_pairs_share_source_date_id_and_preserve_null_to_value(self):
        original = log(comparisons=[{'id': 40, '_source_date': '2026-11-05', 'sku': None}])
        before_copy = deepcopy(original)
        rows = service.paired_rows(original)
        self.assertEqual(before_copy, original)
        self.assertEqual(['비교 이력', '수정 전', '수정 후'], [r['_phase'] for r in rows])
        self.assertEqual([57,57], [r['id'] for r in rows[-2:]])
        self.assertEqual(['2026-11-06']*2, [r['_source_date'] for r in rows[-2:]])
        self.assertIsNone(rows[-2]['sku'])
        self.assertEqual('WW90T554DAX', rows[-1]['sku'])
        self.assertEqual('reviewer', rows[-1]['_reviewer'])

    def test_all_validation_kinds_and_empty_values(self):
        for kind in service.KINDS:
            for old, new in ((None,'sku'), ('', 'https://example.test'), ('NULL',0), (' ',False)):
                before, after = service.paired_rows(log(correction_type=kind,old_value=old,new_value=new))
                self.assertEqual(old,before['sku'])
                self.assertEqual(new,after['sku'])

    def test_format_confirmation_uses_snapshot_not_null_edit_marker(self):
        projected = log(id=-1, status='normal', old_value=None, new_value='http://bad-url',
                        correction_type='format_check', review_source='format_review')
        cursor = Cursor([projected])
        with patch.object(service.audit, '_sources', return_value=REGISTRY), \
             patch.object(service, '_source', return_value=('saved c', ['2026-11-06'], {-1: projected})):
            rows = service._load(cursor,date(2026,11,6),'format_check')
        before, after = service.paired_rows(rows[0])
        self.assertEqual('http://bad-url',before['sku'])
        self.assertEqual(before['sku'],after['sku'])
        self.assertEqual('확인 후',after['_phase'])

    def test_null_auto_uses_typed_evidence_and_manual_wins_same_cell(self):
        auto = log(id='auto:57',status='auto',evidence_id=91)
        automatic = [auto, log(id='auto:58',record_id=58,evidence_id=92)]
        cursor = Cursor([log(status='normal')], [(91,1,{'type':'string','value':''}), (92,2,{'type':'number','value':'0'})])
        with patch.object(service.audit,'_sources',return_value=REGISTRY), \
             patch.object(service,'_source',return_value=('saved c',['2026-11-06'],{})), \
             patch('apps.dx.dx_layer2.null_validation.services.get_auto_applied_null_reviews',return_value=automatic):
            rows = service._load(cursor,date(2026,11,6),'null_check')
        self.assertEqual(2,len(rows))
        self.assertEqual(['normal','auto'],[r['status'] for r in rows])
        self.assertEqual(['','0'],[r['old_value'] for r in rows])
        self.assertEqual(['','0'],[r['new_value'] for r in rows])

    def test_unknown_auto_snapshot_is_not_claimed_to_be_sql_null(self):
        rows=service.paired_rows(log(status='auto',value_known=False))
        self.assertFalse(rows[0]['_known'])
        self.assertFalse(rows[1]['_known'])

    def test_registered_sources_only_and_sql_values_bound(self):
        with patch.object(service.audit,'_sources',return_value=REGISTRY), \
             patch.object(service,'_source') as source:
            with self.assertRaises(ValueError):
                service._load(Cursor(),date(2026,11,6),'cross_field',"x; DROP TABLE t")
        source.assert_not_called()
        cursor=Cursor([log(correction_type='cross_field')])
        with patch.object(service.audit,'_sources',return_value=REGISTRY), \
             patch.object(service,'_source',return_value=('saved c',['2026-11-06'],{})):
            service._load(cursor,date(2026,11,6),'cross_field')
        self.assertNotIn('cross_field',cursor.calls[0][0])
        self.assertIn('cross_field',cursor.calls[0][1])


@override_settings(MONITORING_CACHE_ENABLED=False)
class ContextTests(SimpleTestCase):
    available=[(c, 'text') for c in ('id','account_name','item','sku','crawl_datetime','retailer_sku_name','product_url')]

    def setUp(self):
        registry = patch.object(service.audit, '_sources', return_value=REGISTRY)
        registry.start()
        self.addCleanup(registry.stop)

    def test_selected_columns_and_sql_preserve_identity_dates_and_saved_value(self):
        available=self.available+[(c,) for c in ('count_of_reviews','star_rating','detailed_review_content')]
        target=dict(id=57,account_name='MediaMarkt',item="A'001",sku='current',
                    count_of_reviews=5,_source_date='2026-11-06')
        cursor=Cursor(available,[target],[])
        logs=[log(item="A'001")]
        tools={}
        with patch.object(service.audit,'_sources',return_value=REGISTRY):
            columns=service._context(cursor,logs,3,date(2026,11,6),['count_of_reviews'],tools)
        self.assertIn('star_rating',tools['available_columns'])
        self.assertIn('count_of_reviews',columns)
        self.assertNotIn('detailed_review_content',columns)
        self.assertIn('source.count_of_reviews',cursor.calls[1][0])
        self.assertIn("A''001",tools['query'])
        self.assertIn("crawl_datetime >= '2026-11-04'",tools['query'])
        self.assertIn("crawl_datetime < '2026-11-07'",tools['query'])
        self.assertTrue(tools['query'].startswith('SELECT'))
        self.assertTrue(tools['query'].endswith('ORDER BY item, crawl_datetime;'))
        before,after=service.paired_rows(logs[0])
        self.assertIsNone(before['sku'])
        self.assertEqual('WW90T554DAX',after['sku'])
        self.assertEqual(5,before['count_of_reviews'])
        self.assertEqual(5,after['count_of_reviews'])

    def test_column_validation_precedes_source_query(self):
        for selected in (['not_a_column'],['sku;DROP TABLE t'],['sku']):
            cursor=Cursor(self.available)
            with patch.object(service.audit,'_sources',return_value=REGISTRY):
                with self.assertRaises(ValueError):
                    service._context(cursor,[log()],1,date(2026,11,6),selected,{})
            self.assertEqual(1,len(cursor.calls))

    def test_review_defaults_and_one_day_query_with_missing_item(self):
        available=self.available+[(c,) for c in (*service.audit.RATING_FIELDS,'detailed_review_content')]
        cursor=Cursor(available,[])
        tools={}
        with patch.object(service.audit,'_sources',return_value=REGISTRY):
            service._context(cursor,[log(column_name='detailed_review_content',item=None)],1,date(2026,11,6),tools=tools)
        self.assertIn('count_of_reviews',tools['selected_columns'])
        self.assertIn('id = 57',tools['query'])
        self.assertIn('item IS NULL',tools['query'])
        self.assertIn("crawl_datetime >= '2026-11-06'",tools['query'])
        self.assertIn("crawl_datetime < '2026-11-07'",tools['query'])
        self.assertEqual(2,len(cursor.calls))  # SQL display itself does not query.

    def test_selected_columns_do_not_affect_other_validation_kinds(self):
        for kind in ('format_check','field_missing'):
            with patch.object(service,'dx_connection',return_value=connection(None)), \
                 patch.object(service,'_load',return_value=[log()]), \
                 patch.object(service,'_context',return_value=['sku']) as context:
                result=service.records(date(2026,11,6),kind,SOURCE['table_name'],'MediaMarkt','sku',extra_columns=['count_of_reviews'])
            self.assertEqual({},context.call_args.kwargs)
            self.assertNotIn('query',result)

    def test_null_and_cross_field_details_supply_selected_columns_and_sql(self):
        available = self.available + [('count_of_reviews',)]
        for kind in ('null_check', 'cross_field'):
            cursor = Cursor(available, [], [])
            with patch.object(service, 'dx_connection', return_value=connection(cursor)), \
                    patch.object(service, '_load', return_value=[log(correction_type=kind)]):
                result = service.records(date(2026,11,6), kind, SOURCE['table_name'],
                                         'MediaMarkt', 'sku', extra_columns=['count_of_reviews'])
            self.assertEqual(['count_of_reviews'], result['selected_columns'])
            self.assertIn('count_of_reviews', result['query'])
            self.assertIn("crawl_datetime >= '2026-11-04'", result['query'])
            self.assertIn("crawl_datetime < '2026-11-07'", result['query'])
            self.assertEqual('WW90T554DAX', result['groups'][0]['rows'][-1]['sku'])
            self.assertEqual(3, len(cursor.calls))  # SQL is displayed, not executed.

    def test_search_field_and_sort_keep_review_pairs_together_before_pagination(self):
        rows = [log(id=i, record_id=i, item=f'A{i:02}', new_value='needle') for i in range(1,22)]
        with patch.object(service, '_load', side_effect=lambda *_args: deepcopy(rows)), \
                patch.object(service, 'dx_connection', side_effect=lambda: connection(None)), \
                patch.object(service, '_context', return_value=['sku']):
            args = (date(2026,11,6), 'null_check', SOURCE['table_name'], 'MediaMarkt', 'sku')
            result = service.records(*args, sort_by='id', sort_order='desc')
            self.assertEqual(list(range(21,11,-1)), [group['id'] for group in result['groups']])
            for group in result['groups']:
                self.assertEqual(['수정 전','수정 후'], [row['_phase'] for row in group['rows']])
            self.assertEqual(0, service.records(*args, q='needle', q_field='item')['total'])
            self.assertEqual(21, service.records(*args, q='needle', q_field='value')['total'])
            self.assertEqual([2], [group['id'] for group in service.records(*args, q='A02', q_field='item')['groups']])

    def test_raw_offset_date_same_target_identity_and_all_batches(self):
        target=dict(id=57,account_name=' MediaMarkt ',item='A001',sku='latest',
                    crawl_datetime='2026-11-06T23:59:00-04:00',_source_date='2026-11-06')
        cursor=Cursor(self.available,[target],[dict(target,id=56,_source_date='2026-11-05'),
                      dict(target,id=55,item='other',_source_date='2026-11-05'),target])
        logs=[log()]
        with patch.object(service.audit,'_sources',return_value=REGISTRY):
            service._context(cursor,logs,3,date(2026,11,6))
        self.assertEqual('2026-11-06',logs[0]['source_date'])
        self.assertEqual([56],[r['id'] for r in logs[0]['comparisons']])
        self.assertNotIn('AT TIME ZONE',cursor.calls[1][0])
        self.assertNotIn('batch_id =',cursor.calls[2][0])
        self.assertEqual(['2026-11-04','2026-11-06'],cursor.calls[2][1][-2:])
        before,after=service.paired_rows(logs[0])[-2:]
        self.assertIsNone(before['sku'])
        self.assertEqual('WW90T554DAX',after['sku'])

    def test_siel_exception_kept(self):
        cursor=Cursor(self.available,[])
        tools={}
        with patch.object(service.audit,'_sources',return_value={'dx_test_retail':{**SOURCE,'country':'SIEL','key':'siel_ldy'}}):
            service._context(cursor,[log()],1,date(2026,11,6),tools=tools)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'",cursor.calls[1][0])
        self.assertIn("crawl_datetime AT TIME ZONE 'Asia/Seoul'",tools['query'])

    def test_seda_alias_restores_url_name_and_comparison_history(self):
        source = {**SOURCE, 'country':'SEDA', 'key':'seda_tv'}
        target = dict(id=57, account_name='CasasBahia', item='A001',
                      retailer_sku_name='TV cabinet', product_url='https://example.test/A001',
                      crawl_datetime='2026-11-05T23:59:00-04:00', _source_date='2026-11-05')
        history = [dict(target, id=56, account_name=' CASAS BAHIA ', _source_date='2026-11-04'),
                   dict(target, id=55, account_name='Magalu'), dict(target, id=54, item='other')]
        for status in ('normal', 'auto'):
            with self.subTest(status=status):
                cursor = Cursor(self.available, [target], history)
                logs = [log(retailer='Casas Bahia', status=status, old_value=None, new_value=None)]
                tools = {}
                with patch.object(service.audit, '_sources', return_value={'dx_test_retail':source}):
                    service._context(cursor, logs, 3, date(2026,11,6), tools=tools)
                self.assertTrue(logs[0]['context_available'])
                self.assertEqual([56], [row['id'] for row in logs[0]['comparisons']])
                for row in service.paired_rows(logs[0])[-2:]:
                    self.assertEqual(target['product_url'], row['product_url'])
                    self.assertEqual('TV cabinet', row['retailer_sku_name'])
                    self.assertEqual('2026-11-05', row['_source_date'])
                    self.assertIsNone(row['sku'])
                self.assertIn("LOWER(REPLACE(BTRIM(source.account_name), ' ', '')) = %s", cursor.calls[2][0])
                self.assertEqual(['casasbahia', 'A001', '2026-11-03', '2026-11-05'], cursor.calls[2][1])
                self.assertIn("LOWER(REPLACE(BTRIM(account_name), ' ', '')) = 'casasbahia'", tools['query'])
                self.assertIn("crawl_datetime >= '2026-11-03'", tools['query'])
                self.assertIn("crawl_datetime < '2026-11-06'", tools['query'])
                self.assertNotIn('AT TIME ZONE', tools['query'])

    def test_seda_missing_source_sql_still_matches_aliases(self):
        source = {**SOURCE, 'country':'SEDA', 'key':'seda_tv'}
        cursor = Cursor(self.available, [])
        logs, tools = [log(retailer='Casas Bahia')], {}
        with patch.object(service.audit, '_sources', return_value={'dx_test_retail':source}):
            service._context(cursor, logs, 1, date(2026,11,6), tools=tools)
        self.assertFalse(logs[0]['context_available'])
        self.assertIn("LOWER(REPLACE(BTRIM(account_name), ' ', '')) = 'casasbahia'", tools['query'])

    def test_alias_handling_keeps_item_and_other_country_identity_checks(self):
        for country, key, item in (('SEDA', 'seda_tv', 'other'), ('SEIB', 'seib_ldy', 'A001')):
            cursor = Cursor(self.available, [dict(id=57, account_name='CasasBahia', item=item)])
            logs = [log(retailer='Casas Bahia')]
            source = {**SOURCE, 'country':country, 'key':key}
            with patch.object(service.audit, '_sources', return_value={'dx_test_retail':source}):
                service._context(cursor, logs, 1, date(2026,11,6))
            self.assertFalse(logs[0]['context_available'])
            self.assertIsNone(logs[0]['target'])

    def test_display_groups_items_and_selects_only_visible_columns(self):
        logs=[log(item=str(i), source_date='2026-11-05', retailer='casasbahia',
                  target={'account_name':'CasasBahia'}) for i in range(5)]
        columns=['id','crawl_datetime','item','retailer_sku_name','sku','product_url','savings','account_name']
        tools={'selected_columns':['savings']}
        service._display_query(Cursor(), SOURCE, columns, logs, 3, tools, 'text')
        query=tools['query']
        self.assertIn("item IN ('0', '1', '2', '3', '4')", query)
        self.assertIn("account_name = 'CasasBahia'", query)
        self.assertEqual(1,query.count('account_name'))
        self.assertIn("crawl_datetime >= '2026-11-03'",query)
        self.assertIn("crawl_datetime < '2026-11-06'",query)
        self.assertEqual({'id','crawl_datetime','item','retailer_sku_name','sku','savings','product_url'},
                         set(query.split('FROM')[0].removeprefix('SELECT').replace('\n','').replace(' ','').split(',')))
        for unnecessary in ('source.', ' OR ', 'LEFT(', 'CAST(', 'source_date', 'LIMIT', 'SELECT *'):
            self.assertNotIn(unnecessary,query)

    def test_display_preserves_distinct_date_windows_and_account_spellings(self):
        logs=[log(item='A',source_date='2026-11-05',target={'account_name':'MediaMarkt'}),
              log(item='B',source_date='2026-11-06',target={'account_name':'mediamarkt'})]
        tools={'selected_columns':[]}
        service._display_query(Cursor(), SOURCE, ['id','item','sku','crawl_datetime'], logs, 1, tools, 'text')
        first,second=tools['query'].split('\n   OR ')
        self.assertIn("crawl_datetime < '2026-11-06'",first)
        self.assertIn("item IN ('A')",first)
        self.assertIn("crawl_datetime >= '2026-11-06'",second)
        self.assertIn("item IN ('B')",second)
        self.assertIn("account_name IN ('MediaMarkt', 'mediamarkt')",first)

    def test_display_offset_text_keeps_raw_day_and_trims_only_when_needed(self):
        for timestamp,expression in [('2026-11-06T23:59:00-04:00','crawl_datetime'),
                                     (' 2026-11-06T23:59:00-04:00 ','BTRIM(crawl_datetime)')]:
            tools={'selected_columns':[]}
            logs=[log(target={'account_name':'MediaMarkt','crawl_datetime':timestamp})]
            service._display_query(Cursor(), SOURCE, ['id','item','sku','crawl_datetime'], logs, 1, tools, 'text')
            self.assertIn(f"{expression} >= '2026-11-06'",tools['query'])
            self.assertIn(f"{expression} < '2026-11-07'",tools['query'])
            self.assertNotIn('AT TIME ZONE',tools['query'])

    def test_missing_or_reused_source_row_does_not_hide_saved_pair(self):
        for target in ([],[dict(id=57,account_name='other',item='A001',_source_date='2026-11-05')]):
            cursor=Cursor(self.available,target)
            logs=[log()]
            with patch.object(service.audit,'_sources',return_value=REGISTRY):
                service._context(cursor,logs,1,date(2026,11,6))
            self.assertIsNone(logs[0]['target'])
            self.assertFalse(logs[0]['context_available'])
            self.assertEqual('WW90T554DAX',service.paired_rows(logs[0])[-1]['sku'])

    def test_cross_field_rule_isolation_and_corrected_records_survive_filter(self):
        rows=[log(correction_type='cross_field',rule_id=1),log(id=2,correction_type='cross_field',rule_id=2)]
        with patch.object(service,'dx_connection',return_value=connection(None)), \
             patch.object(service,'_load',return_value=rows), \
             patch.object(service,'_context',return_value=['sku']):
            result=service.records(date(2026,11,6),'cross_field',SOURCE['table_name'],'mediamarkt','sku',1)
        self.assertEqual(1,result['total'])
        self.assertEqual('수정 후',result['groups'][0]['rows'][-1]['_phase'])
        self.assertEqual('WW90T554DAX',result['groups'][0]['rows'][-1]['sku'])


class AutoReviewOptimizationTests(unittest.TestCase):
    def test_scope_is_conservative_and_normalizes_source_and_retailer(self):
        from apps.dx.dx_layer2.null_validation.auto_review_scope import load_scope
        cursor=Cursor([('public.tv_retail_com',' AMAZON '),('ref_retail_com','Amazon')])
        scope=load_scope(cursor,date(2026,11,9))
        self.assertTrue(scope('tv_retail_com','amazon'))
        self.assertTrue(scope('public.ref_retail_com'))
        self.assertFalse(scope('tv_retail_com','Other'))
        self.assertFalse(scope('unknown'))
        self.assertIn('inspection_date <= %s',cursor.calls[0][0])
        # Do not omit newer revoked decisions or same-day linked evidence.
        for exclusion in ('revoked_at IS NULL','auto_apply_from','reason ='):
            self.assertNotIn(exclusion,cursor.calls[0][0])

    def test_partitions_are_disjoint_and_keep_every_source(self):
        from apps.dx.dx_layer2.null_validation.auto_review_scope import ReviewScope
        scopes={str(i):{str(n) for n in range(i+1)} for i in range(8)}
        parts=ReviewScope(scopes).partitions()
        self.assertEqual(3,len(parts))
        keys=[key for part in parts for key in part.scopes]
        self.assertEqual(len(set(keys)),len(keys))
        self.assertEqual(set(scopes),set(keys))
        self.assertEqual([],ReviewScope({}).partitions())

    def test_no_evidence_skips_country_source_reads(self):
        from apps.dx.dx_layer2 import seda_null_validation,seib_null_validation,seuk_null_validation,seg_validation,sem_validation
        from apps.dx.dx_layer2.null_validation import services
        for module in (seda_null_validation,seib_null_validation,seuk_null_validation,seg_validation,sem_validation):
            cursor=Cursor()
            result=module.append_null_stats(cursor,date(2026,11,9),{'tables':[]},review_filter=lambda *_:False)
            self.assertEqual(0,result)
            self.assertEqual([],cursor.calls)
        cursor=Cursor()
        self.assertEqual(([],0),services._get_tse_null_tables(cursor,date(2026,11,9),
                         {'sources':{'tv':{'table_name':'tv'}}},{},review_filter=lambda *_:False))
        self.assertEqual([],cursor.calls)

    def test_parallel_reads_own_connections_and_return_all_rows(self):
        import threading
        from apps.common import db
        from apps.dx.dx_layer2.null_validation import auto_review_scope as scopes,services
        barrier=threading.Barrier(3)
        opened,closed=[],[]
        @contextmanager
        def connect():
            token=object()
            opened.append(token)
            try: yield None,token
            finally: closed.append(token)
        def read(cursor,day,review_filter):
            self.assertIn(cursor,opened)
            barrier.wait(timeout=5)
            return {'auto_null_reviews':list(review_filter.scopes)},0
        with patch.object(db,'dx_connection',connect),patch.object(services,'get_null_stats',read):
            rows=scopes.collect(scopes.ReviewScope({'a':{'A'},'b':{'B'},'c':{'C'}}),date(2026,11,9),strict=True)
        self.assertEqual(['a','b','c'],sorted(rows))
        self.assertEqual(3,len(set(opened)))
        self.assertEqual(set(opened),set(closed))

    def test_partial_results_raise_and_empty_scope_does_not_connect(self):
        from apps.common import db
        from apps.dx.dx_layer2.null_validation import auto_review_scope as scopes,services
        with patch.object(db,'dx_connection',return_value=connection(None)) as connect, \
                patch.object(services,'get_null_stats',return_value=({'tables':[{'status':'ERROR'}]},0)):
            self.assertEqual([],scopes.collect(scopes.ReviewScope({}),date(2026,11,9),strict=True))
            connect.assert_not_called()
            with self.assertRaises(RuntimeError):
                scopes.collect(scopes.ReviewScope({'a':{'A'}}),date(2026,11,9),strict=True)

    def test_legacy_dates_keep_original_automatic_policy(self):
        from apps.dx.dx_layer2.null_validation import services,auto_review_scope
        with patch.object(services,'get_tse_auto_applied_null_reviews',return_value=['legacy']) as old, \
                patch.object(auto_review_scope,'load_scope') as scope:
            self.assertEqual(['legacy'],services.get_auto_applied_null_reviews(None,date(2026,9,11),review_only=True))
            old.assert_called_once()
            scope.assert_not_called()


class TemplateTests(unittest.TestCase):
    def test_entry_is_admin_only_and_all_four_templates_render_once(self):
        root = Path(__file__).resolve().parents[1]
        urls = SimpleNamespace(urlpatterns=[
            path('dx/layer2/', include(([
                path('admin-review/', views.page, name='admin_review'),
                path('api/admin-review/', views.data, name='api_admin_review'),
                path('api/admin-review/check/', views.check, name='api_admin_review_check'),
            ], 'dx_layer2'), namespace='dx_layer2')),
            path('accounts/', include(([
                path('login/', views.page, name='login'), path('logout/', views.page, name='logout'),
                path('admin/', views.page, name='admin_dashboard'),
            ], 'accounts'), namespace='accounts')),
        ])
        # URL resolvers cache the module object; SimpleNamespace isn't hashable.
        from types import ModuleType
        module = ModuleType('admin_review_test_urls')
        module.urlpatterns = urls.urlpatterns
        engine = Engine(dirs=[str(root/'templates'),
                              str(root/'apps/dx/dx_layer2/templates'),
                              str(root/'apps/dx/dx_layer3/templates')],
                        libraries={'static':'django.templatetags.static'})
        with override_settings(ROOT_URLCONF=module, STATIC_URL='/static/'):
            for kind,(label,layer,section) in service.KINDS.items():
                request = RequestFactory().get('/')
                request.user = SimpleNamespace(is_authenticated=True,is_staff=False,is_superuser=False)
                context = dict(request=request,user=request.user,section=section,
                               layer=dict(number=layer,color='#0d9488',name='검증'),
                               sidebar_base_url=f'/dx/layer{layer}/',target_date='2026-11-06',
                               base_template=f'base_layer{layer}.html',review_kind=kind,review_label=label)
                entry=engine.get_template('includes/_validation_review_entry.html')
                menu=engine.get_template('includes/_validation_review_menu.html')
                self.assertNotIn('data-review-kind',menu.render(Context(context)))
                self.assertNotIn('admin-validation-review-link',entry.render(Context(context)))
                request.user.is_staff=True
                self.assertIn('admin-validation-review-link',entry.render(Context(context)))
                context['admin_review']=True
                html=engine.get_template('validation_review.html').render(Context(context))
                self.assertEqual(1,html.count('id="validation-review"'))
                self.assertEqual(1,html.count('src="/static/js/validation-review.js'))
                self.assertNotIn('id="admin-validation-review-link"',html)
                self.assertIn('data-kind="'+kind+'"',html)
                self.assertEqual(2,html.count('data-review-kind="'))
                self.assertEqual(1,html.count('aria-current="page"'))
                self.assertIn(f'?type={kind}&amp;date=2026-11-06',html)
                for other,(_,other_layer,_) in service.KINDS.items():
                    self.assertEqual(other_layer==layer, f'data-review-kind="{other}"' in html)
                request.user.is_staff=False
                request.user.is_superuser=True
                self.assertIn('data-review-kind',menu.render(Context(context)))
                request.user.is_authenticated=False
                self.assertNotIn('data-review-kind',menu.render(Context(context)))
                request.user.is_authenticated=True
                context['sidebar_base_url']='/ds/layer2/'
                self.assertNotIn('data-review-kind',menu.render(Context(context)))


class ReviewSnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(MONITORING_CACHE_DIR=directory.name,
                                     MONITORING_CACHE_ENABLED=True, DEBUG=False)
        settings.enable()
        self.addCleanup(settings.disable)
        registry = patch.object(service.audit, '_sources', return_value=REGISTRY)
        registry.start()
        self.addCleanup(registry.stop)
        db = patch.object(service, 'dx_connection', side_effect=lambda: connection(None))
        db.start()
        self.addCleanup(db.stop)

    def test_list_drilldown_search_and_pages_reuse_one_snapshot(self):
        rows = [log(id=i, record_id=i, old_value='', new_value=str(i),
                    status='normal' if i == 21 else 'corrected') for i in range(1, 22)]
        with patch.object(service, '_load', side_effect=lambda *_args: deepcopy(rows)) as load, \
                patch.object(service, '_context', return_value=['sku']):
            summary = service.summary(date(2026,11,6), 'null_check')
            fields = service.summary(date(2026,11,6), 'null_check', SOURCE['table_name'], 'mediamarkt')
            args = (date(2026,11,6), 'null_check', SOURCE['table_name'], 'MediaMarkt', 'sku')
            first = service.records(*args)
            second = service.records(*args, page=2)
            searched = service.records(*args, q='21', status='normal')
        self.assertEqual(load.call_count, 1)
        self.assertEqual(summary['total'], fields['total'])
        self.assertEqual((21, 3), (first['total'], first['pages']))
        self.assertEqual(list(range(1,11)), [group['id'] for group in first['groups']])
        self.assertEqual(list(range(11,21)), [group['id'] for group in second['groups']])
        self.assertEqual([21], [group['id'] for group in searched['groups']])
        self.assertEqual(20, searched['counts']['corrected'])

    def test_broader_snapshot_expiry_is_not_extended_by_drilldown(self):
        now = time.time()
        with patch.object(service, '_load', side_effect=lambda *_args: [log()]) as load:
            with patch('time.time', return_value=now):
                service.summary(date(2026,11,6), 'null_check')
            with patch('time.time', return_value=now + 50):
                service.summary(date(2026,11,6), 'null_check', SOURCE['table_name'], 'MediaMarkt')
            self.assertEqual(load.call_count, 1)
            with patch('time.time', return_value=now + 61):
                service.summary(date(2026,11,6), 'null_check', SOURCE['table_name'], 'MediaMarkt')
            self.assertEqual(load.call_count, 2)

    def test_errors_are_valid_review_decisions_and_writes_invalidate_all_kinds(self):
        from apps.common.monitoring_cache import invalidate_monitoring_cache
        with patch.object(service, '_load', side_effect=lambda *_args: [log(status='error')]) as load:
            for kind in service.KINDS:
                for _ in range(2):
                    result = service.summary(date(2026,11,6), kind)
                    self.assertEqual(1, result['counts']['error'])
            self.assertEqual(load.call_count, 4)
            invalidate_monitoring_cache()
            for kind in service.KINDS:
                service.summary(date(2026,11,6), kind)
            self.assertEqual(load.call_count, 8)

    def test_cached_admin_data_is_still_denied_to_regular_users(self):
        request = RequestFactory().get('/dx/layer2/api/admin-review/',
                                       {'date':'2026-11-06', 'type':'null_check'})
        request.user = SimpleNamespace(is_authenticated=True, is_staff=True, is_superuser=False)
        with patch.object(service, '_load', return_value=[log()]) as load, \
                patch.object(views.checks, 'attach') as attach:
            self.assertEqual(200, views.data(request).status_code)
            request.user.is_staff = False
            self.assertEqual(403, views.data(request).status_code)
            request.user.is_authenticated = False
            self.assertEqual(403, views.data(request).status_code)
            self.assertEqual(load.call_count, 1)
            self.assertEqual(attach.call_count, 1)

    def test_cached_rows_do_not_keep_context_or_expose_other_dates(self):
        with patch.object(service, '_load', side_effect=lambda *_args: [log()]) as load:
            rows = service._review_rows(date(2026,11,6), 'null_check')
            rows[0]['old_value'] = 'changed in this request'
            rows[0]['target'] = {'sku':'current source value'}
            fresh = service._review_rows(date(2026,11,6), 'null_check')
            self.assertIsNone(fresh[0]['old_value'])
            self.assertNotIn('target', fresh[0])
            service._review_rows(date(2026,11,5), 'null_check')
            self.assertEqual(load.call_count, 2)


if __name__=='__main__':
    unittest.main()
