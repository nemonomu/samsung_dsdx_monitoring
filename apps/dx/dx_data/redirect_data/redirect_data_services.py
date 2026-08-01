"""Read-only service for inspecting Amazon redirect rows."""

import re

from apps.common.db import dx_connection
from apps.common.retail_columns import get_retailer_columns

from .redirect_data_repositories import (
    get_redirect_count_db,
    get_redirect_page_db,
)


_SAFE_COLUMN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_BASE_COLUMNS = ['id', 'batch_id', 'crawl_datetime', 'account_name', 'redirect']


def get_amazon_redirect_columns():
    configured = get_retailer_columns('tv', 'Amazon')
    columns = []
    for column in _BASE_COLUMNS + configured:
        if column in columns:
            continue
        if not _SAFE_COLUMN.match(column):
            continue
        columns.append(column)
    return columns


def get_amazon_redirect_list(target_date, page, page_size):
    columns = get_amazon_redirect_columns()
    batch_date = str(target_date).replace('-', '')
    offset = (page - 1) * page_size

    with dx_connection() as (conn, cursor):
        total = get_redirect_count_db(cursor, batch_date)
        items = get_redirect_page_db(
            cursor, columns, batch_date, page_size, offset,
        )

    return {
        'columns': columns,
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'date': str(target_date),
    }
