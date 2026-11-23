"""UK retail source contracts, using the original collection date."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql, source_date_value
from apps.common.dryer_onboarding import config as onboarding_config

SEUK_COUNTRY = 'SEUK'
# Production monitoring starts with the original October 25 collection date.
FIRST_SOURCE_DATE = date(2026, 10, 25)
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
        'date_column': 'crawl_datetime', 'retailers': (RETAILER,) if product == 'tv' else (RETAILER, 'AO'),
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
    source = get_seuk_source(value)
    if retailer is not None:
        normalize_retailer(source, retailer)
    return source['required_columns']


def normalize_retailer(source, retailer):
    for name in source['retailers']:
        if seuk_retailer_key(name) == seuk_retailer_key(retailer):
            return name
    raise ValueError('Unsupported SEUK retailer')


def retailer_start_date(source, retailer):
    name = normalize_retailer(source, retailer)
    spec = onboarding_config('SEUK', source['category'], name)
    return spec['preview_from'] if spec else FIRST_SOURCE_DATE


def get_seuk_null_select_columns(value):
    return get_seuk_source(value)['columns']


def _text_filter(column, values):
    literals = ["'" + value.replace("'", "''") + "'" for value in values]
    if len(literals) == 1:
        return f'{column} = {literals[0]}'
    return f"{column} IN ({', '.join(literals)})"


def _tv_account_scope(account, rows, include_items):
    account_filter = _text_filter('account_name', (account,))
    if not include_items:
        return account_filter
    items = sorted({row['item'] for row in rows if (row.get('item') or '').strip()})
    missing_item_ids = sorted({int(row['id']) for row in rows if not (row.get('item') or '').strip()})
    item_filters = []
    if items:
        item_filters.append(_text_filter('item', items))
    if missing_item_ids:
        item_filters.append(f"id IN ({', '.join(map(str, missing_item_ids))})")
    item_filter = item_filters[0] if len(item_filters) == 1 else '(' + ' OR '.join(item_filters) + ')'
    return account_filter + '\n  AND ' + item_filter


def tv_review_query(columns, rows, start, end, *, raw_accounts=None, include_items=True):
    """Copy-only item history by the original crawl_datetime date range."""
    source = SEUK_SOURCE_CONFIG['seuk_tv']
    allowed = {*source['columns'], 'is_redirect'}
    fields = [column for column in dict.fromkeys(columns) if column in allowed]
    if not fields:
        return ''
    by_account = defaultdict(list)
    raw_accounts = raw_accounts or {}
    for row in rows:
        by_account[raw_accounts.get(row['id'], row['account_name'])].append(row)
    scopes = [_tv_account_scope(account, records, include_items) for account, records in by_account.items()]
    where = 'FALSE'
    if scopes:
        where = scopes[0] if len(scopes) == 1 else '(' + '\n   OR '.join(f'({scope})' for scope in scopes) + ')'
        where += f"\n  AND crawl_datetime >= '{start}'\n  AND crawl_datetime < '{end + timedelta(days=1)}'"
        if all(seuk_retailer_key(account) == 'amazon' for account in by_account):
            where += '\n  AND is_redirect IS NOT TRUE'
    return (f"SELECT {', '.join(fields)}\nFROM {source['table_name']}\n"
            f"WHERE {where}\nORDER BY item, crawl_datetime, id;")


def enabled(day):
    return source_date_value(day) >= str(FIRST_SOURCE_DATE)


def collection_phase(day, now=None, *, start=time(1), end=time(4)):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    selected = date.fromisoformat(source_date_value(day))
    if not enabled(day) or selected > current.date():
        return 'pending'
    if selected < current.date() or current.time().replace(tzinfo=None) >= end:
        return 'complete'
    return 'pending' if current.time().replace(tzinfo=None) < start else 'collecting'


def latest_scope(source, start, end, retailer=RETAILER):
    """One latest batch per original source day; never infer a day from batch_id."""
    day = source_date_sql('anchor.crawl_datetime')
    source_day = source_date_sql('source.crawl_datetime')
    if retailer is None:
        account = 'LOWER(BTRIM(anchor.account_name))'
        clauses, params = [], [str(start), str(end)]
        for name in source['retailers']:
            clauses.append(f'({account} = %s AND {day} >= %s)')
            params.extend((name.lower(), str(retailer_start_date(source, name))))
        cte = f"""WITH latest AS (
            SELECT DISTINCT ON ({day}, {account}) {day} AS source_date,
                   {account} AS retailer_key, anchor.batch_id
            FROM {source['table_name']} anchor
            WHERE {day} BETWEEN %s AND %s AND ({' OR '.join(clauses)})
            ORDER BY {day}, {account}, anchor.id DESC
        )"""
        scope = f"""FROM {source['table_name']} source
            JOIN latest ON {source_day} = latest.source_date
             AND LOWER(BTRIM(source.account_name)) = latest.retailer_key
             AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
            WHERE TRUE"""
        return cte, scope, params
    retailer = normalize_retailer(source, retailer)
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
    return cte, scope, [max(str(start), str(retailer_start_date(source, retailer))), str(end), retailer.lower(), retailer.lower()]
