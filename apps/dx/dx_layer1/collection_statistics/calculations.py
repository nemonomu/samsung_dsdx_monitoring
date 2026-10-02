"""Pure calculations. Raw source queries belong only to the offline collector."""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from apps.dx.dx_layer1.common.retail_verification import verification_state

COUNTRIES = ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE')
OFFSETS = {'SEA': 1, 'SEDA': 1, 'SIEL': 0, 'SEG': 0, 'SEM': 0, 'TSE': 0}
METRICS = ('main', 'bsr', 'total')
PENDING = {'PENDING', 'COLLECTING', 'ANALYZING', 'VERIFYING'}


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
                collected_count = int(total or 0)
                if country in ('SEM', 'TSE') and retailer.get('actual') is not None:
                    total = retailer['actual']
                verification = verification_state(check, slot, retailer)
                complete = verification == 'ready'
                status = retailer.get('status', 'UNASSESSED')
                rows.append({
                    'product': product, 'retailer': name, 'slot': slot.get('name') or 'daily',
                    'main': int(retailer.get('main_count', items.get('Main Rank', 0)) or 0),
                    'bsr': int(retailer.get('bsr_count', items.get('BSR Rank', 0)) or 0),
                    'total': int(total or 0), 'batch_id': str(retailer.get('batch_id') or ''),
                    'collected_count': collected_count,
                    'verification_state': verification,
                    'complete': complete, 'base_status': status,
                    'baseline_eligible': complete and int(total or 0) > 0 and status != 'ERROR',
                    'active_from': '2026-09-20' if country == 'SEA' and name == 'HomeDepot' else None,
                })
    return sorted(rows, key=row_key)


BSR_POLICY_VERSION = 3
MAIN_POLICY_VERSION = 3
MAIN_CHANGE_PERCENT = 30
OBSERVATION_POLICY_VERSION = 1
MINIMUM_DAYS = 5


def observation_key(row):
    # Observation belongs to a retailer/product, regardless of collection slots.
    return (row['product'], row['retailer'])


def observation_eligible(row):
    return (row.get('complete') and row.get('base_status') != 'ERROR'
            and not row.get('refresh_error')
            and any((row.get(metric) or 0) > 0 for metric in (*METRICS, 'collected_count')))


def remember_observation(days, rows, source_date):
    for row in rows:
        key = observation_key(row)
        if observation_eligible(row) and len(days[key]) < MINIMUM_DAYS:
            days[key].add(source_date)


def tiered_bsr(row, country):
    retailer = str(row['retailer']).strip().casefold()
    product = row['product']
    return ((country == 'SEA' and retailer == 'lowes' and product in ('REF', 'LDY'))
            or (retailer == 'amazon' and product in {
                'SEA': ('TV',), 'SIEL': ('TV', 'REF', 'LDY'), 'SEG': ('TV', 'REF'),
            }.get(country, ())))


def variable_bsr(row, country):
    return tiered_bsr(row, country) or (
        country == 'SEM' and str(row['retailer']).strip().casefold() in ('homedepot', 'coppel'))


def _compare_bsr(row, history, country, *, saved_basis=None):
    """After observation, compare fixed targets or five good days of history."""
    variable = variable_bsr(row, country)
    rule = 'median_28d' if variable else 'fixed_100'
    if not row['complete'] or row.get('base_status') == 'ERROR' or row.get('refresh_error'):
        return rule, 'pending', None, None
    if all((row.get(metric) or 0) == 0 for metric in (*METRICS, 'collected_count')):
        return rule, 'missing', None, None
    if row.get('observation_state') in ('observing', 'unknown'):
        return rule, row['observation_state'], None, None
    current = row.get('bsr')
    if current is None:
        # Older snapshots can contain NULL; never invent zero collected rows.
        return rule, 'insufficient', None, None
    if variable and saved_basis is not None:
        if (saved_basis.get('rule') != rule or saved_basis.get('days', 0) < MINIMUM_DAYS
                or saved_basis.get('value', 0) <= 0):
            return rule, 'insufficient', None, None
        basis = dict(saved_basis)
        baseline = basis['value']
    elif variable:
        days = {}
        for index, old in enumerate(history):
            if (old.get('complete') and old.get('bsr') is not None and old['bsr'] > 0
                    and not any(a.get('metric') == 'bsr' and a.get('status') in ('VOLUME_LOW', 'VOLUME_REVIEW')
                                and a.get('rule') != 'fixed_100'
                                for a in old.get('alerts', []))):
                days[old.get('source_date', index)] = old['bsr']
        if len(days) < MINIMUM_DAYS:
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
    candidate = {**row, 'complete': row.get('complete', row.get('state') == 'complete')}
    if row.get('state', 'complete') != 'complete':
        candidate['complete'] = False
    saved_basis = row.get('baselines', {}).get('bsr', {}) if variable_bsr(row, country) else None
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
    """Compare MAIN against its prior median before rounding."""
    baseline = basis.get('value', 0)
    if current is None or baseline <= 0 or basis.get('days', 0) < MINIMUM_DAYS:
        return None
    change = (current - baseline) * 100
    if change <= -baseline * MAIN_CHANGE_PERCENT:
        status = 'VOLUME_LOW'
    elif change >= baseline * MAIN_CHANGE_PERCENT:
        status = 'VOLUME_HIGH'
    else:
        return None
    percent = change / baseline
    return {'metric': 'main', 'baseline': baseline, 'actual': current,
            'percent': round(percent, 1), 'status': status,
            'reason': f'MAIN 과거 중앙값 {baseline:g}개 / 수집 {current}개 / '
                      + ('30% 이상 감소' if status == 'VOLUME_LOW' else
                         '30% 이상 증가 / 확인 필요')}


