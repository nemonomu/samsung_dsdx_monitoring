"""SEDA Brazil retail source definitions used by Layer 1 and backup."""

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
