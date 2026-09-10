"""SEG retail monitoring source definitions and Layer 2 allowlists."""

from datetime import time

SEG_COUNTRY = 'SEG'
SEG_CHECK_TYPE = 'seg_retail'
SEG_COLLECTION_START = time(7, 0)
SEG_COLLECTION_END = time(12, 0)
SEG_HISTORY_DAYS = 7
SEG_RETAILERS = ('Amazon', 'Mediamarkt', 'OTTO')
SEG_NULL_COLUMNS = {
    'seg_tv': {
        'Mediamarkt': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'screen_size', 'star_rating',
        ),
        'OTTO': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'screen_size', 'sku', 'star_rating',
        ),
        'Amazon': (
            'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'screen_size', 'sku', 'star_rating',
        ),
    },
    'seg_ref': {
        'Mediamarkt': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'star_rating',
        ),
        'OTTO': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'ref_capacity', 'retailer_sku_name', 'sku', 'star_rating',
        ),
        'Amazon': (
            'count_of_star_ratings', 'final_sku_price',
            'retailer_sku_name', 'sku', 'star_rating',
        ),
    },
    'seg_ldy': {
        'Mediamarkt': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'ldy_capacity', 'ldy_loading_type', 'retailer_sku_name',
            'star_rating',
        ),
        'OTTO': (
            'count_of_reviews', 'count_of_star_ratings', 'final_sku_price',
            'ldy_capacity', 'ldy_loading_type', 'retailer_sku_name', 'sku',
            'star_rating',
        ),
    },
}

SEG_COMMON_TABLE_COLUMNS = (
    'id', 'country', 'product', 'item', 'account_name', 'page_type',
    'retailer_sku_name', 'product_url', 'original_sku_price',
    'final_sku_price', 'savings', 'sku_status', 'sku_popularity',
    'discount_type', 'delivery_availability', 'pick_up_availability', 'sku',
    'model_year', 'summarized_review_content',
    'retailer_sku_name_similar', 'star_rating', 'count_of_star_ratings',
    'count_of_reviews', 'recommendation_intent', 'detailed_review_content',
    'bsr_rank', 'main_rank', 'calendar_week', 'crawl_strdatetime',
    'batch_id',
)
SEG_PRODUCT_TABLE_COLUMNS = {
    'seg_tv': (
        'screen_size', 'estimated_annual_electricity_use',
        'number_of_units_purchased_past_month',
        'available_quantity_for_purchase', 'fastest_delivery',
        'inventory_status', 'redirect',
    ),
    'seg_ref': (
        'ref_refrigerator_type', 'ref_capacity',
        'number_of_units_purchased_past_month', 'redirect',
        'available_quantity_for_purchase', 'fastest_delivery',
        'inventory_status',
    ),
    'seg_ldy': ('ldy_loading_type', 'ldy_capacity'),
}

# Format validation intentionally excludes URL, redirect, collection datetime,
# batch id, and cross-field identity checks. Missing values are handled by the
# separate NULL validation policy.
SEG_FORMAT_COMMON_COLUMNS = (
    'final_sku_price', 'original_sku_price', 'savings',
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
    'main_rank', 'bsr_rank', 'calendar_week',
)
SEG_FORMAT_PRODUCT_COLUMNS = {
    'seg_tv': ('screen_size',),
    'seg_ref': ('ref_capacity', 'ref_refrigerator_type'),
    'seg_ldy': ('ldy_capacity', 'ldy_loading_type'),
}

# Layer 3 cross-field findings may be corrected only in fields participating
# in the fixed SEG rules. Source identity and audit fields remain read-only.
SEG_CROSSFIELD_COMMON_EDITABLE_COLUMNS = (
    'star_rating', 'count_of_star_ratings',
    'final_sku_price', 'original_sku_price', 'savings',
    'page_type', 'main_rank', 'bsr_rank',
)

SEG_SOURCE_CONFIG = {
    f'seg_{product.lower()}': {
        'source_key': f'seg_{product.lower()}',
        'category': product,
        'section_code': f'seg_{product.lower()}_retail',
        'display_name': f'SEG {product}',
        'table_name': f'dx_seg.dx_seg_{product.lower()}_retail_com',
        'backup_table_name': f'dx_seg.dx_seg_{product.lower()}_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Mediamarkt', 'OTTO') if product == 'LDY'
                     else ('Mediamarkt', 'OTTO', 'Amazon'),
        'has_redirect': product != 'LDY',
    }
    for product in ('TV', 'REF', 'LDY')
}

