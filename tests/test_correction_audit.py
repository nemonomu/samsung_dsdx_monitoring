"""Read-only audit details: no production DB connections."""
import json
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend
from django.test import RequestFactory
from apps.dx.dx_layer4.corrections import detail, api, services
from tests.unit.support import ScriptedCursor


class Cursor:
    def __init__(self, table='dx_seuk.dx_seuk_tv_retail_com', missing=False, field='savings', many=False):
        self.calls=[]
        self.table=table
        self.missing=missing
        self.field=field
        self.many=many
        self.bound=[]

    def execute(self, sql, params=None):
        self.calls.append((sql,params))
        assert sql.lstrip().startswith('SELECT'),sql
        if sql.startswith('SELECT id, table_name'):
            row=dict(id=7,table_name=self.table,record_id=42,retailer='Currys',item="A'B",
                     column_name=self.field,crawl_date=date(2026,10,27),old_value='£400.00',
                     new_value='£400.99',status='corrected',reason='price',memo='note',
                     created_id='reviewer',created_at='2026-10-27 09:00',updated_id=None,
                     updated_at=None,cancel_memo=None)
            self.rows=[row]
        elif 'information_schema.columns' in sql:
            self.rows=[{'column_name':c} for c in ('id','batch_id','item','account_name','crawl_datetime','crawl_strdatetime','retailer_sku_name','sku',*detail.PRICE_FIELDS,*detail.RATING_FIELDS,'product_url')]
        elif sql.startswith('SELECT source.'):
            row=dict(id=42,batch_id='audited',item="A'B",account_name='Currys',crawl_datetime='2026-10-26T23:59:59-04:00',
                     sku=None,savings='£400.99',product_url='https://example.test/product',_source_date='2026-10-26')
            if 'LIMIT' in sql:
                self.rows=[{**row,'id':i+100} for i in range(301)] if self.many else [dict(row,id=41),row]
            else:
                self.rows=[] if self.missing else [row]
        else:
            self.rows=[dict(id=7,column_name=self.field,old_value='£400.00',new_value='£400.99',status='corrected',
                            reason='price',memo='note',created_id='reviewer',created_at='2026-10-27 09:00',
                            updated_id=None,updated_at=None,cancel_memo=None)]
        self.description=[(k,) for k in self.rows[0]] if self.rows else []

    def fetchall(self):
        return [tuple(row.values()) for row in self.rows]

    def mogrify(self, sql, params):
        self.bound.append((sql,params))
        # Test adapter; production uses psycopg2's bound-value quoting.
        for value in params:
            sql=sql.replace('%s','NULL' if value is None else "'"+str(value).replace("'","''")+"'",1)
        return sql.encode()


@contextmanager
def connection(cursor):
    yield object(),cursor


