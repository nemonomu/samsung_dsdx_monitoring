"""Isolated shared review lifecycle; source snapshots are mocked, never written."""
import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_collection_statistics_backend import TestCase, RequestFactory, DiscoverRunner
from django.test import override_settings
from apps.dx.dx_layer1.collection_statistics import volume_review_api as api
from apps.dx.dx_layer1.collection_statistics.reviews import attach_review, review_index
from apps.dx.dx_layer1.collection_issues import volume, services
from apps.dx.dx_layer1.models import CollectionIssue, RetailNormalReview


class MetricReviewTests(TestCase):
    def setUp(self):
        self.target = dict(country='SEA', product='LDY', retailer='Costco', slot='daily',
                           source_date='2026-10-28', metric='main')
        self.row = dict(product='LDY', retailer='Costco', slot='daily', date='2026-10-28',
                        state='complete', complete=True, base_status='OK', batch_id='batch1', batch_count=1,
                        main=63, bsr=71, total=74,
                        alerts=[dict(metric='main', baseline=74.5, actual=63, status='VOLUME_REVIEW', reason='MAIN low'),
                                dict(metric='bsr', baseline=100, actual=71, status='VOLUME_LOW', rule='fixed_100', exact=True, reason='BSR low')])
        self.issue = CollectionIssue.objects.create(environment='production',country='SEA',product='LDY',retailer='Costco',
            source_date=date(2026,10,28), column=volume.metric_column('main','daily'), severity='review',
            observed_count=63,current_count=63,baseline=74.5,first_detected_at='2026-10-30T00:00:00Z',
            last_checked_at='2026-10-30T00:00:00Z',evidence={'metric':'main','slot':'daily','kind':'volume','current_row':self.row})
        self.mock = patch('apps.dx.dx_layer1.collection_statistics.live.current_snapshot', side_effect=self.snapshot)
        self.mock.start(); self.addCleanup(self.mock.stop)

    def attached(self):
        return attach_review(deepcopy(self.row),'SEA','LDY','Costco','daily',review_index(date(2026,10,28),date(2026,10,28)))

    def snapshot(self, country, inspection):
        self.assertEqual(('SEA',date(2026,10,29)),(country,inspection))
        return {'rows':[self.attached()]}

    def request(self, payload, post=False, auth=True):
        req = (RequestFactory().post('/',data=json.dumps(payload),content_type='application/json') if post
               else RequestFactory().get('/',payload))
        req.user=SimpleNamespace(is_authenticated=auth,get_username=lambda:'reviewer')
        return api.review(req)

    def save(self, metric='main', action='confirm'):
        target={**self.target,'metric':metric}
        response=self.request(target);self.assertEqual(200,response.status_code,response.content)
        data=json.loads(response.content)
        response=self.request({**target,'token':data['token'],'revision':data['revision'],'action':action,'memo':'source checked'},True)
        self.assertEqual(200,response.status_code,response.content)

    def test_confirm_statistics_and_issue_share_metric_and_cancel(self):
        self.save()
        self.assertEqual({'main'},set(self.attached()['metric_reviews']))
        self.assertNotIn('review',self.attached())
        self.issue.refresh_from_db()
        self.assertEqual('confirmed',services.serialize(self.issue)['status'])
        self.assertEqual([],volume.hide_confirmed([self.issue]))
        self.save('bsr')
        self.assertEqual(['bsr','main'],self.attached()['review']['metrics'])
        self.save('main','cancel')
        self.assertEqual({'bsr'},set(self.attached()['metric_reviews']))
        self.assertEqual('open',services.serialize(self.issue)['status'])
        self.assertEqual(['normal_confirm','normal_cancel'],list(self.issue.events.values_list('action',flat=True)))

    def test_stale_evidence_revision_and_tampered_token_rejected(self):
        data=json.loads(self.request(self.target).content)
        payload={**self.target,'token':data['token'],'revision':0,'action':'confirm','memo':'checked'}
        self.row['main']=62
        self.assertEqual(409,self.request(payload,True).status_code)
        self.row['main']=63
        self.save()
        self.assertEqual(409,self.request(payload,True).status_code)
        self.assertEqual(400,self.request({**payload,'token':'forged'},True).status_code)
        self.assertEqual(1,RetailNormalReview.objects.count())

    def test_changed_batch_counts_basis_and_environment_do_not_inherit(self):
        self.save()
        for field,value in [('batch_id','new'),('main',62),('batch_count',2)]:
            old=self.row[field];self.row[field]=value
            self.assertEqual({},self.attached()['metric_reviews'])
            self.row[field]=old
        self.row['alerts'][0]['baseline']=75
        self.assertEqual({},self.attached()['metric_reviews'])
        self.row['alerts'][0]['baseline']=74.5
        with override_settings(DEBUG=True):
            self.assertEqual({},self.attached()['metric_reviews'])
        self.assertEqual({'main'},set(self.attached()['metric_reviews']))

    def test_auth_missing_pending_and_reason_do_not_write(self):
        self.assertEqual(401,self.request(self.target,auth=False).status_code)
        self.row['state']='pending'
        self.assertEqual(400,self.request(self.target).status_code)
        self.row['state']='complete'
        data=json.loads(self.request(self.target).content)
        self.assertEqual(400,self.request({**self.target,'token':data['token'],'revision':0,'action':'confirm','memo':''},True).status_code)
        self.assertFalse(RetailNormalReview.objects.exists())

    def test_metric_cancel_supersedes_legacy_whole_row_without_cancelling_sibling(self):
        context={**self.target,'version':1,'date':'2026-10-29','batch_id':'batch1','counts':[63,71,74,1],
                 'basis':json.dumps({'alerts':self.row['alerts']})}
        context.pop('metric')
        RetailNormalReview.objects.create(fingerprint='legacy',inspection_date='2026-10-29',context=context,
            active=True,history=[{'action':'confirm','at':'2020-01-01T00:00:00Z','memo':'legacy','username':'first'}])
        self.assertEqual({'main','bsr'},set(self.attached()['metric_reviews']))
        self.save('main','cancel')
        self.assertEqual({'bsr'},set(self.attached()['metric_reviews']))
        self.save('main')
        self.assertEqual({'main','bsr'},set(self.attached()['metric_reviews']))


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests(['__main__'])))
