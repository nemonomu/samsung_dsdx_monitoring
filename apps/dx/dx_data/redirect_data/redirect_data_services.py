"""Read-only service for inspecting Amazon redirect rows."""

import re

from apps.common.db import dx_connection
from apps.common.retail_columns import get_retailer_columns
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.common.siel_retail import SIEL_SOURCE_CONFIG

from .redirect_data_repositories import (
    get_redirect_count_db,
    get_redirect_page_db,
)


_SAFE_COLUMN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_BASE_COLUMNS = [
    'id', 'country', 'product', 'batch_id', 'crawl_datetime',
    'account_name', 'page_type', 'item', 'sku', 'retailer_sku_name',
    'product_url', 'redirect',
]
_SIEL_AMAZON_COLUMNS = {
    'TV': (
        'count_of_star_ratings', 'final_sku_price', 'screen_size',
        'star_rating',
    ),
    'REF': (
        'count_of_star_ratings', 'final_sku_price', 'star_rating',
    ),
    'LDY': (
        'count_of_star_ratings', 'final_sku_price', 'star_rating',
    ),
}
_REDIRECT_SOURCES = {
    'SEA': {
        'TV': {
            'country': 'SEA',
            'product': 'TV',
            'product_line': 'tv',
            'table_name': SEA_RETAIL_SOURCES['tv']['table_name'],
            'date_mode': 'batch',
            'display_columns': (),
        },
    },
    'SIEL': {
        source['category']: {
            'country': 'SIEL',
            'product': source['category'],
            'product_line': source_key,
            'table_name': source['table_name'],
            'date_mode': 'timestamp_kst',
            'display_columns': _SIEL_AMAZON_COLUMNS[source['category']],
        }
        for source_key, source in SIEL_SOURCE_CONFIG.items()
    },
}


def get_redirect_source(country='SEA', product='TV'):
    country_key = str(country or '').strip().upper()
    product_key = str(product or '').strip().upper()
    source = _REDIRECT_SOURCES.get(country_key, {}).get(product_key)
    if not source:
        raise ValueError(f'허용되지 않은 redirect 조회 범위: {country}/{product}')
    return dict(source)


def get_amazon_redirect_columns(country='SEA', product='TV'):
    source = get_redirect_source(country, product)
    configured = get_retailer_columns(source['product_line'], 'Amazon')
    columns = []
    candidates = [
        *_BASE_COLUMNS,
        *source.get('display_columns', ()),
        *configured,
    ]
    for column in candidates:
        if column in columns:
            continue
        if not _SAFE_COLUMN.match(column):
            continue
        columns.append(column)
    return columns


def get_amazon_redirect_list(
        target_date, page, page_size, country='SEA', product='TV'):
    source = get_redirect_source(country, product)
    columns = get_amazon_redirect_columns(country, product)
    offset = (page - 1) * page_size

    with dx_connection() as (conn, cursor):
        total = get_redirect_count_db(cursor, source, target_date)
        items = get_redirect_page_db(
            cursor, source, columns, target_date, page_size, offset,
        )

    return {
        'columns': columns,
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'date': str(target_date),
        'country': source['country'],
        'product': source['product'],
    }
