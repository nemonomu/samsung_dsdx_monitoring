"""Attach human decisions to the same saved collection, without altering counts."""
import json
from collections import defaultdict
from datetime import date, timedelta

from apps.dx.dx_layer1.models import RetailNormalReview
from .calculations import OFFSETS


def review_index(start, end):
    result = defaultdict(list)
    # SEA/SEDA inspection happens the next day; source dates stay unchanged.
    for record in RetailNormalReview.objects.filter(
        inspection_date__range=(start, end + timedelta(days=max(OFFSETS.values())))
    ).iterator():
        c = record.context
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
    if day.get('state') != 'complete' or day.get('base_status') == 'ERROR' or day.get('refresh_error'):
        return result
    key = (country, product, retailer, slot, day['date'], day.get('batch_id'))
    candidates = index.get(key, [])
    if not candidates or not day.get('batch_id'):
        return result
    # Latest action wins, including cancellation. Never revive an older approval.
    record = max(candidates, key=lambda r: (r.history[-1].get('at', '') if r.history else '', r.pk))
    c = record.context
    expected_date = str(date.fromisoformat(day['date']) + timedelta(days=OFFSETS[country]))
    if c.get('date') != expected_date or c.get('counts', [])[:3] != [day.get(k) for k in ('main', 'bsr', 'total')]:
        return result
    if 'batch_count' in day and c['counts'][3] != day['batch_count']:
        return result
    try:
        basis = alert_basis(json.loads(c['basis']).get('alerts', []))
    except (KeyError, TypeError, ValueError, AttributeError):
        return result
    if not basis or basis != alert_basis(day.get('alerts', [])):
        return result
    event = record.history[-1] if record.history else {}
    if not ((record.active and event.get('action') == 'confirm')
            or (not record.active and event.get('action') == 'reject')):
        return result
    result['review'] = {k: event.get(k, '') for k in ('action', 'memo', 'username', 'at')}
    result['review']['metrics'] = sorted({entry[0] for entry in basis})
    result['review']['inspection_date'] = c['date']
    return result
