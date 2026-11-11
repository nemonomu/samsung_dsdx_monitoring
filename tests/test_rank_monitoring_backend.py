"""Isolated in-memory review DB and mocked source reads; no production writes."""
import json
import sys
import tempfile
import time
import threading
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=['apps.dx.dx_layer1'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True, TIME_ZONE='Asia/Seoul', BASE_DIR=Path.cwd(), SECRET_KEY='rank-isolated-test')
import django
django.setup()
from django.core import signing
from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase, RequestFactory, override_settings
from django.test.runner import DiscoverRunner

from apps.dx.dx_layer1.rank_monitoring.comparison import compare, snapshot
from apps.dx.dx_layer1.rank_monitoring.repository import query_spec
from apps.dx.dx_layer1.rank_monitoring.sources import select_source, catalog, COUNTRIES
from apps.dx.dx_layer1.rank_monitoring import api, reviews, snapshots, listing
from apps.dx.dx_layer1.models import RetailRankReview
from tests.rank_monitoring_fixtures import DAY, row, samples


class ComparisonTests(TestCase):
    def test_presence_movement_returns_and_samsung_keep_retailer_ranks(self):
        result = compare(samples(), DAY)
        products = {p['item']:p for p in result['products']}
        self.assertEqual('return', products['30']['status'])
        self.assertEqual('swing', products['80']['status'])
        self.assertEqual([80, 150, 95], [c['rank'] for c in products['80']['cells']])
        self.assertEqual('missing', products['95']['status'])
        self.assertEqual('next_missing', products['240']['status'])
        self.assertEqual('stable', products['1']['status'])
        only = compare(samples(), DAY, samsung=True)
        self.assertNotIn('280', [p['item'] for p in only['products']])
        self.assertEqual(150, next(p for p in only['products'] if p['item']=='80')['cells'][1]['rank'])

    def test_tier_retention_denominator_and_expanded_search(self):
        raw = [row(9, i, i) for i in range(1,301)]
        raw += [row(10, i, i) for i in range(1,91)]
        raw += [row(10, i, i+100) for i in range(91,96)]
        result = compare(raw, DAY)
        top = result['bands'][0]
        self.assertEqual((100,90,5,5,90.0),tuple(top[k] for k in ('count','kept','moved','missing','rate')))
        self.assertFalse(top['below_target'])
        self.assertEqual(100, result['bands'][2]['count'])

    def test_empty_day_and_future_wait_are_not_individual_missing(self):
        raw = [r for r in samples() if r['date'] != '2026-11-10']
        result = compare(raw, DAY)
        self.assertEqual(0,result['counts']['missing'])
        self.assertEqual(0,result['counts']['return'])
        self.assertIsNone(result['bands'][0]['rate'])
        self.assertEqual('unassessed',result['products'][0]['status'])
        pending = compare([r for r in samples() if r['date'] != '2026-11-11'],DAY,today=DAY)
        self.assertEqual('pending',pending['coverage'][2]['state'])
        self.assertEqual(0,pending['counts']['return'])
        self.assertEqual(0,pending['counts']['next_missing'])

    def test_duplicates_invalid_and_missing_item_never_invent_matches(self):
        raw = [row(9,1,1),row(10,1,1),row(10,1,2,id=99999),
               {**row(9,2,2), 'item':''}, {**row(10,3,3), 'item':''}]
        # Construct empty ITEMs separately from the positional helper argument.
        result = compare(raw,DAY)
        self.assertEqual(3,result['counts']['data'])
        self.assertIsNone(result['bands'][0]['rate'])
        duplicate = snapshot([row(9,1,1),row(9,1,1,id=99999)])['item:1']
        self.assertEqual('ranked',duplicate['state'])
        self.assertEqual([9001,99999],duplicate['record_ids'])
        invalid = snapshot([row(9,1,'not-a-rank')])['item:1']
        self.assertEqual('invalid',invalid['state'])

    def test_outside_300_is_movement_not_a_collection_gap(self):
        raw=[row(9,1,30),row(10,1,350),row(11,1,32)]
        result=compare(raw,DAY)
        self.assertTrue(result['products'][0]['signals']['missing'])
        self.assertTrue(result['products'][0]['signals']['swing'])
        self.assertFalse(result['products'][0]['signals']['return'])
        self.assertEqual('outside',result['products'][0]['cells'][1]['state'])

    def test_same_sku_different_item_stays_distinct_and_brand_is_bounded(self):
        raw=[row(9,1,1,sku='SAME',name='NotSamsung'),row(10,2,2,sku='SAME',name='SAMSUNG TV')]
        self.assertEqual(2,compare(raw,DAY)['counts']['all'])
        self.assertEqual(['2'],[p['item'] for p in compare(raw,DAY,samsung=True)['products']])

    def test_missing_batch_id_is_not_a_complete_daily_snapshot(self):
        result=compare([row(9,1,1),row(10,1,1,batch_id=None)],DAY)
        self.assertEqual('data',result['products'][0]['status'])
        self.assertFalse(result['coverage'][1]['available'])
        self.assertIsNone(result['bands'][0]['rate'])


