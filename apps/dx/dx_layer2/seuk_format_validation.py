"""Layer 2 format checks for UK Currys' four retail products."""

import re
from collections import defaultdict
from datetime import date, timedelta

from apps.common.seuk_retail import (
    FIRST_SOURCE_DATE, RETAILER, SEUK_SOURCE_CONFIG, product_line_for,
    seuk_retailer_key,
)
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer2 import seuk_null_validation


_INTEGER = re.compile(r'^(?:0|[1-9][0-9]*)$')
_RATING = re.compile(r'^(?:[0-4](?:\.[0-9])?|5(?:\.0)?)$')
_GBP = re.compile(r'^£(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}$')
_REF_CAPACITY = re.compile(r'^[0-9]+(?:\.[0-9]+)?\s*L$', re.I)
_LDY_CAPACITY = re.compile(r'^[0-9]+(?:\.[0-9]+)?\s*kg$', re.I)
_WASHER_CAPACITY = re.compile(r'^[0-9]+(?:\.[0-9]+)?\s*kg(?:,\s*[0-9]+(?:\.[0-9]+)?\s*kg)?$', re.I)
_REF_TYPES = frozenset({
    'Freezer-on-Bottom(Bottom Mount)', 'Freezer-on-Top(Top Mount)',
    'French Door', 'Side-by-Side',
})
_LOADING_TYPES = frozenset({'Front loading'})

_COMMON_RULES = {
    'country': (lambda value: str(value).strip().upper() == 'SEUK', 'SEUK'),
    'account_name': (lambda value: str(value).strip().casefold() == 'currys', 'Currys'),
    'count_of_reviews': (lambda value: bool(_INTEGER.fullmatch(str(value).strip())), '0 이상의 정수'),
    'count_of_star_ratings': (lambda value: bool(_INTEGER.fullmatch(str(value).strip())), '0 이상의 정수'),
    'star_rating': (lambda value: bool(_RATING.fullmatch(str(value).strip())), '0~5, 소수 첫째 자리'),
    'final_sku_price': (lambda value: bool(_GBP.fullmatch(str(value).strip())), '£1399.00 / £1,399.00'),
    'original_sku_price': (lambda value: bool(_GBP.fullmatch(str(value).strip())), '£1799.99 / £1,799.99'),
    'savings': (lambda value: bool(_GBP.fullmatch(str(value).strip())), '£400.99'),
}
_EXTRA_RULES = {
    'tv': {},
    'ref': {
        'ref_capacity': (lambda value: bool(_REF_CAPACITY.fullmatch(str(value).strip())), '605L / 605 L'),
        'ref_refrigerator_type': (lambda value: str(value).strip() in _REF_TYPES, ' / '.join(sorted(_REF_TYPES))),
    },
    'ldy': {
        'capacity': (lambda value: bool(_WASHER_CAPACITY.fullmatch(str(value).strip())), '9kg / 10kg, 6kg'),
        'loading_type': (lambda value: str(value).strip() in _LOADING_TYPES, 'Front loading'),
    },
    'ldy_dryer': {
        'capacity': (lambda value: bool(_LDY_CAPACITY.fullmatch(str(value).strip())), '9kg'),
        'loading_type': (lambda value: str(value).strip() in _LOADING_TYPES, 'Front loading'),
    },
}


def format_rules(product_line):
    source = SEUK_SOURCE_CONFIG[product_line]
    return {**_COMMON_RULES, **_EXTRA_RULES[source['product_key']]}


def get_format_columns(product_line):
    return tuple(format_rules(product_line))


def get_format_editable_columns(product_line):
    return get_format_columns(product_line)


def get_format_rule_details(product_line, retailer=RETAILER):
    key = product_line_for(product_line)
    if key is None or seuk_retailer_key(retailer) != seuk_retailer_key(RETAILER):
        return []
    return [{'field': field, 'description': f'{field} 값 형식', 'pattern': pattern}
            for field, (_validator, pattern) in format_rules(key).items()]


def evaluate_format(row, product_line):
    return [field for field, (validator, _pattern) in format_rules(product_line).items()
            if row.get(field) is not None and str(row[field]).strip()
            and not validator(row[field])]


