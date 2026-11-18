"""python tests/test_session_expiry.py -- isolated in-memory session DB."""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY='session-test-only',
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        MIDDLEWARE=['apps.accounts.sessions.SessionExpiryMiddleware',
                    'django.contrib.auth.middleware.AuthenticationMiddleware',
                    'apps.accounts.middleware.LoginRequiredMiddleware'],
        ROOT_URLCONF=__name__, ALLOWED_HOSTS=['testserver'], USE_TZ=True,
        SESSION_COOKIE_AGE=24 * 60 * 60, SESSION_SAVE_EVERY_REQUEST=True,
        SESSION_EXPIRE_AT_BROWSER_CLOSE=False,
        PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    )

import django
django.setup()
from django.contrib.auth import get_user_model, logout
from django.contrib.sessions.models import Session
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.test.runner import DiscoverRunner
from django.urls import include, path
from django.utils import timezone
from apps.accounts.sessions import session_status


def page(request):
    return HttpResponse('ok')


def logout_page(request):
    logout(request)
    return HttpResponse('logged out')


urlpatterns = [
    path('accounts/', include(([
        path('login/', page, name='login'),
        path('logout/', logout_page, name='logout'),
        path('session-status/', session_status, name='session_status'),
    ], 'accounts'))),
    path('', page),
    path('failure/', lambda request: HttpResponse(status=500)),
]


class SessionExpiryTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('tester', is_staff=True))
        self.key = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def expiry(self):
        return Session.objects.get(session_key=self.key).expire_date

    def test_normal_request_extends_old_session_to_24_hours(self):
        Session.objects.filter(session_key=self.key).update(expire_date=timezone.now() + timedelta(minutes=20))
        before = timezone.now()
        response = self.client.get('/')
        after = timezone.now()
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(self.expiry(), before + timedelta(hours=24))
        self.assertLessEqual(self.expiry(), after + timedelta(hours=24))
        self.assertEqual(response.cookies['sessionid']['max-age'], 86400)
        self.assertTrue(response.cookies['sessionid']['httponly'])
        self.assertEqual(int(response.cookies['sessionid_expires'].value), int(self.expiry().timestamp() * 1000))
        self.assertFalse(response.cookies['sessionid_expires']['httponly'])

    def test_status_returns_saved_deadline_without_extending_or_setting_cookies(self):
        before = self.expiry()
        for _ in range(2):
            response = self.client.get('/accounts/session-status/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['expiresAt'], int(before.timestamp() * 1000))
            self.assertLess(abs(response.json()['serverTime'] - timezone.now().timestamp() * 1000), 1000)
            self.assertEqual(self.expiry(), before)
            self.assertFalse(response.cookies)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertIn('Cookie', response['Vary'])

    def test_expired_status_is_401_and_cannot_revive_session(self):
        expired_at = timezone.now() - timedelta(seconds=1)
        Session.objects.filter(session_key=self.key).update(expire_date=expired_at)
        response = self.client.get('/accounts/session-status/')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['authenticated'])
        self.assertEqual(self.expiry(), expired_at)
        self.assertFalse(response.cookies)

    def test_status_post_does_not_extend(self):
        before = self.expiry()
        self.assertEqual(self.client.post('/accounts/session-status/').status_code, 405)
        self.assertEqual(self.expiry(), before)

    def test_server_error_does_not_extend(self):
        before = self.expiry()
        response = self.client.get('/failure/')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.expiry(), before)
        self.assertNotIn('sessionid_expires', response.cookies)

    def test_logout_deletes_both_cookies_and_status_is_401(self):
        self.client.get('/')
        response = self.client.get('/accounts/logout/')
        self.assertEqual(response.cookies['sessionid']['max-age'], 0)
        self.assertEqual(response.cookies['sessionid_expires']['max-age'], 0)
        self.assertEqual(self.client.get('/accounts/session-status/').status_code, 401)

    @override_settings(SESSION_COOKIE_NAME='customsession', SESSION_COOKIE_SECURE=True,
                       SESSION_COOKIE_PATH='/accounts/', SESSION_COOKIE_SAMESITE='Strict')
    def test_metadata_matches_cookie_scope_and_custom_name(self):
        self.client.force_login(get_user_model().objects.get(username='tester'))
        response = self.client.get('/accounts/login/')
        cookie = response.cookies['customsession_expires']
        self.assertTrue(cookie['secure'])
        self.assertEqual(cookie['path'], '/accounts/')
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(self.client.get('/accounts/session-status/').json()['expiryCookie'], 'customsession_expires')


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests([__name__])))
