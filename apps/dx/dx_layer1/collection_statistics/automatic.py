"""Bounded background refresh: recent days first, then one history chunk per country."""
from datetime import timedelta
from apps.common.dryer_onboarding import SOURCES as DRYER_SOURCES, is_preview

from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily
from .calculations import COUNTRIES, OFFSETS, SOURCE_START_DATES
from .collector import refresh_country
from apps.common.seib_retail import FIRST_SOURCE_DATE as SEIB_START_DATE
from apps.common.sem_retail import SEM_DRYER_FIRST_SOURCE_DATE, SEM_COPPEL_DRYER_FIRST_SOURCE_DATE
from apps.dx.dx_layer1.retail import costco, bestbuy_dryer, homedepot_dryer, lowes_dryer
from apps.dx.dx_layer1.seg_retail.sources import EXPERT_START_DATE, EXPERT_COLUMNS, MEDIAMARKT_DRYER_START_DATE


def history_range(country, last_due):
    start, end = last_due - timedelta(days=111), last_due - timedelta(days=3)
    if country in SOURCE_START_DATES:
        start = max(start, SOURCE_START_DATES[country])
        if start > end:
            return None
    stored = {day for day, rows in Daily.objects.filter(country=country, refresh_error=False,
        source_date__range=(start, end)).values_list('source_date', 'rows')
        if not any(row.get('bsr') is None for row in rows)
        and not any(is_preview(country, r['product'], r['retailer'], day) and r.get('collected_count', r.get('total', 0)) for r in rows)
        and all(day < spec['preview_from'] or any(
            r['product'] == product and r['retailer'] == spec['retailer']
            and r.get('source_date_basis') == 'db_original' for r in rows)
            for (code, _), spec in DRYER_SOURCES.items() if code == country
            for product in spec.get('products', ('LDY_DRYER',)))
        and (country != 'SEA' or all(
            row.get('source_date_basis') == 'db_original'
            for row in rows if row['retailer'] in ('Costco', 'HomeDepot')))
        and (country != 'SEA' or not lowes_dryer.enabled(day)
             or any(lowes_dryer.matches(r['product'], r['retailer'])
                    and r.get('source_date_basis') == 'db_original' for r in rows))
        and (country != 'SEA' or not homedepot_dryer.enabled(day)
             or any(homedepot_dryer.matches(r['product'], r['retailer']) for r in rows))
        and (country != 'SEA' or not bestbuy_dryer.enabled(day)
             or any(bestbuy_dryer.matches(r['product'], r['retailer']) for r in rows))
        and (country != 'SEA' or not costco.enabled(day)
             or {r['product'] for r in rows if r['retailer'] == 'Costco'} ==
                ({'TV', 'REF', 'LDY', 'LDY_DRYER'} if costco.enabled(day, 'ldy_dryer') else {'TV', 'REF', 'LDY'}))
        and (country != 'SEUK' or {r['product'] for r in rows if r['retailer'] == 'Currys'
             and r.get('source_date_basis') == 'db_original'} == {'TV', 'REF', 'LDY', 'LDY_DRYER'})
        and (country != 'SEIB' or day < SEIB_START_DATE
             or {r['product'] for r in rows if r['retailer'] == 'MediaMarkt'
                 and r.get('source_date_basis') == 'db_original'} == {'TV', 'REF', 'LDY', 'LDY_DRYER'})
        and (country != 'SEM' or day < SEM_DRYER_FIRST_SOURCE_DATE
             or any(r['product'] == 'LDY_DRYER' and r['retailer'] == 'HomeDepot'
                    and r.get('source_date_basis') == 'db_original' for r in rows))
        and (country != 'SEM' or day < SEM_COPPEL_DRYER_FIRST_SOURCE_DATE
             or any(r['product'] == 'LDY_DRYER' and r['retailer'] == 'Coppel'
                    and r.get('source_date_basis') == 'db_original' for r in rows))
        and (country != 'SEG' or day < EXPERT_START_DATE
             or {r['product'] for r in rows if r['retailer'] == 'Expert'} == set(EXPERT_COLUMNS))
        and (country != 'SEG' or day < MEDIAMARKT_DRYER_START_DATE
             or any(r['product'] == 'LDY_DRYER' and r['retailer'] == 'Mediamarkt'
                    and r.get('source_date_basis') == 'db_original' for r in rows))}
    # Most recent missing history first, so the default page becomes useful early.
    day = end
    while day >= start and day in stored:
        day -= timedelta(days=1)
    if day < start:
        return None
    chunk_end = day
    while day > start and (chunk_end - day).days < 13 and day - timedelta(days=1) not in stored:
        day -= timedelta(days=1)
    return day, chunk_end


def refresh_automatic(today, *, countries=COUNTRIES, refresh=None, report=None):
    refresh = refresh or refresh_country
    report = report or (lambda *_: None)
    errors, ready = 0, []
    # Every country gets current data before any country starts its backfill.
    for country in countries:
        end = today - timedelta(days=OFFSETS[country])
        result = refresh(country, end - timedelta(days=2), end, today=today)
        report(country, 'recent', result)
        errors += result['errors']
        if not result['busy'] and not result['errors']:
            ready.append((country, end))
    for country, end in ready:
        missing = history_range(country, end)
        if missing:
            result = refresh(country, *missing, today=today)
            report(country, 'history', result)
            errors += result['errors']
    return errors
