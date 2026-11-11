"""Pure comparisons: a missing day is not a missing product."""
import re
from collections import defaultdict
from datetime import timedelta

LIMIT = 300
SWING = 40
TARGETS = (90, 70, 50)
SAMSUNG = re.compile(r'(?<![a-z0-9])samsung(?![a-z0-9])|삼성', re.I)
LABELS = {
    'return': '일시 누락 의심', 'missing': '300위 내 미발견',
    'next_missing': 'D+1 300위 내 미발견', 'swing': '순위 급변', 'data': '식별값 / 순위 확인',
    'stable': '특이 신호 없음', 'new': '신규 진입', 'unassessed': '비교 대기',
}


def text(value):
    return str(value).strip() if value is not None else ''


def rank(value):
    raw = text(value)
    return int(raw) if re.fullmatch(r'[1-9][0-9]{0,8}', raw) else None


def bucket(value):
    return (value - 1) // 100 if value is not None and 1 <= value <= LIMIT else None


def snapshot(rows):
    grouped = defaultdict(list)
    for row in rows:
        # Missing ITEMs never match unrelated rows across dates or by model SKU.
        key = 'item:' + text(row['item']) if text(row['item']) else f"row:{row['date']}:{row['id']}"
        grouped[key].append(row)
    result = {}
    for key, values in grouped.items():
        latest = max(values, key=lambda r: r['id'])
        ranks = {rank(r['rank']) for r in values}
        r = next(iter(ranks)) if len(ranks) == 1 else None
        state = ('batch' if not text(latest['batch_id']) else 'identity' if not text(latest['item']) else
                 'ambiguous' if len(ranks) > 1 else 'invalid' if r is None else
                 'ranked' if r <= LIMIT else 'outside')
        result[key] = {**latest, 'rank': r, 'state': state,
                       'duplicates': len(values), 'record_ids': sorted(v['id'] for v in values)}
    return result


def compare(raw, day, *, samsung=False, today=None):
    dates = [str(day + timedelta(days=i)) for i in (-1, 0, 1)]
    by_day = {d: snapshot([r for r in raw if r['date'] == d]) for d in dates}
    coverage = []
    for d in dates:
        rows = by_day[d]
        available = any(r['state'] in ('ranked', 'outside') for r in rows.values())
        coverage.append({'date': d, 'available': available,
                         'state': 'available' if available else 'invalid' if rows else
                                  'pending' if today and d > str(today) else 'empty',
                         'raw_count': sum(r['duplicates'] for r in rows.values()),
                         'ranked_count': sum(r['state'] == 'ranked' for r in rows.values()),
                         'batch_id': next(iter(rows.values()))['batch_id'] if rows else None})
    products = []
    for key in sorted(set().union(*(set(r) for r in by_day.values()))):
        observations = [by_day[d].get(key) for d in dates]
        # Include the union of three top-300 snapshots, plus malformed records.
        if not any(r and (r['state'] in ('ranked', 'batch', 'identity', 'ambiguous', 'invalid')) for r in observations):
            continue
        latest = next(r for r in reversed(observations) if r)
        is_samsung = any(r and SAMSUNG.search(text(r['name'])) for r in observations)
        if samsung and not is_samsung:
            continue
        cells = [{**r} if r else {'state': 'absent' if coverage[i]['available'] else 'unavailable',
                                  'rank': None, 'record_ids': []} for i, r in enumerate(observations)]
        a, b, c = cells
        before = a['state'] == 'ranked'
        absent_today = coverage[1]['available'] and b['state'] in ('absent', 'outside')
        swings = [abs(cells[i]['rank'] - cells[i-1]['rank']) for i in (1, 2)
                  if cells[i]['state'] in ('ranked', 'outside') and
                  cells[i-1]['state'] in ('ranked', 'outside')]
        missing = before and absent_today
        next_missing = b['state'] == 'ranked' and coverage[2]['available'] and c['state'] in ('absent', 'outside')
        returned = missing and c['state'] == 'ranked'
        data_issue = any(r['state'] in ('batch', 'identity', 'ambiguous', 'invalid') for r in cells)
        # A return from rank 301+ is observed movement, not a collection gap.
        returned = returned and b['state'] == 'absent'
        swing = bool(swings and max(swings) >= SWING)
        status = ('data' if data_issue else 'return' if returned else 'missing' if missing else
                  'next_missing' if next_missing else
                  'swing' if swing else 'unassessed' if not coverage[0]['available'] or not coverage[1]['available'] else
                  'new' if b['state'] == 'ranked' and a['state'] != 'ranked' else
                  'unassessed' if a['state'] != 'ranked' and b['state'] != 'ranked' else 'stable')
        products.append({'key': key, 'item': text(latest['item']), 'sku': text(latest['sku']),
                         'name': text(latest['name']), 'url': text(latest['url']),
                         'samsung': bool(is_samsung), 'cells': cells, 'status': status,
                         'label': LABELS[status], 'review_needed': status in ('data', 'return', 'missing', 'next_missing', 'swing'),
                         'signals': {'return': returned, 'missing': missing, 'next_missing': next_missing, 'swing': swing, 'data': data_issue}})
    products.sort(key=lambda p: (p['cells'][0]['rank'] or 10**9, p['item'], p['key']))
    bands = []
    for b in range(3):
        cohort = [p for p in products if p['cells'][0]['state'] == 'ranked' and bucket(p['cells'][0]['rank']) == b]
        kept = sum(p['cells'][1]['state'] == 'ranked' and bucket(p['cells'][1]['rank']) == b for p in cohort)
        moved = sum(p['cells'][1]['state'] == 'ranked' and bucket(p['cells'][1]['rank']) != b for p in cohort)
        absent = sum(p['cells'][1]['state'] in ('absent', 'outside') for p in cohort)
        unknown = len(cohort) - kept - moved - absent
        comparable = coverage[0]['available'] and coverage[1]['available'] and bool(cohort) and not unknown
        rate = round(kept / len(cohort) * 100, 1) if comparable else None
        bands.append({'tier': b, 'count': len(cohort), 'kept': kept, 'moved': moved,
                      'missing': absent, 'unknown': unknown, 'rate': rate, 'target': TARGETS[b],
                      'below_target': rate is not None and rate < TARGETS[b]})
    return {'dates': dates, 'coverage': coverage, 'products': products, 'bands': bands,
            'counts': {'all': len(products), 'review': sum(p['review_needed'] for p in products),
                       **{s: sum(p['signals'][s] for p in products) for s in ('return', 'missing', 'next_missing', 'swing', 'data')}},
            'criteria': {'swing': SWING, 'targets': TARGETS, 'limit': LIMIT}}
