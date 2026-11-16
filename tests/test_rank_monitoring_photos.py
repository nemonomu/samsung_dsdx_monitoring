"""Rank review photo API regression tests; isolated in-memory DB only."""
import io
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_rank_monitoring_backend as existing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.http import Http404
from django.test import TestCase, override_settings
from django.test.runner import DiscoverRunner
from PIL import Image

from apps.dx.dx_layer1.models import RetailRankReview, RetailRankReviewImage
from apps.dx.dx_layer1.rank_monitoring import api, photos


def image_bytes(fmt='PNG', color='red', size=(12, 8), animated=False):
    stream = io.BytesIO()
    first = Image.new('RGB', size, color)
    options = {}
    if animated:
        options = dict(save_all=True, append_images=[Image.new('RGB', size, 'blue')],
                       duration=100, loop=0)
    first.save(stream, format=fmt, **options)
    return stream.getvalue()


def upload(content=None, name='proof.png', mime='image/png'):
    return SimpleUploadedFile(name, image_bytes() if content is None else content,
                              content_type=mime)


class RankPhotoTests(TestCase):
    # Reuse fixtures, without inheriting or rediscovering the existing tests.
    setUp = existing.ApiTests.setUp
    get = existing.ApiTests.get
    post = existing.ApiTests.post

    def review_token(self, key='item:30'):
        code, data = self.get('detail', key=key)
        self.assertEqual(200, code)
        return data['review_token']

    def multipart(self, token, revision=0, refs=None, files=(), omit_refs=False, **changes):
        fields = dict(token=token, result='품절 확인', memo='상품 페이지 품절 확인',
                      revision=str(revision))
        if not omit_refs:
            fields['photo_refs'] = json.dumps([] if refs is None else refs)
        if files:
            fields['images'] = list(files)
        fields.update(changes)
        request = self.factory.post('/rank/api/review/', data=fields)
        request.user = self.user
        response = api.save_review(request)
        return response.status_code, json.loads(response.content)

    def image_response(self, photo_id):
        request = self.factory.get(f'/rank/api/review/images/{photo_id}/')
        request.user = self.user
        return api.review_image(request, photo_id)

    def first_photo(self, key='item:30'):
        token = self.review_token(key)
        code, data = self.multipart(token, refs=['new:0'], files=[upload()])
        self.assertEqual(200, code, data)
        return token, data['review']['photos'][0]

    def test_upload_retain_replace_remove_preserves_every_history_and_blob(self):
        token, original = self.first_photo()
        record = RetailRankReview.objects.get()
        first_event = deepcopy(record.history[0])
        self.assertEqual(image_bytes(), bytes(record.images.get().content))
        self.assertEqual('proof.png', original['name'])
        self.assertEqual(1, record.images.get().revision)
        self.assertEqual(200, self.multipart(token, 1, [original['id']], memo='메모 수정')[0])
        code, data = self.multipart(token, 2, ['new:0'], [upload(image_bytes(color='green'), 'replacement.png')])
        self.assertEqual(200, code, data)
        replacement = data['review']['photos'][0]
        self.assertNotEqual(original['id'], replacement['id'])
        self.assertEqual(200, self.multipart(token, 3, [])[0])
        record.refresh_from_db()
        self.assertEqual(4, record.revision)
        self.assertEqual(first_event, record.history[0])
        self.assertEqual([original], record.history[1]['photos'])
        self.assertEqual([replacement], record.history[2]['photos'])
        self.assertEqual([], record.history[3]['photos'])
        self.assertEqual(2, record.images.count())
        self.assertEqual(image_bytes(), self.image_response(original['id']).content)
        self.assertEqual(image_bytes(color='green'), self.image_response(replacement['id']).content)
        self.assertEqual([], self.get('detail', key='item:30')[1]['review']['photos'])

    def test_mixed_photo_order_is_preserved(self):
        token, original = self.first_photo()
        code, data = self.multipart(token, 1, ['new:1', original['id'], 'new:0'],
                                    [upload(name='first.png'), upload(name='second.png')])
        self.assertEqual(200, code, data)
        self.assertEqual(['second.png', 'proof.png', 'first.png'],
                         [p['name'] for p in data['review']['photos']])

    def test_legacy_json_edits_preserve_current_photos_and_legacy_history(self):
        token, original = self.first_photo()
        code, data = self.post(token, 1, memo='사진 유지하며 메모만 수정')
        self.assertEqual(200, code, data)
        self.assertEqual([original], data['review']['photos'])
        self.assertEqual(1, RetailRankReviewImage.objects.count())
        record = RetailRankReview.objects.get()
        record.history = [{'result': '품절 확인', 'memo': 'legacy', 'at': '2026-11-16', 'username': 'old'}]
        record.save(update_fields=['history'])
        self.assertEqual([], self.get('detail', key='item:30')[1]['review']['photos'])
        code, data = self.post(token, 2)
        self.assertEqual(200, code, data)
        self.assertEqual([], data['review']['photos'])
        self.assertNotIn('photos', data['review']['history'][0])

    def test_optional_photos_for_new_multipart_and_json_reviews(self):
        token = self.review_token()
        code, data = self.multipart(token)
        self.assertEqual(200, code, data)
        self.assertEqual([], data['review']['photos'])
        code, data = self.post(self.review_token('item:1'))
        self.assertEqual(200, code, data)
        self.assertEqual([], data['review']['photos'])
        self.assertEqual(0, RetailRankReviewImage.objects.count())

    def test_revision_conflicts_rollback_new_records_and_leave_old_photos_unchanged(self):
        token = self.review_token()
        self.assertEqual(409, self.multipart(token, 4, ['new:0'], [upload()])[0])
        self.assertEqual(0, RetailRankReview.objects.count())
        self.assertEqual(0, RetailRankReviewImage.objects.count())
        token, original = self.first_photo()
        before = deepcopy(RetailRankReview.objects.get().history)
        self.assertEqual(409, self.multipart(token, 0, ['new:0'], [upload()])[0])
        record = RetailRankReview.objects.get()
        self.assertEqual(1, record.revision)
        self.assertEqual(before, record.history)
        self.assertEqual([original], photos.current(record))
        self.assertEqual(1, RetailRankReviewImage.objects.count())

    def test_foreign_and_historical_photo_ids_cannot_be_attached(self):
        token, original = self.first_photo()
        foreign_token = self.review_token('item:1')
        self.assertEqual(400, self.multipart(foreign_token, refs=[original['id']])[0])
        self.assertEqual(1, RetailRankReview.objects.count())
        self.assertEqual(200, self.multipart(token, 1, [])[0])
        self.assertEqual(400, self.multipart(token, 2, [original['id']])[0])
        self.assertEqual(400, self.multipart(token, 2, [999999])[0])
        self.assertEqual(2, RetailRankReview.objects.get().revision)
        self.assertEqual(1, RetailRankReviewImage.objects.count())

    def test_malformed_duplicate_and_unreferenced_photo_refs_are_rejected(self):
        token = self.review_token()
        for refs in (None, {}, 'new:0', [True], [False], [1.0], [0], [-1], [[]], [{}],
                     ['1'], ['new:-1'], ['new:1'], ['new:00'], ['https://evil/image']):
            with self.subTest(refs=refs):
                response = self.multipart(token, photo_refs=json.dumps(refs))
                self.assertEqual(400, response[0], response)
        self.assertEqual(400, self.multipart(token, photo_refs='not json')[0])
        self.assertEqual(400, self.multipart(token, refs=['new:0', 'new:0'], files=[upload()])[0])
        self.assertEqual(400, self.multipart(token, refs=[], files=[upload()])[0])
        self.assertEqual(400, self.multipart(token, files=[upload()], omit_refs=True)[0])
        self.assertEqual(400, self.multipart(token, unexpected=upload())[0])
        token, original = self.first_photo()
        self.assertEqual(400, self.multipart(token, 1, [original['id'], original['id']])[0])
        self.assertEqual(1, RetailRankReview.objects.get().revision)

    def test_revision_types_are_rejected_without_writes(self):
        token = self.review_token()
        for value in ('true', '-1', '1.5', 'not-int', ''):
            with self.subTest(value=value):
                self.assertEqual(400, self.multipart(token, revision=value)[0])
        for value in (True, False, -1, 0.5, '0', None):
            with self.subTest(json_revision=value):
                self.assertEqual(400, self.post(token, revision=value)[0])
        self.assertFalse(RetailRankReview.objects.exists())

    def test_photo_count_limits_include_retained_and_new(self):
        token = self.review_token()
        self.assertEqual(400, self.multipart(token, refs=[f'new:{i}' for i in range(6)],
                                             files=[upload() for _ in range(6)])[0])
        code, data = self.multipart(token, refs=[f'new:{i}' for i in range(5)], files=[upload() for _ in range(5)])
        self.assertEqual(200, code, data)
        ids = [p['id'] for p in data['review']['photos']]
        self.assertEqual(400, self.multipart(token, 1, ids+['new:0'], [upload()])[0])
        self.assertEqual(5, RetailRankReviewImage.objects.count())

    def test_per_photo_and_total_bytes_are_bounded(self):
        token = self.review_token()
        raw = image_bytes()
        with patch.object(photos, 'MAX_IMAGE', len(raw)-1):
            self.assertEqual(400, self.multipart(token, refs=['new:0'], files=[upload(raw)])[0])
        with patch.object(photos, 'MAX_TOTAL', len(raw)*2-1):
            self.assertEqual(400, self.multipart(token, refs=['new:0', 'new:1'], files=[upload(raw), upload(raw)])[0])
        token, original = self.first_photo()
        with patch.object(photos, 'MAX_TOTAL', len(raw)*2-1):
            self.assertEqual(400, self.multipart(token, 1, [original['id'], 'new:0'], [upload(raw)])[0])
        self.assertEqual(1, RetailRankReviewImage.objects.count())
        # Never trust the advertised size when reading an uploaded stream.
        deceptive = upload(raw)
        deceptive.size = 1
        with patch.object(photos, 'MAX_IMAGE', len(raw)-1):
            with self.assertRaises(photos.PhotoError):
                photos.read_uploads([deceptive])

    def test_corrupt_animated_and_untrusted_formats_rejected(self):
        token = self.review_token()
        invalid = [b'<script>alert(1)</script>', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                   image_bytes()[:40], image_bytes('GIF'), image_bytes('BMP'), image_bytes(animated=True)]
        for raw in invalid:
            with self.subTest(length=len(raw)):
                self.assertEqual(400, self.multipart(token, refs=['new:0'], files=[upload(raw)])[0])
        self.assertFalse(RetailRankReview.objects.exists())
        self.assertFalse(RetailRankReviewImage.objects.exists())

    def test_image_mime_is_derived_from_decoded_content(self):
        token = self.review_token()
        for revision, fmt in enumerate(('PNG', 'JPEG', 'WEBP')):
            code, data = self.multipart(token, revision, ['new:0'],
                                        [upload(image_bytes(fmt), name='untrusted.html', mime='text/html')])
            self.assertEqual(200, code, data)
            response = self.image_response(data['review']['photos'][0]['id'])
            self.assertEqual(photos.TYPES[fmt], response['Content-Type'])

    def test_pixel_bombs_rejected(self):
        token = self.review_token()
        with patch.object(Image, 'MAX_IMAGE_PIXELS', 50):
            self.assertEqual(400, self.multipart(token, refs=['new:0'], files=[upload()])[0])
        stream = io.BytesIO()
        Image.new('L', (5001, 4000)).save(stream, 'PNG')
        self.assertEqual(400, self.multipart(token, refs=['new:0'], files=[upload(stream.getvalue())])[0])
        self.assertFalse(RetailRankReviewImage.objects.exists())

    def test_authenticated_environment_scoped_image_get_and_private_headers(self):
        token, original = self.first_photo()
        response = self.image_response(original['id'])
        self.assertEqual(200, response.status_code)
        self.assertEqual('private, no-store', response['Cache-Control'])
        self.assertEqual('nosniff', response['X-Content-Type-Options'])
        self.assertIn('sandbox', response['Content-Security-Policy'])
        with override_settings(DEBUG=True):
            with self.assertRaises(Http404):
                self.image_response(original['id'])
        with self.assertRaises(Http404):
            self.image_response(999999)
        self.user.is_authenticated = False
        self.assertEqual(401, self.image_response(original['id']).status_code)
        self.assertEqual(401, self.multipart(token, 1, [original['id']])[0])

    def test_listing_contains_only_review_summary_not_photos_or_history(self):
        _, original = self.first_photo()
        code, payload = self.get()
        self.assertEqual(200, code)
        row = next(p for p in payload['products'] if p['key'] == 'item:30')
        self.assertEqual({'result': '품절 확인'}, row['review'])
        self.assertNotIn(original['url'], json.dumps(payload))
        self.assertNotIn('photos', json.dumps(payload))
        self.assertNotIn('history', json.dumps(payload))

    def test_image_insert_failure_rolls_back_revision_history_and_partial_insert(self):
        token, original = self.first_photo()
        before = deepcopy(RetailRankReview.objects.get().history)
        real_create = RetailRankReviewImage.objects.create
        calls = []

        def failing_create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise DatabaseError('simulated evidence storage failure')
            return real_create(**kwargs)

        with patch.object(RetailRankReviewImage.objects, 'create', side_effect=failing_create):
            code, data = self.multipart(token, 1, ['new:0', 'new:1'], [upload(), upload()])
        self.assertEqual(503, code, data)
        self.assertEqual(2, len(calls))
        record = RetailRankReview.objects.get()
        self.assertEqual(1, record.revision)
        self.assertEqual(before, record.history)
        self.assertEqual([original], photos.current(record))
        self.assertEqual(1, RetailRankReviewImage.objects.count())
        with patch.object(RetailRankReviewImage.objects, 'create', side_effect=DatabaseError('unavailable')):
            self.assertEqual(503, self.multipart(self.review_token('item:1'), refs=['new:0'], files=[upload()])[0])
        self.assertEqual(1, RetailRankReview.objects.count())


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=2).run_tests(['__main__.RankPhotoTests'])))
