"""Isolated SQLite lifecycle tests; no production DB queries."""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=['apps.dx.dx_layer1'],
        DATABASES={'default': {'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},
        USE_TZ=True,TIME_ZONE='Asia/Seoul',SECRET_KEY='isolated-issues',DEBUG=False)
import django
django.setup()
from django.test import TestCase, RequestFactory, override_settings
from django.test.runner import DiscoverRunner
from django.db import OperationalError
from apps.dx.dx_layer1.collection_issues import services as s, api
from apps.dx.dx_layer1.collection_issues.queries import sql_queries
from apps.dx.dx_layer1.column_statistics.dates import day_sql
from apps.dx.dx_layer1.column_statistics.services import select_source
from apps.dx.dx_layer1.column_statistics.comparison import KST, compare_columns
from apps.dx.dx_layer1.models import CollectionIssue as Issue, CollectionIssueScan as Scan

TARGET=date(2026,10,14)
NOW=datetime(2026,10,20,15,tzinfo=KST)

def sample(target=TARGET,count=0,total=300,history=100):
    daily=[{'date':str(target-timedelta(days=i)), 'total':300,'counts':{'offer':history}} for i in range(1,29)]
    daily.append({'date':str(target),'total':total,'counts':{'offer':count}})
    data={'country':'SEA','product':'TV','retailer':'Walmart','columns':['offer'],'daily':daily}
    return data,{d['date']:True for d in daily}

class IssueTests(TestCase):
    def test_past_review_page_uses_separate_section(self):
        req = RequestFactory().get('/dx/layer1/past-review/')
        req.user = SimpleNamespace(is_authenticated=True)
        with patch('apps.dx.dx_layer1.common.context.build_context', return_value={'section': 'past_review'}) as context, \
             patch.object(api, 'render') as render:
            api.page(req)
        context.assert_called_once_with('past_review', req)
        render.assert_called_once_with(req, 'dx_layer1_past_review.html', {'section': 'past_review'})

    def test_past_review_menu_follows_column_alerts_and_is_independent(self):
        from apps.dx.dx_layer1.common.context import _build_sidebar_groups
        with patch('apps.dx.dx_layer1.common.context.load_collection_schedules', return_value=[]):
            groups = _build_sidebar_groups('past_review')
        keys = [group['key'] for group in groups]
        self.assertEqual(keys.index('past_review'), keys.index('column_alerts') + 1)
        selected = [group for group in groups if group['active']]
        self.assertEqual([group['key'] for group in selected], ['past_review'])
        self.assertEqual(selected[0]['href'], '/dx/layer1/past-review/')

    def test_listing_identifies_schema_and_lock_errors_without_exposing_sql(self):
        req = RequestFactory().get('/')
        req.user = SimpleNamespace(is_authenticated=True)
        for error, code in (
            ('no such table: dx_layer1_collectionissue', 'issue_storage_schema'),
            ('database is locked', 'issue_storage_busy'),
            ('private connection detail', 'issue_storage_error'),
        ):
            with patch.object(Issue.objects, 'filter', side_effect=OperationalError(error)):
                with self.assertLogs('apps.dx.dx_layer1.collection_issues.errors', level='ERROR'):
                    response = api.listing(req)
            payload = json.loads(response.content)
            self.assertEqual(503, response.status_code)
            self.assertEqual(code, payload['code'])
            self.assertTrue(payload['action'])
            self.assertNotIn(error, response.content.decode())

    def observe(self,*,target=TARGET,count=0,total=300,raw=300,history=100):
        data,complete=sample(target,count,total,history)
        s.reconcile_day(data,target,complete,raw,now=NOW)
        return Issue.objects.filter(source_date=target).first()

    def request(self,record,action,reason='확인 근거',revision=None,user='reviewer'):
        req=RequestFactory().post('/',json.dumps({'action':action,'reason':reason,
            'revision':record.revision if revision is None else revision}),content_type='application/json')
        req.user=SimpleNamespace(is_authenticated=bool(user),get_username=lambda:user)
        response=api.action(req,record.pk)
        return response.status_code,json.loads(response.content)

    def test_next_day_normal_and_collapsed_median_cannot_resolve_original(self):
        row=self.observe()
        self.observe(target=TARGET+timedelta(days=1),count=100)
        self.observe(history=0)
        row.refresh_from_db()
        self.assertEqual(row.status,'open')
        self.assertEqual(row.baseline,100)
        self.assertEqual(row.evidence['history_days'],28)
        self.assertEqual(row.events.count(),1)
        self.observe(count=61,history=0)
        row.refresh_from_db()
        self.assertEqual(row.status,'resolved')
        self.assertEqual(list(row.events.values_list('action',flat=True)),['detected','recovered'])
        self.observe(count=0,history=0)
        row.refresh_from_db()
        self.assertEqual(row.status,'open')
        self.assertEqual(row.baseline,100)

    def test_whole_collection_one_incident_without_minimum_history(self):
        data,complete=sample(total=0)
        data['daily']=data['daily'][-1:]
        data['columns']=['offer','other']
        data['daily'][0]['counts']['other']=0
        s.reconcile_day(data,TARGET,complete,0,now=NOW)
        row=Issue.objects.get()
        self.assertEqual(row.column,'')
        self.assertEqual(row.severity,'uncollected')
        # Raw rows outside the column-count scope are still a collection.
        self.observe(total=0,raw=20)
        row.refresh_from_db()
        self.assertEqual(row.status,'resolved')

    def test_older_cached_observation_cannot_undo_verified_recovery(self):
        row=self.observe()
        data,complete=sample(count=100)
        s.reconcile_day(data,TARGET,complete,300,now=NOW+timedelta(minutes=10))
        self.observe()
        row.refresh_from_db()
        self.assertEqual(row.status,'resolved')
        self.assertEqual(row.current_count,100)

    def test_listing_collapses_columns_under_whole_missing_and_separates_history(self):
        self.observe()
        self.observe(total=0,raw=0)
        req=RequestFactory().get('/',{'country':'SEA','status':'open'})
        req.user=SimpleNamespace(is_authenticated=True)
        payload=json.loads(api.listing(req).content)
        self.assertEqual(len(payload['issues']),1)
        self.assertEqual(payload['issues'][0]['column'],'')
        self.assertEqual(payload['start_date'],'2026-09-01')
        self.assertEqual(payload['scans'],[])  # not a claim of complete coverage
        bad=RequestFactory().get('/',{'country':'UNKNOWN'})
        bad.user=req.user
        self.assertEqual(api.listing(bad).status_code,400)

    def test_pending_and_before_september_never_create_incident(self):
        data,complete=sample()
        complete[str(TARGET)]=False
        s.reconcile_day(data,TARGET,complete,0,now=NOW)
        self.observe(target=date(2026,8,31),total=0,raw=0)
        self.assertFalse(Issue.objects.exists())

    def past_listing(self, **params):
        req = RequestFactory().get('/', params)
        req.user = SimpleNamespace(is_authenticated=True)
        return api.listing(req)

    def create_past_issue(self, country, day, **overrides):
        values = dict(environment='production', country=country, product='TV',
            retailer={'SEA':'Walmart', 'SEDA':'Casas Bahia', 'SEG':'OTTO', 'SIEL':'Amazon'}[country],
            source_date=day, column='', severity='uncollected', observed_count=0,
            current_count=0, first_detected_at=NOW, last_checked_at=NOW)
        values.update(overrides)
        return Issue.objects.create(**values)

    def test_past_listing_excludes_current_us_brazil_day_and_rolls_forward(self):
        for country in ('SEA', 'SEDA', 'SEG', 'SIEL'):
            for day in (21, 22, 23):
                self.create_past_issue(country, date(2026, 10, day))
        # Column incidents and all products obey the same source-day boundary.
        self.create_past_issue('SEA', date(2026, 10, 22), product='LDY_DRYER', column='offer')
        for inspection_day, latest in ((23, '2026-10-21'), (24, '2026-10-22')):
            payload = json.loads(self.past_listing(inspection_date=f'2026-10-{inspection_day}').content)
            for country in ('SEA', 'SEDA'):
                rows = [r for r in payload['issues'] if r['country'] == country]
                self.assertEqual(max(r['source_date'] for r in rows), latest)
            for country in ('SEG', 'SIEL'):
                self.assertEqual(len([r for r in payload['issues'] if r['country'] == country]), 3)
        self.assertEqual(Issue.objects.count(), 13)  # Listing never deletes evidence.
        self.assertEqual(Issue.objects.filter(status='open').count(), 13)

    def test_past_listing_cutoff_applies_to_country_filters_and_history(self):
        for country in ('SEA', 'SEDA'):
            for status in ('open', 'resolved', 'excepted'):
                for day in (21, 22):
                    self.create_past_issue(country, date(2026, 10, day), column=status, status=status)
            for status in ('open', 'resolved', 'excepted', 'all'):
                payload = json.loads(self.past_listing(country=country, status=status,
                    inspection_date='2026-10-23').content)
                self.assertEqual(len(payload['issues']), 3 if status == 'all' else 1)
                self.assertTrue(all(r['source_date'] == '2026-10-21' for r in payload['issues']))

    def test_past_listing_defaults_to_kst_inspection_day_and_validates_dates(self):
        self.create_past_issue('SEA', date(2026, 10, 22))
        with patch.object(api.timezone, 'now', return_value=datetime.fromisoformat('2026-10-23T15:01:00+00:00')):
            payload = json.loads(self.past_listing(country='SEA').content)
        self.assertEqual(payload['inspection_date'], '2026-10-24')
        self.assertEqual(len(payload['issues']), 1)
        for invalid in ('', '2026-02-30', '20261023', '2026-10-23T00:00:00'):
            self.assertEqual(self.past_listing(inspection_date=invalid).status_code, 400)

    def test_past_listing_month_year_and_leap_boundaries(self):
        for inspection_day in (date(2026, 11, 1), date(2027, 1, 1), date(2028, 3, 1)):
            for country in ('SEA', 'SEDA'):
                past = self.create_past_issue(country, inspection_day-timedelta(days=2))
                current = self.create_past_issue(country, inspection_day-timedelta(days=1))
                payload = json.loads(self.past_listing(country=country, inspection_date=str(inspection_day)).content)
                ids = {r['id'] for r in payload['issues']}
                self.assertIn(past.id, ids)
                self.assertNotIn(current.id, ids)

    def test_acknowledgement_exception_and_revision_history(self):
        row=self.observe()
        self.assertEqual(self.request(row,'acknowledge')[0],200)
        row.refresh_from_db()
        self.assertEqual(row.status,'open')
        self.assertEqual(self.request(row,'except',reason='')[0],400)
        self.assertEqual(self.request(row,'except',revision=0)[0],409)
        self.assertEqual(self.request(row,'except',user='')[0],401)
        self.assertEqual(self.request(row,'except')[0],200)
        self.observe()
        row.refresh_from_db()
        self.assertEqual(row.status,'excepted')
        self.assertEqual(self.request(row,'reopen')[0],200)
        row.refresh_from_db()
        self.assertEqual(row.status,'open')
        self.assertEqual(row.events.last().username,'reviewer')

    def test_failed_recheck_keeps_incident_and_timestamp(self):
        row=self.observe()
        with patch.object(api,'daily_counts',side_effect=RuntimeError('private detail')):
            code,payload=self.request(row,'recheck')
        self.assertEqual(code,503)
        self.assertNotIn('private',str(payload))
        row.refresh_from_db()
        self.assertEqual(row.status,'open')
        self.assertEqual(row.last_checked_at,NOW)

    def test_environment_isolation(self):
        production=self.observe()
        with override_settings(DEBUG=True):
            self.observe()
            self.assertEqual(Issue.objects.count(),2)
            self.assertEqual(self.request(production,'except')[0],404)

    def test_uncollected_scope_and_new_launch(self):
        data,complete=sample(total=0)
        data['daily'][-1]['raw_total']=20
        self.assertEqual(compare_columns(data,TARGET,complete)[0]['status'],'no_scoped_rows')
        data['active_from']='2026-10-15'
        self.assertEqual(compare_columns(data,TARGET,complete)[0]['status'],'not_scheduled')

    def test_sql_uses_original_dates_and_siel_exception(self):
        for country,retailer in [('SEA','Walmart'),('SEDA','Casas Bahia'),('SEG','OTTO'),('SIEL','Amazon')]:
            source=select_source(country,'TV',retailer)
            sql=sql_queries(country,'TV',retailer,TARGET)
            self.assertIn("'2026-10-14'",sql['count'])
            self.assertNotIn('WHERE source.batch_id',sql['count'])
            if country=='SIEL':
                self.assertIn("AT TIME ZONE 'Asia/Seoul'",sql['count'])
            else:
                self.assertIn('LEFT(BTRIM(CAST(source.crawl_',sql['count'])
                self.assertNotIn('AT TIME ZONE',day_sql(source))
            if country=='SEDA':
                self.assertIn("'casasbahia'",sql['count'])
                self.assertIn("'casas bahia'",sql['count'])
        with self.assertRaises(ValueError):
            sql_queries('SEA','TV',"Walmart';DROP TABLE x",TARGET)

    def test_scan_from_september_incremental_new_launch_and_failure_retains_coverage(self):
        def counts(country,product,retailer,end,days):
            return {'country':country,'product':product,'retailer':retailer,'columns':['offer'],
                'daily':[{'date':str(end-timedelta(days=i)), 'total':100,'counts':{'offer':100}} for i in range(days)]}
        def raw(country,product,retailer,start,end):
            return {str(start+timedelta(days=i)):100 for i in range((end-start).days+1)}
        with patch.object(s,'daily_counts',side_effect=counts), patch.object(s,'raw_counts',side_effect=raw), \
                patch.object(s,'first_observed',return_value=date(2026,6,1)), \
                patch.object(s,'collection_complete',return_value=True),patch.object(s.timezone,'now',return_value=NOW):
            s.refresh_target('SEA','TV','Walmart',now=NOW)
            scan=Scan.objects.get()
            self.assertEqual(scan.scanned_through,date(2026,9,28))
            s.refresh_target('SEA','TV','Walmart',now=NOW)
            scan.refresh_from_db()
            self.assertEqual(scan.scanned_through,date(2026,10,19))
            s.refresh_target('SEA','LDY_DRYER','Lowes',now=NOW)
            self.assertEqual(Scan.objects.get(retailer='Lowes').scanned_through,date(2026,10,19))
            with patch.object(s,'raw_counts',side_effect=RuntimeError('outage')):
                with self.assertRaises(RuntimeError):
                    s.refresh_target('SEA','TV','Walmart',now=NOW)
            scan.refresh_from_db()
            self.assertTrue(scan.error)
            self.assertEqual(scan.scanned_through,date(2026,10,19))
        self.assertFalse(Issue.objects.exists())

    def test_first_observed_start_does_not_move_forward_on_later_deletion(self):
        with patch.object(s,'first_observed',return_value=date(2026,9,6)):
            start,basis=s.coverage_start('SEM','TV','Liverpool')
        self.assertEqual(start,date(2026,9,6))
        self.assertEqual(basis,'first_observed')
        Scan.objects.create(**s.identity('SEM','TV','Liverpool'),coverage_start=start,start_basis=basis)
        with patch.object(s,'first_observed',return_value=date(2026,9,10)):
            self.assertEqual(s.coverage_start('SEM','TV','Liverpool')[0],date(2026,9,6))
        with patch.object(s,'first_observed',return_value=None):
            self.assertEqual(s.coverage_start('SEM','TV','Liverpool')[0],date(2026,9,6))

if __name__=='__main__':
    sys.exit(bool(DiscoverRunner(verbosity=1).run_tests([__name__])))
