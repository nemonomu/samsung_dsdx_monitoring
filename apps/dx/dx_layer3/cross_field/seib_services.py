"""Spain MediaMarkt cross-field checks on the original collection date."""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import re

from apps.common.crossfield_history import build_detail_history
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.null_review_evidence import exclude_page_absent_records
from apps.common.seib_retail import (
    FIRST_SOURCE_DATE, RETAILER, SEIB_SOURCE_CONFIG, get_seib_source,
    latest_scope,
)
from apps.common.source_dates import source_date_sql, source_date_value


EDITABLE_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
    'final_sku_price', 'original_sku_price', 'savings',
)
RULES = OrderedDict((
    ('review_count_match', ('리뷰 수와 별점 수 일치', 'count_of_reviews',
                            'count_of_star_ratings',
                            '리뷰 수와 별점 수가 다릅니다.',
                            'count_of_reviews|count_of_star_ratings|star_rating')),
    ('rating_count_presence', ('별점과 건수의 0 여부 일치', 'star_rating',
                               'count_of_star_ratings|count_of_reviews',
                               '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.',
                               'star_rating|count_of_star_ratings|count_of_reviews')),
    ('final_original_price', ('판매가와 원가 순서', 'final_sku_price',
                              'original_sku_price',
                              '판매가가 원가보다 크거나 같습니다.',
                              'final_sku_price|original_sku_price|savings')),
    ('savings_missing', ('할인율 누락', 'savings',
                         'original_sku_price|final_sku_price',
                         '계산 할인율의 버림값이 1% 이상인데 savings가 없습니다.',
                         'final_sku_price|original_sku_price|savings')),
    ('original_missing', ('원가 누락', 'original_sku_price',
                          'final_sku_price|savings',
                          '판매가와 savings가 있는데 원가가 없습니다.',
                          'final_sku_price|original_sku_price|savings')),
    ('final_missing', ('판매가 누락', 'final_sku_price',
                       'original_sku_price|savings',
                       '원가 또는 savings가 있는데 판매가가 없습니다.',
                       'final_sku_price|original_sku_price|savings')),
    ('savings_rate_match', ('할인율 일치', 'savings',
                            'original_sku_price|final_sku_price',
                            '표시 할인율과 계산 할인율의 소수점 버림값이 다릅니다.',
                            'final_sku_price|original_sku_price|savings')),
))


def _present(value):
    return value is not None and str(value).strip().casefold() not in ('', 'null', 'none', '-')


def _number(value):
    if not _present(value):
        return None
    text = str(value).strip()
    if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?', text):
        return None
    try:
        return Decimal(text.replace(',', '.'))
    except InvalidOperation:
        return None


def _money(value):
    if not _present(value):
        return None
    text = str(value).strip().replace('\u00a0', ' ').replace('\u20ac', '').strip().replace(' ', '')
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?', text):
        return None
    try:
        return Decimal(text.replace('.', '').replace(',', '.'))
    except InvalidOperation:
        return None


def _percent(value):
    if not _present(value):
        return None
    match = re.fullmatch(r'\s*(\d{1,3})%\s*', str(value))
    return Decimal(match.group(1)) if match else None


def evaluate_seib_row(row):
    """Invalid formats are left to Layer 2; dependent checks never cascade."""
    errors = set()
    reviews = _number(row.get('count_of_reviews'))
    stars = _number(row.get('count_of_star_ratings'))
    rating = _number(row.get('star_rating'))
    if reviews is not None and stars is not None and reviews != stars:
        errors.add('review_count_match')
    if rating is not None:
        if stars is not None and (rating == 0) != (stars == 0):
            errors.add('rating_count_presence')
        if reviews is not None and (rating == 0) != (reviews == 0):
            errors.add('rating_count_presence')

    final_present = _present(row.get('final_sku_price'))
    original_present = _present(row.get('original_sku_price'))
    savings_present = _present(row.get('savings'))
    if not final_present and (original_present or savings_present):
        errors.add('final_missing')
        return errors
    if final_present and savings_present and not original_present:
        errors.add('original_missing')
        return errors

    final = _money(row.get('final_sku_price'))
    original = _money(row.get('original_sku_price'))
    if final is None or original is None or original <= 0:
        return errors
    if final >= original:
        errors.add('final_original_price')
        return errors
    expected = ((original - final) * 100 / original).to_integral_value(rounding=ROUND_FLOOR)
    if not savings_present:
        if expected >= 1:
            errors.add('savings_missing')
    else:
        displayed = _percent(row.get('savings'))
        if displayed is not None and displayed != expected:
            errors.add('savings_rate_match')
    return errors


