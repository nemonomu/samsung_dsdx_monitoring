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
                    'bsr': None if retailer.get('bsr_applicable') is False else int(retailer.get('bsr_count', items.get('BSR Rank', 0)) or 0),
                    'total': int(total or 0), 'batch_id': str(retailer.get('batch_id') or ''),
                    'complete': complete, 'base_status': status,
                    'baseline_eligible': complete and int(total or 0) > 0 and status not in ('CRITICAL', 'WARNING', 'ERROR'),
                    'active_from': '2026-09-20' if country == 'SEA' and name == 'HomeDepot' else None,
                })
    return sorted(rows, key=row_key)


def compare_rows(rows, history):
    """history contains only the previous 28 source dates, never the target day."""
    groups = defaultdict(list)
    for old in history:
        if old.get('baseline_eligible'):
            groups[row_key(old)].append(old)
    result = []
    for row in rows:
        baselines, alerts = {}, []
        for metric in METRICS:
            values = [old[metric] for old in groups[row_key(row)] if old.get(metric) is not None]
            if len(values) < 7:
                continue
            baseline = median(values)
            baselines[metric] = {'value': baseline, 'days': len(values)}
            current = row.get(metric)
            if not row['complete'] or baseline <= 0 or current is None:
                continue
            # Compare before rounding: 29.95% must not become an alert.
            delta = (current - baseline) * 100 / baseline
            if abs(delta) >= 30:
                alerts.append({'metric': metric, 'baseline': baseline, 'actual': current,
                               'percent': round(delta, 1), 'status': 'VOLUME_LOW' if delta < 0 else 'VOLUME_HIGH'})
        state = ('pending' if not row['complete'] else 'ready' if len(baselines) == len([m for m in METRICS if row.get(m) is not None]) else 'insufficient')
        result.append({**row, 'baselines': baselines, 'alerts': alerts, 'comparison_state': state})
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
