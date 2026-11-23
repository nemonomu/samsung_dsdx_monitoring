"""Layer 2 format checks for SEUK retailers."""

import re
from collections import defaultdict
from datetime import date, timedelta

from apps.common.seuk_retail import (
    FIRST_SOURCE_DATE, RETAILER, product_line_for,
    seuk_retailer_key,
)
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer2 import seuk_null_validation
from apps.dx.dx_layer2.seuk_null_validation import SEUK_SOURCE_CONFIG, retailer_start_date


_INTEGER = re.compile(r'^(?:0|[1-9][0-9]*)$')
_RATING = re.compile(r'^(?:[0-4](?:\.[0-9])?|5(?:\.0)?)$')
_GBP = re.compile(r'^£(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}$')
_PERCENT = re.compile(r'^(?:100|[1-9]?[0-9])%$')
_SCREEN_INCHES = re.compile(r'^[1-9][0-9]*(?:\.[0-9]+)?\s*inch(?:es)?$', re.I)
_PRICE_STATUSES = {
    'amazon': ('Out of stock', 'Currently unavailable', 'Price higher than typical'),
    'argos': ('Currently unavailable',),
}
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


def format_retailers(product_line):
    source = SEUK_SOURCE_CONFIG[product_line]
    return source['retailers'] if product_line == 'seuk_tv' else (RETAILER,)


def format_rules(product_line, retailer=RETAILER):
    retailer = next((name for name in format_retailers(product_line)
                     if seuk_retailer_key(name) == seuk_retailer_key(retailer)), None)
    if retailer is None:
        return {}
    source = SEUK_SOURCE_CONFIG[product_line]
    rules = {**_COMMON_RULES, **_EXTRA_RULES[source['product_key']]}
    if retailer == RETAILER:
        return rules

    statuses = _PRICE_STATUSES[seuk_retailer_key(retailer)]
    rules['account_name'] = (lambda value: seuk_retailer_key(value) == seuk_retailer_key(retailer), retailer)
    rules['final_sku_price'] = (
        lambda value: bool(_GBP.fullmatch(str(value).strip())) or str(value).strip() in statuses,
        ' / '.join(('£1399.00', '£1,399.00', *statuses)),
    )
    rules['screen_size'] = (lambda value: bool(_SCREEN_INCHES.fullmatch(str(value).strip())),
                            '55inch / 54.6 inch / 55 inches')
    if retailer == 'Amazon':
        rules.pop('count_of_reviews')
        rules['savings'] = (lambda value: bool(_PERCENT.fullmatch(str(value).strip())), '15%')
    else:
        rules['savings'] = (
            lambda value: bool(_GBP.fullmatch(str(value).strip()) or _PERCENT.fullmatch(str(value).strip())),
            '£20.99 / 10% / 25%',
        )
    return rules


def get_format_columns(product_line, retailer=RETAILER):
    return tuple(format_rules(product_line, retailer))


def get_format_editable_columns(product_line, retailer=RETAILER):
    return get_format_columns(product_line, retailer)


def uses_rule_descriptions(product_line, retailer):
    return product_line == 'seuk_tv' and seuk_retailer_key(retailer) in _PRICE_STATUSES


def _retailer_rule_descriptions(retailer):
    retailer_key = seuk_retailer_key(retailer)
    money = '£ 기호가 붙은 0 이상의 금액. 소수점 이하 두 자리이며 천 단위 쉼표는 선택입니다.'
    percent = '0~100의 정수 뒤에 %를 붙인 할인율'
    statuses = ', '.join(_PRICE_STATUSES[retailer_key])
    return {
        'country': '국가 코드 SEUK. 대소문자 무관.',
        'account_name': f'리테일러명 {retailer_key.capitalize()}. 대소문자 무관.',
        'count_of_reviews': '0 이상의 정수.',
        'count_of_star_ratings': '0 이상의 정수.',
        'star_rating': '0~5의 숫자. 소수점 이하 한 자리까지 허용합니다.',
        'final_sku_price': f'{money} 상태 문구도 허용합니다. {statuses}',
        'original_sku_price': money,
        'savings': f'{percent}.' if retailer_key == 'amazon' else f'{money} {percent}도 허용합니다.',
        'screen_size': '1 이상의 숫자(소수 허용)에 inch 또는 inches를 붙입니다. 단위 앞 공백은 선택입니다.',
    }