def _rows(cursor):
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], dict):
        return [dict(value) for value in values]
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, value)) for value in values]


def load_active_rules(cursor, source):
    cursor.execute("""
        SELECT id, detail_code, validation_type, retailer
        FROM public.monitoring_validation_rules
        WHERE rule_type = 'crossfield' AND is_active IS TRUE
          AND section_code = %s AND table_name = %s
        ORDER BY sort_order, id
    """, (source['section_code'], source['table_name']))
    result = []
    prefix = source['source_key'] + '_'
    for rule_id, detail_code, validation_type, retailer in cursor.fetchall():
        code = str(detail_code or '')
        key = code[len(prefix):] if code.startswith(prefix) else ''
        if key not in RULES or validation_type != key or str(retailer or '').casefold() != RETAILER.casefold():
            continue
        name, field1, field2, description, fields = RULES[key]
        result.append({
            'rule_id': rule_id, 'detail_code': code, 'rule_key': key,
            'validation_type': key, 'detail_name': name, 'guide_name': name,
            'guide_description': description, 'error_message': description,
            'field1': field1, 'field2': field2, 'select_fields': fields,
            'retailers': [RETAILER],
        })
    return result


def _load_rows(cursor, source, start, end):
    if date.fromisoformat(str(end)) < FIRST_SOURCE_DATE:
        return []
    cte, scope, params = latest_scope(source, start, end)
    cursor.execute(f"{cte} SELECT source.* {scope} ORDER BY source.item, source.id", params)
    return _rows(cursor)


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def display_query(source, source_date, days=3, items=None):
    end = date.fromisoformat(str(source_date))
    start = end - timedelta(days=min(30, max(1, int(days))) - 1)
    day = source_date_sql('anchor.crawl_datetime')
    source_day = source_date_sql('source.crawl_datetime')
    item_sql = ''
    if items is not None:
        item_sql = (' AND source.item IN (' + ', '.join(_literal(item) for item in sorted(set(items)))
                    + ')') if items else ' AND FALSE'
    return f"""WITH latest AS (
    SELECT DISTINCT ON ({day}) {day} AS source_date, anchor.batch_id
    FROM {source['table_name']} anchor
    WHERE {day} BETWEEN {_literal(max(start, FIRST_SOURCE_DATE))} AND {_literal(end)}
      AND LOWER(BTRIM(anchor.account_name)) = 'mediamarkt'
    ORDER BY {day}, anchor.id DESC
)
SELECT source.*
FROM {source['table_name']} source
JOIN latest ON {source_day} = latest.source_date
  AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
WHERE LOWER(BTRIM(source.account_name)) = 'mediamarkt'{item_sql}
ORDER BY source.item, source.crawl_datetime, source.id;"""


def _result(cursor, inspection_date, product_line, from_date=None):
    source = get_seib_source(product_line)
    mapping = resolve_monitoring_date(inspection_date, 'SEIB', source['source_key'])
    rules = load_active_rules(cursor, source)
    result = {
        **mapping, 'date': mapping['inspection_date'], 'source': source,
        'product_line': source['source_key'].upper(), 'label': source['display_name'],
        'table_name': source['table_name'], 'date_col': source['date_column'],
        'configured': bool(rules), 'rules': rules, 'rows': [],
        'corrections': [], 'page_exclusions': [],
    }
    if not rules:
        return result
    start = resolve_monitoring_date(from_date or inspection_date, 'SEIB', source['source_key'])['source_date']
    rows = _load_rows(cursor, source, start, mapping['source_date'])
    rows, exclusions = exclude_page_absent_records(
        cursor, inspection_date, rows, table_name=source['table_name'],
        country='SEIB', product_line=source['category'],
    )
    cursor.execute("""
        SELECT record_id, rule_id, column_name, memo, reason, created_id, created_at
        FROM public.monitoring_corrections
        WHERE layer = 3 AND correction_type = 'cross_field' AND status = 'normal'
          AND table_name = %s AND crawl_date = %s AND rule_id = ANY(%s)
    """, (source['table_name'], str(inspection_date), [rule['rule_id'] for rule in rules]))
    names = ('record_id', 'rule_id', 'column_name', 'memo', 'reason', 'created_id', 'created_at')
    corrections = [dict(value) if isinstance(value, dict) else dict(zip(names, value))
                   for value in cursor.fetchall()]
    normal = {(str(value['record_id']), str(value['rule_id'])) for value in corrections}
    for row in rows:
        row['account_name'] = RETAILER
    evaluated = {str(row['id']): evaluate_seib_row(row) for row in rows}
    for rule in rules:
        findings = []
        for row in rows:
            if source_date_value(row.get('crawl_datetime')) != mapping['source_date']:
                continue
            if (str(row['id']), str(rule['rule_id'])) in normal:
                continue
            if rule['rule_key'] in evaluated[str(row['id'])]:
                findings.append({
                    **row, 'finding_level': 'anomaly', 'rule_key': rule['rule_key'],
                    'validation_tag': rule['error_message'],
                })
        rule['findings'] = findings
    result.update(rows=rows, corrections=corrections, page_exclusions=exclusions)
    return result


