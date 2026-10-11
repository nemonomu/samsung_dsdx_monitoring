"""Costco's Layer 1 collection contract (UTC timestamps, combined rank rows)."""
from datetime import date, datetime, time

from apps.common.sea_collection import KST

FIRST_SOURCE_DATE = date(2026, 10, 4)
DRYER_FIRST_SOURCE_DATE = date(2026, 10, 9)
MINIMUM_DAYS = 5
COMMON_COLUMNS = (
    'item', 'retailer_sku_name', 'final_sku_price', 'original_sku_price',
    'savings', 'product_url', 'star_rating', 'count_of_star_ratings',
    'count_of_reviews', 'main_rank', 'bsr_rank',
)
COLUMNS = {
    'tv': ('id', 'crawl_datetime', *COMMON_COLUMNS[:2], 'screen_size', *COMMON_COLUMNS[2:]),
    'ref': ('id', 'crawl_strdatetime', 'sku', 'ref_refrigerator_type', 'ref_capacity', *COMMON_COLUMNS),
    'ldy': ('id', 'crawl_strdatetime', 'sku', 'ldy_loading_type', 'ldy_capacity', *COMMON_COLUMNS),
    'ldy_dryer': ('id', 'crawl_datetime', 'sku', 'loading_type', 'capacity', *COMMON_COLUMNS),
}

DRYER_SOURCE = {
    'key': 'sea_ldy_dryer', 'product_key': 'ldy_dryer',
    'product_line': 'sea_ldy_dryer', 'source_key': 'sea_ldy_dryer',
    'category': 'LDY_DRYER', 'table_name': 'public.ldy_dryer_retail',
    'date_column': 'crawl_datetime', 'date_mode': 'text_prefix',
    'retailers': ('Costco',), 'extra_rank_field': None, 'extra_rank_name': '',
    'latest_main_batch': True, 'raw_columns': COLUMNS['ldy_dryer'],
}


def first_source_date(product=''):
    return DRYER_FIRST_SOURCE_DATE if 'ldy_dryer' in str(product).lower() else FIRST_SOURCE_DATE


def enabled(source_date, product=''):
    return str(source_date)[:10] >= first_source_date(product).isoformat()


def complete(source_date, now=None):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    day = date.fromisoformat(str(source_date)[:10])
    return enabled(day) and current >= datetime.combine(day, time(15), KST)


def source_date_sql(column):
    return (f"TO_CHAR(NULLIF(BTRIM(CAST({column} AS TEXT)), '')::timestamptz "
            "AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')")
