"""Bounded background refresh: recent days first, then one history chunk per country."""
from datetime import timedelta

from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily
from .calculations import COUNTRIES, OFFSETS
from .collector import refresh_country


def history_range(country, last_due):
    start, end = last_due - timedelta(days=111), last_due - timedelta(days=3)
    stored = set(Daily.objects.filter(country=country, refresh_error=False,
        source_date__range=(start, end)).values_list('source_date', flat=True))
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
