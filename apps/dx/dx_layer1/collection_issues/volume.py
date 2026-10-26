"""Persist MAIN/BSR and batch incidents using the existing collection policy."""
import hashlib
from datetime import timedelta

from apps.dx.dx_layer1.collection_statistics.calculations import current_volume_decision, OFFSETS
from apps.dx.dx_layer1.collection_statistics.live import current_snapshot
from apps.dx.dx_layer1.collection_statistics.reviews import attach_review, review_index

METRICS = ('main', 'bsr')
BATCH_COLUMN = '__batches'


def metric_column(metric, slot):
    return '__' + metric + ':' + hashlib.sha256(slot.encode()).hexdigest()[:16]


def retailer_key(value, country):
    key = str(value).strip().casefold()
    return key.replace(' ', '') if country == 'SEDA' else key


def load_days(country, product, retailer, days, *, cache=None, strict=True):
    # One fresh country/day read per background run, shared across retailers.
    # Saved prior-day statistics supply baselines, never stale recovery counts.
    cache = {} if cache is None else cache
    result = {}
    for day in days:
        key = country, day
        if key not in cache:
            try:
                cache[key] = current_snapshot(country, day + timedelta(days=OFFSETS[country]))
            except Exception as exc:
                cache[key] = exc
        if isinstance(cache[key], Exception):
            if strict:
                raise cache[key]
            result[str(day)] = None
            continue
        rows = [r for r in cache[key]['rows'] if r['product'] == product
                and retailer_key(r['retailer'],country) == retailer_key(retailer,country)]
        if not rows or any(not r.get('complete') or r.get('base_status') == 'ERROR'
                           or r.get('refresh_error') or r.get('observation_state') == 'unknown'
                           for r in rows):
            if strict:
                raise ValueError('Collection volume verification pending; retry required')
            rows = None
        result[str(day)] = rows
    return result


def confirmed(issue, index):
    metric = issue.evidence.get('metric')
    row = issue.evidence.get('current_row')
    if metric not in METRICS or not row:
        return False
    reviewed = attach_review(row, issue.country, issue.product, row.get('retailer',issue.retailer),
                             row['slot'], index).get('review', {})
    return reviewed.get('action') == 'confirm' and metric in reviewed.get('metrics', [])


def hide_confirmed(issues):
    if not issues:
        return issues
    index = review_index(min(r.source_date for r in issues), max(r.source_date for r in issues))
    return [r for r in issues if not confirmed(r, index)]


def reconcile(country, product, retailer, day, rows, batch_ids, *, now):
    from .services import identity, event
    from apps.dx.dx_layer1.models import CollectionIssue as Issue
    from django.db import transaction

    scope = identity(country, product, retailer)
    with transaction.atomic():
        existing = {r.column: r for r in Issue.objects.filter(**scope, source_date=day)
                    if r.column.startswith('__')}
        candidates = {BATCH_COLUMN: dict(count=len(batch_ids), abnormal=len(batch_ids) >= 2,
                       baseline=1, evidence={'kind': 'batches', 'batch_ids': batch_ids})}
        for row in rows:
            if not row.get('complete') or row.get('base_status') == 'ERROR' or row.get('refresh_error'):
                continue
            row = current_volume_decision(dict(row, batch_count=len(batch_ids)), country)
            for metric in METRICS:
                column = metric_column(metric, row['slot'])
                previous = existing.get(column)
                # A weakened later median cannot clear an older incident.
                evaluated = row
                if previous and previous.evidence.get('basis'):
                    evaluated = current_volume_decision(dict(row,
                        baselines={**row.get('baselines', {}), metric: previous.evidence['basis']}), country)
                alert = next((a for a in evaluated.get('alerts', []) if a['metric'] == metric), None)
                basis = evaluated.get('baselines', {}).get(metric)
                if not basis or row.get(metric) is None:
                    continue  # Missing policy/history is not proof of recovery.
                if metric == 'bsr' and evaluated.get('bsr_comparison_state') != 'ready':
                    continue
                candidates[column] = dict(count=row[metric], abnormal=bool(alert),
                    baseline=basis['value'], evidence={'kind': 'volume', 'metric': metric,
                    'slot': row['slot'], 'basis': basis, 'alert': alert, 'current_alert': alert,
                    'current_row': row, 'batch_ids': batch_ids})
        for column, candidate in candidates.items():
            issue = existing.get(column)
            if not issue and not candidate['abnormal']:
                continue
            if not issue:
                issue = Issue.objects.create(**scope, source_date=day, column=column,
                    severity='review', baseline=candidate['baseline'],
                    observed_count=candidate['count'], current_count=candidate['count'],
                    evidence=candidate['evidence'], first_detected_at=now, last_checked_at=now)
                event(issue, 'detected', now, evidence=candidate['evidence'])
            if issue.last_checked_at > now:
                continue
            evidence = dict(issue.evidence)
            for key in ('current_row', 'batch_ids', 'current_alert'):
                if key in candidate['evidence']:
                    evidence[key] = candidate['evidence'][key]
            issue.evidence = evidence
            issue.current_count, issue.last_checked_at = candidate['count'], now
            if issue.status != 'excepted':
                status = 'open' if candidate['abnormal'] else 'resolved'
                if status != issue.status:
                    issue.status, issue.resolved_at = status, now if status == 'resolved' else None
                    issue.revision += 1
                    event(issue, 'recovered' if status == 'resolved' else 'reopened', now,
                          evidence={'current': candidate['count'], 'baseline': issue.baseline})
            issue.save()


def label(issue):
    if issue.column == BATCH_COLUMN:
        return f'배치 ID {issue.current_count}개'
    metric = issue.evidence.get('metric')
    if metric in METRICS:
        alert = issue.evidence.get('current_alert') or issue.evidence.get('alert') or {}
        text = metric.upper() + (' 기준 불일치' if alert.get('exact') else
            ' 수집량 증가' if alert.get('status') == 'VOLUME_HIGH' else ' 수집량 부족')
        slot = issue.evidence.get('slot')
        return text + (' · ' + slot if slot and slot != 'daily' else '')
    return issue.column or '전체 미수집'
