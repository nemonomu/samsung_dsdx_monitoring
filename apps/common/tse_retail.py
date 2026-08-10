"""TSE retail monitoring constants and identifier allowlists.

All SQL callers must resolve table and editable column names through this
module before interpolating identifiers into a query.  Values continue to be
passed to the database driver as parameters.
"""

from datetime import time


TSE_CHECK_TYPE = 'tse_retail'
TSE_COUNTRY = 'TSE'
TSE_EXPECTED_COUNT = 300
TSE_COLLECTION_START = time(9, 0)
TSE_COLLECTION_END = time(9, 30)

TSE_COMMON_REQUIRED_COLUMNS = (
    'country',
    'account_name',
    'item',
    'sku',
    'product_url',
    'retailer_sku_name',
    'count_of_reviews',
    'star_rating',
    'count_of_star_ratings',
    'final_sku_price',
)

TSE_EDIT_ONLY_COLUMNS = (
    'original_sku_price',
    'savings',
)

TSE_SOURCE_CONFIG = {
    'tse_tv': {
        'category': 'TV',
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
        'extra_required_columns': ('screen_size',),
    },
    'tse_ref': {
        'category': 'REF',
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
        'extra_required_columns': ('ref_capacity',),
    },
    'tse_ldy': {
        'category': 'LDY',
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
        'extra_required_columns': ('ldy_capacity',),
    },
}

TSE_TABLE_TO_PRODUCT_LINE = {
    config['table_name']: product_line
    for product_line, config in TSE_SOURCE_CONFIG.items()
}
TSE_SECTION_TO_PRODUCT_LINE = {
    config['section_code']: product_line
    for product_line, config in TSE_SOURCE_CONFIG.items()
}


def normalize_tse_product_line(value):
    """Return a known TSE product-line key or raise ``ValueError``."""
    key = str(value or '').strip().lower()
    if key not in TSE_SOURCE_CONFIG:
        raise ValueError(f'허용되지 않은 TSE 제품군: {value}')
    return key


def get_tse_source(value):
    """Return a copy of the source configuration for a product-line key."""
    key = normalize_tse_product_line(value)
    return dict(TSE_SOURCE_CONFIG[key])


def resolve_tse_table(value):
    """Resolve a logical key or canonical table name to an allowed table."""
    raw = str(value or '').strip()
    key = raw.lower()
    if key in TSE_SOURCE_CONFIG:
        return TSE_SOURCE_CONFIG[key]['table_name']
    if raw in TSE_TABLE_TO_PRODUCT_LINE:
        return raw
    raise ValueError(f'허용되지 않은 TSE 테이블: {value}')


def get_tse_product_line_for_table(table_name):
    """Return the product-line key for an allowed canonical table name."""
    canonical = resolve_tse_table(table_name)
    return TSE_TABLE_TO_PRODUCT_LINE[canonical]


def get_tse_required_columns(product_line):
    """Return the configured default NULL-check columns for a product line."""
    source = get_tse_source(product_line)
    return TSE_COMMON_REQUIRED_COLUMNS + source['extra_required_columns']


def get_tse_editable_columns(product_line):
    """Return the maximum server-side editable-column allowlist.

    The database ``monitoring_retail_columns.is_editable`` flag must also be
    true before a particular column can be updated.
    """
    return get_tse_required_columns(product_line) + TSE_EDIT_ONLY_COLUMNS


def validate_tse_editable_column(product_line, column_name):
    """Validate and return an editable TSE column identifier."""
    key = normalize_tse_product_line(product_line)
    column = str(column_name or '').strip()
    if column not in get_tse_editable_columns(key):
        raise ValueError(f'수정할 수 없는 TSE 컬럼: {column_name}')
    return column


def display_tse_retailer(value):
    """Return the current display spelling while supporting future retailers."""
    retailer = str(value or '').strip()
    if not retailer:
        return ''
    if retailer.lower() == 'homepro':
        return 'Homepro'
    return retailer


def get_tse_collection_phase(current_time):
    """Return the RDP-time collection phase for the supplied ``time`` value."""
    if current_time < TSE_COLLECTION_START:
        return 'pending'
    if current_time <= TSE_COLLECTION_END:
        return 'collecting'
    return 'complete'


def get_tse_count_status(actual_count, expected_count=TSE_EXPECTED_COUNT):
    """Classify a completed collection count using the agreed thresholds."""
    actual = int(actual_count or 0)
    expected = int(expected_count or TSE_EXPECTED_COUNT)
    if actual >= expected:
        return 'ok'
    if actual >= 200:
        return 'warning'
    return 'critical'
