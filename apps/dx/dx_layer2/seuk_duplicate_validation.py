"""SEUK duplicate inspection on the original collection day and latest batch."""
from apps.common.seuk_retail import SEUK_SOURCE_CONFIG, enabled, product_line_for, normalize_retailer, retailer_start_date
from .seuk_null_validation import latest_rows
from .sem_validation import _duplicate_groups


def append_duplicate_stats(cursor, target_date, validation, category=None):
    if not enabled(target_date):
        return 0
    total = 0
    for source in SEUK_SOURCE_CONFIG.values():
        if category and category != source['section_code']:
            continue
        retailers = []
        for retailer in source['retailers']:
            if str(target_date) < str(retailer_start_date(source, retailer)):
                continue
            rows, mapping = latest_rows(cursor, target_date, source, retailer)
            groups = _duplicate_groups(rows)
            retailers.append({
                'retailer': retailer, 'total': len(rows),
                'duplicate_groups': len(groups), 'duplicate_keys': ['item'],
                'status': 'PENDING' if not rows else 'CRITICAL' if groups else 'OK', **mapping,
            })
        issues = sum(row['duplicate_groups'] for row in retailers)
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(row['total'] for row in retailers),
            'total_issues': issues, 'duplicate_groups': issues,
            'duplicate_keys': ['item'], 'status': 'PENDING' if not any(r['total'] for r in retailers) else 'CRITICAL' if issues else 'OK',
            'retailers': retailers, **mapping,
        })
        total += issues
    return total


def duplicate_detail(cursor, target_date, table, retailer, page=1, page_size=50):
    source = SEUK_SOURCE_CONFIG.get(product_line_for(table))
    if source is None:
        raise ValueError('Unsupported SEUK duplicate source or retailer')
    retailer = normalize_retailer(source, retailer)
    page, page_size = max(1, int(page)), min(200, max(1, int(page_size)))
    rows, mapping = latest_rows(cursor, target_date, source, retailer)
    groups = _duplicate_groups(rows)
    start = (page - 1) * page_size
    return {
        'date': mapping['inspection_date'], 'table': source['section_code'],
        'retailer': retailer, 'actual_table': source['table_name'],
        'select_cols': {
            'group': ['duplicate_type', 'item', 'retailer_sku_name', 'dup_count', 'reason'],
            'record': ['id', 'sku', 'retailer_sku_name', 'final_sku_price',
                       'crawl_datetime', 'product_url'],
        },
        'editable_cols': ['sku'], 'readonly': False, 'allow_cleanup': False,
        'results': {
            'duplicates': groups[start:start + page_size], 'total_groups': len(groups),
            'total_pages': (len(groups) + page_size - 1) // page_size,
            'page': page, 'page_size': page_size,
        }, **mapping,
    }
