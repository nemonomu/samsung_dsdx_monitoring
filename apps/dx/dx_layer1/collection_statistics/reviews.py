"""Attach human decisions to the same saved collection, without altering counts."""
import json
from collections import defaultdict
from datetime import date, timedelta
from django.conf import settings

from apps.dx.dx_layer1.models import RetailNormalReview
from .calculations import OFFSETS


def review_index(start, end):
    result = defaultdict(list)
    # SEA/SEDA inspection happens the next day; source dates stay unchanged.
    for record in RetailNormalReview.objects.filter(
        inspection_date__range=(start, end + timedelta(days=max(OFFSETS.values())))
    ).iterator():
        c = record.context
        if c.get('version') == 2 and c.get('environment') != ('test' if settings.DEBUG else 'production'):
            continue
        key = tuple(c.get(k) for k in ('country', 'product', 'retailer', 'slot', 'source_date', 'batch_id'))
        result[key].append(record)
    return result


def alert_basis(alerts):
    """Ignore wording and the observation-only review label, retain numeric rules."""
    result = []
    for alert in alerts:
        metric = alert.get('metric')
        if metric not in ('main', 'bsr'):
            continue
        status = alert.get('status')
        if metric == 'bsr' and alert.get('exact') and status == 'VOLUME_REVIEW':
            status = 'VOLUME_LOW'
        result.append((metric, alert.get('baseline'), alert.get('actual'),
                       alert.get('rule', 'median_28d' if metric == 'main' else None),
                       bool(alert.get('exact')), status))
    return sorted(result, key=lambda item: item[0])


def attach_review(day, country, product, retailer, slot, index):
    result = dict(day)
    result.pop('review', None)
    result['metric_reviews'] = {}
    if day.get('state') != 'complete' or day.get('base_status') == 'ERROR' or day.get('refresh_error'):
        return result
    key = (country, product, retailer, slot, day['date'], day.get('batch_id'))
    candidates = index.get(key, [])
    if not candidates or not day.get('batch_id'):
        return result
    expected_date = str(date.fromisoformat(day['date']) + timedelta(days=OFFSETS[country]))
    # Resolve each metric independently; a later cancellation also wins over
    # legacy whole-row approvals. Never carry a decision to changed evidence.
    latest = {}
    current_basis = alert_basis(day.get('alerts', []))
    for record in sorted(candidates, key=lambda r: (r.history[-1].get('at', '') if r.history else '', r.pk)):
        c = record.context
        # The most recent decision for the metric supersedes older evidence,
        # including when its counts no longer match the current collection.
        for metric in ([c.get('metric')] if c.get('version') == 2 else ('main', 'bsr')):
            latest.pop(metric, None)
        if c.get('date') != expected_date or c.get('counts', [])[:3] != [day.get(k) for k in ('main', 'bsr', 'total')]:
            continue
        if 'batch_count' in day and c['counts'][3] != day['batch_count']:
            continue
        try:
            parsed = json.loads(c['basis']).get('alerts', [])
            if c.get('version') == 2:
                metric = c.get('metric')
                basis = [tuple(entry) for entry in parsed]
                expected = [entry for entry in current_basis if entry[0] == metric]
            else:
                basis, expected = alert_basis(parsed), current_basis
            if not basis or basis != expected:
                continue
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        event = record.history[-1] if record.history else {}
        for metric in {entry[0] for entry in basis}:
            latest[metric] = (record, event)
    for metric, (record, event) in latest.items():
        if ((record.active and event.get('action') == 'confirm')
                or (not record.active and event.get('action') == 'reject')):
            result['metric_reviews'][metric] = {**{k: event.get(k, '') for k in ('action', 'memo', 'username', 'at')},
                                                 'metrics': [metric], 'inspection_date': expected_date}
    # Compatibility for consumers of whole-row decisions. Partial reviews must
    # never mark a sibling metric normal.
    decisions = result['metric_reviews']
    affected = {entry[0] for entry in current_basis}
    if affected and affected == set(decisions) and len({v['action'] for v in decisions.values()}) == 1:
        result['review'] = {**next(iter(decisions.values())), 'metrics': sorted(affected)}
    return result
