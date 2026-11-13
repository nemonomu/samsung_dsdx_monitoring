"""Image-backed column reviews in isolated SQLite databases; no source DB writes."""
import copy
import io
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_dx_manual as config
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import path
from django.core.management import call_command
from PIL import Image
from apps.dx.dx_layer1.column_statistics import reviews as api
from apps.dx.dx_layer1.models import ColumnNormalReview, ColumnReviewImage

PREFIX = '/dx/layer1/api/column-review/'
urlpatterns = [path(PREFIX.lstrip('/'), api.review),
               path((PREFIX+'images/<int:image_id>/').lstrip('/'), api.image)]
TARGET = dict(country='SEA', product='TV', retailer='Amazon', column='offer',
              source_date='2026-10-14', inspection_date='2026-10-15')
CONTEXT = dict(environment='production', country='SEA', product='TV', retailer='Amazon',
               source_date='2026-10-14', column='offer', current=20, baseline=100,
               status='abnormal', total=300, raw_total=300)
ROW = dict(column='offer', current=20, baseline=100, history_days=28, ratio=20, delta=-80, status='abnormal')


def image_file():
    buffer = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(buffer, format='PNG')
    return SimpleUploadedFile('clipboard.png', buffer.getvalue(), content_type='image/png')


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
class ColumnReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='reviewer', is_staff=True)
        self.client.force_login(self.user)
        self.context, self.row = copy.deepcopy(CONTEXT), copy.deepcopy(ROW)
        self.inspector = patch.object(api, 'inspect', side_effect=lambda target:(copy.deepcopy(self.context), copy.deepcopy(self.row)))
        self.inspector.start()
        self.addCleanup(self.inspector.stop)

    def get_review(self):
        response = self.client.get(PREFIX, TARGET)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def save(self, token=None, action='confirm', memo='', files=True):
        payload = dict(TARGET, token=token or self.get_review()['token'], action=action, memo=memo)
        if files:
            payload['images'] = [image_file()]
        return self.client.post(PREFIX, payload)

    def test_confirm_reload_image_cancel_and_history(self):
        response = self.save(memo='쇼핑몰에서도 해당 항목이 없는 것을 확인')
        self.assertEqual(response.status_code, 200, response.content)
        review = self.get_review()['review']
        self.assertTrue(review['active'])
        self.assertEqual(review['history'][0]['username'], 'reviewer')
        url = review['history'][0]['images'][0]['url']
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url)['Content-Type'], 'image/png')
        self.assertIn('no-store', self.client.get(url)['Cache-Control'])
        response = self.save(action='cancel', memo='재검수 필요', files=False)
        self.assertEqual(response.status_code, 200)
        review = self.get_review()['review']
        self.assertFalse(review['active'])
        self.assertEqual(len(review['history']), 2)
        self.assertEqual(ColumnReviewImage.objects.count(), 1)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.row, ROW, 'manual confirmation does not overwrite automatic counts')

    def test_image_required_and_invalid_file_rejected_without_partial_save(self):
        self.assertEqual(self.save(files=False).status_code, 400)
        payload = dict(TARGET, token=self.get_review()['token'], action='confirm', memo='',
                       images=[SimpleUploadedFile('fake.png', b'<script>bad</script>', content_type='image/png')])
        self.assertEqual(self.client.post(PREFIX, payload).status_code, 400)
        self.assertEqual(ColumnNormalReview.objects.count(), 0)
        self.assertEqual(ColumnReviewImage.objects.count(), 0)

    def test_changed_counts_and_stale_revision_rejected(self):
        token = self.get_review()['token']
        self.context['current'] = 21
        self.assertEqual(self.save(token=token).status_code, 409)
        self.context['current'] = 20
        self.assertEqual(self.save(token=token).status_code, 200)
        self.assertEqual(self.save(token=token).status_code, 409)
        self.assertEqual(ColumnReviewImage.objects.count(), 1)

    def test_storage_failure_rolls_back_decision_and_all_images(self):
        with patch.object(ColumnReviewImage.objects, 'create', side_effect=RuntimeError('test write failure')):
            self.assertEqual(self.save().status_code, 503)
        self.assertEqual(ColumnNormalReview.objects.count(), 0)
        self.assertEqual(ColumnReviewImage.objects.count(), 0)

    def test_scope_isolation_and_historical_evidence_after_counts_change(self):
        self.assertEqual(self.save().status_code, 200)
        self.context['current'] = 25
        result = self.get_review()
        self.assertFalse(result['review']['active'])
        self.assertEqual(len(result['previous']), 1)
        for key, value in [('product','REF'), ('country','SEG'), ('retailer','Walmart'),
                           ('column','sku'), ('source_date','2026-10-13')]:
            with self.subTest(key=key):
                self.context = {**CONTEXT, key:value}
                self.assertEqual(self.get_review()['previous'], [])

    def test_auth_csrf_and_environment_image_isolation(self):
        self.assertEqual(self.save().status_code, 200)
        url = self.get_review()['review']['history'][0]['images'][0]['url']
        with override_settings(DEBUG=True):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        non_dx = get_user_model().objects.create_user(username='no-dx')
        self.client.force_login(non_dx)
        self.assertEqual(self.client.get(url).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(PREFIX, TARGET).status_code, 403)

    def test_image_limits_and_unsupported_format(self):
        with self.assertRaises(ValueError):
            api.read_images([image_file() for _ in range(6)])
        with self.assertRaises(ValueError):
            api.read_images([SimpleUploadedFile('large.png', b'x'*(api.MAX_IMAGE+1))])
        buf=io.BytesIO()
        Image.new('RGB',(10,10)).save(buf,format='GIF')
        with self.assertRaises(ValueError):
            api.read_images([SimpleUploadedFile('capture.gif',buf.getvalue())])

    def test_uncollected_and_pending_cannot_be_confirmed(self):
        for status in ('pending','uncollected','normal','no_scoped_rows'):
            self.row['status'] = self.context['status'] = status
            self.assertEqual(self.save().status_code, 400)

    def test_overlay_keeps_auto_verdict_and_ignores_changed_result(self):
        self.save()
        data = dict(country='SEA', product='TV', retailer='Amazon', inspection_date='2026-10-15',
                    comparison_date='2026-10-14', daily=[dict(date='2026-10-14',total=300,raw_total=300)],
                    comparisons=[copy.deepcopy(ROW)])
        api.attach_reviews(data)
        self.assertTrue(data['comparisons'][0]['review']['active'])
        self.assertEqual(data['comparisons'][0]['status'],'abnormal')
        data['comparisons'][0]['current'] = 21
        api.attach_reviews(data)
        self.assertIsNone(data['comparisons'][0]['review'])
        self.assertTrue(data['comparisons'][0]['review_history'])

    def test_inspect_uses_existing_country_date_policy(self):
        self.inspector.stop()
        day = date(2026,10,14)
        for country, retailer, inspection in [('SEA','Amazon','2026-10-15'), ('SIEL','Amazon','2026-10-14')]:
            data = dict(country=country, product='TV', retailer=retailer, columns=['offer'],
                daily=[dict(date=str(day-timedelta(days=i)),total=300,counts={'offer':100 if i else 20}) for i in range(29)])
            with patch.object(api,'daily_counts',return_value=data), patch.object(api,'raw_counts',return_value={str(day):300}), \
                 patch('apps.dx.dx_layer1.column_statistics.comparison.collection_complete',return_value=True):
                context, row = api.inspect(dict(TARGET,country=country,retailer=retailer,inspection_date=inspection))
                self.assertEqual(context['source_date'],str(day))
                self.assertEqual(row['current'],20)
                with self.assertRaises(ValueError):
                    api.inspect(dict(TARGET,country=country,retailer=retailer,inspection_date=inspection,source_date='2026-10-13'))
        self.inspector.start()

    def test_model_migration_matches(self):
        call_command('makemigrations','dx_layer1',check=True,dry_run=True,verbosity=0)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests([__name__])))
