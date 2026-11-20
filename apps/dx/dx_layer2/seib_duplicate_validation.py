"""SEIB duplicate inspection on the original collection day and latest batch."""
from apps.common.seib_retail import (SEIB_SOURCE_CONFIG, enabled, product_line_for, active_retailers,
                                    normalize_retailer, is_eci_appliance, is_eci_appliance_preview)
from .seib_null_validation import latest_rows
from .sem_validation import _duplicate_groups


def append_duplicate_stats(cursor, target_date, validation, category=None):
    if not enabled(target_date):
        return 0
    total = 0
    for source in SEIB_SOURCE_CONFIG.values():
        if category and category != source['section_code']:
            continue
        retailers = []
        for retailer in active_retailers(source, target_date, include_preview=True):
            preview = is_eci_appliance_preview(source['source_key'], retailer, target_date)
            rows, mapping = latest_rows(cursor, target_date, source, retailer, include_preview=preview)
            if preview and not rows:
                continue
            groups = _duplicate_groups(rows)
            result = {
                'retailer': retailer, 'total': len(rows),
                'duplicate_groups': len(groups), 'duplicate_keys': ['item'],
                'status': ('PENDING' if not rows and is_eci_appliance(source['source_key'], retailer)
                           else 'CRITICAL' if groups else 'OK'), **mapping,
            }
            if preview:
                result.update(preview_mode=True, status='PENDING',
                              validation_label=f'테스트 조회 · {len(rows):,}건 검사 · 중복 {len(groups)}그룹')
            retailers.append(result)
        operating = [row for row in retailers if not row.get('preview_mode')]
        issues = sum(row['duplicate_groups'] for row in operating)
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(row['total'] for row in operating),
            'total_issues': issues, 'duplicate_groups': issues,
            'duplicate_keys': ['item'], 'status': 'CRITICAL' if issues else 'OK',
            'retailers': retailers, **mapping,
        })
        total += issues
    return total


def duplicate_detail(cursor, target_date, table, retailer, page=1, page_size=50):
    source = SEIB_SOURCE_CONFIG.get(product_line_for(table))
    if source is None:
        raise ValueError('Unsupported SEIB duplicate source or retailer')
    retailer = normalize_retailer(source, retailer)
    page, page_size = max(1, int(page)), min(200, max(1, int(page_size)))
    preview = is_eci_appliance_preview(source['source_key'], retailer, target_date)
    rows, mapping = latest_rows(cursor, target_date, source, retailer, include_preview=preview)
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
        'editable_cols': [] if preview else ['sku'], 'readonly': preview, 'allow_cleanup': False,
        **({'preview_mode': True, 'readonly_message': '테스트 조회 · 원본을 수정할 수 없습니다.'} if preview else {}),
        'results': {
            'duplicates': groups[start:start + page_size], 'total_groups': len(groups),
            'total_pages': (len(groups) + page_size - 1) // page_size,
            'page': page, 'page_size': page_size,
        }, **mapping,
    }
