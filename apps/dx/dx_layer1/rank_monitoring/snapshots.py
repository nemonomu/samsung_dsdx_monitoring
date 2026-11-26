"""On-demand shared rank snapshots; request workers never wait on source queries.

One nonblocking OS lock limits all rank refreshes to one per application host.
There is no queue and no periodic scan of unrequested retailers. Rank files and
locks are separate from the existing monitoring cache. A source-write generation
invalidates rank snapshots; review-only writes do not.
"""
import hashlib
import json
import logging
import time
import uuid
from datetime import date, timedelta, timezone as tz
from pathlib import Path
from threading import Thread

from django.conf import settings
from django.core import signing
from django.core.cache.backends.filebased import FileBasedCache
from django.core.files import locks
from django.utils import timezone

from apps.common.monitoring_cache import monitoring_cache_generation
from apps.common.sem_retail import sem_start_date, sem_tv_observation_retailer
from apps.common.seib_retail import ECI_APPLIANCE_START, is_eci_appliance, is_eci_appliance_preview
from apps.dx.dx_layer1.seuk_retail.sources import TV_START, new_tv_retailer
from apps.dx.dx_layer1.siel_retail import jiomart
from .sources import select_source
from .repository import load_snapshots
from .comparison import compare
from . import reviews

logger = logging.getLogger(__name__)
FRESH_SECONDS = 60
STALE_SECONDS = 300
SNAPSHOT_SECONDS = 1200
RETRY_SECONDS = 20
SALT = 'retail-rank-snapshot-v2'
VERSION = 'v3'


class SnapshotExpired(ValueError):
    pass


def backend():
    base = getattr(settings, 'RANK_CACHE_DIR', None)
    root = Path(base) if base is not None else Path(settings.BASE_DIR) / '.cache' / 'rank-monitoring'
    root = root / reviews.environment()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root, FileBasedCache(str(root / 'snapshots'), {
        'TIMEOUT': SNAPSHOT_SECONDS, 'OPTIONS': {'MAX_ENTRIES': 256, 'CULL_FREQUENCY': 3},
    })


def scope_key(scope, generation):
    version = VERSION
    if jiomart.matches(scope['country'], scope['product'], scope['retailer']):
        version = f'{VERSION}:{jiomart.DATE_BASIS}'
    return hashlib.sha256(json.dumps([version, generation, scope], sort_keys=True).encode()).hexdigest()


def token(snapshot):
    return signing.dumps({'id': snapshot['id'], 'environment': reviews.environment()}, salt=SALT)


def pinned(value):
    try:
        payload = signing.loads(value, salt=SALT, max_age=SNAPSHOT_SECONDS)
        if payload['environment'] != reviews.environment():
            raise SnapshotExpired
        _, cache = backend()
        snapshot = cache.get('snapshot:' + payload['id'])
        if (not snapshot or time.time() - snapshot['created'] >= SNAPSHOT_SECONDS
                or snapshot['generation'] != monitoring_cache_generation()):
            raise SnapshotExpired
        return snapshot
    except (signing.BadSignature, KeyError, TypeError):
        raise SnapshotExpired from None


def build(scope, generation):
    source, account = select_source(scope['country'], scope['product'], scope['retailer'])
    day = date.fromisoformat(scope['date'])
    started = time.time()
    bsr = scope.get('rank_type') == 'bsr'
    raw = load_snapshots(source, account, day, 'bsr') if bsr else load_snapshots(source, account, day)
    active_from = (ECI_APPLIANCE_START if scope['country'] == 'SEIB'
                   and is_eci_appliance(scope['product'], scope['retailer']) else None)
    preview = bool(active_from and is_eci_appliance_preview(scope['product'], scope['retailer'], day))
    is_jiomart = jiomart.matches(scope['country'], scope['product'], scope['retailer'])
    if is_jiomart:
        active_from, preview = jiomart.START, jiomart.preview(day)
    if new_tv_retailer(scope['country'], scope['product'], scope['retailer']):
        active_from = TV_START
    if sem_tv_observation_retailer(source['key'], scope['retailer']):
        active_from = sem_start_date(source['key'], scope['retailer'])
    today = timezone.localdate(timezone=tz(timedelta(hours=9)))
    results = {}
    for mode in ('all', 'samsung'):
        result = compare(raw['rows'], day, samsung=mode == 'samsung', today=today,
                         limit=100 if bsr else 300, active_from=active_from, preview=preview)
        result.update(scope, mode=mode, basis=raw['basis'], sku_from_master=raw['sku_from_master'],
                      updated_at=timezone.now().isoformat(), preview_mode=preview)
        reviews.prepare(result, scope)
        results[mode] = result
    return {'id': uuid.uuid4().hex, 'scope': scope, 'generation': generation,
            'created': started, 'results': results}


def refresh(scope, generation, key, cache, lock):
    try:
        snapshot = build(scope, generation)
        if generation == monitoring_cache_generation():
            # Write immutable version before publishing its latest pointer.
            cache.set('snapshot:' + snapshot['id'], snapshot, SNAPSHOT_SECONDS)
            cache.set('latest:' + key, snapshot['id'], SNAPSHOT_SECONDS)
            cache.delete('error:' + key)
    except Exception:
        logger.exception('Rank snapshot refresh failed: %s', scope)
        try:
            cache.set('error:' + key, True, RETRY_SECONDS)
        except OSError:
            logger.warning('Rank refresh failure marker could not be stored')
    finally:
        locks.unlock(lock)
        lock.close()


def schedule(scope, generation, key, cache, root):
    """Acquire without waiting; at most one background thread/DB read per host."""
    lock = (root / 'refresh.lock').open('a+b')
    try:
        if not locks.lock(lock, locks.LOCK_EX | locks.LOCK_NB):
            lock.close()
            return False
    except BlockingIOError:
        lock.close()
        return False
    try:
        # Another worker may have completed the same request since our first read.
        latest = cache.get('latest:' + key)
        recent = cache.get('snapshot:' + latest) if latest else None
        if recent and time.time() - recent['created'] < FRESH_SECONDS:
            locks.unlock(lock)
            lock.close()
            return False
        if cache.get('error:' + key):
            locks.unlock(lock)
            lock.close()
            return False
        worker = Thread(target=refresh, args=(dict(scope), generation, key, cache, lock),
                        name='rank-snapshot-refresh', daemon=True)
        worker.start()
        return True
    except Exception:
        locks.unlock(lock)
        lock.close()
        raise


def latest(scope):
    generation = monitoring_cache_generation()
    key = scope_key(scope, generation)
    root, cache = backend()
    version = cache.get('latest:' + key)
    snapshot = cache.get('snapshot:' + version) if version else None
    age = time.time() - snapshot['created'] if snapshot else None
    if snapshot and age < FRESH_SECONDS:
        return snapshot, {'state': 'fresh', 'age_seconds': max(0, int(age))}
    failed = bool(cache.get('error:' + key))
    if not failed:
        schedule(scope, generation, key, cache, root)
    if snapshot and age < STALE_SECONDS:
        return snapshot, {'state': 'refresh_failed' if failed else 'refreshing', 'age_seconds': max(0, int(age))}
    return None, {'state': 'failed' if failed else 'pending', 'age_seconds': None}
