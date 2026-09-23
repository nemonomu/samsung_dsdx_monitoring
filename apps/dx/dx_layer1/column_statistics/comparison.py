"""Column count comparisons, independent of dashboard volume alerts."""
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from statistics import median

KST = timezone(timedelta(hours=9))
BASELINE_DAYS = 28
MINIMUM_DAYS = 7


def collection_complete(country, product, retailer, source_day, now=None):
    """Use Layer 1's existing collection windows, always with source dates."""
    now = (now or datetime.now(KST)).astimezone(KST)
    if source_day > now.date():
        return False
    if country == 'SEA':
        if retailer == 'HomeDepot':
            from apps.common.sea_collection import collection_schedule, homedepot_source_enabled
            return (homedepot_source_enabled(source_day)
                    and now >= collection_schedule(source_day, retailer) + timedelta(hours=1))
        from apps.common.dx_schedules import get_retail_time_slots
        slots = get_retail_time_slots(product, source_day, now=now.replace(tzinfo=None))
        matching = [s for s in slots if any(
            str(r.get('name', '')).strip().casefold() == retailer.casefold()
            for r in s.get('retailers', []))]
        # SEA appliances have no registered slots in some installations.
        # In that case use the existing D-1 inspection contract; never treat
        # today's partially collected rows as finished merely because they exist.
        if not matching:
            return source_day < now.date()
        return all(not s.get('time_status') for s in matching)
    if country == 'SEDA':
        return source_day < now.date()  # D-1 inspection contract.
    if source_day < now.date():
        return True
    key = country.lower()
    module = import_module(f'apps.common.{key}_retail')
    return getattr(module, f'get_{key}_collection_phase')(now.time().replace(tzinfo=None)) == 'complete'


def compare_columns(data, target, completed):
    start = target - timedelta(days=BASELINE_DAYS)
    history = [day for day in data['daily']
               if str(start) <= day['date'] < str(target)
               and day['total'] > 0 and completed.get(day['date'], False)]
    current = next(day for day in data['daily'] if day['date'] == str(target))
    rows = []
    for column in data['columns']:
        values = [day['counts'][column] for day in history if column in day['counts']]
        baseline = median(values) if len(values) >= MINIMUM_DAYS else None
        count = current['counts'][column]
        ratio = count / baseline * 100 if baseline is not None and baseline > 0 else None
        delta = count - baseline if baseline is not None else None
        if not completed.get(str(target), False):
            status = 'pending'
        elif current['total'] == 0:
            status = 'uncollected'
        elif baseline is None:
            status = 'insufficient'
        elif baseline == 0:
            status = 'no_baseline'
        elif count * 100 <= baseline * 30:
            status = 'abnormal'
        elif count * 100 <= baseline * 60:
            status = 'review'
        else:
            status = 'normal'
        rows.append({'column': column, 'current': count, 'baseline': baseline,
                     'history_days': len(values), 'ratio': ratio, 'delta': delta, 'status': status})
    return rows


def attach_comparisons(data, target, now=None):
    completed = {day['date']: collection_complete(
        data['country'], data['product'], data['retailer'], date.fromisoformat(day['date']), now)
        for day in data['daily']}
    return {**data, 'comparison_date': str(target), 'baseline_days': BASELINE_DAYS,
            'minimum_history_days': MINIMUM_DAYS,
            'comparisons': compare_columns(data, target, completed),
            'completion': completed}
