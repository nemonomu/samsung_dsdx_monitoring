"""SEDA duplicate groups on D-1, within each latest MAIN-anchored batch."""

from collections import defaultdict

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seda_retail import (
    SEDA_SOURCE_CONFIG, display_seda_retailer, get_seda_product_line, seda_retailer_key,
)
from .seda_null_validation import _scope, _rows


product_line_for = get_seda_product_line
DUPLICATE_KEY = 'page_type + item'
SELECT_COLUMNS = (
    'id', 'account_name', 'page_type', 'item', 'sku', 'retailer_sku_name',
    'batch_id', 'crawl_strdatetime', 'main_rank', 'bsr_rank',
    'original_sku_price', 'final_sku_price', 'savings', 'product_url',
)


def _text(value):
    return '' if value is None else str(value).strip()


def build_duplicate_groups(rows):
    """Do not merge different days, retailers, batches, pages, or missing items."""
    grouped = defaultdict(list)
    for row in rows:
        retailer = seda_retailer_key(row.get('account_name'))
        page_type = _text(row.get('page_type')).casefold()
        item = _text(row.get('item')).casefold()
        if retailer not in ('magalu', 'casasbahia') or page_type not in ('main', 'bsr') or not item:
            continue
        key = (retailer, _text(row.get('crawl_strdatetime'))[:10],
               row.get('batch_id'), page_type, item)
        grouped[key].append(row)
    groups = []
    for key, records in grouped.items():
        if len(records) < 2:
            continue
        records = sorted(records, key=lambda row: int(row['id']))
        first = records[0]
        conflict = any(len({_text(row.get(field)).casefold() for row in records}) > 1
                       for field in ('sku', 'retailer_sku_name'))
        page_type = key[3].upper()
        groups.append({
            'duplicate_type': '상품 매핑 충돌' if conflict else '동일 상품 중복',
            'page_type': page_type, 'item': _text(first['item']),
            'retailer_sku_name': ', '.join(sorted({_text(row.get('retailer_sku_name'))
                                                 for row in records if _text(row.get('retailer_sku_name'))})),
            'dup_count': len(records),
            'reason': (
                f'{page_type}의 동일 item에 서로 다른 SKU/상품명이 {len(records)}건 연결됨'
                if conflict else f'{page_type}의 동일 item이 최신 배치에 {len(records)}건 수집됨'
            ),
            'records': [{field: value if field == 'id' or value is None else str(value)
                         for field, value in row.items()} for row in records],
        })
    return sorted(groups, key=lambda group: (group['page_type'], group['item'], group['records'][0]['id']))


def latest_rows(cursor, target_date, source, retailer):
    mapping = resolve_monitoring_date(target_date, 'SEDA', source['source_key'])
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'], retailer)
    columns = ', '.join('source.' + column for column in SELECT_COLUMNS)
    cursor.execute(f'{cte} SELECT {columns} {scope} ORDER BY source.id', params)
    return _rows(cursor), mapping


def append_duplicate_stats(cursor, target_date, validation, category=None):
    total_issues = 0
    for source in SEDA_SOURCE_CONFIG.values():
        if category and category != source['section_code']:
            continue
        retailers = []
        for retailer in source['retailers']:
            rows, mapping = latest_rows(cursor, target_date, source, retailer)
            groups = build_duplicate_groups(rows)
            retailers.append({
                'retailer': retailer, 'total': len(rows),
                'duplicate_groups': len(groups), 'duplicate_records': sum(group['dup_count'] for group in groups),
                'duplicate_keys': [DUPLICATE_KEY], 'status': 'CRITICAL' if groups else 'OK', **mapping,
            })
        issues = sum(retailer['duplicate_groups'] for retailer in retailers)
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(retailer['total'] for retailer in retailers),
            'total_issues': issues, 'duplicate_groups': issues,
            'duplicate_keys': [DUPLICATE_KEY], 'status': 'CRITICAL' if issues else 'OK',
            'retailers': retailers, **mapping,
        })
        total_issues += issues
    return total_issues


def duplicate_detail(cursor, target_date, table, retailer, page=1, page_size=50):
    source = SEDA_SOURCE_CONFIG.get(product_line_for(table))
    retailer = display_seda_retailer(retailer)
    if source is None or retailer not in source['retailers']:
        raise ValueError('Unsupported SEDA duplicate source or retailer')
    page, page_size = max(1, int(page)), min(200, max(1, int(page_size)))
    rows, mapping = latest_rows(cursor, target_date, source, retailer)
    groups = build_duplicate_groups(rows)
    start = (page - 1) * page_size
    return {
        'date': mapping['inspection_date'], 'table': source['section_code'],
        'retailer': retailer, 'actual_table': source['table_name'],
        'duplicate_keys': [DUPLICATE_KEY],
        'select_cols': {
            'group': ['duplicate_type', 'page_type', 'item', 'retailer_sku_name', 'dup_count', 'reason'],
            'record': list(SELECT_COLUMNS),
        },
        'editable_cols': [], 'readonly': True,
        'readonly_message': 'SEDA 중복 검증은 확인 전용입니다.',
        'results': {
            'duplicates': groups[start:start + page_size], 'total_groups': len(groups),
            'total_pages': (len(groups) + page_size - 1) // page_size,
            'page': page, 'page_size': page_size,
        },
        **mapping,
    }