class QueryTests(TestCase):
    def columns(self, source):
        from apps.dx.dx_layer1.column_statistics.dates import date_column
        return {c:'text' for c in ('id','item','account_name','retailer_sku_name','product_url','batch_id','main_rank',date_column(source),'page_type','sku')}

    def test_date_policy_and_latest_batch_before_rank_validation(self):
        source, retailer=select_source('SEA','TV','Amazon')
        sql,params,basis=query_spec(source,retailer,self.columns(source),DAY)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)',sql)
        self.assertNotIn('AT TIME ZONE',sql)
        self.assertNotIn('main_rank >',sql)
        self.assertIn('IS NOT DISTINCT FROM',sql)
        self.assertEqual(['2026-11-09','2026-11-11'],params[-2:])
        self.assertIn('최신 MAIN',basis)

    def test_siel_exception_and_unknown_timestamptz_fail_closed(self):
        s,r=select_source('SIEL','TV','Amazon'); cols=self.columns(s);cols['crawl_datetime']='timestamp with time zone'
        self.assertIn("AT TIME ZONE 'Asia/Seoul'",query_spec(s,r,cols,DAY)[0])
        s,r=select_source('SEIB','TV','MediaMarkt');cols=self.columns(s);cols['crawl_datetime']='timestamp with time zone'
        with self.assertRaises(ValueError):query_spec(s,r,cols,DAY)

    def test_coppel_order_and_parameter_allowlist(self):
        s,r=select_source('SEM','LDY_DRYER','Coppel')
        sql,params,_=query_spec(s,r,self.columns(s),DAY)
        self.assertIn('::timestamptz',sql)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)',sql)
        for value in ("Amazon'; DROP TABLE x;--",'unknown'):
            with self.assertRaises(ValueError):select_source('SEA','TV',value)
        self.assertTrue(all(catalog(c) for c in COUNTRIES))


class ApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(RANK_CACHE_DIR=self.directory.name, MONITORING_CACHE_DIR=self.directory.name+'/monitor')
        self.override.enable(); self.addCleanup(self.override.disable)
        self.factory=RequestFactory()
        self.user=SimpleNamespace(is_authenticated=True,get_username=lambda:'reviewer')
        self.scope={'country':'SEA','product':'TV','retailer':'Amazon','date':str(DAY)}
        with patch.object(snapshots,'load_snapshots',return_value={'rows':samples(),'basis':'latest','sku_from_master':True}):
            self.snapshot=snapshots.build(self.scope,snapshots.monitoring_cache_generation())
        _, cache = snapshots.backend()
        cache.set('snapshot:'+self.snapshot['id'],self.snapshot)
        self.token=snapshots.token(self.snapshot)

    def get(self, endpoint='data', **changes):
        request=self.factory.get('/rank/api/'+endpoint+'/',{**self.scope,'mode':'all','snapshot':self.token,**changes})
        request.user=self.user
        with patch.object(snapshots,'load_snapshots',side_effect=AssertionError('pinned requests must not query source')):
            response=getattr(api,endpoint)(request)
        return response.status_code, json.loads(response.content) if endpoint != 'export' or response.status_code != 200 else response.content.decode('utf-8-sig')

    def post(self, token, revision=0, **changes):
        req=self.factory.post('/rank/api/review/',data=json.dumps({'token':token,'result':'품절 확인','memo':'상품 링크 확인 근거','revision':revision,**changes}),content_type='application/json')
        req.user=self.user
        response=api.save_review(req)
        return response.status_code,json.loads(response.content)

    def test_audit_and_pinned_evidence_validation(self):
        code,data=self.get('detail',key='item:30');self.assertEqual(200,code)
        token=data['review_token']
        code,saved=self.post(token);self.assertEqual(200,code)
        self.assertEqual('reviewer',saved['review']['username'])
        self.assertEqual(409,self.post(token)[0])
        self.assertEqual(200,self.post(token,1,result='추가 확인 필요')[0])
        self.assertEqual(2,len(RetailRankReview.objects.get().history))
        code,samsung=self.get('detail',key='item:30',mode='samsung')
        self.assertEqual(2,samsung['review']['revision'])
        payload=signing.loads(token,salt=reviews.SALT);payload['context']['cells'][0]['rank']=29
        self.assertEqual(400,self.post(signing.dumps(payload,salt=reviews.SALT))[0])
        self.assertEqual(1,RetailRankReview.objects.count())

    def test_tokens_scope_validation_and_storage_failure(self):
        _,data=self.get('detail',key='item:1');token=data['review_token']
        self.assertEqual(400,self.post(token+'tampered')[0])
        self.assertEqual(400,self.post(token,memo=' ')[0])
        self.assertEqual(400,self.post(token,revision=True)[0])
        payload=signing.loads(token,salt=reviews.SALT);payload['context']['environment']='invalid'
        self.assertEqual(400,self.post(signing.dumps(payload,salt=reviews.SALT))[0])
        with patch.object(reviews,'summary_index',side_effect=DatabaseError):
            code,data=self.get()
        self.assertEqual(200,code);self.assertFalse(data['review_storage_available'])
        self.assertNotIn('review_token',data['products'][0])
        self.assertEqual(400,self.get(retailer='bad')[0])
        self.assertEqual(400,self.get(date='invalid')[0])
        self.assertEqual(409,self.get(snapshot='bad')[0])
        self.user.is_authenticated=False
        self.assertEqual(401,self.get()[0]);self.assertEqual(401,self.post('invalid')[0])

    def test_pagination_filters_export_and_unchanged_metrics(self):
        raw=[row(d,i,i) for d in (9,10,11) for i in range(1,301)]
        with patch.object(snapshots,'load_snapshots',return_value={'rows':raw,'basis':'latest','sku_from_master':True}):
            snap=snapshots.build(self.scope,self.snapshot['generation'])
        _,cache=snapshots.backend();cache.set('snapshot:'+snap['id'],snap);token=snapshots.token(snap)
        code,data=self.get(snapshot=token,page='2');self.assertEqual(200,code)
        self.assertEqual(300,data['pagination']['count']);self.assertEqual(20,len(data['products']))
        self.assertEqual('21',data['products'][0]['item'])
        self.assertNotIn('record_ids',data['products'][0]['cells'][0])
        self.assertEqual(compare(raw,DAY)['bands'],data['bands'])
        self.assertLess(len(json.dumps(data)),20000)
        code,filtered=self.get(query='SKU-80');self.assertEqual(['80'],[p['item'] for p in filtered['products']])
        code,review=self.get(view='review',sort='priority');self.assertEqual('30',review['products'][0]['item'])
        code,csv=self.get('export',snapshot=token);self.assertEqual(301,len(csv.splitlines()))
        self.assertEqual("'=1+1",api.csv_cell('=1+1'))

    def test_pending_failure_and_source_invalidation(self):
        with patch.object(snapshots,'latest',return_value=(None,{'state':'pending'})):
            code,data=self.get(snapshot='')
        self.assertEqual(202,code);self.assertNotIn('products',data)
        with patch.object(snapshots,'latest',return_value=(None,{'state':'failed'})):
            code,data=self.get(snapshot='')
        self.assertEqual(503,code);self.assertNotIn('products',data)
        from apps.common.monitoring_cache import invalidate_monitoring_cache, MonitoringCacheInvalidationMiddleware
        before=snapshots.monitoring_cache_generation()
        req=self.factory.post('/dx/layer1/rank/api/review/')
        middleware=MonitoringCacheInvalidationMiddleware(lambda request: SimpleNamespace(status_code=200))
        middleware(req)
        self.assertEqual(before,snapshots.monitoring_cache_generation())
        invalidate_monitoring_cache()
        self.assertEqual(409,self.get()[0])


