"""SEG cross-field sources, including Expert's collected-column contract."""
from apps.common import seg_retail as legacy
from apps.dx.dx_layer2.seg_sources import (
    SEG_COUNTRY, SEG_SOURCE_CONFIG, SEG_TABLE_TO_PRODUCT_LINE,
    get_seg_source, get_seg_product_line, EXPERT_START_DATE, record_scope,
)

SEG_RETAILERS = (*legacy.SEG_RETAILERS, 'Expert')
EXPERT_EDITABLE = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
    'final_sku_price', 'original_sku_price',
)


def display_seg_retailer(value):
    return 'Expert' if str(value or '').strip().casefold() == 'expert' else legacy.display_seg_retailer(value)


def normalize_seg_product_line(value):
    key = get_seg_product_line(value)
    if key is None:
        raise ValueError(f'Unsupported SEG product line: {value}')
    return key


get_seg_product_line_for_table = normalize_seg_product_line


def get_seg_crossfield_editable_columns(product_line, retailer):
    normalize_seg_product_line(product_line)
    if display_seg_retailer(retailer) == 'Expert':
        return list(EXPERT_EDITABLE)
    return legacy.get_seg_crossfield_editable_columns(product_line, retailer)