SEG_TABLE_TO_PRODUCT_LINE = {
    source['table_name']: product_line
    for product_line, source in SEG_SOURCE_CONFIG.items()
}
SEG_SECTION_TO_PRODUCT_LINE = {
    source['section_code']: product_line
    for product_line, source in SEG_SOURCE_CONFIG.items()
}


def get_seg_source(product_line):
    source = SEG_SOURCE_CONFIG.get(product_line)
    if source is None:
        raise ValueError(f'Unsupported SEG product line: {product_line}')
    return source


def normalize_seg_product_line(value):
    product_line = get_seg_product_line(value)
    if not product_line:
        raise ValueError(f'Unsupported SEG product line: {value}')
    return product_line


def display_seg_retailer(value):
    normalized = str(value or '').strip().casefold()
    for retailer in SEG_RETAILERS:
        if retailer.casefold() == normalized:
            return retailer
    return str(value or '').strip()


def get_seg_product_line_for_table(table_name):
    product_line = get_seg_product_line(table_name)
    if not product_line:
        raise ValueError(f'Unsupported SEG table: {table_name}')
    return product_line


def get_seg_crossfield_editable_columns(product_line, retailer):
    product_key = normalize_seg_product_line(product_line)
    source = SEG_SOURCE_CONFIG[product_key]
    retailer_name = display_seg_retailer(retailer)
    if retailer_name not in source['retailers']:
        return []
    columns = list(SEG_CROSSFIELD_COMMON_EDITABLE_COLUMNS)
    if retailer_name in ('Mediamarkt', 'OTTO'):
        columns.extend(('count_of_reviews', 'detailed_review_content'))
    return columns


def get_seg_product_line(value):
    raw = str(value or '').strip()
    key = raw.lower()
    if key in SEG_SOURCE_CONFIG:
        return key
    if key in SEG_SECTION_TO_PRODUCT_LINE:
        return SEG_SECTION_TO_PRODUCT_LINE[key]
    for table_name, product_line in SEG_TABLE_TO_PRODUCT_LINE.items():
        if key in {table_name.lower(), table_name.split('.')[-1].lower()}:
            return product_line
    return None


def resolve_seg_table(value):
    product_line = get_seg_product_line(value)
    if not product_line:
        raise ValueError(f'Unsupported SEG table: {value}')
    return SEG_SOURCE_CONFIG[product_line]['table_name']


def get_seg_null_columns(product_line, retailer):
    product_key = get_seg_product_line(product_line)
    if not product_key:
        return ()
    retailer_key = str(retailer or '').strip().casefold()
    for name, columns in SEG_NULL_COLUMNS[product_key].items():
        if name.casefold() == retailer_key:
            return columns
    return ()


def get_seg_all_null_columns(product_line):
    product_key = get_seg_product_line(product_line)
    if not product_key:
        return ()
    return tuple(dict.fromkeys(
        column
        for columns in SEG_NULL_COLUMNS[product_key].values()
        for column in columns
    ))


def get_seg_table_columns(product_line):
    product_key = get_seg_product_line(product_line)
    if not product_key:
        return ()
    return tuple(dict.fromkeys(
        SEG_COMMON_TABLE_COLUMNS + SEG_PRODUCT_TABLE_COLUMNS[product_key]
    ))


def get_seg_format_columns(product_line, _retailer=None):
    product_key = get_seg_product_line(product_line)
    if not product_key:
        return ()
    return tuple(dict.fromkeys(
        SEG_FORMAT_COMMON_COLUMNS + SEG_FORMAT_PRODUCT_COLUMNS[product_key]
    ))


def get_seg_average(counts):
    values = [int(value) for value in counts if int(value or 0) > 0]
    return sum(values) // len(values) if values else None


def get_seg_collection_phase(current_time):
    if current_time < SEG_COLLECTION_START:
        return 'pending'
    return 'collecting' if current_time < SEG_COLLECTION_END else 'complete'
