"""Layer 1 onboarding only; shared validation/report sources stay unchanged."""
from datetime import date

from apps.common.seg_retail import SEG_SOURCE_CONFIG as EXISTING_SOURCES


EXPERT_START_DATE = date(2026, 10, 11)
SEG_SOURCE_CONFIG = {
    key: {**source, 'retailers': (*source['retailers'], 'Expert')}
    for key, source in EXISTING_SOURCES.items()
}
SEG_SOURCE_CONFIG['seg_ldy_dryer'] = {
    'source_key': 'seg_ldy_dryer', 'category': 'LDY_DRYER',
    'table_name': 'dx_seg.dx_seg_ldy_dryer_retail',
    'date_column': 'crawl_datetime', 'retailers': ('Expert',),
    'has_redirect': False, 'has_page_type': False,
}

EXPERT_COMMON_COLUMNS = (
    'id', 'country', 'account_name', 'item', 'sku', 'retailer_sku_name',
    'product_url', 'count_of_reviews', 'star_rating', 'count_of_star_ratings',
    'final_sku_price', 'original_sku_price', 'savings', 'main_rank',
    'bsr_rank', 'calendar_week',
)
EXPERT_COLUMNS = {
    'TV': (*EXPERT_COMMON_COLUMNS, 'screen_size', 'crawl_strdatetime'),
    'REF': (*EXPERT_COMMON_COLUMNS, 'ref_capacity', 'ref_refrigerator_type', 'crawl_strdatetime'),
    'LDY': (*EXPERT_COMMON_COLUMNS, 'ldy_loading_type', 'ldy_capacity', 'crawl_strdatetime'),
    'LDY_DRYER': (*EXPERT_COMMON_COLUMNS, 'loading_type', 'capacity', 'crawl_datetime'),
}


def get_seg_source(product_line):
    if product_line not in SEG_SOURCE_CONFIG:
        raise ValueError(f'Unsupported SEG product line: {product_line}')
    return SEG_SOURCE_CONFIG[product_line]


def active_retailers(source, source_date):
    enabled = date.fromisoformat(str(source_date)) >= EXPERT_START_DATE
    return tuple(name for name in source['retailers'] if name != 'Expert' or enabled)