class SnapshotTests(TestCase):
    def test_workers_share_one_refresh_and_environment_isolation(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        script = '''
import sys,time,threading
from pathlib import Path
from django.conf import settings
settings.configure(INSTALLED_APPS=['apps.dx.dx_layer1'], BASE_DIR=Path.cwd(),
                   SECRET_KEY='test', DEBUG=False, RANK_CACHE_DIR=sys.argv[1],
                   MONITORING_CACHE_DIR=sys.argv[1]+'/monitor')
import django
django.setup()
from apps.dx.dx_layer1.rank_monitoring import snapshots
def build(scope,generation):
    with (Path(sys.argv[1])/'reads').open('a') as log:log.write('read\\n')
    time.sleep(.15)
    return {'id':'shared','scope':scope,'generation':generation,'created':time.time(),'results':{}}
snapshots.build=build
snapshots.latest({'country':'SEA','product':'TV','retailer':'Amazon','date':'2026-11-10'})
for thread in threading.enumerate():
    if thread.name=='rank-snapshot-refresh':thread.join(3)
'''
        processes=[subprocess.Popen([sys.executable,'-c',script,directory.name],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
        for process in processes:
            out,err=process.communicate(timeout=10)
            self.assertEqual(0,process.returncode,err.decode(errors='replace'))
        self.assertEqual(['read'],(Path(directory.name)/'reads').read_text().splitlines())
        with override_settings(RANK_CACHE_DIR=directory.name,MONITORING_CACHE_DIR=directory.name+'/monitor',DEBUG=False):
            _,cache=snapshots.backend()
            snapshot=cache.get('snapshot:shared')
            token=snapshots.token(snapshot)
            self.assertEqual('shared',snapshots.pinned(token)['id'])
            with override_settings(DEBUG=True):
                with self.assertRaises(snapshots.SnapshotExpired):snapshots.pinned(token)

    def test_nonblocking_single_refresh_stale_failure_and_shared_cache(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        with override_settings(RANK_CACHE_DIR=directory.name,MONITORING_CACHE_DIR=directory.name+'/monitor'):
            scope={'country':'SEA','product':'TV','retailer':'Amazon','date':str(DAY)}
            started=threading.Event();release=threading.Event()
            real_build=snapshots.build
            def slow_build(*args):
                started.set();release.wait(3)
                return real_build(*args)
            with patch.object(snapshots,'build',side_effect=slow_build) as build, patch.object(snapshots,'load_snapshots',return_value={'rows':samples(),'basis':'latest','sku_from_master':True}):
                try:
                    value,state=snapshots.latest(scope);self.assertIsNone(value);self.assertEqual('pending',state['state'])
                    self.assertTrue(started.wait(1))
                    for _ in range(8):
                        self.assertIsNone(snapshots.latest(scope)[0])
                    # Different retailer also cannot launch a second source read.
                    snapshots.latest({**scope,'retailer':'Bestbuy'})
                    self.assertEqual(1,build.call_count)
                finally:
                    release.set()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    _,cache=snapshots.backend()
                    key=snapshots.scope_key(scope,snapshots.monitoring_cache_generation())
                    version=cache.get('latest:'+key)
                    if version: break
                    time.sleep(.01)
                self.assertTrue(version)
                # Wait for the worker's finally block before ending patches/temp directory.
                for thread in threading.enumerate():
                    if thread.name=='rank-snapshot-refresh':thread.join(3)
                value,state=snapshots.latest(scope)
                self.assertEqual('fresh',state['state']);self.assertEqual(1,build.call_count)
                value['created']=time.time()-90
                cache.set('snapshot:'+value['id'],value)
                cache.set('error:'+key,True,20)
                old,state=snapshots.latest(scope)
                self.assertEqual('refresh_failed',state['state']);self.assertEqual(value['id'],old['id'])
                value['created']=time.time()-301;cache.set('snapshot:'+value['id'],value)
                self.assertIsNone(snapshots.latest(scope)[0])


if __name__=='__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests(['__main__'])))
