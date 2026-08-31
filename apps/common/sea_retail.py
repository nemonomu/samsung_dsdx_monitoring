"""Fixed, allow-listed metadata for SEA retail sources.

The registry contains physical source information only.  Validation columns
remain database-configured because their rules differ by layer and retailer.
"""


SEA_RETAIL_SOURCES = {
    'tv': {
        'key': 'tv',
        'product_key': 'tv',
        'product_line': 'tv',
        'source_key': 'sea_tv',
        'category': 'TV',
        'table_name': 'public.tv_retail_com',
        'backup_table': 'public.tv_retail_com_backup_all',
        'date_column': 'crawl_datetime',
        'date_mode': 'timestamp',
        'retailers': ('Amazon', 'Bestbuy', 'Walmart'),
        'extra_rank_field': 'promotion_position',
        'extra_rank_name': 'Promotion',
        'latest_main_batch': False,
        'raw_columns': (),
    },
    'ref': {
        'key': 'sea_ref',
        'product_key': 'ref',
        'product_line': 'sea_ref',
        'source_key': 'sea_ref',
        'category': 'REF',
        'table_name': 'public.ref_retail_com',
        'backup_table': 'public.ref_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'date_mode': 'text_prefix',
        'retailers': ('Bestbuy', 'Lowes'),
        'extra_rank_field': None,
        'extra_rank_name': '',
        'latest_main_batch': True,
        'raw_columns': (
            'id', 'account_name', 'page_type', 'item', 'main_rank',
            'bsr_rank', 'crawl_strdatetime', 'batch_id',
        ),
    },
    'ldy': {
        'key': 'sea_ldy',
        'product_key': 'ldy',
        'product_line': 'sea_ldy',
        'source_key': 'sea_ldy',
        'category': 'LDY',
        'table_name': 'public.ldy_retail_com',
        'backup_table': 'public.ldy_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'date_mode': 'text_prefix',
        'retailers': ('Bestbuy', 'Lowes'),
        'extra_rank_field': None,
        'extra_rank_name': '',
        'latest_main_batch': True,
        'raw_columns': (
            'id', 'account_name', 'page_type', 'item', 'main_rank',
            'bsr_rank', 'crawl_strdatetime', 'batch_id',
        ),
    },
}


_SEA_SOURCE_ALIASES = {
    'tv': 'tv',
    'sea_tv': 'tv',
    'ref': 'ref',
    'sea_ref': 'ref',
    'ldy': 'ldy',
    'sea_ldy': 'ldy',
}


def get_sea_retail_source(value):
    """Return one fixed SEA source or fail closed for unknown input."""

    key = str(value or '').strip().lower()
    product_key = _SEA_SOURCE_ALIASES.get(key)
    if product_key is None:
        raise ValueError(f'허용되지 않은 SEA 제품군: {value}')
    return SEA_RETAIL_SOURCES[product_key]
