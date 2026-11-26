"""Column count comparisons, independent of dashboard volume alerts."""
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from statistics import median
from apps.common.dryer_onboarding import config as dryer_config, OPERATIONAL_FROM
from apps.common.seib_retail import (ECI_APPLIANCE_START, ECI_OBSERVATION_DAYS,
                                    is_eci_appliance, is_eci_appliance_preview)
from apps.dx.dx_layer1.retail import costco, bestbuy_dryer, homedepot_dryer, lowes_dryer
from apps.dx.dx_layer1.siel_retail import jiomart
from apps.dx.dx_layer1.seuk_retail import sources as seuk

KST = timezone(timedelta(hours=9))
BASELINE_DAYS = 28
MINIMUM_DAYS = 7


def collection_complete(country, product, retailer, source_day, now=None):
    """Use Layer 1's existing collection windows, always with source dates."""
    now = (now or datetime.now(KST)).astimezone(KST)
    if jiomart.matches(country, product, retailer):
        return jiomart.phase(source_day, now) == 'complete'
    if dryer_config(country, product, retailer) and source_day < OPERATIONAL_FROM:
        return False
    if country == 'SEM':
        from apps.common.sem_retail import sem_start_date
        launch = sem_start_date('sem_' + product.lower(), retailer)
        if launch and source_day < launch:
            return False
    if country == 'SEG':
        from apps.dx.dx_layer1.seg_retail.sources import retailer_start_date, get_seg_source
        launch = retailer_start_date(get_seg_source('seg_' + product.lower()), retailer)
        if launch and source_day < launch:
            return False
    if source_day > now.date():
        return False
    if country == 'SEUK':
        if seuk.new_tv_retailer(country, product, retailer) and source_day < seuk.TV_START:
            return False
        return seuk.collection_phase(source_day, now) == 'complete'
    if country == 'SEIB':
        from apps.common.seib_retail import collection_phase
        from apps.common.seib_retail import get_seib_source
        return collection_phase(source_day, now, source=get_seib_source('seib_' + product.lower()), retailer=retailer) == 'complete'
    if country == 'SEA':
        from apps.common.sea_collection import afternoon_collection_phase
        afternoon_phase = afternoon_collection_phase(source_day, retailer, now)
        if afternoon_phase is not None:
            return afternoon_phase == 'complete'
        if lowes_dryer.matches(product, retailer):
            return lowes_dryer.complete(source_day, now)
        if homedepot_dryer.matches(product, retailer):
            return homedepot_dryer.complete(source_day, now)
        if bestbuy_dryer.matches(product, retailer):
            return bestbuy_dryer.complete(source_day, now)
        if retailer == 'Costco':
            return costco.enabled(source_day, product) and costco.complete(source_day, now)
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
    eci_appliance = data.get('country') == 'SEIB' and is_eci_appliance(data.get('product'), data.get('retailer'))
    is_jiomart = jiomart.matches(data.get('country'), data.get('product'), data.get('retailer'))
    excluded = (seuk.COLUMN_ALERT_EXCLUSIONS.get(str(data.get('retailer')).strip().casefold())
                if seuk.new_tv_retailer(data.get('country'), data.get('product'), data.get('retailer')) else None)
    if eci_appliance:
        history = [day for day in history if day['date'] >= str(ECI_APPLIANCE_START)]
    rows = []
    for column in data['columns']:
        count = current['counts'][column]
        if column == excluded:
            rows.append({'column': column, 'current': count, 'baseline': None, 'history_days': 0,
                         'ratio': None, 'delta': None, 'status': 'not_applicable'})
            continue
        values = [day['counts'][column] for day in history if column in day['counts']]
        baseline = median(values) if len(values) >= minimum_days(data) else None
        ratio = count / baseline * 100 if baseline is not None and baseline > 0 else None
        delta = count - baseline if baseline is not None else None
        if current['total'] and ((eci_appliance and is_eci_appliance_preview(data['product'], data['retailer'], target))
                                 or (is_jiomart and jiomart.preview(target))):
            status = 'preview'
        elif data.get('active_from') and str(target) < data['active_from']:
            status = 'not_scheduled'
        elif not completed.get(str(target), False):
            status = 'pending'
        elif current.get('raw_total', current['total']) == 0:
            status = 'uncollected'
        elif current['total'] == 0:
            status = 'no_scoped_rows'
        elif ((eci_appliance and column == 'savings')
              or costco.optional_null_column(data.get('country'), data.get('retailer'), column)):
            status = 'normal'
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


def minimum_days(data):
    if jiomart.matches(data.get('country'), data.get('product'), data.get('retailer')):
        return 5
    if data.get('country') == 'SEIB' and is_eci_appliance(data.get('product'), data.get('retailer')):
        return ECI_OBSERVATION_DAYS
    return costco.MINIMUM_DAYS if data.get('country') == 'SEA' and data.get('retailer') == 'Costco' else MINIMUM_DAYS


def attach_comparisons(data, target, now=None):
    scope = (data['country'], data['product'], data['retailer'])
    now = now or datetime.now(KST)
    completed = {day['date']: collection_complete(
        *scope, date.fromisoformat(day['date']), now)
        for day in data['daily']}
    target_key = str(target)
    if completed.get(target_key) and data.get('updated_at'):
        read_at = datetime.fromisoformat(data['updated_at'])
        completed[target_key] = collection_complete(*scope, target, read_at)
    return {**data, 'comparison_date': str(target), 'baseline_days': BASELINE_DAYS,
            'minimum_history_days': minimum_days(data),
            'comparisons': compare_columns(data, target, completed),
            'completion': completed}
