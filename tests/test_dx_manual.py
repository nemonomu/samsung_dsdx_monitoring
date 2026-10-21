"""Isolated manual tests: python tests/test_dx_manual.py (no production DB access)."""
import copy
import io
import json
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY='manual-isolated-test',
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes',
                        'django.contrib.sessions', 'django.contrib.staticfiles', 'apps.dx.dx_document'],
        DATABASES={
            'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
            'dx': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
        },
        ROOT_URLCONF=__name__, USE_TZ=True, STATIC_URL='/static/',
        LOGIN_URL='/login/', ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
        MIDDLEWARE=['django.contrib.sessions.middleware.SessionMiddleware',
                    'django.middleware.csrf.CsrfViewMiddleware',
                    'django.contrib.auth.middleware.AuthenticationMiddleware'],
        TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                    'APP_DIRS': True, 'DIRS': [str(Path(__file__).resolve().parents[1] / 'templates')],
                    'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                                                       'django.contrib.auth.context_processors.auth']}}],
        PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    )

import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.test.runner import DiscoverRunner
from django.urls import path
from PIL import Image
from apps.dx.dx_document import manual
from apps.dx.dx_document.models import ManualRevision, ManualImage, PostgresManualRevision, PostgresManualImage
from apps.dx.dx_document import manual_storage as storage
from django.db import connections
from django.core.management import call_command
from django.core.management.base import CommandError


class ManualTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        result = super().setup_databases(**kwargs)
        # Unmanaged production tables are created only in the isolated test DX DB.
        with connections['dx'].schema_editor() as editor:
            editor.create_model(PostgresManualRevision)
            editor.create_model(PostgresManualImage)
        return result

urlpatterns = [
    path('dx/documents/manual/content/', manual.content),
    path('dx/documents/manual/save/', manual.save),
    path('dx/documents/manual/history/', manual.history),
    path('dx/documents/manual/upload/', manual.upload),
    path('dx/documents/manual/images/<str:digest>/', manual.image),
]
PREFIX = '/dx/documents/manual/'


