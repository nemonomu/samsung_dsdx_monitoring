"""SEDA Brazil retail sources and approved Layer 2 NULL columns."""

SEDA_COUNTRY = 'SEDA'
SEDA_CHECK_TYPE = 'seda_retail'
SEDA_HISTORY_DAYS = 7
SEDA_RETAILERS = ('Magalu', 'Casas Bahia')
SEDA_RETAILER_KEYS = ('magalu', 'casasbahia')

_SEDA_RETAILER_ALIASES = {
    'magalu': 'Magalu',
    'casas bahia': 'Casas Bahia',
    'casasbahia': 'Casas Bahia',
}

SEDA_SOURCE_CONFIG = {
    f'seda_{product.lower()}': {
        'source_key': f'seda_{product.lower()}',
        'category': product,
        'section_code': f'seda_{product.lower()}_retail',
        'display_name': f'SEDA {product}',
        'table_name': f'dx_seda.dx_seda_{product.lower()}_retail_com',
        'backup_table_name': (
            f'dx_seda.dx_seda_{product.lower()}_retail_com_backup'
        ),
        'date_column': 'crawl_strdatetime',
        'retailers': SEDA_RETAILERS,
        'retailer_keys': SEDA_RETAILER_KEYS,
    }
    for product in ('TV', 'REF', 'LDY')
}

_SEDA_COMMON_NULL_COLUMNS = (
    'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
    'retailer_sku_name', 'star_rating',
)
SEDA_NULL_COLUMNS = {
    'seda_tv': {
        'casasbahia': _SEDA_COMMON_NULL_COLUMNS + ('screen_size',),
        'magalu': _SEDA_COMMON_NULL_COLUMNS + ('screen_size', 'sku'),
    },
    'seda_ref': {
        'casasbahia': _SEDA_COMMON_NULL_COLUMNS,
        'magalu': _SEDA_COMMON_NULL_COLUMNS,
    },
    'seda_ldy': {
        'casasbahia': _SEDA_COMMON_NULL_COLUMNS + ('ldy_color',),
        'magalu': _SEDA_COMMON_NULL_COLUMNS,
    },
}


def get_seda_product_line(value):
    key = str(value or '').strip().lower()
    for product_line, source in SEDA_SOURCE_CONFIG.items():
        if key in (product_line, source['section_code'], source['table_name']):
            return product_line
    return None


def seda_retailer_key(value):
    return str(value or '').strip().lower().replace(' ', '')


def get_seda_null_columns(product_line, retailer=None):
    columns = SEDA_NULL_COLUMNS.get(get_seda_product_line(product_line), {})
    if retailer is None:
        return tuple(dict.fromkeys(column for fields in columns.values() for column in fields))
    return columns.get(seda_retailer_key(retailer), ())


def get_seda_null_select_columns(product_line):
    return tuple(dict.fromkeys((
        'id', 'country', 'product', 'item', 'account_name', 'page_type',
        'batch_id', 'crawl_strdatetime', 'sku', 'retailer_sku_name',
        *get_seda_null_columns(product_line), 'product_url',
    )))


def get_seda_source(product_line):
    source = SEDA_SOURCE_CONFIG.get(str(product_line or '').strip().lower())
    if source is None:
        raise ValueError(f'Unsupported SEDA product line: {product_line}')
    return source


def display_seda_retailer(value):
    retailer = str(value or '').strip()
    return _SEDA_RETAILER_ALIASES.get(retailer.casefold(), retailer)


def get_seda_average(counts):
    values = [int(value) for value in counts if int(value or 0) > 0]
    return sum(values) // len(values) if values else None


_SEDA_CROSSFIELD_COLUMNS = (
    'main_rank', 'bsr_rank', 'original_sku_price', 'final_sku_price',
    'count_of_reviews', 'count_of_star_ratings', 'star_rating',
    'detailed_review_content', 'summarized_review_content',
)


def get_seda_crossfield_editable_columns(product_line, retailer=None):
    if get_seda_product_line(product_line) is None:
        return ()
    key = seda_retailer_key(retailer) if retailer is not None else None
    if key is not None and key not in SEDA_RETAILER_KEYS:
        return ()
    return _SEDA_CROSSFIELD_COLUMNS + (
        ('recommendation_intent',) if key in (None, 'casasbahia') else ()
    )
