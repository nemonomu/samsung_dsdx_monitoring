"""Durable source-day incidents. Source queries are read-only; evidence is local."""
import hashlib
from datetime import date, timedelta
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_layer1.models import CollectionIssue as Issue, CollectionIssueEvent as Event
from apps.dx.dx_layer1.models import CollectionIssueScan as Scan, CollectionStatisticsLease as Lease
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, compare_columns, KST
from apps.dx.dx_layer1.column_statistics.dates import active_from
from apps.dx.dx_layer1.column_statistics.services import daily_counts
from .queries import raw_counts, selection, first_observed, daily_batch_ids
from . import volume
from .retry import retry_locked_write

START_DATE = date(2026, 10, 1)
POLICY_VERSION = 1  # Original-day missing/column + MAIN/BSR + distinct batches.
CHUNK_DAYS = 28


def environment():
    return 'test' if settings.DEBUG else 'production'


def identity(country, product, retailer):
    return dict(environment=environment(), country=country, product=product, retailer=retailer)


def coverage_start(country, product, retailer):
    source, _ = selection(country, product, retailer)
    registered = active_from(source, retailer)
    if registered:
        return max(START_DATE, registered), 'registered'
    scope = identity(country, product, retailer)
    # Once monitoring has started, deleting the earliest day's data must not
    # move its start forward and erase an expected collection day.
    stored = Scan.objects.filter(**scope).values_list('coverage_start', flat=True).first()
    observed = first_observed(country, product, retailer)
    candidates = [d for d in (stored, observed) if d is not None]
    return (max(START_DATE, min(candidates)) if candidates else None), 'first_observed'


def event(issue, action, at, *, username='', reason='', evidence=None):
    Event.objects.create(issue=issue, action=action, created_at=at,
                         username=username, reason=reason, evidence=evidence or {})


def reconcile_day(data, target, completed, raw_total, *, now=None):
    observed_at = now or timezone.now()
    return retry_locked_write(lambda: _reconcile_day(data, target, completed, raw_total, now=observed_at))


def _reconcile_day(data, target, completed, raw_total, *, now=None):
    """Use the original incident's baseline when checking a later restoration."""
    now = now or timezone.now()
    if target < START_DATE or not completed.get(str(target), False):
        return
    scope = identity(data['country'], data['product'], data['retailer'])
    current = next(d for d in data['daily'] if d['date'] == str(target))
    comparisons = compare_columns(data, target, completed)
    new = ({'': {'status': 'uncollected', 'current': 0, 'baseline': None,
                 'history_days': 0}} if raw_total == 0 else
           {r['column']: r for r in comparisons if r['status'] in ('abnormal', 'review')})
    with transaction.atomic():
        existing = {r.column: r for r in Issue.objects.filter(**scope, source_date=target)}
        for column, row in new.items():
            if column in existing:
                continue
            evidence = dict(row, raw_total=raw_total, scoped_total=current['total'],
                            source_date=str(target), date_basis=('SIEL Asia/Seoul' if data['country']=='SIEL' else 'db_original'),
                            baseline_days=28)
            issue = Issue.objects.create(**scope, source_date=target, column=column,
                severity=row['status'], baseline=row['baseline'], observed_count=row['current'],
                current_count=row['current'], evidence=evidence,
                first_detected_at=now, last_checked_at=now)
            event(issue, 'detected', now, evidence=evidence)
        for column, issue in existing.items():
            if column.startswith('__'):
                continue  # MAIN/BSR and batch issues have their own recovery policy.
            if issue.last_checked_at > now:
                continue  # A cached response cannot undo a newer verification.
            # Removed/disabled fields are not silently marked recovered.
            count = raw_total if not column else current['counts'].get(column)
            if count is None:
                continue
            recovered = raw_total > 0 and (not column or (
                current['total'] > 0 and issue.baseline is not None
                and count * 100 > issue.baseline * 60))
            expected_status = issue.status if issue.status == 'excepted' else 'resolved' if recovered else 'open'
            if (issue.last_checked_at == now and issue.current_count == count
                    and issue.status == expected_status):
                continue  # Re-reading the same cached observation needs no write.
            old_status = issue.status
            issue.current_count, issue.last_checked_at = count, now
            if issue.status != 'excepted':
                issue.status = 'resolved' if recovered else 'open'
                if issue.status != old_status:
                    issue.resolved_at = now if recovered else None
                    issue.revision += 1
                    event(issue, 'recovered' if recovered else 'reopened', now,
                          evidence={'current': count, 'raw_total': raw_total,
                                    'original_baseline': issue.baseline})
            issue.save()


