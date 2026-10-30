"""November dryer onboarding; preview dates never become operating history."""
from datetime import date

from apps.common.source_dates import source_date_value

OPERATIONAL_FROM = date(2026, 11, 1)
REQUIRED_COLUMNS = (
    'country', 'account_name', 'item', 'sku', 'retailer_sku_name',
    'product_url', 'final_sku_price', 'count_of_reviews', 'star_rating',
    'count_of_star_ratings', 'capacity',
)
# Preview visibility comes from the supplied source timestamps, not batch IDs.
SOURCES = {
    ('SEG', 'otto'): dict(retailer='OTTO', preview_from=date(2026, 10, 29)),
    ('SEM', 'liverpool'): dict(retailer='Liverpool', preview_from=date(2026, 10, 30)),
    ('SEIB', 'eci'): dict(retailer='ECI', preview_from=date(2026, 10, 29)),
}


def config(country, product, retailer):
    if str(product).lower() not in ('ldy_dryer', str(country).lower() + '_ldy_dryer'):
        return None
    return SOURCES.get((country, str(retailer or '').strip().casefold()))


def is_preview(country, product, retailer, day):
    return bool(config(country, product, retailer)) and source_date_value(day) < str(OPERATIONAL_FROM)


def decorate_row(row, country, product, day):
    """Only these three new selections get preview/launch metadata."""
    if not config(country, product, row['retailer']):
        return row
    row.update(active_from=str(OPERATIONAL_FROM),
               preview_mode=is_preview(country, product, row['retailer'], day))
    if row['preview_mode']:
        received = bool(row.get('raw_count', row.get('actual', 0)))
        row.update(status='OK' if received else 'PENDING',
                   collection_phase='complete' if received else 'pending',
                   expected=None, expected_precise=None, rate=None,
                   difference=None, history_day_count=0, history=[])
    return row


def bsr_policy_pending(country, product, retailer):
    return country in ('SEM', 'SEIB') and bool(config(country, product, retailer))


def operating_history(row, country, day):
    return not is_preview(country, row.get('product'), row.get('retailer'), day)
