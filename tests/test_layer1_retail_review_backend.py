"""python tests/test_layer1_retail_review_backend.py (isolated SQLite only)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(
        INSTALLED_APPS=['apps.dx.dx_layer1'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True, TIME_ZONE='Asia/Seoul', SECRET_KEY='isolated-review-tests',
    )
import django
django.setup()
from django.test import TestCase, RequestFactory
from django.test.runner import DiscoverRunner
from apps.dx.dx_layer1.common.retail_review_api import reviews
from apps.dx.dx_layer1.models import RetailNormalReview


def sample():
    return dict(version=1, date='2026-09-30', source_date='2026-09-30', country='TSE',
                product='LDY', slot='daily', retailer='Homepro', batch_id='h20260930_090003',
                status='VOLUME_REVIEW', counts=[264, 100, 264, 1],
                reasons=['MAIN 과거 중앙값 300개 / 수집 264개 / 5~15% 감소 / 확인 필요'],
                basis='{"baseline":300}')


class ReviewTests(TestCase):
    def request(self, action=None, context=None, revision=0, memo='원본 사이트와 일치', user='reviewer', **extra):
        factory = RequestFactory()
        request = factory.post('/reviews/', data=json.dumps({
            'action': action, 'context': context or sample(), 'revision': revision, 'memo': memo, **extra,
        }), content_type='application/json') if action else factory.get('/reviews/', {'date': '2026-09-30'})
        request.user = SimpleNamespace(is_authenticated=bool(user), get_username=lambda: user)
        response = reviews(request)
        return response.status_code, json.loads(response.content)

    def test_save_reload_cancel_and_reconfirm_preserve_history(self):
        code, payload = self.request('confirm', username='spoofed')
        self.assertEqual(200, code)
        record = payload['review']
        self.assertTrue(record['active'])
        self.assertEqual('reviewer', record['history'][0]['username'])
        self.assertEqual(record, self.request()[1]['reviews'][0])
        code, payload = self.request('cancel', revision=1, memo='다시 검토')
        self.assertEqual(200, code)
        self.assertFalse(payload['review']['active'])
        self.assertEqual(['confirm', 'cancel'], [r['action'] for r in payload['review']['history']])
        code, payload = self.request('confirm', revision=2)
        self.assertEqual(200, code)
        self.assertTrue(payload['review']['active'])
        self.assertEqual(3, payload['review']['revision'])

    def test_changes_are_separate_decisions(self):
        self.request('confirm')
        for field, value in [('date', '2026-10-01'), ('batch_id', 'new-batch'), ('country', 'SEM'),
                             ('counts', [263, 100, 263, 1]), ('reasons', ['새 사유']),
                             ('basis', '{"baseline":301}'), ('slot', '오후')]:
            context = sample()
            context[field] = value
            self.assertEqual(200, self.request('confirm', context=context)[0], field)
        self.assertEqual(8, RetailNormalReview.objects.count())
        self.assertEqual(7, len(self.request()[1]['reviews']))

    def test_stale_revision_cannot_overwrite_other_reviewer(self):
        self.request('confirm')
        self.assertEqual(409, self.request('cancel', revision=0)[0])
        self.assertEqual(409, self.request('confirm', revision=0)[0])
        self.assertTrue(RetailNormalReview.objects.get().active)
        self.assertEqual(1, len(RetailNormalReview.objects.get().history))

    def test_reject_bad_inputs_and_unauthenticated_requests(self):
        self.assertEqual(401, self.request('confirm', user='')[0])
        self.assertEqual(401, self.request(user='')[0])
        for field, value in [('status', 'OK'), ('status', 'COLLECTING'), ('status', 'UNASSESSED'),
                             ('status', 'VERIFYING'), ('status', 'CRITICAL'), ('date', 'invalid'), ('batch_id', ''),
                             ('counts', [-1, 100, 264, 1]), ('counts', [True, 100, 264, 1]),
                             ('reasons', []), ('basis', '[]'), ('country', 'INVALID')]:
            context = sample()
            context[field] = value
            self.assertEqual(400, self.request('confirm', context=context)[0], field)
        self.assertEqual(400, self.request('confirm', memo=' ')[0])
        self.assertEqual(400, self.request('confirm', memo='x' * 1001)[0])
        self.assertEqual(400, self.request('cancel')[0])
        self.assertEqual(0, RetailNormalReview.objects.count())


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests(['__main__'])))
