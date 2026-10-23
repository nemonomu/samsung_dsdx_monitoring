"""UK Currys source contract, using the original collection date."""
from datetime import date, datetime, time

from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql, source_date_value

SEUK_COUNTRY = 'SEUK'
# Temporary preview requested by the user. Restore to October 25 at final rollout.
FIRST_SOURCE_DATE = date(2026, 10, 23)
RETAILER = 'Currys'
COMMON_REQUIRED = (
    'country', 'account_name', 'item', 'sku', 'retailer_sku_name', 'product_url',
    'final_sku_price', 'count_of_reviews', 'star_rating', 'count_of_star_ratings',
)
COMMON_COLUMNS = (
    'id', 'batch_id', *COMMON_REQUIRED, 'original_sku_price', 'savings',
    'main_rank', 'bsr_rank', 'crawl_datetime', 'calendar_week',
)
SEUK_SOURCE_CONFIG = {
    'seuk_' + product: {
        'source_key': 'seuk_' + product, 'product_key': product,
        'category': product.upper(), 'section_code': 'seuk_' + product + '_retail',
        'display_name': 'SEUK ' + product.upper(),
        'table_name': 'dx_seuk.dx_seuk_' + product + '_retail_com',
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
    for product_line, source in SEUK_SOURCE_CONFIG.items():
        if key in (product_line, source['section_code'], source['table_name'], source['table_name'].split('.')[-1]):
            return product_line
    return None


def get_seuk_source(value):
    key = product_line_for(value)
    if key is None:
        raise ValueError('Unsupported SEUK source')
    return SEUK_SOURCE_CONFIG[key]


def seuk_retailer_key(value):
    return str(value or '').strip().casefold()


def get_seuk_null_columns(value, retailer=None):
    if retailer is not None and seuk_retailer_key(retailer) != seuk_retailer_key(RETAILER):
        raise ValueError('Unsupported SEUK retailer')
    return get_seuk_source(value)['required_columns']


def get_seuk_null_select_columns(value):
    return get_seuk_source(value)['columns']


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
        raise ValueError('Unsupported SEUK retailer')
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
