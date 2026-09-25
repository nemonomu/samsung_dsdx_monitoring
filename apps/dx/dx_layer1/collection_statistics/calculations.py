"""Pure calculations. Raw source queries belong only to the offline collector."""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

COUNTRIES = ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE')
OFFSETS = {'SEA': 1, 'SEDA': 1, 'SIEL': 0, 'SEG': 0, 'SEM': 0, 'TSE': 0}
METRICS = ('main', 'bsr', 'total')
PENDING = {'PENDING', 'COLLECTING', 'ANALYZING'}


def row_key(row):
    return (row['product'], row['retailer'], row['slot'])


def normalize_check(check, country, inspection_date):
    """Reuse the exact daily counts already used by Layer1, without adding ranks."""
    source_day = inspection_date - timedelta(days=OFFSETS[country])
    rows = []
    for category in check.get('categories', []):
        product = str(category.get('name') or category.get('category', '')).upper()
        if product not in ('TV', 'REF', 'LDY'):
            continue
        slots = category.get('time_slots') or [{'name': 'daily', 'retailers': category.get('retailers', [])}]
        for slot in slots:
            for retailer in slot.get('retailers', []):
                name = retailer['retailer']
                if country == 'SEA' and name == 'HomeDepot' and source_day < date(2026, 9, 20):
                    continue
                items = {item['name']: int(item.get('count') or 0) for item in retailer.get('items', [])}
                total = next((retailer[key] for key in ('raw_count', 'actual', 'count', 'total')
                              if retailer.get(key) is not None), 0)
                if country in ('SEM', 'TSE') and retailer.get('actual') is not None:
                    total = retailer['actual']
                complete = (check.get('phase', 'complete') == 'complete'
                            and retailer.get('status') not in PENDING
                            and slot.get('status') not in PENDING)
                status = retailer.get('status', 'UNASSESSED')
                rows.append({
                    'product': product, 'retailer': name, 'slot': slot.get('name') or 'daily',
                    'main': int(retailer.get('main_count', items.get('Main Rank', 0)) or 0),
                    'bsr': int(retailer.get('bsr_count', items.get('BSR Rank', 0)) or 0),
                    'total': int(total or 0), 'batch_id': str(retailer.get('batch_id') or ''),
                    'complete': complete, 'base_status': status,
                    'baseline_eligible': complete and int(total or 0) > 0 and status not in ('CRITICAL', 'WARNING', 'ERROR'),
                    'active_from': '2026-09-20' if country == 'SEA' and name == 'HomeDepot' else None,
                })
    return sorted(rows, key=row_key)


BSR_POLICY_VERSION = 2
MAIN_POLICY_VERSION = 1


def tiered_bsr(row, country):
    retailer = str(row['retailer']).strip().casefold()
    product = row['product']
    return ((country == 'SEA' and retailer == 'lowes' and product in ('REF', 'LDY'))
            or (retailer == 'amazon' and product in {
                'SEA': ('TV',), 'SIEL': ('TV', 'REF', 'LDY'), 'SEG': ('TV', 'REF'),
            }.get(country, ())))


def variable_bsr(row, country):
    return tiered_bsr(row, country) or (
        country == 'SEM' and str(row['retailer']).strip().casefold() == 'homedepot')


