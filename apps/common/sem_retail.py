"""SEM (Mexico) Liverpool retail monitoring constants and allowlists."""

from datetime import time


SEM_CHECK_TYPE = 'sem_retail'
SEM_COUNTRY = 'SEM'
SEM_RETAILER = 'Liverpool'
SEM_COLLECTION_START = time(9, 0)
SEM_COLLECTION_END = time(11, 0)
SEM_HISTORY_DAYS = 7
SEM_CRITICAL_DEVIATION = 20

SEM_COMMON_REQUIRED_COLUMNS = (
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

SEM_OPTIONAL_COLUMNS = (
    'original_sku_price',
    'savings',
)

SEM_COMMON_EDITABLE_COLUMNS = (
    *SEM_COMMON_REQUIRED_COLUMNS,
    'original_sku_price',
    'calendar_week',
)

SEM_COMMON_TABLE_COLUMNS = (
    'id',
    'batch_id',
    'country',
    'account_name',
    'item',
    'sku',
    'retailer_sku_name',
    'product_url',
    'count_of_reviews',
    'star_rating',
    'count_of_star_ratings',
    'final_sku_price',
    'original_sku_price',
    'savings',
    'main_rank',
    'bsr_rank',
    'crawl_datetime',
    'calendar_week',
)

SEM_SOURCE_CONFIG = {
    'sem_tv': {
        'source_key': 'sem_tv',
        'category': 'TV',
        'section_code': 'sem_tv_retail',
        'display_name': 'SEM TV',
        'table_name': 'dx_sem.dx_sem_tv_retail_com',
        'backup_table_name': 'dx_sem.dx_sem_tv_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': (SEM_RETAILER,),
        'extra_required_columns': ('screen_size',),
        'extra_format_columns': ('screen_size',),
        'extra_table_columns': ('screen_size',),
    },
    'sem_ref': {
        'source_key': 'sem_ref',
        'category': 'REF',
        'section_code': 'sem_ref_retail',
        'display_name': 'SEM REF',
        'table_name': 'dx_sem.dx_sem_ref_retail_com',
        'backup_table_name': 'dx_sem.dx_sem_ref_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': (SEM_RETAILER,),
        'extra_required_columns': ('ref_capacity',),
        'extra_format_columns': ('ref_capacity', 'ref_refrigerator_type'),
        'extra_table_columns': ('ref_capacity', 'ref_refrigerator_type'),
    },
    'sem_ldy': {
        'source_key': 'sem_ldy',
        'category': 'LDY',
        'section_code': 'sem_ldy_retail',
        'display_name': 'SEM LDY',
        'table_name': 'dx_sem.dx_sem_ldy_retail_com',
        'backup_table_name': 'dx_sem.dx_sem_ldy_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': (SEM_RETAILER,),
        'extra_required_columns': ('ldy_capacity',),
        'extra_format_columns': ('ldy_capacity', 'ldy_loading_type'),
        'extra_table_columns': ('ldy_loading_type', 'ldy_capacity'),
    },
}

SEM_TABLE_TO_PRODUCT_LINE = {
    source['table_name']: product_line
    for product_line, source in SEM_SOURCE_CONFIG.items()
}
SEM_SECTION_TO_PRODUCT_LINE = {
    source['section_code']: product_line
    for product_line, source in SEM_SOURCE_CONFIG.items()
}


def normalize_sem_product_line(value):
    key = str(value or '').strip().lower()
    if key not in SEM_SOURCE_CONFIG:
        raise ValueError(f'Unsupported SEM product line: {value}')
    return key


def get_sem_source(value):
    return dict(SEM_SOURCE_CONFIG[normalize_sem_product_line(value)])


def resolve_sem_table(value):
    raw = str(value or '').strip()
    key = raw.lower()
    if key in SEM_SOURCE_CONFIG:
        return SEM_SOURCE_CONFIG[key]['table_name']
    if raw in SEM_TABLE_TO_PRODUCT_LINE:
        return raw
    raise ValueError(f'Unsupported SEM table: {value}')


def get_sem_required_columns(product_line):
    source = get_sem_source(product_line)
    return SEM_COMMON_REQUIRED_COLUMNS + source['extra_required_columns']


def get_sem_product_line_for_table(table_name):
    canonical = resolve_sem_table(table_name)
    return SEM_TABLE_TO_PRODUCT_LINE[canonical]


def get_sem_editable_columns(product_line):
    source = get_sem_source(product_line)
    return tuple(dict.fromkeys(
        SEM_COMMON_EDITABLE_COLUMNS + source['extra_format_columns']
    ))


def get_sem_table_columns(product_line):
    """Return every physical source column available to detail selectors."""
    source = get_sem_source(product_line)
    return tuple(dict.fromkeys(
        SEM_COMMON_TABLE_COLUMNS + source['extra_table_columns']
    ))


def validate_sem_editable_column(product_line, column_name):
    key = normalize_sem_product_line(product_line)
    column = str(column_name or '').strip()
    if column not in get_sem_editable_columns(key):
        raise ValueError(f'{column_name} 컬럼은 수정할 수 없습니다')
    return column


def get_sem_collection_phase(current_time):
    if current_time < SEM_COLLECTION_START:
        return 'pending'
    if current_time <= SEM_COLLECTION_END:
        return 'collecting'
    return 'complete'


def get_sem_count_status(main_count, history_counts):
    """Classify MAIN volume against up to seven previous valid days."""
    current = int(main_count or 0)
    history = [int(value) for value in history_counts if int(value or 0) > 0]
    if not history:
        return ('ok', float(current)) if current > 0 else ('critical', None)
    baseline = sum(history) / len(history)
    status = (
        'critical'
        if abs(current - baseline) >= SEM_CRITICAL_DEVIATION
        else 'ok'
    )
    return status, baseline
