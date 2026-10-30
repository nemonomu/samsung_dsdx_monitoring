"""Layer 1 onboarding only; shared validation/report sources stay unchanged."""
from datetime import date
from apps.common.dryer_onboarding import config as dryer_config

from apps.common.seg_retail import SEG_SOURCE_CONFIG as EXISTING_SOURCES


EXPERT_START_DATE = date(2026, 10, 11)
# Earliest Mediamarkt dryer collection verified in the original DB timestamp.
MEDIAMARKT_DRYER_START_DATE = date(2026, 10, 25)
SEG_SOURCE_CONFIG = {
    key: {**source, 'retailers': (*source['retailers'], 'Expert')}
    for key, source in EXISTING_SOURCES.items()
}
SEG_SOURCE_CONFIG['seg_ldy_dryer'] = {
    'source_key': 'seg_ldy_dryer', 'category': 'LDY_DRYER',
    'table_name': 'dx_seg.dx_seg_ldy_dryer_retail',
    'date_column': 'crawl_datetime', 'retailers': ('Mediamarkt', 'Expert', 'OTTO'),
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
DRYER_COLUMNS = (*EXPERT_COLUMNS['LDY_DRYER'], 'batch_id')


def retailer_start_date(source, retailer):
    onboarding = dryer_config('SEG', source['source_key'], retailer)
    if onboarding:
        return onboarding['preview_from']
    name = str(retailer).strip().casefold()
    if name == 'expert':
        return EXPERT_START_DATE
    if source['source_key'] == 'seg_ldy_dryer' and name == 'mediamarkt':
        return MEDIAMARKT_DRYER_START_DATE
    return None


def get_seg_source(product_line):
    if product_line not in SEG_SOURCE_CONFIG:
        raise ValueError(f'Unsupported SEG product line: {product_line}')
    return SEG_SOURCE_CONFIG[product_line]


def active_retailers(source, source_date):
    day = date.fromisoformat(str(source_date))
    return tuple(name for name in source['retailers']
                 if retailer_start_date(source, name) is None
                 or day >= retailer_start_date(source, name))