def get_seib_cross_field_summary(cursor, inspection_date, product_line):
    result = _result(cursor, inspection_date, product_line)
    rows, rules = result['rows'], result['rules']
    targets = [row for row in rows if source_date_value(row.get('crawl_datetime')) == result['source_date']]
    failed = {str(row['id']) for rule in rules for row in rule['findings']}
    summaries = [{
        **{key: value for key, value in rule.items() if key != 'findings'},
        'error_count': len(rule['findings']), 'review_count': 0,
        'query': display_query(result['source'], result['source_date'],
                               items=[row['item'] for row in rule['findings']] or None),
    } for rule in rules]
    return {
        **{key: value for key, value in result.items()
           if key not in ('source', 'rows', 'rules', 'corrections')},
        'total_checked': len(targets), 'failed_records': len(failed),
        'total_anomalies': sum(rule['error_count'] for rule in summaries),
        'passed_records': len(targets) - len(failed),
        'rule_summary': summaries, 'no_review_texts': '',
        'retailers': [{'retailer': RETAILER, 'total_checked': len(targets),
                       'failed_records': len(failed),
                       'total_errors': sum(rule['error_count'] for rule in summaries)}],
    }


def get_seib_cross_field_rule_detail(cursor, inspection_date, product_line, rule_id, days=3):
    days = min(30, max(1, int(days)))
    result = _result(cursor, inspection_date, product_line,
                     from_date=inspection_date - timedelta(days=days - 1))
    rule = next((rule for rule in result['rules'] if str(rule['rule_id']) == str(rule_id)), None)
    if rule is None:
        return {'found': False}
    targets = rule['findings']
    anomalies = build_detail_history(
        result['rows'], targets, result['source_date'], result['date_col'], days,
        date_of=lambda row, column: source_date_value(row.get(column)),
    )
    corrections = [row for row in result['corrections'] if str(row['rule_id']) == str(rule_id)]
    normal_reviews = {}
    for correction in corrections:
        payload = {key: str(correction.get(key) or '') for key in ('memo', 'reason', 'created_id', 'created_at')}
        for column in EDITABLE_COLUMNS:
            normal_reviews[f"{correction['record_id']}_{column}"] = payload
    items = sorted({str(row['item']) for row in anomalies if _present(row.get('item'))})
    query = display_query(result['source'], result['source_date'], days, items)
    return {
        **{key: result[key] for key in ('date', 'inspection_date', 'source_date',
                                       'offset_days', 'product_line', 'table_name', 'date_col')},
        **{key: value for key, value in rule.items() if key != 'findings'},
        'found': True, 'days': days, 'anomalies': anomalies,
        'total_anomalies': len(targets), 'total_findings': len(targets),
        'retailer_summary': {RETAILER: {'count': len(targets), 'review_count': 0, 'items': items}},
        'editable_columns': list(EDITABLE_COLUMNS),
        'retailer_columns': {RETAILER: list(result['source']['columns'])},
        'retailer_editable_columns': {RETAILER: list(EDITABLE_COLUMNS)},
        'normal_reviews': normal_reviews, 'query': query, 'queries': {RETAILER: query},
    }
