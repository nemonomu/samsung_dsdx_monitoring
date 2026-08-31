"""TSE retail monitoring constants and identifier allowlists.

All SQL callers must resolve table and editable column names through this
module before interpolating identifiers into a query.  Values continue to be
passed to the database driver as parameters.
"""

from datetime import time


TSE_CHECK_TYPE = 'tse_retail'
TSE_COUNTRY = 'TSE'
TSE_EXPECTED_COUNT = 300
TSE_ALLOWED_SHORTFALL = 100
TSE_LOTUSS_RETAILER = 'lotuss'
TSE_LAZADA_RETAILER = 'lazada'
TSE_POWERBUY_RETAILER = 'powerbuy'
TSE_UNASSIGNED_RETAILER = '__unassigned__'
TSE_UNASSIGNED_DISPLAY_NAME = '리테일러 미지정'
TSE_LOTUSS_HISTORY_DAYS = 7
TSE_LOTUSS_CRITICAL_DEVIATION = 20
TSE_COLLECTION_START = time(9, 0)
TSE_COLLECTION_END = time(11, 0)

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

TSE_REVIEW_COLUMNS = (
    'count_of_reviews',
    'star_rating',
    'count_of_star_ratings',
)

TSE_DEFAULT_FORMAT_FIELDS = (
    'final_sku_price',
    'original_sku_price',
    'savings',
    *TSE_REVIEW_COLUMNS,
)

TSE_LOTUSS_FORMAT_FIELDS = {
    'tse_tv': (
        'item', 'product_url', 'final_sku_price', 'original_sku_price',
        'savings', 'screen_size',
    ),
    'tse_ref': (
        'item', 'product_url', 'final_sku_price', 'ref_capacity',
        'ref_refrigerator_type',
    ),
    'tse_ldy': (
        'item', 'product_url', 'final_sku_price', 'ldy_capacity',
        'ldy_loading_type',
    ),
}

TSE_LOTUSS_CROSSFIELD_RULE_KEYS = {
    'tse_tv': frozenset({
        'final_original_price',
        'savings_requires_original',
        'savings_format',
        'original_price_zero',
        'savings_amount_match',
        'savings_rate_match',
    }),
    'tse_ref': frozenset(),
    'tse_ldy': frozenset(),
}

TSE_LAZADA_FORMAT_FIELDS = {
    'tse_tv': (
        'product_url', 'final_sku_price', 'original_sku_price',
        'savings', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'screen_size',
    ),
    'tse_ref': (
        'product_url', 'final_sku_price', 'original_sku_price',
        'savings', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'ref_capacity', 'ref_refrigerator_type',
    ),
    'tse_ldy': (
        'product_url', 'final_sku_price', 'original_sku_price',
        'savings', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'ldy_capacity', 'ldy_loading_type',
    ),
}

_TSE_LAZADA_CROSSFIELD_RULE_KEYS = frozenset({
    'review_count_match',
    # Keep zero-review/rating mismatches visible until the source behavior is
    # reviewed; CSV presence alone does not prove that the value is normal.
    'review_zero_pair',
    'final_original_price',
    'savings_requires_original',
    'savings_format',
    'original_price_zero',
    'savings_amount_match',
    'savings_rate_match',
})
TSE_LAZADA_CROSSFIELD_RULE_KEYS = {
    product_line: _TSE_LAZADA_CROSSFIELD_RULE_KEYS
    for product_line in ('tse_tv', 'tse_ref', 'tse_ldy')
}

TSE_RETAILER_POLICIES = {
    'homepro': {
        'display_name': 'Homepro',
        # Missing account names are data-quality issues and are monitored in
        # a separate Layer 2 "unassigned retailer" bucket.
        'include_unassigned': False,
    },
    TSE_LOTUSS_RETAILER: {
        'display_name': 'Lotuss',
        'include_unassigned': False,
        'unsupported_columns': {
            'tse_tv': frozenset(TSE_REVIEW_COLUMNS),
            'tse_ref': frozenset({
                *TSE_REVIEW_COLUMNS,
                'original_sku_price',
                'savings',
            }),
            'tse_ldy': frozenset({
                *TSE_REVIEW_COLUMNS,
                'original_sku_price',
                'savings',
            }),
        },
        'format_fields': TSE_LOTUSS_FORMAT_FIELDS,
        'crossfield_rule_keys': TSE_LOTUSS_CROSSFIELD_RULE_KEYS,
    },
    TSE_LAZADA_RETAILER: {
        'display_name': 'Lazada',
        'include_unassigned': False,
        'format_fields': TSE_LAZADA_FORMAT_FIELDS,
        'crossfield_rule_keys': TSE_LAZADA_CROSSFIELD_RULE_KEYS,
    },
    TSE_POWERBUY_RETAILER: {
        'display_name': 'PowerBuy',
        'include_unassigned': False,
    },
}

