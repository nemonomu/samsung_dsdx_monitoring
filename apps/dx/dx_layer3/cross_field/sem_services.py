"""SEM Liverpool cross-field validation for the latest daily batch."""

from apps.common.sem_retail import (
    SEM_RETAILER,
    SEM_SOURCE_CONFIG,
    get_sem_editable_columns,
)
from apps.dx.dx_layer2.sem_validation import _latest_rows, product_line_for


_RULES = (
    ('rating_count_consistency', '평점과 평가 수 일치', 'star_rating',
     'count_of_star_ratings',
     '평점과 평가 수의 0 여부가 다르거나 평점과 리뷰 수의 존재 여부가 다릅니다.'),
    ('review_rating_count', '리뷰 수와 평가 수 일치', 'count_of_reviews',
     'count_of_star_ratings',
     'Liverpool 리뷰 수와 평가 수가 일치하지 않습니다.'),
    ('final_original_price', '최종가와 원가 순서', 'final_sku_price',
     'original_sku_price', '최종 판매가가 원가보다 큽니다.'),
    ('original_price_zero', '원가 0 검사', 'original_sku_price',
     None, 'original_sku_price가 0입니다.'),
)


def _blank(value):
    return value is None or str(value).strip() == ''


def _number(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _failed_rules(row):
    rating = row.get('star_rating')
    rating_count = row.get('count_of_star_ratings')
    review_count = row.get('count_of_reviews')
    rating_present = not _blank(rating)
    rating_count_present = not _blank(rating_count)
    review_count_present = not _blank(review_count)
    failed = []
    if rating_present and rating_count_present:
        rating_value = _number(rating)
        rating_count_value = _number(rating_count)
        if ((rating_value == 0) != (rating_count_value == 0)):
            failed.append('rating_count_consistency')
    if rating_present != review_count_present:
        if 'rating_count_consistency' not in failed:
            failed.append('rating_count_consistency')
    if rating_count_present and review_count_present:
        rating_count_value = _number(rating_count)
        review_count_value = _number(review_count)
        if rating_count_value != review_count_value:
            failed.append('review_rating_count')
    final_price = _number(row.get('final_sku_price'))
    original_price = _number(row.get('original_sku_price'))
    if original_price == 0:
        failed.append('original_price_zero')
    elif final_price is not None and original_price is not None and final_price > original_price:
        failed.append('final_original_price')
    return failed


def _result(cursor, target_date, product_line):
    key = product_line_for(product_line)
    source = SEM_SOURCE_CONFIG.get(key)
    if not source:
        raise ValueError(f'Unsupported SEM product line: {product_line}')
    rows, mapping = _latest_rows(cursor, target_date, source)
    failures = {rule[0]: [] for rule in _RULES}
    failed_ids = set()
    for row in rows:
        for rule_key in _failed_rules(row):
            failures[rule_key].append(row)
            failed_ids.add(row.get('id'))
    summaries = []
    for index, rule in enumerate(_RULES, 1):
        rule_key, name, field1, field2, message = rule
        summaries.append({
            'rule_id': f'{key}:{rule_key}',
            'detail_code': f'{key}_{rule_key}',
            'rule_key': rule_key,
            'detail_name': name,
            'field1': field1,
            'field2': field2,
            'validation_type': rule_key,
            'error_message': message,
            'error_count': len(failures[rule_key]),
            'select_fields': 'star_rating|count_of_star_ratings|count_of_reviews|final_sku_price|original_sku_price',
            'sort_order': index * 10,
        })
    return source, rows, failures, failed_ids, summaries, mapping


def get_sem_cross_field_summary(cursor, target_date, product_line):
    source, rows, _failures, failed_ids, rules, mapping = _result(
        cursor, target_date, product_line
    )
    return {
        'configured': True,
        'label': source['display_name'],
        'product_line': source['source_key'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'total_checked': len(rows),
        'failed_records': len(failed_ids),
        'passed_records': max(0, len(rows) - len(failed_ids)),
        'total_anomalies': sum(rule['error_count'] for rule in rules),
        'rule_summary': rules,
        'no_review_texts': '',
        **mapping,
    }


def get_sem_cross_field_rule_detail(cursor, target_date, product_line, rule_id, days=1):
    source, _rows, failures, _failed_ids, rules, mapping = _result(
        cursor, target_date, product_line
    )
    rule = next((item for item in rules if str(item['rule_id']) == str(rule_id)), None)
    if rule is None:
        return {'found': False}
    anomalies = failures[rule['rule_key']]
    editable_columns = list(get_sem_editable_columns(source['source_key']))
    return {
        'found': True,
        'date': mapping['inspection_date'],
        'days': days,
        'product_line': source['source_key'].upper(),
        'rule_id': rule['rule_id'],
        'detail_code': rule['detail_code'],
        'field1': rule['field1'],
        'field2': rule['field2'],
        'validation_type': rule['validation_type'],
        'error_message': rule['error_message'],
        'total_anomalies': len(anomalies),
        'retailer_summary': {SEM_RETAILER: {
            'count': len(anomalies),
            'items': list(dict.fromkeys(str(row.get('item') or '') for row in anomalies)),
        }},
        'anomalies': anomalies,
        'select_fields': rule['select_fields'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'editable_columns': editable_columns,
        'normal_reviews': {},
        'retailer_columns': {SEM_RETAILER: editable_columns},
        **mapping,
    }
