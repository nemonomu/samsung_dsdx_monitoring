"""Shared aggregate cache: coalescing, expiry and write/read races (no DB)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.http import JsonResponse
from django.test import RequestFactory, override_settings
from apps.common import monitoring_cache as cache


class MonitoringCacheTests(unittest.TestCase):
    def setUp(self):
        from django.conf import settings
        _ = settings.DEFAULT_CHARSET
        self.directory = tempfile.TemporaryDirectory()
        self.settings = override_settings(MONITORING_CACHE_DIR=self.directory.name,
                                          MONITORING_CACHE_ENABLED=True, DEBUG=False)
        self.settings.enable()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.settings.disable)
        self.addCleanup(cache._backend.cache_clear)
        self.factory = RequestFactory()

    def request(self, query='date=2026-11-06&section=null_validation', user='a'):
        request = self.factory.get('/dx/layer2/api/stats/?' + query)
        request.user = SimpleNamespace(is_authenticated=True, username=user)
        return request

    def test_identical_requests_share_result_across_users_and_backends(self):
        calls = []
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            return JsonResponse({'count': len(calls)})
        first = view(self.request())
        cache._backend.cache_clear()  # A new worker/backend reads the same files.
        self.assertEqual(first.content, view(self.request(user='b')).content)
        view(self.request('date=2026-11-05'))
        with override_settings(DEBUG=True):
            view(self.request())
        self.assertEqual(len(calls), 3)

    def test_concurrent_requests_compute_only_once(self):
        calls = []
        barrier = threading.Barrier(5)
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            time.sleep(.05)
            return JsonResponse({'count': len(calls)})
        def get(_):
            barrier.wait(timeout=3)
            return view(self.request()).content
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(get, range(5)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(set(results)), 1)

    def test_separate_worker_processes_share_lock_and_result(self):
        script = '''
import sys, time
from pathlib import Path
from types import SimpleNamespace
from django.conf import settings
settings.configure(BASE_DIR=Path.cwd(), DEBUG=False, DEFAULT_CHARSET='utf-8',
                   MONITORING_CACHE_DIR=sys.argv[1])
from django.http import JsonResponse
from django.test import RequestFactory
from apps.common.monitoring_cache import cached_monitoring_stats
@cached_monitoring_stats
def view(request):
    with (Path(sys.argv[1]) / 'computations').open('a') as log:
        log.write('computed\\n')
    time.sleep(.1)
    return JsonResponse({'count': 9})
request = RequestFactory().get('/dx/layer2/api/stats/?date=2026-11-06')
request.user = SimpleNamespace(is_authenticated=True)
assert view(request).status_code == 200
'''
        processes = [subprocess.Popen([sys.executable, '-c', script, self.directory.name],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(3)]
        for process in processes:
            _, error = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, error.decode(errors='replace'))
        from pathlib import Path
        self.assertEqual((Path(self.directory.name) / 'computations').read_text().splitlines(), ['computed'])

    def test_expiry_force_and_mutation_invalidation(self):
        calls = []
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            return JsonResponse({'count': len(calls)})
        now = time.time()
        with patch('time.time', return_value=now):
            view(self.request())
        with patch('time.time', return_value=now + 61):
            view(self.request())
        with patch('time.time', return_value=now + 62):
            view(self.request('date=2026-11-06&section=null_validation&refresh=1'))
        middleware = cache.MonitoringCacheInvalidationMiddleware(lambda request: JsonResponse({'ok': True}))
        middleware(self.factory.post('/dx/layer3/api/save/'))
        view(self.request())
        self.assertEqual(len(calls), 4)

    def test_completion_check_keeps_snapshot_but_real_edits_still_invalidate(self):
        key = ['2026-11-09', 'null_check', '', None, None, None]
        cache.monitoring_cached_value('admin-review-v1', key, lambda: [1, 2, 3])
        middleware = cache.MonitoringCacheInvalidationMiddleware(lambda request: JsonResponse({'ok': True}))
        for path in ('/dx/layer2/api/admin-review/check/', '/layer2/api/admin-review/check/'):
            middleware(self.factory.post(path))
            self.assertEqual([1, 2, 3], cache.monitoring_cached_value('admin-review-v1', key))
        middleware(self.factory.post('/dx/layer2/api/update-cell/'))
        self.assertIsNone(cache.monitoring_cached_value('admin-review-v1', key))

    def test_inflight_read_cannot_repopulate_cache_after_write(self):
        calls = []
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            if len(calls) == 1:
                cache.invalidate_monitoring_cache()
            return JsonResponse({'count': len(calls)})
        view(self.request())
        view(self.request())
        view(self.request())
        self.assertEqual(len(calls), 2)

    def test_partial_errors_and_anonymous_requests_are_not_cached(self):
        calls = []
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            return JsonResponse({'checks': [{'status': 'ERROR'}]})
        view(self.request())
        view(self.request())
        request = self.request()
        request.user.is_authenticated = False
        view(request)
        self.assertEqual(len(calls), 3)

    def test_view_exception_is_not_retried(self):
        calls = []
        @cache.cached_monitoring_stats
        def view(request):
            calls.append(1)
            raise ValueError('invalid input')
        with self.assertRaises(ValueError):
            view(self.request())
        self.assertEqual(len(calls), 1)

    def test_value_snapshot_coalesces_threads_and_copies_results(self):
        calls = []
        barrier = threading.Barrier(4)
        def load():
            calls.append(1)
            time.sleep(.05)
            return [{'before': None, 'after': 'value'}]
        def get(_):
            barrier.wait(timeout=3)
            return cache.monitoring_cached_value('test-review', ['2026-11-06'], load)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(get, range(4)))
        self.assertEqual(len(calls), 1)
        results[0][0]['before'] = 'mutated'
        self.assertIsNone(cache.monitoring_cached_value('test-review', ['2026-11-06'])[0]['before'])

    def test_value_snapshot_invalidation_during_read_and_empty_hit(self):
        calls = []
        def load():
            calls.append(1)
            if len(calls) == 1:
                cache.invalidate_monitoring_cache()
            return []
        for _ in range(3):
            self.assertEqual(cache.monitoring_cached_value('test-review', [], load), [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(cache.monitoring_cached_value('test-review', []), [])
        self.assertIsNone(cache.monitoring_cached_value('other-review', []))

    def test_value_snapshot_never_caches_failed_reads(self):
        with patch.object(cache, '_has_error', return_value=True):
            calls = []
            def load():
                calls.append(1)
                return {'status': 'ERROR'}
            for _ in range(2):
                cache.monitoring_cached_value('test-review', [], load)
            self.assertEqual(len(calls), 2)
        def fail():
            calls.append(1)
            raise ValueError('incomplete review snapshot')
        with self.assertRaises(ValueError):
            cache.monitoring_cached_value('test-review', [], fail)
        self.assertEqual(len(calls), 3)

    def test_cache_io_failure_falls_back_and_failed_write_invalidates(self):
        @cache.cached_monitoring_stats
        def view(request):
            return JsonResponse({'count': 12})
        with patch.object(cache, '_root', side_effect=PermissionError), self.assertLogs(cache.logger, 'WARNING'):
            self.assertEqual(json.loads(view(self.request()).content), {'count': 12})
        def fail(request):
            raise RuntimeError('partial write')
        with patch.object(cache, 'invalidate_monitoring_cache') as invalidate:
            with self.assertRaises(RuntimeError):
                cache.MonitoringCacheInvalidationMiddleware(fail)(self.factory.post('/layer2/api/save/'))
            self.assertEqual(invalidate.call_count, 2)