def get_format_rule_details(product_line, retailer=RETAILER):
    key = product_line_for(product_line)
    if key is None:
        return []
    descriptions = _retailer_rule_descriptions(retailer) if uses_rule_descriptions(key, retailer) else {}
    return [{'field': field, 'description': descriptions.get(field, f'{field} 값 형식'), 'pattern': pattern}
            for field, (_validator, pattern) in format_rules(key, retailer).items()]


def evaluate_format(row, product_line, retailer=RETAILER):
    return [field for field, (validator, _pattern) in format_rules(product_line, retailer).items()
            if row.get(field) is not None and str(row[field]).strip()
            and not validator(row[field])]


def _serialize(row, product_line, retailer):
    result = dict(row)
    result['_source_date'] = source_date_value(row.get('crawl_datetime'))
    result['error_fields'] = evaluate_format(row, product_line, retailer)
    result['error_field'] = ', '.join(result['error_fields'])
    rules = format_rules(product_line, retailer)
    descriptions = _retailer_rule_descriptions(retailer) if uses_rule_descriptions(product_line, retailer) else {}
    result['error_details'] = {field: {'rule': descriptions.get(field, rules[field][1]),
                                       'reason': '허용 형식 또는 값과 일치하지 않습니다'}
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
        mapping = seuk_null_validation._mapping(target_date, source)
        normal = _normal_reviews(cursor, mapping['inspection_date'], source)
        retailers = []
        for retailer in format_retailers(key):
            if mapping['source_date'] < str(retailer_start_date(source, retailer)):
                continue
            rows, _ = seuk_null_validation.latest_rows(cursor, target_date, source, retailer)
            issues = sum(f'{row["id"]}_{field}' not in normal
                         for row in rows for field in evaluate_format(row, key, retailer))
            retailers.append({
                'retailer': retailer, 'total': len(rows), 'issue_count': issues,
                'status': 'PENDING' if not rows else 'CRITICAL' if issues else 'OK',
            })
        issues = sum(retailer['issue_count'] for retailer in retailers)
        checked = sum(retailer['total'] for retailer in retailers)
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_checked': checked, 'total_issues': issues,
            'status': 'PENDING' if not checked else 'CRITICAL' if issues else 'OK',
            'retailers': retailers,
            **mapping,
        })
        total += issues
    return total


def format_detail(cursor, target_date, table, retailer=RETAILER, days=1, include_normal=False):
    key = product_line_for(table)
    if key is None or not get_format_columns(key, retailer):
        return {'results': [], 'column_names': [], 'actual_table': ''}
    source = SEUK_SOURCE_CONFIG[key]
    retailer = next(name for name in format_retailers(key)
                    if seuk_retailer_key(name) == seuk_retailer_key(retailer))
    mapping = seuk_null_validation._mapping(target_date, source)
    active_from = str(retailer_start_date(source, retailer))
    rows, normal = [], {}
    if mapping['source_date'] >= active_from:
        rows, _ = seuk_null_validation.latest_rows(cursor, target_date, source, retailer)
        normal = _normal_reviews(cursor, mapping['inspection_date'], source)
    current = [_serialize(row, key, retailer) for row in rows]
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
                cursor, source, retailer, source_day - timedelta(days=history_days - 1),
                source_day, items,
            )
            current_by_id = {row['id']: row for row in current}
            results = [current_by_id.get(row['id']) or _serialize(row, key, retailer) for row in history]
            seen = {row['id'] for row in results}
            results.extend(row for row in targets if row['id'] not in seen)
    columns = list(dict.fromkeys((
        'id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name',
        *get_format_columns(key, retailer), 'product_url',
    )))
    return {
        'date': mapping['inspection_date'], 'table': source['section_code'],
        'retailer': retailer, 'actual_table': source['table_name'],
        'column_names': columns, 'select_cols': list(source['columns']),
        'editable_cols': list(get_format_editable_columns(key, retailer)),
        'validation_fields': list(get_format_columns(key, retailer)),
        'target_ids': [row['id'] for row in targets],
        'batch_id': rows[0].get('batch_id') if rows else None,
        'normal_reviews': normal, 'results': results,
        'field_counts': dict(counts), 'total_format_count': sum(counts.values()),
        'supports_day_history': True, 'history_days': history_days,
        'active_from': active_from,
        'date_column': source['date_column'], 'readonly': False,
        **mapping,
    }
