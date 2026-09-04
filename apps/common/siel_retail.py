"""SIEL retail monitoring constants and identifier allowlists."""

from datetime import time


SIEL_CHECK_TYPE = 'siel_retail'
SIEL_COUNTRY = 'SIEL'
SIEL_EXPECTED_COUNT = 300
SIEL_OK_THRESHOLD = 200
SIEL_COLLECTION_END = time(9, 0)
SIEL_BUSINESS_TIMEZONE = 'Asia/Seoul'
SIEL_RETAILERS = ('Amazon', 'Flipkart')

# Layer2 SIEL format-detail cells that may be corrected.  These mirror the
# fields validated by ``dx_layer2.format_validation`` and deliberately omit
# source identity/audit columns such as id, batch_id, crawl_datetime and
# redirect.
SIEL_FORMAT_COMMON_EDITABLE_COLUMNS = (
    'account_name', 'calendar_week', 'country',
    'detailed_review_content', 'original_sku_price', 'page_type',
    'product', 'product_url', 'star_rating',
)
SIEL_FORMAT_EDITABLE_COLUMNS = {
    'siel_tv': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'screen_size',
            'estimated_annual_electricity_use', 'model_year',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'screen_size',
            'estimated_annual_electricity_use', 'model_year',
        ),
    },
    'siel_ref': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'ref_capacity',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'ref_capacity',
            'ref_refrigerator_type',
        ),
    },
    'siel_ldy': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'ldy_capacity',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'ldy_capacity',
        ),
    },
}

SIEL_SOURCE_CONFIG = {
    'siel_tv': {
        'source_key': 'siel_tv',
        'category': 'TV',
        'section_code': 'siel_tv_retail',
        'display_name': 'SIEL TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_tv_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
    'siel_ref': {
        'source_key': 'siel_ref',
        'category': 'REF',
        'section_code': 'siel_ref_retail',
        'display_name': 'SIEL REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ref_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
    'siel_ldy': {
        'source_key': 'siel_ldy',
        'category': 'LDY',
        'section_code': 'siel_ldy_retail',
        'display_name': 'SIEL LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ldy_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
}

SIEL_TABLE_TO_PRODUCT_LINE = {
    config['table_name']: product_line
    for product_line, config in SIEL_SOURCE_CONFIG.items()
}
SIEL_SECTION_TO_PRODUCT_LINE = {
    config['section_code']: product_line
    for product_line, config in SIEL_SOURCE_CONFIG.items()
}


def normalize_siel_product_line(value):
    """Return a known SIEL source key or raise ``ValueError``."""
    key = str(value or '').strip().lower()
    if key not in SIEL_SOURCE_CONFIG:
        raise ValueError(f'허용되지 않은 SIEL 제품군: {value}')
    return key


def get_siel_source(value):
    """Return a copy of one allow-listed SIEL source configuration."""
    return dict(SIEL_SOURCE_CONFIG[normalize_siel_product_line(value)])


def resolve_siel_table(value):
    """Resolve a logical key or canonical table name to an allowed table."""
    raw = str(value or '').strip()
    key = raw.lower()
    if key in SIEL_SOURCE_CONFIG:
        return SIEL_SOURCE_CONFIG[key]['table_name']
    if raw in SIEL_TABLE_TO_PRODUCT_LINE:
        return raw
    raise ValueError(f'허용되지 않은 SIEL 테이블: {value}')


def get_siel_product_line_for_table(table_name):
    """Return the product-line key for an allowed canonical table."""
    canonical = resolve_siel_table(table_name)
    return SIEL_TABLE_TO_PRODUCT_LINE[canonical]


def display_siel_retailer(value):
    """Return the canonical display name for a SIEL retailer."""
    normalized = str(value or '').strip().lower()
    for retailer in SIEL_RETAILERS:
        if retailer.lower() == normalized:
            return retailer
    return str(value or '').strip()


def get_siel_format_editable_columns(product_line, retailer):
    """Return the fixed allowlist for one SIEL format-validation card."""
    key = normalize_siel_product_line(product_line)
    retailer_key = str(retailer or '').strip().casefold()
    if retailer_key not in {'amazon', 'flipkart'}:
        return []
    specific = SIEL_FORMAT_EDITABLE_COLUMNS.get(key, {}).get(
        retailer_key, ()
    )
    return list(dict.fromkeys((
        *SIEL_FORMAT_COMMON_EDITABLE_COLUMNS,
        *specific,
    )))


def get_siel_collection_phase(current_time):
    """Return the current-day phase using the confirmed KST completion time."""
    return (
        'collecting'
        if current_time <= SIEL_COLLECTION_END
        else 'complete'
    )


def get_siel_count_status(actual_count):
    """Classify one completed MAIN+BSR retailer count."""
    return (
        'ok'
        if int(actual_count or 0) >= SIEL_OK_THRESHOLD
        else 'critical'
    )
