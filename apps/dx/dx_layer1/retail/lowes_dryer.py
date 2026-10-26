"""SEA Lowes dryer monitoring, using the original DB collection date."""
from datetime import date, datetime

from apps.common.sea_collection import KST, afternoon_collection_phase
from apps.common.source_dates import source_date_sql as original_date_sql

FIRST_SOURCE_DATE = date(2026, 10, 17)
NULL_COLUMNS = (
    'country', 'account_name', 'item', 'sku', 'retailer_sku_name',
    'product_url', 'final_sku_price', 'star_rating',
    'count_of_star_ratings', 'count_of_reviews', 'capacity',
)


def matches(product, retailer):
    return ('ldy_dryer' in str(product).lower()
            and str(retailer or '').strip().casefold() == 'lowes')


def enabled(source_date):
    return str(source_date)[:10] >= str(FIRST_SOURCE_DATE)


def complete(source_date, now=None):
    phase = afternoon_collection_phase(source_date, 'Lowes', now)
    if phase is not None:
        return enabled(source_date) and phase == 'complete'
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    # D-1 inspection is separate from the date recorded in crawl_datetime.
    return enabled(source_date) and str(source_date)[:10] < current.date().isoformat()


def source_date_sql(column):
    day = original_date_sql(column)
    return f"(CASE WHEN {day} >= '{FIRST_SOURCE_DATE}' THEN {day} END)"
