"""SEM cross-field validation for each retailer's latest daily batch."""

from datetime import date, timedelta
from decimal import Decimal

from apps.common.crossfield_history import build_detail_history
from apps.common.null_review_evidence import exclude_page_absent_records
from apps.common.sem_retail import (
    SEM_COUNTRY,
    SEM_HOMEDEPOT_RETAILER,
    SEM_RETAILER,
    SEM_SOURCE_CONFIG,
    get_sem_editable_columns,
    get_sem_table_columns,
)
from apps.dx.dx_layer2.sem_validation import (
    _format_checks, _history_rows, _latest_rows, product_line_for,
)


_RULES = (
    ('rating_count_consistency', '평점과 평가 수 일치', 'star_rating',
     'count_of_star_ratings',
     '평점과 평가 수 또는 리뷰 수의 0 여부가 다르거나 평점과 리뷰 수의 존재 여부가 다릅니다.'),
    ('review_rating_count', '리뷰 수와 평가 수 일치', 'count_of_reviews',
     'count_of_star_ratings',
     '리뷰 수와 평가 수가 일치하지 않습니다.'),
    ('final_original_price', '최종가와 원가 순서', 'final_sku_price',
     'original_sku_price', '두 가격이 숫자이고 원가가 0이 아닐 때 최종 판매가가 원가보다 크거나 같으면 이상입니다.'),
    ('original_price_zero', '원가 0 검사', 'original_sku_price',
     None, 'original_sku_price가 0입니다.'),
)
_HOMEDEPOT_RULES = (
    ('savings_missing', 'HomeDepot savings 누락', 'final_sku_price',
     'original_sku_price', '최종가와 원가가 있는데 savings가 없습니다.'),
    ('original_missing', 'HomeDepot 원가 누락', 'original_sku_price',
     'savings', '최종가와 savings가 있는데 원가가 없습니다.'),
    ('final_missing', 'HomeDepot 최종가 누락', 'final_sku_price',
     'savings', '최종가가 없는데 원가 또는 savings가 있습니다.'),
    ('savings_rate_match', 'HomeDepot 할인율 일치', 'savings',
     'original_sku_price',
     '최종가·원가·savings 형식이 유효하고 원가 > 0, 최종가 < 원가일 때 계산 할인율이 savings의 할인율 크기 이상, 그 값+1 미만 범위를 벗어나면 이상입니다.'),
)
_REVIEW_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)


def _blank(value):
    return value is None or str(value).strip() == ''