class CorrectionAuditTests(unittest.TestCase):
    def request(self, *, staff=False, superuser=False, authenticated=True, method='get', query=None):
        req=getattr(RequestFactory(),method)('/',query or {'id':7,'days':3})
        req.user=SimpleNamespace(is_authenticated=authenticated,is_staff=staff,is_superuser=superuser)
        return req

    def test_query_requires_admin_before_any_database_access(self):
        with patch.object(detail,'queries') as queries:
            for req in [self.request(),self.request(authenticated=False)]:
                self.assertEqual(403,api.correction_query(req).status_code)
            queries.assert_not_called()
            for req in [self.request(staff=True),self.request(superuser=True)]:
                queries.return_value={'success':True,'sql':'SELECT 1;'}
                self.assertEqual(200,api.correction_query(req).status_code)
            self.assertEqual(2,queries.call_count)

    def test_apis_reject_mutations_and_invalid_arguments(self):
        with patch.object(detail,'queries') as queries,patch.object(detail,'detail') as reader:
            self.assertEqual(405,api.correction_query(self.request(staff=True,method='post')).status_code)
            self.assertEqual(405,api.correction_detail(self.request(method='post')).status_code)
            self.assertEqual(403,api.correction_detail(self.request(authenticated=False)).status_code)
            for query in [{'id':'1;DROP','days':3},{'id':7,'days':0},{'id':7,'days':31},{'id':0}]:
                self.assertEqual(400,api.correction_query(self.request(staff=True,query=query)).status_code)
            queries.assert_not_called();reader.assert_not_called()

    def test_detail_keeps_audit_values_separate_from_current_source_and_has_no_sql(self):
        cursor=Cursor()
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            result=detail.detail(7)
        self.assertEqual('£400.00',result['correction']['old_value'])
        self.assertEqual('£400.99',result['target']['savings'])
        self.assertEqual('2026-10-26',result['source_date'])
        self.assertEqual('2026-10-24',result['start_date'])
        self.assertIsNone(result['target']['sku'])
        self.assertEqual(1,len(result['events']))
        self.assertFalse(any('sql' in k for k in result))
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in cursor.calls))
        history=[c for c in cursor.calls if 'LIMIT 301' in c[0]][0]
        self.assertNotIn('AT TIME ZONE',history[0])
        self.assertNotIn('latest',history[0])
        self.assertEqual(['currys',"A'B",'2026-10-24','2026-10-26'],history[1])

    def test_read_only_query_is_bounded_quoted_and_log_driven(self):
        cursor=Cursor()
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            result=detail.queries(7)
        self.assertIn("A''B",result['sql'])
        self.assertIn('LIMIT 301',result['sql'])
        self.assertTrue(result['sql'].startswith('SELECT'))
        self.assertNotIn('UPDATE ',result['sql'])
        self.assertNotIn('record_sql',result)
        self.assertNotIn('history_sql',result)
        self.assertEqual(1,len(cursor.bound))
        self.assertEqual(3,len(cursor.calls))  # no execution of generated history SELECT
        projection=result['sql'].split('FROM ')[0]
        for column in ('id','crawl_datetime','batch_id','item','retailer_sku_name','product_url',*detail.PRICE_FIELDS):
            self.assertIn('source.'+column,projection)
        self.assertNotIn('source.sku',projection)
        self.assertNotIn('source.star_rating',projection)
        self.assertNotIn('_source_date',projection)

    def test_context_columns_include_only_basics_checked_field_and_related_group(self):
        basic=['id','crawl_datetime','batch_id','item','retailer_sku_name','product_url']
        available=set(basic+['account_name','sku','capacity',*detail.PRICE_FIELDS,*detail.RATING_FIELDS])
        for field in detail.PRICE_FIELDS:
            columns=detail.context_columns(available,'crawl_datetime',field)
            self.assertEqual(set(basic+list(detail.PRICE_FIELDS)),set(columns))
            self.assertEqual(len(columns),len(set(columns)))
        for field in detail.RATING_FIELDS:
            columns=detail.context_columns(available,'crawl_datetime',field)
            self.assertEqual(set(basic+list(detail.RATING_FIELDS)),set(columns))
        for field in ['sku','capacity']:
            self.assertEqual(set(basic+[field]),set(detail.context_columns(available,'crawl_datetime',field)))
        self.assertEqual(['id','crawl_strdatetime','sku'],detail.context_columns({'id','crawl_strdatetime','sku'},'crawl_strdatetime','sku'))

    def test_missing_source_preserves_saved_log_and_uses_inspection_mapping(self):
        cursor=Cursor(missing=True)
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            result=detail.detail(7)
        self.assertIsNone(result['target'])
        self.assertEqual('2026-10-27',result['source_date'])
        self.assertEqual('£400.00',result['correction']['old_value'])
        cursor=Cursor(table='public.ref_retail_com',missing=True)
        # SEA is D-1 even when the audited row is no longer present.
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            self.assertEqual('2026-10-26',detail.detail(7)['source_date'])

    def test_allowlists_and_untrusted_column_never_enter_sql(self):
        cursor=Cursor(table='dx_seuk.x; DELETE FROM source')
        with patch.object(detail,'dx_connection',lambda:connection(cursor)),self.assertRaises(ValueError):
            detail.detail(7)
        self.assertEqual(1,len(cursor.calls))
        cursor=Cursor(field='savings;DELETE FROM source')
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            result=detail.detail(7)
        self.assertFalse(result['field_available'])
        self.assertFalse(any('savings;DELETE' in sql for sql,_ in cursor.calls))

    def test_history_cap_retains_exact_target(self):
        cursor=Cursor(many=True)
        with patch.object(detail,'dx_connection',lambda:connection(cursor)):
            result=detail.detail(7)
        self.assertTrue(result['truncated'])
        self.assertEqual(301,len(result['rows']))
        self.assertEqual(42,result['rows'][-1]['id'])

    def test_registry_covers_every_retail_country_and_siel_exception(self):
        registry=detail._sources()
        self.assertEqual({'SEA','SEDA','SIEL','SEG','SEM','TSE','SEIB','SEUK'},{s['country'] for s in registry.values()})
        for source in registry.values():
            sql=detail.day_sql(source)
            self.assertEqual(source['country']=='SIEL','AT TIME ZONE' in sql)

    def test_list_enrichment_batches_identity_checks_and_comparison_values(self):
        fields=['id','account_name','item','crawl_datetime','product_url','retailer_sku_name','savings']
        columns=[('id',),('account_name',),('item',),('crawl_datetime',),('product_url',),('retailer_sku_name',)]
        history_columns=columns+[('savings',),('source_date',)]
        cursor=ScriptedCursor([
            {'fetchall':[(f,) for f in fields]},
            {'description':columns,'fetchall':[(42,'Currys',"A'B",'2026-10-26T23:59:59-04:00','https://example.test','TV')]},
            {'fetchall':[(42,'2026-10-26')]},
            {'description':history_columns,'fetchall':[(41,'Currys',"A'B",'2026-10-25T23:59:59-04:00','https://example.test','TV','£400.00','2026-10-25')]},
        ])
        logs=[dict(id=7,table_name='dx_seuk.dx_seuk_tv_retail_com',record_id=42,retailer=' currys ',item="A'B",column_name='savings',crawl_date=date(2026,10,27))]
        self.assertEqual([],detail.enrich_list(cursor,logs,3))
        self.assertEqual('SEUK TV',logs[0]['category_label'])
        self.assertEqual('TV',logs[0]['retailer_sku_name'])
        self.assertEqual('2026-10-26T23:59:59-04:00',logs[0]['crawl_time'])
        self.assertEqual('£400.00',logs[0]['comparison_rows'][0]['value'])
        self.assertTrue(logs[0]['source_available'])
        self.assertEqual(['currys',"A'B",'2026-10-24','2026-10-26'],cursor.calls[-1][1])
        self.assertTrue(all(sql.startswith('SELECT') for sql,_ in cursor.calls))

    def test_list_missing_or_reused_source_never_adopts_another_product_url(self):
        cursor=ScriptedCursor([
            {'fetchall':[(f,) for f in ['id','account_name','item','crawl_datetime','product_url']]},
            {'description':[(f,) for f in ['id','account_name','item','crawl_datetime','product_url']],
             'fetchall':[(42,'Other','reused','2026-10-27T01:00:00Z','https://wrong.test')]},
        ])
        log=dict(id=7,table_name='dx_seuk.dx_seuk_tv_retail_com',record_id=42,retailer='Currys',item='A',column_name='sku')
        detail.enrich_list(cursor,[log],1)
        self.assertFalse(log['source_available'])
        self.assertEqual('',log['product_url'])

    def test_list_filters_and_summary_counts_are_saved_records_not_history_rows(self):
        row=(7,2,'null_check','dx_seuk.dx_seuk_tv_retail_com',42,'sku',None,'MODEL',
             date(2026,10,27),'corrected','memo','tester',None,'reason','Currys','A',None,None,None,None,None)
        cursor=ScriptedCursor([
            {'fetchall':[('Currys','tester')]},
            {'fetchall':[('null_check',3),('format_check',1)]},
            {'fetchall':[('corrected',2),('normal',1)]},
            {'fetchone':(2,)},
            {'fetchall':[row,tuple([8,*row[1:]])]},
        ])
        def enrich(_, logs, days):
            self.assertEqual(3,days)
            for log in logs:
                log['comparison_rows']=[{'id':1},{'id':2}]
            return []
        with patch.object(services,'dx_connection',lambda:connection(cursor)),patch.object(detail,'enrich_list',side_effect=enrich):
            result=services.get_corrections(date(2026,10,27),'null_check','corrected',
                country='SEUK',product='TV',retailer='Currys',reviewer='tester',days=3)
        self.assertEqual(2,result['total'])
        self.assertEqual({'corrected':2,'normal':1,'reverted':0},result['status_counts'])
        self.assertEqual({'null_check':3,'format_check':1},result['type_counts'])
        self.assertEqual(2,len(result['items']))
        self.assertEqual(4,sum(len(r['comparison_rows']) for r in result['items']))
        self.assertIn('c.table_name = ANY(%s)',cursor.calls[-1][0])
        self.assertIn(['dx_seuk.dx_seuk_tv_retail_com'],cursor.calls[-1][1])
        self.assertIn('currys',cursor.calls[-1][1])
        self.assertIn('tester',cursor.calls[-1][1])
        self.assertNotIn('corrected',cursor.calls[2][1])
        self.assertIn('corrected',cursor.calls[-1][1])
        self.assertTrue(all(sql.startswith('SELECT') for sql,_ in cursor.calls))

    def test_list_api_validates_query_bounds_and_passes_structured_filters(self):
        req=self.request(query={'date':'2026-10-27','country':'SEUK','product':'TV','retailer':'Currys','reviewer':'tester','days':'7'})
        with patch.object(api,'get_corrections',return_value={'success':True}) as read:
            self.assertEqual(200,api.corrections_list(req).status_code)
            self.assertEqual('SEUK',read.call_args.kwargs['country'])
            self.assertEqual('tester',read.call_args.kwargs['reviewer'])
            self.assertEqual(7,read.call_args.kwargs['days'])
        with patch.object(api,'get_corrections') as read:
            for key,value in [('page','0'),('page_size','201'),('days','31'),('page','bad')]:
                req=self.request(query={'date':'2026-10-27',key:value})
                self.assertEqual(400,api.corrections_list(req).status_code)
            read.assert_not_called()


if __name__=='__main__':
    unittest.main()
