"""SEA HomeDepot dryer launch and original DB collection-date policy."""
from datetime import date, datetime

from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql as original_date_sql

FIRST_SOURCE_DATE = date(2026, 10, 15)


def matches(product, retailer):
    return ('ldy_dryer' in str(product).lower()
            and str(retailer or '').strip().casefold() == 'homedepot')


def enabled(source_date):
    return str(source_date)[:10] >= str(FIRST_SOURCE_DATE)


def complete(source_date, now=None):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    # No confirmed same-day completion window; use SEA's D-1 inspection.
    return enabled(source_date) and str(source_date)[:10] < current.date().isoformat()


def source_date_sql(column):
    day = original_date_sql(column)
    return f"(CASE WHEN {day} >= '{FIRST_SOURCE_DATE}' THEN {day} END)"
