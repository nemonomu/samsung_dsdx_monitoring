"""SEG NULL/duplicate onboarding; format and Layer 3 retain their own sources."""
from apps.common import seg_retail as legacy
from apps.dx.dx_layer1.seg_retail.sources import (
    SEG_SOURCE_CONFIG as LAYER1_SOURCES, EXPERT_COLUMNS, EXPERT_START_DATE,
    active_retailers,
)

SEG_COUNTRY = legacy.SEG_COUNTRY
SEG_FORMAT_SOURCE_CONFIG = legacy.SEG_SOURCE_CONFIG
SEG_SOURCE_CONFIG = {
    key: {**source, 'section_code': f'{key}_retail',
          'display_name': f"SEG {source['category']}"}
    for key, source in LAYER1_SOURCES.items()
}
SEG_TABLE_TO_PRODUCT_LINE = {s['table_name']: k for k, s in SEG_SOURCE_CONFIG.items()}
EXPERT_NULL_COMMON = (
    'item', 'product_url', 'sku', 'retailer_sku_name', 'final_sku_price',
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)
EXPERT_NULL_COLUMNS = {
    'seg_tv': (*EXPERT_NULL_COMMON, 'screen_size'),
    'seg_ref': (*EXPERT_NULL_COMMON, 'ref_capacity', 'ref_refrigerator_type'),
    'seg_ldy': (*EXPERT_NULL_COMMON, 'ldy_capacity', 'ldy_loading_type'),
    'seg_ldy_dryer': (*EXPERT_NULL_COMMON, 'capacity', 'loading_type'),
}


def is_expert(retailer):
    return str(retailer or '').strip().casefold() == 'expert'


def get_seg_product_line(value):
    key = str(value or '').strip().lower()
    for product, source in SEG_SOURCE_CONFIG.items():
        if key in (product, source['section_code'], source['table_name'],
                   source['table_name'].split('.')[-1]):
            return product
    return None


def get_seg_source(value):
    key = get_seg_product_line(value)
    if key is None:
        raise ValueError(f'Unsupported SEG source: {value}')
    return SEG_SOURCE_CONFIG[key]


def resolve_seg_table(value):
    return get_seg_source(value)['table_name']


def get_seg_null_columns(product_line, retailer):
    key = get_seg_product_line(product_line)
    return (EXPERT_NULL_COLUMNS.get(key, ()) if is_expert(retailer)
            else legacy.get_seg_null_columns(key, retailer))


def get_seg_all_null_columns(product_line):
    key = get_seg_product_line(product_line)
    return tuple(dict.fromkeys((*legacy.get_seg_all_null_columns(key),
                               *EXPERT_NULL_COLUMNS.get(key, ()))))


def get_seg_format_columns(product_line, retailer=None):
    if is_expert(retailer):
        return ()
    return legacy.get_seg_format_columns(product_line, retailer)


def get_seg_table_columns(product_line):
    key = get_seg_product_line(product_line)
    if key == 'seg_ldy_dryer':
        return (*EXPERT_COLUMNS['LDY_DRYER'], 'batch_id')
    return legacy.get_seg_table_columns(key)


def page_scope(source, retailer, alias='source', anchor=False):
    if is_expert(retailer) or not source.get('has_page_type', True):
        return ''
    test = "= 'main'" if anchor else "IN ('main', 'bsr')"
    return f' AND LOWER(BTRIM(CAST({alias}.page_type AS TEXT))) {test}'


def record_scope(source, source_date, alias='source', anchor=False):
    """Mixed-retailer edit/review queries must enforce the same batch policy."""
    expert = f"LOWER(BTRIM(CAST({alias}.account_name AS TEXT))) = 'expert'"
    enabled = str(source_date)[:10] >= str(EXPERT_START_DATE)
    if not source.get('has_page_type', True):
        return f' AND {expert}' if enabled else ' AND FALSE'
    test = "= 'main'" if anchor else "IN ('main', 'bsr')"
    page = f'LOWER(BTRIM(CAST({alias}.page_type AS TEXT))) {test}'
    return f' AND ({expert} OR {page})' if enabled else f' AND NOT ({expert}) AND {page}'