def refresh_target(country, product, retailer, *, now=None, volume_cache=None):
    """Recent days, one backfill chunk, and every still-open source day."""
    now = now or timezone.now()
    source, _ = selection(country, product, retailer)
    today = now.astimezone(KST).date()
    target = date.fromisoformat(resolve_monitoring_date(today, country, source['key'])['source_date']) - timedelta(days=1)
    scope = identity(country, product, retailer)
    lease_key = 'issues:' + hashlib.sha256(repr(sorted(scope.items())).encode()).hexdigest()[:32]
    owner = str(uuid4())
    Lease.objects.get_or_create(name=lease_key, defaults={'owner': '', 'expires_at': now})
    if not Lease.objects.filter(name=lease_key, expires_at__lte=now).update(
            owner=owner, expires_at=now+timedelta(minutes=15)):
        return {'busy': True, 'days': 0}
    scan, _ = Scan.objects.get_or_create(**scope)
    try:
        if scan.policy_version != POLICY_VERSION:
            # A completed legacy column scan proves nothing about volume/batches.
            # Reset here too: deployment may have skipped the one-off reset migration.
            scan.scanned_through, scan.last_checked_at = None, None
            scan.save(update_fields=['scanned_through','last_checked_at'])
        start, basis = coverage_start(country, product, retailer)
        scan.coverage_start, scan.start_basis = start, basis
        scan.save(update_fields=['coverage_start','start_basis'])
        if start is None:
            raise ValueError('No authoritative start or observed collection day')
        if target < start:
            scan.last_checked_at, scan.error = now, False
            scan.policy_version = POLICY_VERSION
            scan.save()
            return {'busy': False, 'days': 0}
        # Do not advance coverage through a source day still inside its collection window.
        last_complete = target
        while last_complete >= start and not collection_complete(country, product, retailer, last_complete, now):
            last_complete -= timedelta(days=1)
        backfill_start = max(start, scan.scanned_through+timedelta(days=1) if scan.scanned_through else start)
        backfill_end = min(last_complete, backfill_start+timedelta(days=CHUNK_DAYS-1))
        wanted = {target-timedelta(days=i) for i in range(3) if target-timedelta(days=i) >= start}
        if backfill_start <= backfill_end:
            wanted.update(backfill_start+timedelta(days=i) for i in range((backfill_end-backfill_start).days+1))
        wanted.update(Issue.objects.filter(**scope, status='open', source_date__range=(start,target))
                      .values_list('source_date', flat=True))
        # Bounded windows even when an unresolved incident is years old.
        pending = sorted(wanted)
        volume_pending = False
        while pending:
            first = pending[0]
            end = min(target, first+timedelta(days=CHUNK_DAYS-1))
            days = [d for d in pending if d <= end]
            pending = [d for d in pending if d > end]
            query_start = first-timedelta(days=28)
            data = daily_counts(country, product, retailer, end, (end-query_start).days+1)
            totals = raw_counts(country, product, retailer, first, end)
            batches = daily_batch_ids(country, product, retailer, first, end)
            complete = {d['date']: collection_complete(country, product, retailer,
                        date.fromisoformat(d['date']), now) for d in data['daily']}
            volumes = volume.load_days(country, product, retailer,
                [d for d in days if complete.get(str(d)) and totals.get(str(d), 0) > 0],
                cache=volume_cache, strict=False)
            for day in days:
                reconcile_day(data, day, complete, totals.get(str(day), 0), now=now)
                if complete.get(str(day), False):
                    volume_pending |= volumes.get(str(day), []) is None
                    volume.reconcile(country, product, retailer, day, volumes.get(str(day)) or [],
                                     batches.get(str(day), []), now=now)
            if not Lease.objects.filter(name=lease_key, owner=owner, expires_at__gt=timezone.now()).update(
                    expires_at=timezone.now()+timedelta(minutes=15)):
                raise RuntimeError('Collection issue scan lease expired')
        if volume_pending:
            raise ValueError('Collection volume verification pending; retry required')
        if backfill_start <= backfill_end:
            scan.scanned_through = backfill_end
        scan.last_checked_at, scan.error = now, False
        scan.policy_version = POLICY_VERSION
        scan.save()
        return {'busy': False, 'days': len(wanted)}
    except Exception:
        Scan.objects.filter(pk=scan.pk).update(error=True)
        raise
    finally:
        Lease.objects.filter(name=lease_key, owner=owner).update(expires_at=timezone.now())


def serialize(issue, *, detail=False, reviews=None):
    result = {k: getattr(issue, k) for k in
              ('id', 'country', 'product', 'retailer', 'column', 'severity', 'status',
               'baseline', 'observed_count', 'current_count', 'revision')}
    result.update(source_date=str(issue.source_date),
                  kind=issue.evidence.get('kind', 'column' if issue.column else 'uncollected'),
                  label=volume.label(issue),
                  batch_ids=issue.evidence.get('batch_ids', []),
                  first_detected_at=issue.first_detected_at.isoformat(),
                  last_checked_at=issue.last_checked_at.isoformat(),
                  resolved_at=issue.resolved_at.isoformat() if issue.resolved_at else None)
    if issue.evidence.get('metric') in ('main', 'bsr'):
        from apps.dx.dx_layer1.collection_statistics.reviews import review_index
        decision = volume.review_decision(issue, reviews if reviews is not None else review_index(issue.source_date, issue.source_date))
        result['review'] = decision
        result['review_target'] = dict(country=issue.country, product=issue.product, retailer=issue.retailer,
            source_date=str(issue.source_date), metric=issue.evidence['metric'], slot=issue.evidence.get('slot', 'daily'))
        if issue.status == 'open' and decision.get('action') == 'confirm':
            result['status'] = 'confirmed'
    if detail:
        result['evidence'] = issue.evidence
        result['history'] = list(issue.events.order_by('id').values(
            'action', 'username', 'reason', 'evidence', 'created_at'))
    return result
