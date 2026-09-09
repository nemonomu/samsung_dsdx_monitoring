"""SEG Layer 1 source definitions; validation rules are configured separately."""

from datetime import time

SEG_COUNTRY = 'SEG'
SEG_CHECK_TYPE = 'seg_retail'
SEG_COLLECTION_START = time(7, 0)
SEG_COLLECTION_END = time(12, 0)
SEG_HISTORY_DAYS = 7
SEG_SOURCE_CONFIG = {
    f'seg_{product.lower()}': {
        'source_key': f'seg_{product.lower()}',
        'category': product,
        'table_name': f'dx_seg.dx_seg_{product.lower()}_retail_com',
        'backup_table_name': f'dx_seg.dx_seg_{product.lower()}_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Mediamarkt', 'OTTO') if product == 'LDY'
                     else ('Mediamarkt', 'OTTO', 'Amazon'),
        'has_redirect': product != 'LDY',
    }
    for product in ('TV', 'REF', 'LDY')
}


def get_seg_source(product_line):
    source = SEG_SOURCE_CONFIG.get(product_line)
    if source is None:
        raise ValueError(f'Unsupported SEG product line: {product_line}')
    return source


def get_seg_average(counts):
    values = [int(value) for value in counts if int(value or 0) > 0]
    return sum(values) // len(values) if values else None


def get_seg_collection_phase(current_time):
    if current_time < SEG_COLLECTION_START:
        return 'pending'
    return 'collecting' if current_time < SEG_COLLECTION_END else 'complete'
