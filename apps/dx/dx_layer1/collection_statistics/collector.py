"""Offline collector: never import or call this module from a page/API handler."""
import hashlib
import importlib
import json
from collections import defaultdict
from datetime import timedelta, timezone as tz
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.dx.dx_layer1.models import (
    CollectionDailySnapshot as Daily, CollectionWeeklySnapshot as Weekly,
    CollectionStatisticsLease as Lease,
)
from .calculations import (COUNTRIES, OFFSETS, BSR_POLICY_VERSION, MAIN_POLICY_VERSION,
                           OBSERVATION_POLICY_VERSION, remember_observation,
                           normalize_check, compare_rows, week_start, build_week)

SERVICE_MODULES = {
    country: f'apps.dx.dx_layer1.{country.lower()}_retail.{country.lower()}_retail_services'
    for country in COUNTRIES if country != 'SEA'
}
SERVICE_MODULES['SEA'] = 'apps.dx.dx_layer1.retail.retail_services'
LEASE_TIME = timedelta(minutes=20)


def load_check(country, inspection_date):
    from datetime import datetime, timezone as tz
    from apps.common.db import dx_connection
    service = importlib.import_module(SERVICE_MODULES[country])
    now = datetime.now(tz(timedelta(hours=9)))
    # SEA's legacy schedule compares naive KST datetimes. Other country
    # services already accept the timezone-aware KST value.
    if country == 'SEA':
        now = now.replace(tzinfo=None)
    with dx_connection() as (_connection, cursor):
        cursor.execute("SET LOCAL statement_timeout = '30000ms'")
        result = service.get_layer1_stats(cursor, inspection_date, now)
    if not isinstance(result, dict) or not isinstance(result.get('check'), dict):
        raise ValueError('Invalid collection result')
    check = result['check']
    if check.get('error') or check.get('status') == 'ERROR' or not check.get('categories'):
        raise ValueError('Collection counts unavailable')
    return check


def acquire_lease(country):
    now, owner = timezone.now(), str(uuid4())
    Lease.objects.get_or_create(name=country, defaults={'owner': '', 'expires_at': now})
    changed = Lease.objects.filter(name=country, expires_at__lte=now).update(owner=owner, expires_at=now + LEASE_TIME)
    return owner if changed else None


def renew_lease(country, owner):
    now = timezone.now()
    if not Lease.objects.filter(name=country, owner=owner, expires_at__gt=now).update(expires_at=now + LEASE_TIME):
        raise RuntimeError('Statistics refresh lease expired')


def refresh_country(country, start, end, *, loader=load_check, today=None):
    """Dates are source dates. Rebuild later medians and lifetime observation progress."""
    if country not in COUNTRIES or start > end or (end - start).days > 119:
        raise ValueError('Invalid statistics refresh range')
    owner = acquire_lease(country)
    if owner is None:
        return {'busy': True, 'updated': 0, 'errors': 0}
    result = {'busy': False, 'updated': 0, 'errors': 0}
    today = today or timezone.localdate(timezone=tz(timedelta(hours=9)))
    last_due = today - timedelta(days=OFFSETS[country])
    end = min(end, last_due)
    try:
        if start > end:
            return result
        day = start
        while day <= end:
            renew_lease(country, owner)
            inspection = day + timedelta(days=OFFSETS[country])
            try:
                rows = normalize_check(loader(country, inspection), country, inspection)
                if not rows:
                    raise ValueError('No collection rows')
                digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
                renew_lease(country, owner)
                previous = Daily.objects.filter(country=country, inspection_date=inspection).first()
                if previous is None or previous.digest != digest or previous.refresh_error:
                    Daily.objects.update_or_create(country=country, inspection_date=inspection, defaults={
                        'source_date': day, 'rows': rows, 'digest': digest,
                        'refresh_error': False, 'updated_at': timezone.now(),
                    })
                    result['updated'] += 1
                else:
                    Daily.objects.filter(pk=previous.pk).update(updated_at=timezone.now())
            except Exception:
                # Preserve last good counts; do not manufacture a zero on an outage.
                Daily.objects.filter(country=country, inspection_date=inspection).update(refresh_error=True)
                result['errors'] += 1
            day += timedelta(days=1)
        renew_lease(country, owner)
        rebuild(country, start, last_due, last_due)
        return result
    finally:
        Lease.objects.filter(name=country, owner=owner).update(expires_at=timezone.now())


def rebuild(country, start, end, last_due):
    """Read small stored snapshots only. Publish weekly data and alerts atomically."""
    first_week, last_week = week_start(start), week_start(end)
    # Upgrade existing saved comparisons on the next normal background refresh,
    # without re-querying raw source data or changing the web read path.
    policy_start = min(start, last_due - timedelta(days=111))
    history_start = week_start(policy_start) - timedelta(days=28)
    snapshots = list(Daily.objects.filter(country=country,
        source_date__range=(history_start, last_week + timedelta(days=6))).order_by('source_date'))
    stale_days = [snapshot.source_date for snapshot in snapshots
                  if policy_start <= snapshot.source_date <= end
                  and any(row.get('main_policy_version') != MAIN_POLICY_VERSION
                          or row.get('bsr_policy_version') != BSR_POLICY_VERSION
                          or row.get('observation_policy_version') != OBSERVATION_POLICY_VERSION
                          for row in snapshot.rows)]
    if stale_days:
        start = min(start, min(stale_days))
        first_week = week_start(start)
    by_date = {snapshot.source_date: snapshot for snapshot in snapshots}
    # Keep only the first five successful dates per retailer/product. Read older
    # stored summaries in chunks so a long outage never resets an established
    # retailer to new. No raw source queries or schema changes are needed.
    observed_dates = defaultdict(set)
    for old in Daily.objects.filter(country=country, source_date__lt=history_start,
                                   refresh_error=False).only('source_date', 'rows').order_by('source_date').iterator(chunk_size=100):
        remember_observation(observed_dates, old.rows, str(old.source_date))
    updated = []
    for snapshot in snapshots:
        if not start <= snapshot.source_date <= end:
            if not snapshot.refresh_error:
                remember_observation(observed_dates, snapshot.rows, str(snapshot.source_date))
            continue
        history = [{**row, 'source_date': str(older.source_date)} for older in snapshots
                   if snapshot.source_date - timedelta(days=28) <= older.source_date < snapshot.source_date
                   and not older.refresh_error for row in older.rows]
        snapshot.rows = compare_rows(
            [{**row, 'refresh_error': snapshot.refresh_error} for row in snapshot.rows],
            history, country=country, observed_dates=observed_dates)
        if not snapshot.refresh_error:
            remember_observation(observed_dates, snapshot.rows, str(snapshot.source_date))
        updated.append(snapshot)
    with transaction.atomic():
        if updated:
            Daily.objects.bulk_update(updated, ['rows'])
        monday = first_week
        while monday <= last_week:
            rows = build_week({day: [{**row, 'refresh_error': snapshot.refresh_error} for row in snapshot.rows]
                               for day, snapshot in by_date.items()}, monday, last_due)
            Weekly.objects.update_or_create(country=country, week_start=monday,
                defaults={'rows': rows, 'updated_at': timezone.now()})
            monday += timedelta(days=7)
