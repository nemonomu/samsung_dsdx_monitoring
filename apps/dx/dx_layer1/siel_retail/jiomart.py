"""Layer 1 Jiomart batches and schedule within the SIEL business day."""
from datetime import date, time, timedelta, timezone

from apps.common.siel_retail import SIEL_BUSINESS_TIMEZONE

RETAILER = 'Jiomart'
START = date(2026, 11, 22)
TEST_DAY = date(2026, 11, 20)
TEST_BATCH = 'j20261120_0534'
TEST_TIMESTAMP = '2026-11-20 05:34:11.610053+00'
DATE_BASIS = 'siel_business_day'
WINDOW = 'KST 09:00~11:00'
KST = timezone(timedelta(hours=9))
METADATA_COLUMNS = (
    'item', 'sku', 'retailer_sku_name', 'product_url', 'final_sku_price',
    'original_sku_price', 'savings', 'star_rating', 'count_of_star_ratings',
    'count_of_reviews',
)
PRODUCT_COLUMNS = {
    'TV': ('screen_size',), 'REF': ('ref_capacity', 'ref_refrigerator_type'),
    'LDY': ('ldy_capacity', 'ldy_loading_type'),
}


def matches(country, product, retailer):
    return (country == 'SIEL' and str(product).upper().removeprefix('SIEL_') in PRODUCT_COLUMNS
            and str(retailer).strip().casefold() == RETAILER.casefold())


def preview(day):
    return str(day) == str(TEST_DAY)


def scope_start(day):
    return TEST_DAY if preview(day) else START


def phase(day, now):
    current = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    if day < START or day > current.date():
        return 'pending'
    if day < current.date() or current.time() >= time(11):
        return 'complete'
    return 'pending' if current.time() < time(9) else 'collecting'


def _product(table):
    key = table.removeprefix('dx_siel.dx_siel_').removesuffix('_retail_com').upper()
    if key not in PRODUCT_COLUMNS or table != f'dx_siel.dx_siel_{key.lower()}_retail_com':
        raise ValueError('Unsupported Jiomart table')
    return key


def scope_sql(table, start, end, *, include_preview=False):
    _product(table)
    start = str(start)
    if include_preview:
        # Exact test identity. TEST_DAY comes from the test fixture, not its batch name.
        day = f"'{TEST_DAY}'::date"
        condition = (f"source.batch_id = '{TEST_BATCH}' "
                     f"AND source.crawl_datetime = TIMESTAMPTZ '{TEST_TIMESTAMP}' "
                     f"AND {day} BETWEEN %s::date AND %s::date")
    else:
        start = max(start, str(START))
        zone = SIEL_BUSINESS_TIMEZONE
        day = f"source.crawl_datetime AT TIME ZONE '{zone}'"
        condition = (f"source.crawl_datetime >= (%s::date::timestamp AT TIME ZONE '{zone}') "
                     f"AND source.crawl_datetime < ((%s::date + 1)::timestamp AT TIME ZONE '{zone}')")
    return f"""scoped AS MATERIALIZED (
        SELECT source.*, TO_CHAR({day}, 'YYYY-MM-DD') AS source_day
        FROM {table} source
        WHERE LOWER(BTRIM(source.account_name)) = %s AND {condition}
    ), latest AS (
        SELECT DISTINCT ON (source_day) source_day, batch_id
        FROM scoped
        ORDER BY source_day, crawl_datetime DESC NULLS LAST, id DESC
    )""", [RETAILER.casefold(), start, str(end)]


LATEST_ROWS = ("FROM scoped source JOIN latest ON source.source_day = latest.source_day "
               "AND source.batch_id IS NOT DISTINCT FROM latest.batch_id")


def copy_scope(table, day):
    ctes, params = scope_sql(table, day, day, include_preview=preview(day))
    for value in params:
        ctes = ctes.replace('%s', "'" + value.replace("'", "''") + "'", 1)
    return ctes


def copy_queries(table, day):
    ctes = copy_scope(table, day)
    return {
        'count': f'WITH {ctes}\nSELECT COUNT(*) AS collected_rows {LATEST_ROWS};',
        'rows': f'WITH {ctes}\nSELECT source.* {LATEST_ROWS} ORDER BY source.id;',
        'batches': f'WITH {ctes}\nSELECT batch_id, COUNT(*) FROM scoped GROUP BY batch_id;',
    }