def comparison_rules(row, country):
    """Supply historical bases and current policy for evaluating live counts."""
    if row.get('observation_state') != 'ready':
        return {}
    rules = {}
    for metric in ('main', 'bsr'):
        variable = metric == 'main' or variable_bsr(row, country)
        basis = row.get('baselines', {}).get(metric, {})
        if variable:
            if basis.get('days', 0) < MINIMUM_DAYS or basis.get('value', 0) <= 0:
                continue
            if metric == 'bsr' and basis.get('rule') != 'median_28d':
                continue
        else:
            basis = {'value': 100, 'days': 0, 'rule': 'fixed_100'}
        rules[metric] = {
            'baseline': basis['value'], 'days': basis['days'],
            'rule': 'median_28d' if variable else 'fixed_100',
            'low_percent': (20 if tiered_bsr(row, country) else 30) if metric == 'bsr' else MAIN_CHANGE_PERCENT,
            'review_percent': 15 if metric == 'bsr' and tiered_bsr(row, country) else None,
            'high_percent': MAIN_CHANGE_PERCENT if metric == 'main' else None,
        }
    return rules


def current_volume_decision(row, country):
    """Reapply MAIN and BSR policies to stored baselines without database writes."""
    if 'verification_state' not in row and row.get('state') == 'pending':
        received = any((row.get(metric) or 0) > 0 for metric in (*METRICS, 'collected_count'))
        row = {**row, 'verification_state': 'waiting' if received else 'collecting'}
    if 'observation_state' not in row:
        # A saved median proves sufficient prior history. Otherwise wait for the
        # offline rebuild; a missing snapshot is not evidence of a new retailer.
        proven = any(b.get('days', 0) >= MINIMUM_DAYS for b in row.get('baselines', {}).values())
        row = {**row, 'observation_state': 'ready' if proven else 'unknown'}
    result = current_bsr_decision(row, country)
    if row['observation_state'] != 'ready':
        return {**result, 'alerts': [], 'baselines': {},
                'comparison_state': row['observation_state']}
    alerts = [a for a in result.get('alerts', []) if a.get('metric') == 'bsr']
    if (row.get('complete', row.get('state') == 'complete')
            and row.get('state', 'complete') == 'complete'
            and row.get('base_status') != 'ERROR' and not row.get('refresh_error')):
        alert = _main_alert(row.get('main'), row.get('baselines', {}).get('main', {}))
        if alert:
            alerts.insert(0, alert)
    baselines = {k: v for k, v in result.get('baselines', {}).items() if k in ('main', 'bsr')}
    ready = len(comparison_rules({**result, 'baselines': baselines}, country)) == 2
    state = 'pending' if not row.get('complete', row.get('state') == 'complete') else 'ready' if ready else 'insufficient'
    return {**result, 'alerts': alerts, 'baselines': baselines, 'comparison_state': state}


def compare_rows(rows, history, country=None, *, observed_dates=None):
    """history contains only the previous 28 source dates, never the target day."""
    groups = defaultdict(list)
    for old in history:
        # Legacy minimum-count failures are not part of the MAIN/BSR policy.
        eligible = old.get('baseline_eligible') or old.get('base_status') in ('CRITICAL', 'WARNING', 'REVIEW')
        if eligible and observation_eligible(old):
            groups[row_key(old)].append(old)
    if observed_dates is None:
        observed_dates = defaultdict(set)
        for index, old in enumerate(history):
            remember_observation(observed_dates, [old], old.get('source_date', index))
    collected_today = {observation_key(row) for row in rows if observation_eligible(row)}
    result = []
    for row in rows:
        prior_days = min(MINIMUM_DAYS, len(observed_dates.get(observation_key(row), ())))
        observing = prior_days < MINIMUM_DAYS
        row = {**row, 'observation_state': 'observing' if observing else 'ready',
               'observation_days': min(MINIMUM_DAYS, prior_days + (observation_key(row) in collected_today)),
               'observation_prior_days': prior_days,
               'observation_policy_version': OBSERVATION_POLICY_VERSION}
        baselines, alerts = {}, []
        if not observing:
            values = list({old.get('source_date', index): old['main']
                           for index, old in enumerate(groups[row_key(row)])
                           if (old.get('main') or 0) > 0}.values())
            if len(values) >= MINIMUM_DAYS:
                baselines['main'] = {'value': median(values), 'days': len(values)}
                if row['complete'] and row.get('base_status') != 'ERROR' and not row.get('refresh_error'):
                    alert = _main_alert(row.get('main'), baselines['main'])
                    if alert:
                        alerts.append(alert)
        bsr_rule, bsr_state, bsr_basis, bsr_alert = _compare_bsr(
            row, groups[row_key(row)], country or row.get('country'))
        if bsr_basis is not None:
            baselines['bsr'] = bsr_basis
        if bsr_alert:
            alerts.append(bsr_alert)
        state = ('pending' if not row['complete'] else 'observing' if observing else
                 'ready' if all(baselines.get(m, {}).get('value', 0) > 0 for m in ('main', 'bsr')) else 'insufficient')
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
                       'missing_days': sum(not any((r.get(metric) or 0) > 0 for metric in (*METRICS, 'collected_count')) for r in completed),
                       'unknown_days': sum(r['state'] in ('unknown', 'error') for r in daily),
                       'partial': len(completed) < due_days or due_days < 7,
                       'daily': daily})
    return result