def _compare_bsr(row, history, country, *, saved_basis=None):
    """Fixed targets need no history; variable targets require seven good days."""
    variable = variable_bsr(row, country)
    rule = 'median_28d' if variable else 'fixed_100'
    if not row['complete'] or row.get('base_status') == 'ERROR' or row.get('refresh_error'):
        return rule, 'pending', None, None
    if all(row.get(metric) == 0 for metric in METRICS):
        return rule, 'missing', None, None
    current = row.get('bsr')
    if current is None:
        # Older snapshots can contain NULL; never invent zero collected rows.
        return rule, 'insufficient', None, None
    if variable and saved_basis is not None:
        if (saved_basis.get('rule') != rule or saved_basis.get('days', 0) < 7
                or saved_basis.get('value', 0) <= 0):
            return rule, 'insufficient', None, None
        basis = dict(saved_basis)
        baseline = basis['value']
    elif variable:
        days = {}
        for index, old in enumerate(history):
            if (old.get('complete') and old.get('bsr') is not None and old['bsr'] > 0
                    and not any(a.get('metric') == 'bsr' and a.get('status') in ('VOLUME_LOW', 'VOLUME_REVIEW')
                                and not (tiered_bsr(row, country) and a.get('rule') == 'fixed_100')
                                for a in old.get('alerts', []))):
                days[old.get('source_date', index)] = old['bsr']
        if len(days) < 7:
            return rule, 'insufficient', None, None
        baseline = median(days.values())
        basis = {'value': baseline, 'days': len(days), 'rule': rule}
    else:
        baseline = 100
        basis = {'value': baseline, 'days': 0, 'rule': rule}
    threshold = 15 if tiered_bsr(row, country) else 30
    low = ((baseline - current) * 100 >= baseline * threshold
           if variable else current < baseline)
    alert = None
    if low:
        review = tiered_bsr(row, country) and (baseline - current) * 100 < baseline * 20
        threshold = 15 if review else 20 if tiered_bsr(row, country) else 30
        alert = {'metric': 'bsr', 'baseline': baseline, 'actual': current,
                 'percent': round((current - baseline) * 100 / baseline, 1),
                 'status': 'VOLUME_REVIEW' if review else 'VOLUME_LOW', 'rule': rule,
                 'reason': (f'BSR 기준 100개 / 수집 {current}개 / {100-current}개 부족'
                            if not variable else
                            f'BSR 과거 중앙값 {baseline:g}개 / 수집 {current}개 / {threshold}% 이상 감소'
                            + (' / 확인 필요' if review else ''))}
    return rule, 'ready', basis, alert


def current_bsr_decision(row, country):
    """Reapply current thresholds using stored counts and a valid median only.

    Legacy fixed baselines cannot stand in for history. The offline collector
    rebuilds them; until then their BSR comparison is insufficient.
    """
    if variable_bsr(row, country) and not tiered_bsr(row, country):
        return row
    candidate = {**row, 'complete': row.get('complete', row.get('state') == 'complete')}
    if row.get('state', 'complete') != 'complete':
        candidate['complete'] = False
    saved_basis = row.get('baselines', {}).get('bsr', {}) if tiered_bsr(row, country) else None
    rule, state, basis, alert = _compare_bsr(candidate, [], country, saved_basis=saved_basis)
    baselines = {k: v for k, v in row.get('baselines', {}).items() if k != 'bsr'}
    if basis is not None:
        baselines['bsr'] = basis
    alerts = [a for a in row.get('alerts', []) if a.get('metric') != 'bsr']
    if alert:
        alerts.append(alert)
    return {**row, 'baselines': baselines, 'alerts': alerts,
            'bsr_rule': rule, 'bsr_comparison_state': state}


def _main_alert(current, basis):
    """Classify before rounding: 5 through 15 percent down needs review."""
    baseline = basis.get('value', 0)
    if current is None or baseline <= 0 or basis.get('days', 0) < 7:
        return None
    change = (current - baseline) * 100
    if change < -baseline * 15:
        status = 'VOLUME_LOW'
    elif change <= -baseline * 5:
        status = 'VOLUME_REVIEW'
    elif change >= baseline * 30:
        status = 'VOLUME_HIGH'
    else:
        return None
    percent = change / baseline
    return {'metric': 'main', 'baseline': baseline, 'actual': current,
            'percent': round(percent, 1), 'status': status,
            'reason': f'MAIN 과거 중앙값 {baseline:g}개 / 수집 {current}개 / '
                      + ('15% 초과 감소' if status == 'VOLUME_LOW' else
                         '5~15% 감소 / 확인 필요' if status == 'VOLUME_REVIEW' else
                         '30% 이상 증가 / 확인 필요')}


def current_volume_decision(row, country):
    """Reapply MAIN and BSR policies to stored baselines without database writes."""
    result = current_bsr_decision(row, country)
    alerts = [a for a in result.get('alerts', []) if a.get('metric') != 'main']
    if (row.get('complete', row.get('state') == 'complete')
            and row.get('state', 'complete') == 'complete'
            and row.get('base_status') != 'ERROR' and not row.get('refresh_error')):
        alert = _main_alert(row.get('main'), row.get('baselines', {}).get('main', {}))
        if alert:
            alerts.insert(0, alert)
    return {**result, 'alerts': alerts}


