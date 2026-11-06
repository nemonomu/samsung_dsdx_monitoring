"""Short-lived DX aggregate cache shared by workers on one server.

Only explicitly decorated, user-independent aggregate views are cached. The
directory must be private to the application, outside static/media roots.
"""
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import date
from functools import lru_cache, wraps
from pathlib import Path

from django.conf import settings
from django.core.cache.backends.filebased import FileBasedCache
from django.core.files import locks
from django.http import HttpResponse

logger = logging.getLogger(__name__)
TTL = 60


def _root():
    directory = getattr(settings, 'MONITORING_CACHE_DIR', None)
    base = Path(directory) if directory is not None else settings.BASE_DIR / '.cache' / 'dx-monitoring'
    root = base / ('test' if settings.DEBUG else 'production')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


@lru_cache(maxsize=4)
def _backend(root):
    return FileBasedCache(str(root / 'responses'), {
        'TIMEOUT': TTL, 'OPTIONS': {'MAX_ENTRIES': 512},
    })


def _generation(root):
    try:
        return (root / 'generation').read_text(encoding='ascii')
    except FileNotFoundError:
        return 'initial'


def invalidate_monitoring_cache():
    """Invalidate all products together, including shared normal approvals."""
    path = None
    try:
        root = _root()
        with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False,
                                         encoding='ascii') as file:
            path = file.name
            file.write(uuid.uuid4().hex)
        os.replace(path, root / 'generation')
    except OSError:
        logger.warning('DX aggregate cache invalidation failed', exc_info=True)
    finally:
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except OSError:
            logger.warning('DX cache temporary file cleanup failed', exc_info=True)


def _has_error(value):
    if isinstance(value, dict):
        if value.get('error') or value.get('refresh_error'):
            return True
        if any(str(value.get(key, '')).upper() == 'ERROR'
               for key in ('status', 'overall_status')):
            return True
        return any(_has_error(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_error(item) for item in value)
    return False


def _value_digest(namespace, identity):
    return hashlib.sha256(json.dumps(['value', namespace, identity],
                                    sort_keys=True).encode()).hexdigest()


def monitoring_cached_value(namespace, identity, loader=None, *, cacheable=None):
    """Read a shared snapshot; optionally compute it once on a cache miss.

    A lookup without a loader returns None on a miss. Callers may reuse a
    broader snapshot without writing a narrower copy and extending its TTL.
    FileBasedCache deserializes a fresh object for every hit, so source context
    added to one review page cannot mutate another page's saved audit values.
    """
    if not getattr(settings, 'MONITORING_CACHE_ENABLED', True):
        return loader() if loader else None
    digest = _value_digest(namespace, identity)
    result, computed, computing = None, False, False
    try:
        root = _root()
        cache = _backend(root)
        with (root / ('lock-' + digest[:2])).open('a+b') as lock:
            if not locks.lock(lock, locks.LOCK_EX):
                raise OSError('File locking unavailable')
            try:
                generation = _generation(root)
                key = generation + ':' + digest
                entry = cache.get(key)
                if entry is not None:
                    return entry['value']
                if loader is None:
                    return None
                started = time.time()
                computing = True
                result = loader()
                computing, computed = False, True
                remaining = TTL - (time.time() - started)
                if (remaining > 0 and generation == _generation(root)
                        and (cacheable(result) if cacheable else not _has_error(result))):
                    cache.set(key, {'value': result}, timeout=remaining)
            finally:
                locks.unlock(lock)
    except (OSError, ValueError):
        if computing:
            raise
        logger.warning('DX snapshot cache unavailable; using uncached result', exc_info=True)
    return result if computed else loader() if loader else None


def cached_monitoring_stats(view):
    """Coalesce identical requests; expire source data at most 60s after read."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if (getattr(request, 'method', 'GET') != 'GET'
                or not getattr(getattr(request, 'user', None), 'is_authenticated', False)
                or not getattr(settings, 'MONITORING_CACHE_ENABLED', True)):
            return view(request, *args, **kwargs)
        started = time.time()
        query = sorted((key, request.GET.getlist(key)) for key in request.GET
                       if key != 'refresh')
        identity = json.dumps([view.__module__, view.__name__, date.today().isoformat(), query])
        digest = hashlib.sha256(identity.encode()).hexdigest()
        response = None
        computing = False
        try:
            root = _root()
            cache = _backend(root)
            # Fixed lock buckets bound file count; OS releases locks on exit.
            with (root / ('lock-' + digest[:2])).open('a+b') as lock:
                if not locks.lock(lock, locks.LOCK_EX):
                    raise OSError('File locking unavailable')
                try:
                    generation = _generation(root)
                    key = generation + ':' + digest
                    entry = cache.get(key)
                    force = request.GET.get('refresh') == '1'
                    if entry and (not force or entry['started'] >= started):
                        response = HttpResponse(entry['content'], content_type='application/json')
                    else:
                        read_started = time.time()
                        computing = True
                        response = view(request, *args, **kwargs)
                        computing = False
                        remaining = TTL - (time.time() - read_started)
                        if (response.status_code == 200 and not response.streaming
                                and remaining > 0 and _generation(root) == generation
                                and not response.cookies
                                and not _has_error(json.loads(response.content))):
                            cache.set(key, {'content': response.content, 'started': read_started},
                                      timeout=remaining)
                finally:
                    locks.unlock(lock)
        except (OSError, ValueError):
            if computing:
                raise
            logger.warning('DX aggregate cache unavailable; using uncached result', exc_info=True)
        if response is None:
            response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response
    return wrapped


class MonitoringCacheInvalidationMiddleware:
    """Discard aggregates before and after DX writes, even partial failures.

Generation checks also prevent a read already in flight from repopulating an
old result after a write. Legacy layer URLs use the same invalidation path.
"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        invalidate = (request.method not in ('GET', 'HEAD', 'OPTIONS')
                      and request.path_info.startswith((
                          '/dx/', '/layer1/', '/layer2/', '/layer3/', '/layer4/', '/layer5/')))
        if not invalidate:
            return self.get_response(request)
        invalidate_monitoring_cache()
        try:
            return self.get_response(request)
        finally:
            invalidate_monitoring_cache()
