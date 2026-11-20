"""Layer 1 Jiomart source policy. Existing SIEL retailer policies stay separate."""
from datetime import date, time, timedelta, timezone

RETAILER = 'Jiomart'
START = date(2026, 11, 22)
TEST_DAY = date(2026, 11, 20)
TEST_BATCH = 'j20261120_0534'
TEST_TIMESTAMP = '2026-11-20 05:34:11.610053+00'
REGISTRY = 'dx_siel.jiomart_collection_dates'
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


def scope_sql(table, start, end, *, include_preview=False, registered=False):
    product = _product(table)
    join = ''
    if include_preview:
        # Exact test identity. TEST_DAY comes from the test fixture, not its batch name.
        day = f"'{TEST_DAY}'::date"
        condition = (f"source.batch_id = '{TEST_BATCH}' "
                     f"AND source.crawl_datetime = TIMESTAMPTZ '{TEST_TIMESTAMP}'")
    elif registered:
        day = 'recorded.source_collection_date'
        join = (f"JOIN {REGISTRY} recorded ON recorded.product = '{product}' "
                "AND recorded.batch_id = source.batch_id "
                "AND recorded.crawl_datetime = source.crawl_datetime")
        condition = f"{day} >= DATE '{START}'"
    else:
        day, condition = 'NULL::date', 'FALSE'
    return f"""scoped AS MATERIALIZED (
        SELECT source.*, TO_CHAR({day}, 'YYYY-MM-DD') AS source_day
        FROM {table} source {join}
        WHERE LOWER(BTRIM(source.account_name)) = %s AND {condition}
          AND ({day}) BETWEEN %s::date AND %s::date
    ), latest AS (
        SELECT DISTINCT ON (source_day) source_day, batch_id
        FROM scoped
        ORDER BY source_day, crawl_datetime DESC NULLS LAST, id DESC
    )""", [RETAILER.casefold(), str(start), str(end)]


LATEST_ROWS = ("FROM scoped source JOIN latest ON source.source_day = latest.source_day "
               "AND source.batch_id IS NOT DISTINCT FROM latest.batch_id")


def copy_scope(table, day):
    ctes, params = scope_sql(table, day, day, include_preview=preview(day), registered=day >= START)
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


def _scalar(cursor):
    row = cursor.fetchone()
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def registry_exists(cursor):
    cursor.execute('SELECT to_regclass(%s) IS NOT NULL', (REGISTRY,))
    return _scalar(cursor)


def ready_from(cursor, table, registered):
    if not registered:
        return None
    # A newer unmapped batch is not evidence of a missed collection.
    product = _product(table)
    cursor.execute(f"""
        WITH registered_bounds AS (
            SELECT MIN(crawl_datetime) AS stamp, MIN(source_collection_date) AS first_day FROM {REGISTRY}
            WHERE product = %s AND source_collection_date >= %s
        )
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM {table} source
            WHERE LOWER(BTRIM(source.account_name)) = %s AND source.crawl_datetime >= stamp
              AND NOT EXISTS (SELECT 1 FROM {REGISTRY} recorded WHERE recorded.product = %s
                              AND recorded.batch_id = source.batch_id
                              AND recorded.crawl_datetime = source.crawl_datetime)
        ) THEN first_day END FROM registered_bounds
    """, (product, START, RETAILER.casefold(), product))
    return _scalar(cursor)