def compare_rows(rows, history, country=None):
    """history contains only the previous 28 source dates, never the target day."""
    groups = defaultdict(list)
    for old in history:
        if old.get('baseline_eligible'):
            groups[row_key(old)].append(old)
    result = []
    for row in rows:
        baselines, alerts = {}, []
        for metric in METRICS:
            if metric == 'bsr':
                continue
            values = [old[metric] for old in groups[row_key(row)] if old.get(metric) is not None]
            if len(values) < 7:
                continue
            baseline = median(values)
            baselines[metric] = {'value': baseline, 'days': len(values)}
            current = row.get(metric)
            if not row['complete'] or baseline <= 0 or current is None:
                continue
            if metric == 'main':
                if row.get('base_status') != 'ERROR' and not row.get('refresh_error'):
                    alert = _main_alert(current, baselines[metric])
                    if alert:
                        alerts.append(alert)
                continue
            # Compare before rounding: 29.95% must not become an alert.
            delta = (current - baseline) * 100 / baseline
            if abs(delta) >= 30:
                alerts.append({'metric': metric, 'baseline': baseline, 'actual': current,
                               'percent': round(delta, 1), 'status': 'VOLUME_LOW' if delta < 0 else 'VOLUME_HIGH'})
        bsr_rule, bsr_state, bsr_basis, bsr_alert = _compare_bsr(
            row, groups[row_key(row)], country or row.get('country'))
        if bsr_basis is not None:
            baselines['bsr'] = bsr_basis
        if bsr_alert:
            alerts.append(bsr_alert)
        state = ('pending' if not row['complete'] else 'ready' if len(baselines) == len([m for m in METRICS if row.get(m) is not None]) else 'insufficient')
        result.append({**row, 'baselines': baselines, 'alerts': alerts, 'comparison_state': state,
                       'bsr_policy_version': BSR_POLICY_VERSION,
                       'main_policy_version': MAIN_POLICY_VERSION,
                       'bsr_rule': bsr_rule, 'bsr_comparison_state': bsr_state})
    return result


def week_start(day):
    return day - timedelta(days=day.weekday())


def build_week(rows_by_date, monday, last_due_date):
    """Missing snapshots are unknown, while recorded completed zeros count in averages."""
    groups = defaultdict(dict)
    for day, rows in rows_by_date.items():
        if monday <= day <= monday + timedelta(days=6):
            for row in rows:
                groups[row_key(row)][day] = row
    due_end = min(monday + timedelta(days=6), last_due_date)
    result = []
    for (product, retailer, slot), days in sorted(groups.items()):
        active_from = next((date.fromisoformat(row['active_from']) for row in days.values() if row.get('active_from')), monday)
        due_days = max(0, (due_end - max(monday, active_from)).days + 1)
        daily = []
        for offset in range(7):
            day = monday + timedelta(days=offset)
            row = days.get(day)
            state = ('not_scheduled' if day < active_from else 'future' if day > last_due_date
                     else 'unknown' if row is None else 'error' if row.get('refresh_error')
                     else 'complete' if row['complete'] else 'pending')
            daily.append({'date': str(day), 'state': state, **(row or {})})
        completed = [r for r in daily if r['state'] == 'complete']
        metrics = {}
        for metric in METRICS:
            values = [r[metric] for r in completed if r.get(metric) is not None]
            metrics[metric] = {'sum': sum(values) if values else None,
                               'average': round(sum(values) / len(values), 1) if values else None}
        result.append({'product': product, 'retailer': retailer, 'slot': slot,
                       'metrics': metrics, 'completed_days': len(completed), 'expected_days': due_days,
                       'missing_days': sum(r['total'] == 0 for r in completed),
                       'unknown_days': sum(r['state'] in ('unknown', 'error') for r in daily),
                       'partial': len(completed) < due_days or due_days < 7,
                       'daily': daily})
    return result
