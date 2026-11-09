"""Persistent administrator checks; isolated SQLite, never the source database."""
import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(
        INSTALLED_APPS=['apps.dx.dx_layer1', 'apps.dx.dx_layer2'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True, TIME_ZONE='Asia/Seoul', DEBUG=False, SECRET_KEY='isolated-check-test',
        ROOT_URLCONF=__name__, MIDDLEWARE=[], ALLOWED_HOSTS=['testserver'],
    )
import django
django.setup()
from django.test import TestCase, RequestFactory, Client, override_settings
from django.test.runner import DiscoverRunner
from django.urls import path
from apps.common import validation_review_checks as checks, validation_review_views as views
from apps.dx.dx_layer2.models import AdminValidationReviewCheck


def admin_endpoint(request):
    request.user = SimpleNamespace(is_authenticated=True, is_staff=True, is_superuser=False,
                                   get_username=lambda: 'admin')
    return views.check(request)


urlpatterns = [path('check/', admin_endpoint)]
DAY = date(2026, 11, 6)
ITEM = dict(table_name='public.tv_retail_com', retailer='Amazon', total=7,
            country='SEA', product='TV', counts={'corrected': 7})


class CompletionTests(TestCase):
    def setUp(self):
        registry = patch.object(checks.review.audit, '_sources', return_value={
            'tv_retail_com': {}, 'ref_retail_com': {},
        })
        registry.start()
        self.addCleanup(registry.stop)

    def save(self, checked=True, **kwargs):
        values = dict(day=DAY, kind='null_check', table='public.tv_retail_com',
                      retailer='Amazon', checked=checked, actor='admin')
        values.update(kwargs)
        return checks.set_checked(**values)

    def test_persistence_normalized_identity_and_uncheck_keep_cards_and_counts(self):
        for kind in checks.review.KINDS:
            self.save(kind=kind)
            items = [deepcopy(ITEM)]
            with self.assertNumQueries(1):
                checks.attach(items, DAY, kind)
            self.assertTrue(items[0]['check']['checked'])
            self.assertEqual('admin',items[0]['check']['actor'])
            self.assertEqual(ITEM,{k:v for k,v in items[0].items() if k!='check'})
            self.save(False, kind=kind, table='tv_retail_com', retailer=' AMAZON ', actor='other-admin')
            checks.attach(items, DAY, kind)
            self.assertFalse(items[0]['check']['checked'])
            self.assertEqual('other-admin',items[0]['check']['actor'])
            self.assertEqual(7,items[0]['total'])
        self.assertEqual(4,AdminValidationReviewCheck.objects.count())

    def test_date_kind_product_retailer_and_environment_are_isolated(self):
        self.save()
        for day,kind,changes in [(date(2026,11,5),'null_check',{}),
                                 (DAY,'cross_field',{}),
                                 (DAY,'null_check',{'table_name':'public.ref_retail_com'}),
                                 (DAY,'null_check',{'retailer':'Other'})]:
            items=[{**ITEM,**changes}]
            checks.attach(items,day,kind)
            self.assertFalse(items[0]['check']['checked'])
        with override_settings(DEBUG=True):
            items=[deepcopy(ITEM)]
            checks.attach(items,DAY,'null_check')
            self.assertFalse(items[0]['check']['checked'])
            self.save(False)
        items=[deepcopy(ITEM)]
        checks.attach(items,DAY,'null_check')
        self.assertTrue(items[0]['check']['checked'])

    def test_retries_set_explicit_state_without_toggling(self):
        self.save()
        self.save()
        self.assertEqual(1,AdminValidationReviewCheck.objects.count())
        self.assertTrue(AdminValidationReviewCheck.objects.get().checked)
        self.save(False)
        self.save(False)
        self.assertEqual(1,AdminValidationReviewCheck.objects.count())
        self.assertFalse(AdminValidationReviewCheck.objects.get().checked)

    def test_invalid_scope_or_state_never_writes(self):
        for changes in ({'kind':'other'},{'table':'unknown'},{'table':None},
                        {'retailer':None},{'retailer':'x'*201},{'checked':'false'},{'checked':1}):
            with self.assertRaises((ValueError,TypeError)):
                self.save(**changes)
        self.assertFalse(AdminValidationReviewCheck.objects.exists())

    def test_post_requires_admin_csrf_and_valid_date(self):
        data=dict(date='2026-11-06',type='null_check',table='tv_retail_com',retailer='Amazon',checked=True)
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(403,client.post('/check/',data,content_type='application/json').status_code)
        self.assertEqual(400,client.get('/check/').status_code)
        self.assertEqual(405,client.put('/check/',data,content_type='application/json').status_code)
        for authenticated in (False,True):
            request=RequestFactory().post('/check/',data,content_type='application/json')
            request.user=SimpleNamespace(is_authenticated=authenticated,is_staff=False,is_superuser=False)
            self.assertEqual(403,views.check(request).status_code)
        client.cookies['csrftoken']='a'*32
        for invalid in ([],{**data,'date':None},{**data,'date':'bad'},{**data,'checked':'yes'}):
            self.assertEqual(400,client.post('/check/',invalid,content_type='application/json',HTTP_X_CSRFTOKEN='a'*32).status_code)
        self.assertFalse(AdminValidationReviewCheck.objects.exists())
        with patch.object(checks.review,'_review_rows',side_effect=AssertionError('must not touch audit data')):
            response=client.post('/check/',data,content_type='application/json',HTTP_X_CSRFTOKEN='a'*32)
        self.assertEqual(200,response.status_code)
        self.assertTrue(response.json()['check']['checked'])
        self.assertIn('no-store',response['Cache-Control'])

    def test_status_poll_reads_persisted_check_without_loading_validation(self):
        client=Client()
        query=dict(date='2026-11-06',type='null_check',table='public.tv_retail_com',retailer='AMAZON')
        with patch.object(checks.review,'_review_rows',side_effect=AssertionError('no validation recalculation')):
            self.assertFalse(client.get('/check/',query).json()['check']['checked'])
            self.save()
            response=client.get('/check/',query)
            self.assertTrue(response.json()['check']['checked'])
            self.assertEqual('admin',response.json()['check']['actor'])
            self.assertIn('no-store',response['Cache-Control'])
            self.save(False)
            self.assertFalse(client.get('/check/',query).json()['check']['checked'])
        self.assertEqual(1,AdminValidationReviewCheck.objects.count())
        for authenticated in (False,True):
            request=RequestFactory().get('/check/',query)
            request.user=SimpleNamespace(is_authenticated=authenticated,is_staff=False,is_superuser=False)
            self.assertEqual(403,views.check(request).status_code)

    def test_summary_keeps_checked_retailer_and_original_totals(self):
        self.save()
        request=RequestFactory().get('/',dict(date='2026-11-06',type='null_check'))
        request.user=SimpleNamespace(is_authenticated=True,is_staff=False,is_superuser=True)
        summary=dict(success=True,items=[deepcopy(ITEM)],total=7,counts={'corrected':7})
        with patch.object(checks.review,'summary',return_value=summary):
            response=views.data(request)
        result=json.loads(response.content)
        self.assertEqual(7,result['total'])
        self.assertEqual({'corrected':7},result['counts'])
        self.assertEqual(1,len(result['items']))
        self.assertTrue(result['items'][0]['check']['checked'])


if __name__ == '__main__':
    failures=DiscoverRunner(verbosity=1).run_tests(['__main__'])
    sys.exit(bool(failures))