TSE_SOURCE_CONFIG = {
    'tse_tv': {
        'category': 'TV',
        'section_code': 'tse_tv_retail',
        'display_name': 'TSE TV',
        'table_name': 'dx_tse.dx_tse_tv_retail_com',
        'extra_required_columns': ('screen_size',),
        'extra_format_columns': ('screen_size',),
    },
    'tse_ref': {
        'category': 'REF',
        'section_code': 'tse_ref_retail',
        'display_name': 'TSE REF',
        'table_name': 'dx_tse.dx_tse_ref_retail_com',
        'extra_required_columns': ('ref_capacity',),
        'extra_format_columns': (
            'ref_capacity', 'ref_refrigerator_type',
        ),
    },
    'tse_ldy': {
        'category': 'LDY',
        'section_code': 'tse_ldy_retail',
        'display_name': 'TSE LDY',
        'table_name': 'dx_tse.dx_tse_ldy_retail_com',
        'extra_required_columns': ('ldy_capacity',),
        'extra_format_columns': ('ldy_capacity', 'ldy_loading_type'),
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
    if retailer.casefold() == TSE_UNASSIGNED_RETAILER:
        return TSE_UNASSIGNED_DISPLAY_NAME
    policy = TSE_RETAILER_POLICIES.get(retailer.casefold())
    if policy:
        return policy['display_name']
    return retailer


def normalize_tse_retailer(value):
    """Return a stable case-insensitive retailer key."""
    return str(value or '').strip().casefold()


def get_tse_retailer_policy(retailer):
    """Return a copy of the explicit policy for a known TSE retailer."""
    policy = TSE_RETAILER_POLICIES.get(normalize_tse_retailer(retailer), {})
    return dict(policy)


def tse_retailer_include_unassigned(retailer):
    """Whether blank ``account_name`` rows belong to this retailer."""
    return bool(get_tse_retailer_policy(retailer).get('include_unassigned'))


def tse_retailer_supports_column(product_line, retailer, column_name):
    """Return whether a source column is meaningful for this retailer."""
    key = normalize_tse_product_line(product_line)
    policy = get_tse_retailer_policy(retailer)
    unsupported = policy.get('unsupported_columns', {}).get(key, frozenset())
    return str(column_name or '').strip() not in unsupported


def get_tse_format_fields(product_line, retailer):
    """Return the retailer/product fields that receive format validation."""
    key = normalize_tse_product_line(product_line)
    policy = get_tse_retailer_policy(retailer)
    configured = policy.get('format_fields', {}).get(key)
    if configured is not None:
        return tuple(configured)
    return TSE_DEFAULT_FORMAT_FIELDS


def get_tse_crossfield_rule_keys(product_line, retailer):
    """Return supported cross-field keys, or ``None`` for no restriction."""
    key = normalize_tse_product_line(product_line)
    policy = get_tse_retailer_policy(retailer)
    configured = policy.get('crossfield_rule_keys')
    if configured is None:
        return None
    return frozenset(configured.get(key, frozenset()))


def tse_crossfield_rule_supported(product_line, retailer, rule_key):
    """Return whether one cross-field rule applies to this retailer."""
    supported = get_tse_crossfield_rule_keys(product_line, retailer)
    return supported is None or str(rule_key or '').strip() in supported


def get_tse_collection_phase(current_time):
    """Return the KST collection phase for the supplied ``time`` value."""
    if current_time < TSE_COLLECTION_START:
        return 'pending'
    if current_time <= TSE_COLLECTION_END:
        return 'collecting'
    return 'complete'


def get_tse_count_status(actual_count, expected_count=TSE_EXPECTED_COUNT):
    """Classify a completed count while allowing the normal daily variance."""
    actual = int(actual_count or 0)
    expected = int(expected_count or TSE_EXPECTED_COUNT)
    normal_threshold = max(0, expected - TSE_ALLOWED_SHORTFALL)
    if actual >= normal_threshold:
        return 'ok'
    return 'critical'