class ManualTests(TestCase):
    databases = {'default', 'dx'}
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='editor', is_staff=True)
        self.client.force_login(self.user)
        self.data = copy.deepcopy(manual.seed_data())

    def save(self, version=0, data=None, client=None):
        return (client or self.client).post(PREFIX + 'save/', json.dumps({
            'version': version, 'data': data if data is not None else self.data,
        }, ensure_ascii=False), content_type='application/json')

    def test_original_data_and_images_are_preserved(self):
        self.assertEqual(24, len(self.data['datasets']))
        self.assertEqual(70, len(self.data['photos']))
        self.assertEqual(self.data, manual.validate_data(self.data))
        for uri in set(self.data['assets'].values()):
            response = self.client.get(uri)
            self.assertEqual(200, response.status_code)
            self.assertTrue(response['Content-Type'].startswith('image/'))
            response.close()

    def test_save_reload_audit_and_restore(self):
        self.data['datasets'][0]['fields'][0]['note'] = '수정한 설명'
        first = self.save()
        self.assertEqual(200, first.status_code, first.content)
        self.assertEqual(1, first.json()['version'])
        self.data['datasets'][0]['fields'][0]['note'] = '다음 설명'
        self.assertEqual(200, self.save(1).status_code)
        old = self.client.get(PREFIX + 'history/?version=1').json()['data']
        self.assertEqual('수정한 설명', old['datasets'][0]['fields'][0]['note'])
        self.assertEqual(200, self.save(2, old).status_code)
        current = self.client.get(PREFIX + 'content/')
        self.assertIn(json.dumps('수정한 설명'), current.content.decode())
        history = self.client.get(PREFIX + 'history/').json()['revisions']
        self.assertEqual([3, 2, 1, 0], [r['version'] for r in history])
        self.assertEqual('editor', history[0]['created_by'])

    def test_stale_save_does_not_overwrite(self):
        self.assertEqual(200, self.save().status_code)
        self.data['datasets'][0]['fields'][0]['note'] = 'stale overwrite'
        self.assertEqual(409, self.save().status_code)
        self.assertEqual(1, storage.revisions().count())
        self.assertEqual(0, ManualRevision.objects.using('default').count())
        self.assertNotEqual('stale overwrite', storage.revisions().first().data['datasets'][0]['fields'][0]['note'])

    def test_content_requires_login_and_dx_access(self):
        anonymous = Client()
        self.assertEqual(302, anonymous.get(PREFIX + 'content/').status_code)
        no_access = get_user_model().objects.create_user(username='ds-only')
        anonymous.force_login(no_access)
        for endpoint in ('content/', 'history/'):
            self.assertEqual(403, anonymous.get(PREFIX + endpoint).status_code)
        self.assertEqual(403, self.save(client=anonymous).status_code)
        self.assertEqual(403, anonymous.get(next(iter(self.data['assets'].values()))).status_code)

    def test_csrf_required_and_available_in_editor(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(403, self.save(client=client).status_code)
        response = client.get(PREFIX + 'content/')
        self.assertEqual('SAMEORIGIN', response['X-Frame-Options'])
        self.assertIn('no-store', response['Cache-Control'])
        token = client.cookies['csrftoken'].value
        response = client.post(PREFIX + 'save/', json.dumps({'version': 0, 'data': self.data}),
                               content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(200, response.status_code, response.content)

    def test_invalid_edits_and_executable_urls_rejected(self):
        bad = copy.deepcopy(self.data)
        bad['datasets'][0]['fields'][0]['n'] = '<img src=x onerror=alert(1)>'
        self.assertEqual(400, self.save(data=bad).status_code)
        bad = copy.deepcopy(self.data)
        bad['photos'][0]['url'] = 'javascript:alert(1)'
        self.assertEqual(400, self.save(data=bad).status_code)
        bad['photos'][0]['url'] = ''
        bad['photos'][0]['width'] = '<script>'
        self.assertEqual(400, self.save(data=bad).status_code)
        self.assertEqual(0, storage.revisions().count())

    def test_text_is_embedded_as_safe_json(self):
        self.data['datasets'][0]['fields'][0]['note'] = '</script><script>alert(1)</script>'
        self.assertEqual(200, self.save().status_code)
        response = self.client.get(PREFIX + 'content/')
        self.assertNotContains(response, '</script><script>alert(1)</script>')
        self.assertContains(response, '\\u003C/script\\u003E')

    def test_image_upload_is_validated_and_persists(self):
        rejected = self.client.post(PREFIX + 'upload/', {'image': SimpleUploadedFile('fake.png', b'<script>evil</script>', content_type='image/png')})
        self.assertEqual(400, rejected.status_code)
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), '#123456').save(buffer, format='PNG')
        uploaded = self.client.post(PREFIX + 'upload/', {'image': SimpleUploadedFile('new.png', buffer.getvalue(), content_type='image/png')})
        self.assertEqual(200, uploaded.status_code)
        uri = uploaded.json()['url']
        self.data['photos'][0]['customImage'] = uri
        self.assertEqual(200, self.save().status_code)
        response = self.client.get(uri)
        self.assertEqual(buffer.getvalue(), response.content)
        self.assertEqual('image/png', response['Content-Type'])

    def test_category_matching_is_limited_to_dx_manual(self):
        self.assertTrue(manual.is_manual_category({'category_name': 'DX 검수 매뉴얼'}))
        self.assertTrue(manual.is_manual_category({'category_name': 'DX 검수 메뉴얼'}))
        self.assertFalse(manual.is_manual_category({'category_name': '검수 보고서'}))

    def test_legacy_import_dry_run_apply_and_repeat(self):
        legacy = ManualRevision.objects.using('default').create(version=1, data=self.data, created_by='legacy')
        ManualImage.objects.using('default').create(digest='a' * 64, content=b'legacy-image', content_type='image/png', created_by='legacy')
        call_command('migrate_dx_manual_to_postgres', stdout=io.StringIO())
        self.assertFalse(storage.revisions().exists())
        self.assertFalse(storage.images().exists())
        for _ in range(2):
            call_command('migrate_dx_manual_to_postgres', apply=True, stdout=io.StringIO())
        self.assertEqual(1, storage.revisions().count())
        self.assertEqual(legacy.created_at, storage.revisions().first().created_at)
        self.assertEqual(self.data, storage.revisions().first().data)
        self.assertEqual(b'legacy-image', bytes(storage.images().first().content))
        self.assertEqual(1, ManualRevision.objects.using('default').count())
        self.assertEqual(200, self.save(1).status_code)

    def test_import_conflict_rolls_back_and_preserves_both_histories(self):
        ManualRevision.objects.using('default').create(version=1, data=self.data, created_by='legacy')
        ManualImage.objects.using('default').create(digest='b' * 64, content=b'legacy', content_type='image/png', created_by='legacy')
        self.assertEqual(200, self.save().status_code)
        with self.assertRaises(CommandError):
            call_command('migrate_dx_manual_to_postgres', apply=True, stdout=io.StringIO())
        self.assertEqual('editor', storage.revisions().first().created_by)
        self.assertFalse(storage.images().exists())
        self.assertEqual(1, ManualImage.objects.using('default').count())

    def test_deployment_creates_manual_storage_before_web_restart(self):
        from scripts.deploy_monitoring import deploy
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').touch()
            (root / 'manage.py').touch()
            calls = []

            def fake_run(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout='not-found\n')

            deploy(root, 'preview', 'preview', run=fake_run)
            migration = next(i for i, args in enumerate(calls) if args[-3:] == ['migrate', 'dx_document', '--noinput'])
            static = next(i for i, args in enumerate(calls) if 'collectstatic' in args)
            transfer = next(i for i, args in enumerate(calls) if args[-2:] == ['migrate_dx_manual_to_postgres', '--apply'])
            stop = next(i for i, args in enumerate(calls) if args[-2:] == ['stop', 'gunicorn'])
            restart = next(i for i, args in enumerate(calls) if args[-2:] == ['restart', 'gunicorn'])
            self.assertLess(migration, static)
            self.assertLess(migration, transfer)
            self.assertLess(stop, transfer)
            self.assertLess(transfer, restart)
            self.assertLess(migration, restart)


if __name__ == '__main__':
    sys.exit(bool(ManualTestRunner(verbosity=2).run_tests(['__main__'])))
