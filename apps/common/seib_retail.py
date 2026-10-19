"""Spain MediaMarkt source contract for collection, NULL, and format checks."""
from datetime import date, datetime, time

from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql, source_date_value

SEIB_COUNTRY = 'SEIB'
FIRST_SOURCE_DATE = date(2026, 10, 18)
RETAILER = 'MediaMarkt'
COMMON_REQUIRED = (
    'country', 'account_name', 'item', 'sku', 'retailer_sku_name', 'product_url',
    'final_sku_price', 'count_of_reviews', 'star_rating', 'count_of_star_ratings',
)
COMMON_COLUMNS = (
    'id', 'batch_id', *COMMON_REQUIRED, 'original_sku_price', 'savings',
    'main_rank', 'bsr_rank', 'crawl_datetime', 'calendar_week',
)
SEIB_SOURCE_CONFIG = {
    'seib_' + product: {
        'source_key': 'seib_' + product, 'product_key': product,
        'category': product.upper(), 'section_code': 'seib_' + product + '_retail',
        'display_name': 'SEIB ' + product.upper(),
        'table_name': 'dx_seib.dx_seib_' + product + '_retail_com',
        'date_column': 'crawl_datetime', 'retailers': (RETAILER,),
        'has_page_type': False, 'has_redirect': False,
        'required_columns': (*COMMON_REQUIRED, required),
        'columns': (*COMMON_COLUMNS, *extras),
    }
    for product, required, extras in (
        ('tv', 'screen_size', ('screen_size',)),
        ('ref', 'ref_capacity', ('ref_capacity', 'ref_refrigerator_type')),
        ('ldy', 'capacity', ('capacity', 'loading_type')),
        ('ldy_dryer', 'capacity', ('capacity', 'loading_type')),
    )
}


def product_line_for(value):
    key = str(value or '').strip().lower()
    for product_line, source in SEIB_SOURCE_CONFIG.items():
        if key in (product_line, source['section_code'], source['table_name'], source['table_name'].split('.')[-1]):
            return product_line
    return None


def get_seib_source(value):
    key = product_line_for(value)
    if key is None:
        raise ValueError('Unsupported SEIB source')
    return SEIB_SOURCE_CONFIG[key]


def get_seib_null_columns(value, retailer=None):
    if retailer is not None and str(retailer).strip().casefold() != RETAILER.casefold():
        raise ValueError('Unsupported SEIB retailer')
    return get_seib_source(value)['required_columns']


def get_seib_null_select_columns(value):
    return get_seib_source(value)['columns']


def seib_retailer_key(value):
    return str(value or '').strip().casefold()


def enabled(day):
    return source_date_value(day) >= str(FIRST_SOURCE_DATE)


def collection_phase(day, now=None):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    selected = date.fromisoformat(source_date_value(day))
    if not enabled(day) or selected > current.date():
        return 'pending'
    if selected < current.date() or current.time().replace(tzinfo=None) >= time(4):
        return 'complete'
    return 'pending' if current.time().replace(tzinfo=None) < time(1) else 'collecting'


def latest_scope(source, start, end, retailer=RETAILER):
    """One latest batch per original source day; never infer a day from batch_id."""
    if str(retailer).strip().casefold() != RETAILER.casefold():
        raise ValueError('Unsupported SEIB retailer')
    day = source_date_sql('anchor.crawl_datetime')
    source_day = source_date_sql('source.crawl_datetime')
    cte = f"""WITH latest AS (
        SELECT DISTINCT ON ({day}) {day} AS source_date, anchor.batch_id
        FROM {source['table_name']} anchor
        WHERE {day} BETWEEN %s AND %s
          AND LOWER(BTRIM(anchor.account_name)) = %s
        ORDER BY {day}, anchor.id DESC
    )"""
    scope = f"""FROM {source['table_name']} source
        JOIN latest ON {source_day} = latest.source_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(source.account_name)) = %s"""
    return cte, scope, [max(str(start), str(FIRST_SOURCE_DATE)), str(end), RETAILER.lower(), RETAILER.lower()]
