"""Isolated metadata DB tests; no collector database connections."""
import copy
import base64
import io
import json
import sys
from contextlib import contextmanager, ExitStack
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=['apps.dx.dx_layer2'],
                       DATABASES={'default': {'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},
                       USE_TZ=True, TIME_ZONE='Asia/Seoul', SECRET_KEY='format-review-tests', DEBUG=False)
import django
django.setup()
from django.test import TestCase, RequestFactory
from django.test.runner import DiscoverRunner
from apps.dx.dx_layer2.format_validation import review_service as service, review_repository as repo
from apps.dx.dx_layer2.format_validation import services, review_api
from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewEvent

DAY = date(2026, 10, 11)


def sample():
    rows = []
    for i, value in enumerate(['Pickup Ready by 9am Tomorrow'] * 3 + ['Pickup Ready Today', '<div>'], 1):
        errors = {} if i == 4 else {'pick_up_availability': {'rule':'pickup','reason':'미등록 문구'}}
        if i == 1:
            errors['final_sku_price'] = {'rule':'money','reason':'잘못된 가격'}
        rows.append({'id':i,'item':str(100+i),'product_url':f'https://www.lowes.com/pd/{i}',
                     'retailer_sku_name':f'Fridge {i}', 'crawl_strdatetime':'2026-10-10 10:00:00',
                     'pick_up_availability':value, 'final_sku_price':'bad' if i == 1 else '$100',
                     'error_fields':[f for f in errors if not (i == 3 and f == 'pick_up_availability')],
                     'error_details':errors})
    return {'date':str(DAY),'source_date':'2026-10-10','table':'sea_ref_retail',
            'retailer':'Lowes','actual_table':'public.ref_retail_com','date_column':'crawl_strdatetime',
            'validation_fields':['pick_up_availability','final_sku_price'],
            'target_ids':[1,2,3,4,5], 'results':rows,
            'normal_reviews':{'3_pick_up_availability':{'reason':'과거 정상 확인'}},
            'total_format_count':4,'field_counts':{'pick_up_availability':3,'final_sku_price':1}}


@contextmanager
def connection_stub():
    yield None, None


class FormatReviewTests(TestCase):
    def capture_payload(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(buffer, format='PNG')
        return {'checked_urls': ['https://www.lowes.com/pd/1'],
                'captures': [{'name': '확인.png', 'data': base64.b64encode(buffer.getvalue()).decode()}]}

    def setUp(self):
        self.raw = sample()
        self.loader = patch.object(services, '_get_format_detail_raw', side_effect=lambda *a, **k: copy.deepcopy(self.raw))
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def inventory(self):
        return service.inventory(None, date.fromisoformat(self.raw['date']), 'sea_ref_retail','Lowes')

    def apply(self, value='Pickup Ready by 9am Tomorrow', action='normal'):
        data = self.inventory()
        key = service.group_key('pick_up_availability', value)
        preview = service.preview(data, [key], action, '상품 URL에서 정상 문구 확인' if action=='normal' else 'HTML 수집 오류')
        service.commit(self.inventory(), preview['token'], 'reviewer')
        return preview

    def test_grouping_legacy_baseline_url_and_current_only(self):
        history = dict(self.raw['results'][0], id=90)
        self.raw['results'].append(history)
        data = self.inventory()
        g = next(g for g in data['groups'] if g['value']=='Pickup Ready by 9am Tomorrow')
        self.assertEqual(3, g['count'])
        self.assertEqual({'pending':2,'legacy_normal':1},g['states'])
        self.assertEqual('https://www.lowes.com/pd/1',g['records'][0]['url'])
        self.assertEqual(5,data['record_count'])
        self.assertEqual(5,data['counts']['baseline_normal'])
        self.assertEqual(1,data['counts']['legacy_normal'])

    def test_baseline_exclusions_do_not_change_validation_or_inventory(self):
        data = self.inventory()
        self.assertIn('final_sku_price', data['baseline_excluded_fields'])
        self.assertIn('count_of_star_ratings', data['baseline_excluded_fields'])
        self.assertNotIn('sku_popularity', data['baseline_excluded_fields'])
        prices = [g for g in data['groups'] if g['field']=='final_sku_price']
        self.assertEqual({'issues', 'baseline'}, {g['tab'] for g in prices})
        result = service.apply_detail(self.raw, repo.scopes(), errors_only=True)
        self.assertEqual(1, result['field_counts']['final_sku_price'])

    def test_evidence_saved_atomically_and_preserved_after_undo(self):
        from apps.dx.dx_layer2.models import FormatReviewCapture
        data = self.inventory()
        key = service.group_key('pick_up_availability', 'Pickup Ready by 9am Tomorrow')
        evidence = self.capture_payload()
        preview = service.preview(data, [key], 'normal', '실제 페이지 확인', evidence)
        tampered = copy.deepcopy(evidence)
        tampered['captures'][0]['name'] = '다른근거.png'
        with self.assertRaises(repo.ReviewConflict):
            service.commit(data, preview['token'], 'reviewer', tampered)
        self.assertEqual(0, FormatReviewEvent.objects.count())
        self.assertEqual(0, FormatReviewCapture.objects.count())
        event_id = service.commit(data, preview['token'], 'reviewer', evidence)
        detail = repo.evidence_detail(data['fingerprint'], event_id)
        self.assertEqual(evidence['checked_urls'], detail['checked_urls'])
        self.assertEqual('reviewer', detail['actor'])
        self.assertEqual('확인.png', detail['captures'][0]['name'])
        self.assertEqual(3, detail['targets'][0]['count'])
        self.assertEqual(1, self.inventory()['history'][0]['capture_count'])
        with self.assertRaises(ValueError): repo.evidence_detail('other-scope', event_id)
        repo.undo(data['fingerprint'], 1, event_id, 'other-reviewer', '취소 사유')
        self.assertTrue(repo.evidence_detail(data['fingerprint'], event_id)['is_del'])
        self.assertEqual(1, FormatReviewCapture.objects.count())

    def test_existing_policies_still_apply_before_evidence_migration(self):
        self.apply()
        with patch.object(repo, 'ready', side_effect=lambda evidence=False: not evidence):
            data = self.inventory()
            self.assertFalse(data['available'])
            self.assertEqual([], data['history'])
            self.assertEqual('registered', next(g for g in data['groups'] if g['value']=='Pickup Ready by 9am Tomorrow')['tab'])

    def test_invalid_evidence_and_capture_access(self):
        from apps.dx.dx_layer2.models import FormatReviewCapture
        data = self.inventory()
        key = service.group_key('pick_up_availability', 'Pickup Ready by 9am Tomorrow')
        valid = self.capture_payload()
        cases = [
            {'checked_urls': ['https://unrelated.test']},
            {'checked_urls': ['javascript:alert(1)']},
            {'captures': valid['captures']*4},
            {'captures': [{'name':'x.png', 'data':'invalid base64!'}]},
            {'captures': [{'name':'x.png', 'data':base64.b64encode(b'<svg></svg>').decode()}]},
            {'captures': [{'name':'x.png', 'data':'A'*600000}]},
        ]
        for evidence in cases:
            with self.subTest(evidence=str(evidence)[:90]), self.assertRaises(ValueError):
                service.preview(data, [key], 'normal', '확인', evidence)
        preview = service.preview(data, [key], 'normal', '확인', valid)
        service.commit(data, preview['token'], 'reviewer', valid)
        capture = FormatReviewCapture.objects.get()
        request = RequestFactory().get('/capture/')
        request.user = SimpleNamespace(is_authenticated=False)
        self.assertEqual(401, review_api.capture(request, capture.pk).status_code)
        request.user.is_authenticated = True
        response = review_api.capture(request, capture.pk)
        self.assertEqual(200, response.status_code)
        self.assertEqual('image/png', response['Content-Type'])
        self.assertEqual('private, no-store', response['Cache-Control'])
        with self.settings(DEBUG=True):
            self.assertEqual(404, review_api.capture(request, capture.pk).status_code)

    def test_batch_normal_future_and_other_field_preserved(self):
        preview = self.apply()
        self.assertEqual(3,preview['count'])
        result=service.apply_detail(self.raw,repo.scopes(),errors_only=True)
        self.assertEqual({'final_sku_price':1,'pick_up_availability':1},result['field_counts'])
        self.assertEqual('bad',self.raw['results'][0]['final_sku_price'])
        self.raw['date']='2026-10-12'
        self.raw['results'][0]['id']=11
        self.raw['target_ids'][0]=11
        result=service.apply_detail(self.raw,repo.scopes())
        self.assertEqual('registered_normal',result['results'][0]['review_states']['pick_up_availability'])
        self.raw['results'][0]['pick_up_availability']='Pickup Ready by 10am Tomorrow'
        result=service.apply_detail(self.raw,repo.scopes())
        self.assertEqual('pending',result['results'][0]['review_states']['pick_up_availability'])

    def test_scope_and_exact_text_boundaries(self):
        self.apply()
        for changes in [{'retailer':'Amazon'}, {'table':'sea_ldy_retail'}, {'actual_table':'test_ref_retail_com'}]:
            data={**self.raw,**changes}
            self.assertIn('pick_up_availability',service.apply_detail(data,repo.scopes())['results'][0]['error_fields'])
        for value in ['Pickup Ready by 9am Tomorrow ', 'pickup ready by 9am tomorrow']:
            self.raw['results'][0]['pick_up_availability']=value
            self.assertIn('pick_up_availability',service.apply_detail(self.raw,repo.scopes())['results'][0]['error_fields'])
        with self.settings(DEBUG=True):
            self.assertFalse(service.has_scope(repo.scopes(),'sea_ref_retail','Lowes'))

    def test_false_normal_error_rechecked_next_day_and_new_value_resolves(self):
        self.apply('Pickup Ready Today','error')
        result=service.apply_detail(self.raw,repo.scopes())
        self.assertEqual('error',result['results'][3]['review_states']['pick_up_availability'])
        self.raw['date']='2026-10-12'
        result=service.apply_detail(self.raw,repo.scopes())
        self.assertEqual('pending',result['results'][3]['review_states']['pick_up_availability'])
        self.raw['results'][3]['pick_up_availability']='Valid new value'
        self.assertEqual('baseline_normal',service.apply_detail(self.raw,repo.scopes())['results'][3]['review_states']['pick_up_availability'])

    def test_preview_staleness_tamper_and_revision(self):
        data=self.inventory();key=data['groups'][0]['key']
        preview=service.preview(data,[key],'normal','원본 확인')
        with self.assertRaises(repo.ReviewConflict):service.commit(data,preview['token']+'x','user')
        self.raw['results'][0]['product_url']='https://www.lowes.com/pd/changed'
        with self.assertRaises(repo.ReviewConflict):service.commit(self.inventory(),preview['token'],'user')
        self.apply()
        with self.assertRaises(repo.ReviewConflict):service.commit(self.inventory(),preview['token'],'user')
        self.assertEqual(1,FormatReviewEvent.objects.count())

    def test_revoke_undo_and_audit_actor(self):
        self.apply()
        scope=FormatReviewScope.objects.get()
        event=FormatReviewEvent.objects.get()
        self.assertEqual('reviewer',event.actor)
        repo.undo(scope.fingerprint,scope.revision,event.pk,'reviewer2','잘못 등록해서 취소')
        self.assertEqual('issues',next(g for g in self.inventory()['groups'] if g['value']=='Pickup Ready by 9am Tomorrow')['tab'])
        event.refresh_from_db();self.assertTrue(event.is_del)
        self.apply()
        self.apply(action='revoke')
        self.assertEqual([],self.inventory()['registrations'])

    def test_older_undo_cannot_clobber_later_policy(self):
        self.apply()
        event=FormatReviewEvent.objects.get()
        self.apply(action='error')
        scope=FormatReviewScope.objects.get()
        with self.assertRaises(repo.ReviewConflict):repo.undo(scope.fingerprint,scope.revision,event.pk,'x','취소')
        self.assertEqual('error',self.inventory()['registrations'][0]['action'])

    def test_stats_and_detail_consistency(self):
        self.apply()
        base={'type':'format','tables':[{'table':'sea_ref_retail','retailers':[{'retailer':'Lowes','total':5,'issue_count':4}], 'total_issues':4}]}
        with patch.object(services,'_get_format_stats_raw',return_value=(base,4)):
            stats,total=services.get_format_stats(None,DAY)
        detail=services.get_format_detail(None,DAY,'sea_ref_retail','Lowes',1)
        self.assertEqual(2,total)
        self.assertEqual(total,detail['total_format_count'])
        self.assertEqual(total,stats['tables'][0]['retailers'][0]['issue_count'])

    def test_report_no_double_count_and_error_not_corrected(self):
        self.apply()
        self.apply('<div>','error')
        details=[{'correction_type':'format_check','table_name':'ref_retail_com', 'record_id':3,
                  'column_name':'pick_up_availability','status':'normal','reason':'과거 확인'}]
        types,reasons,tables={},{},{}
        reasons=[]
        service.merge_report(None,DAY,types,reasons,tables,details)
        self.assertEqual({'normal':3,'error':1},types['format_check'])
        self.assertEqual(4,len(details))

    def test_api_authentication_and_invalid_request(self):
        factory=RequestFactory()
        with patch.object(review_api,'dx_connection',connection_stub),patch.object(review_api.timezone,'localdate',return_value=DAY):
            req=factory.get('/reviews/',{'date':str(DAY),'table':'sea_ref_retail','retailer':'Lowes'})
            req.user=SimpleNamespace(is_authenticated=False)
            self.assertEqual(401,review_api.reviews(req).status_code)
            req.user=SimpleNamespace(is_authenticated=True,get_username=lambda:'reviewer')
            self.assertEqual(200,review_api.reviews(req).status_code)
            req=factory.post('/reviews/',data=json.dumps({'date':str(DAY),'table':'sea_ref_retail','retailer':'Lowes','action':'preview','decision':'normal','keys':['forged'],'reason':'확인'}),content_type='application/json')
            req.user=SimpleNamespace(is_authenticated=True,get_username=lambda:'reviewer')
            self.assertEqual(409,review_api.reviews(req).status_code)

    def test_real_collector_loaders_keep_baseline_normal_rows(self):
        self.loader.stop()
        mapping={'inspection_date':str(DAY),'source_date':str(DAY),'offset_days':0}
        cases=[
            ('sea_ref_retail','Lowes',services,'_fetch_sea_format_rows','_load_sea_format_normal_reviews','pick_up_availability','Pickup Ready Today'),
            ('siel_tv_retail','Amazon',services,'_fetch_siel_format_rows','_load_siel_format_normal_reviews','discount_type','Limited time deal'),
            ('tse_tv_retail','Homepro',services,'_fetch_tse_format_rows','_load_tse_format_normal_reviews','final_sku_price','฿10,000'),
            ('seda_tv_retail','Magalu',services.seda_format_validation,'load_rows','normal_reviews','star_rating','5.0'),
            ('seg_ldy_dryer_retail','Expert',services.seg_validation,'_latest_rows','_load_normal_reviews','capacity','8 kg'),
            ('sem_tv_retail','Liverpool',services.sem_validation,'_latest_rows','_load_normal_reviews','star_rating','4.5'),
        ]
        for table,retailer,module,fetch,reviews,field,value in cases:
            row={'id':1,field:value,'product_url':'https://example.test/product/1'}
            fetched=([row],mapping) if fetch=='_latest_rows' else [row]
            with self.subTest(table=table), ExitStack() as stack:
                stack.enter_context(patch.object(module,fetch,return_value=fetched))
                stack.enter_context(patch.object(module,reviews,return_value={}))
                if table.startswith('sea_'):
                    stack.enter_context(patch.object(services,'validate_field',return_value=None))
                data=service.inventory(None,DAY,table,retailer)
                group=next(g for g in data['groups'] if g['field']==field)
                self.assertEqual({'baseline_normal':1},group['states'])
                self.assertEqual(1,data['record_count'])
                self.assertEqual('https://example.test/product/1',group['records'][0]['url'])

    def test_tv_reference_failures_and_history_are_preserved(self):
        self.loader.stop()
        from tests.unit.support import ScriptedCursor
        fields=['item','page_type','product_url','main_rank','bsr_rank','final_sku_price',
                'original_sku_price','count_of_reviews','star_rating','count_of_star_ratings',
                'detailed_review_content','number_of_units_purchased_past_month',
                'available_quantity_for_purchase','sku_popularity','retailer_membership_discounts',
                'rank_1','rank_2','summarized_review_content','savings','offer','retailer_sku_name_similar',
                'recommendation_intent','number_of_ppl_purchased_yesterday','number_of_ppl_added_to_carts','discount_type']
        values={'item':'unlisted','final_sku_price':'bad'}
        current=(2,'2026-10-11','Amazon',*(values.get(f) for f in fields))
        history=(1,'2026-10-10','Amazon',*(values.get(f) for f in fields))
        cursor=ScriptedCursor([{'fetchall':[]},{'fetchall':[current]},
                               {'fetchall':[history,current]},{'fetchall':[]}])
        with patch.object(services,'build_per_field_error_sql',return_value=[{'field':'final_sku_price'}]), \
             patch.object(services,'build_format_error_sql',return_value='TRUE'), \
             patch.object(services,'get_editable_columns',return_value=[]), \
             patch.object(services,'validate_tv_field',side_effect=lambda f,v,r:'bad price' if f=='final_sku_price' else None):
            data=services._get_format_detail_raw(cursor,DAY,'tv_retail','Amazon',3,include_normal=True)
        self.assertEqual([2],data['target_ids'])
        context=service.context_for(data)
        scopes={service.digest(context):SimpleNamespace(revision=1,policies={
            service.group_key('final_sku_price','bad'):{'action':'normal','date':str(DAY)}})}
        result=service.apply_detail(data,scopes,errors_only=True)
        self.assertEqual({'item (참조 무결성)':1},result['field_counts'])
        self.assertEqual([1,2],[r['id'] for r in result['results']])


if __name__=='__main__':
    failures=DiscoverRunner(verbosity=2).run_tests(['__main__'])
    raise SystemExit(bool(failures))