def _serialize(row, product_line):
    result = dict(row)
    result['_source_date'] = source_date_value(row.get('crawl_datetime'))
    result['error_fields'] = evaluate_format(row, product_line)
    result['error_field'] = ', '.join(result['error_fields'])
    rules = format_rules(product_line)
    result['error_details'] = {field: {'rule': rules[field][1], 'reason': '허용 형식 또는 값과 일치하지 않습니다'}
                               for field in result['error_fields']}
    return result


def _normal_reviews(cursor, inspection_date, source):
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s
          AND correction_type = 'format_check' AND status = 'normal'
    """, (source['table_name'], str(inspection_date)))
    return {f'{r[0]}_{r[1]}': {
        'memo': r[2], 'created_id': r[3],
        'created_at': r[4].isoformat() if hasattr(r[4], 'isoformat') else str(r[4] or ''),
        'reason': r[5],
    } for r in cursor.fetchall()}


def append_format_stats(cursor, target_date, validation, category=None):
    if date.fromisoformat(str(target_date)[:10]) < FIRST_SOURCE_DATE:
        return 0
    total = 0
    for key, source in SEUK_SOURCE_CONFIG.items():
        if category and category != source['section_code']:
            continue
        rows, mapping = seuk_null_validation.latest_rows(cursor, target_date, source, RETAILER)
        normal = _normal_reviews(cursor, mapping['inspection_date'], source)
        issues = sum(f'{row["id"]}_{field}' not in normal
                     for row in rows for field in evaluate_format(row, key))
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_checked': len(rows), 'total_issues': issues,
            'status': 'PENDING' if not rows else 'CRITICAL' if issues else 'OK',
            'retailers': [{
                'retailer': RETAILER, 'total': len(rows), 'issue_count': issues,
                'status': 'PENDING' if not rows else 'CRITICAL' if issues else 'OK',
            }],
            **mapping,
        })
        total += issues
    return total


def format_detail(cursor, target_date, table, retailer=RETAILER, days=1, include_normal=False):
    key = product_line_for(table)
    if key is None or seuk_retailer_key(retailer) != seuk_retailer_key(RETAILER):
        return {'results': [], 'column_names': [], 'actual_table': ''}
    source = SEUK_SOURCE_CONFIG[key]
    rows, mapping = seuk_null_validation.latest_rows(cursor, target_date, source, RETAILER)
    normal = _normal_reviews(cursor, mapping['inspection_date'], source)
    current = [_serialize(row, key) for row in rows]
    counts = defaultdict(int)
    for row in current:
        row['error_fields'] = [field for field in row['error_fields']
                               if f'{row["id"]}_{field}' not in normal]
        row['error_field'] = ', '.join(row['error_fields'])
        for field in row['error_fields']:
            counts[field] += 1
    targets = [row for row in current if include_normal or row['error_fields']]
    history_days = min(max(int(days or 1), 1), 30)
    results = targets
    if history_days > 1 and targets:
        items = sorted({str(row['item']) for row in targets if row.get('item')})
        if items:
            source_day = date.fromisoformat(mapping['source_date'])
            history = seuk_null_validation._history_rows(
                cursor, source, RETAILER, source_day - timedelta(days=history_days - 1),
                source_day, items,
            )
            current_by_id = {row['id']: row for row in current}
            results = [current_by_id.get(row['id']) or _serialize(row, key) for row in history]
            seen = {row['id'] for row in results}
            results.extend(row for row in targets if row['id'] not in seen)
    columns = list(dict.fromkeys((
        'id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name',
        *get_format_columns(key), 'product_url',
    )))
    return {
        'date': mapping['inspection_date'], 'table': source['section_code'],
        'retailer': RETAILER, 'actual_table': source['table_name'],
        'column_names': columns, 'select_cols': list(source['columns']),
        'editable_cols': list(get_format_editable_columns(key)),
        'validation_fields': list(get_format_columns(key)),
        'target_ids': [row['id'] for row in targets],
        'batch_id': rows[0].get('batch_id') if rows else None,
        'normal_reviews': normal, 'results': results,
        'field_counts': dict(counts), 'total_format_count': sum(counts.values()),
        'supports_day_history': True, 'history_days': history_days,
        'active_from': str(FIRST_SOURCE_DATE),
        'date_column': source['date_column'], 'readonly': False,
        **mapping,
    }