def _number(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _rule_select_fields(field1, field2, rule_key=None):
    if rule_key in {rule[0] for rule in _HOMEDEPOT_RULES}:
        return 'final_sku_price|original_sku_price|savings'
    fields = (field1, field2)
    if any(field in _REVIEW_COLUMNS for field in fields):
        return '|'.join(_REVIEW_COLUMNS)
    return '|'.join(field for field in fields if field)


def _failed_rules(row, retailer=SEM_RETAILER, product_line='sem_ref'):
    original_row = row
    if retailer == SEM_HOMEDEPOT_RETAILER:
        # Invalid present values belong to format validation. Do not compare
        # their failed parses to zero or calculate dependent price errors.
        checks = _format_checks(product_line, retailer)
        row = dict(row)
        for field in (*_REVIEW_COLUMNS, 'final_sku_price', 'original_sku_price'):
            if not _blank(row.get(field)) and not checks[field](row[field]):
                row[field] = None
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
    if _blank(original_row.get('star_rating')) != _blank(original_row.get('count_of_reviews')):
        if 'rating_count_consistency' not in failed:
            failed.append('rating_count_consistency')
    rating_value = _number(rating)
    review_count_value = _number(review_count)
    if rating_value is not None and review_count_value is not None:
        if (rating_value == 0) != (review_count_value == 0):
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
    elif final_price is not None and original_price is not None and final_price >= original_price:
        failed.append('final_original_price')
    if retailer == SEM_HOMEDEPOT_RETAILER:
        failed.extend(_homedepot_price_rules(original_row, checks))
    return failed


def _homedepot_price_rules(row, checks):
    fields = ('final_sku_price', 'original_sku_price', 'savings')
    final, original, savings = [not _blank(row.get(field)) for field in fields]
    if not final and (original or savings):
        return ['final_missing']
    if final and original and not savings:
        return ['savings_missing']
    if final and savings and not original:
        return ['original_missing']
    if not all((final, original, savings)):
        return []
    if any(not checks[field](row[field]) for field in fields):
        return []
    # Integer cents make the boundary comparison exact without a float or
    # a rounded division, even immediately below the next integer percent.
    cents = lambda value: int(Decimal(str(value).strip().replace('$', '').replace(',', '')) * 100)
    final_cents = cents(row['final_sku_price'])
    original_cents = cents(row['original_sku_price'])
    if original_cents <= 0 or final_cents >= original_cents:
        return []
    discount = int(str(row['savings']).strip()[1:-1])
    difference = (original_cents - final_cents) * 100
    if not discount * original_cents <= difference < (discount + 1) * original_cents:
        return ['savings_rate_match']
    return []


def _result(cursor, target_date, product_line):
    key = product_line_for(product_line)
    source = SEM_SOURCE_CONFIG.get(key)
    if not source:
        raise ValueError(f'Unsupported SEM product line: {product_line}')
    definitions = _RULES + (
        _HOMEDEPOT_RULES if SEM_HOMEDEPOT_RETAILER in source['retailers'] else ()
    )
    rows = []
    page_exclusions = []
    failures = {rule[0]: [] for rule in definitions}
    failed_ids = set()
    for retailer in source['retailers']:
        if retailer == SEM_RETAILER:
            retailer_rows, mapping = _latest_rows(cursor, target_date, source)
        else:
            retailer_rows, mapping = _latest_rows(cursor, target_date, source, retailer=retailer)
        retailer_rows, excluded = exclude_page_absent_records(
            cursor, target_date, retailer_rows, table_name=source['table_name'],
            country='SEM', product_line=key.rsplit('_', 1)[-1],
        )
        page_exclusions.extend(excluded)
        rows.extend(retailer_rows)
        for row in retailer_rows:
            for rule_key in _failed_rules(row, retailer, key):
                failures[rule_key].append(row)
                failed_ids.add(row.get('id'))
    summaries = []
    for index, rule in enumerate(definitions, 1):
        rule_key, name, field1, field2, message = rule
        summaries.append({
            'rule_id': f'{key}:{rule_key}',
            'detail_code': f'{key}_{rule_key}',
            'rule_key': rule_key,
            'detail_name': name,
            'retailers': list(source['retailers']) if rule in _RULES else [SEM_HOMEDEPOT_RETAILER],
            'field1': field1,
            'field2': field2,
            'validation_type': rule_key,
            'error_message': message,
            'error_count': len(failures[rule_key]),
            'select_fields': _rule_select_fields(field1, field2, rule_key),
            'sort_order': index * 10,
        })
    mapping = {**mapping, 'page_exclusions': page_exclusions}
    return source, rows, failures, failed_ids, summaries, mapping


def get_sem_cross_field_summary(cursor, target_date, product_line):
    source, rows, _failures, failed_ids, rules, mapping = _result(
        cursor, target_date, product_line
    )
    return {
        'configured': True,
        'date': mapping['inspection_date'],
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
    target_anomalies = failures[rule['rule_key']]
    days = min(30, max(1, int(days or 1)))
    source_date = date.fromisoformat(mapping['source_date'])
    history = []
    retailer_summary = {}
    for retailer in source['retailers']:
        targets = [row for row in target_anomalies
                   if str(row.get('account_name') or '').strip().casefold() == retailer.casefold()]
        items = sorted({str(row['item']) for row in targets if not _blank(row.get('item'))})
        retailer_summary[retailer] = {'count': len(targets), 'items': items}
        if days > 1 and items:
            options = {} if retailer == SEM_RETAILER else {'retailer': retailer}
            history.extend(_history_rows(
                cursor, source, source_date - timedelta(days=days - 1),
                source_date - timedelta(days=1), items, **options,
            ))
    history = [row for row in history
               if str(row.get('country') or '').strip().upper() == SEM_COUNTRY]
    anomalies = build_detail_history(
        history, target_anomalies, source_date, source['date_column'], days,
    )
    editable_columns = list(get_sem_editable_columns(source['source_key'], None))
    table_columns = list(get_sem_table_columns(source['source_key']))
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
        'total_anomalies': len(target_anomalies),
        'retailer_summary': retailer_summary,
        'anomalies': anomalies,
        'select_fields': rule['select_fields'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'editable_columns': editable_columns,
        'retailer_editable_columns': {
            retailer: list(get_sem_editable_columns(source['source_key'], retailer))
            for retailer in source['retailers']
        },
        'normal_reviews': {},
        'retailer_columns': {retailer: table_columns for retailer in source['retailers']},
        **mapping,
    }
