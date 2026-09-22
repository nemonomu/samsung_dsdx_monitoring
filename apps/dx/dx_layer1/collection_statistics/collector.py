"""Offline collector: never import or call this module from a page/API handler."""
import hashlib
import importlib
import json
from datetime import timedelta, timezone as tz
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.dx.dx_layer1.models import (
    CollectionDailySnapshot as Daily, CollectionWeeklySnapshot as Weekly,
    CollectionStatisticsLease as Lease,
)
from .calculations import COUNTRIES, OFFSETS, normalize_check, compare_rows, week_start, build_week

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
    """Dates are source dates. Changed history also rebuilds following 28-day comparisons."""
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
        rebuild(country, start, min(last_due, end + timedelta(days=28)), last_due)
        return result
    finally:
        Lease.objects.filter(name=country, owner=owner).update(expires_at=timezone.now())


def rebuild(country, start, end, last_due):
    """Read small stored snapshots only. Publish weekly data and alerts atomically."""
    first_week, last_week = week_start(start), week_start(end)
    snapshots = list(Daily.objects.filter(country=country,
        source_date__range=(first_week - timedelta(days=28), last_week + timedelta(days=6))).order_by('source_date'))
    by_date = {snapshot.source_date: snapshot for snapshot in snapshots}
    updated = []
    for snapshot in snapshots:
        if not start <= snapshot.source_date <= end:
            continue
        history = [row for older in snapshots
                   if snapshot.source_date - timedelta(days=28) <= older.source_date < snapshot.source_date
                   and not older.refresh_error for row in older.rows]
        snapshot.rows = compare_rows(snapshot.rows, history)
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
