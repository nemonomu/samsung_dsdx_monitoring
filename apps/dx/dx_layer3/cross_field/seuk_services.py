"""UK retail cross-field checks on the original collection date."""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from apps.common.crossfield_history import build_detail_history
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.null_review_evidence import exclude_page_absent_records
from apps.common.seuk_retail import (
    RETAILER, latest_scope, normalize_retailer, product_line_for, seuk_retailer_key, tv_review_query,
)
from apps.common.source_dates import source_date_sql, source_date_value
from apps.dx.dx_layer1.seuk_retail.sources import SEUK_SOURCE_CONFIG, retailer_start_date


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
    ('savings_missing', ('할인 금액 누락', 'savings',
                         'original_sku_price|final_sku_price',
                         '원가가 판매가보다 큰데 할인 금액(savings)이 없습니다.',
                         'final_sku_price|original_sku_price|savings')),
    ('original_missing', ('원가 누락', 'original_sku_price',
                          'final_sku_price|savings',
                          '판매가와 savings가 있는데 원가가 없습니다.',
                          'final_sku_price|original_sku_price|savings')),
    ('final_missing', ('판매가 누락', 'final_sku_price',
                       'original_sku_price|savings',
                       '원가 또는 savings가 있는데 판매가가 없습니다.',
                       'final_sku_price|original_sku_price|savings')),
    ('savings_amount_match', ('할인 금액 일치', 'savings',
                            'original_sku_price|final_sku_price',
                            '원가에서 판매가를 뺀 금액과 할인 금액(savings)이 다릅니다.',
                            'final_sku_price|original_sku_price|savings')),
))
PRICE_FIELDS = 'final_sku_price|original_sku_price|savings'
AMAZON_RULES = {
    'rating_count_presence': (
        '별점과 별점 수 일치', 'star_rating', 'count_of_star_ratings',
        '숫자 별점이 있는데 별점 수가 없거나 0이거나, 별점 없음 문구와 양수 별점 수가 함께 있습니다.',
        'star_rating|count_of_star_ratings',
    ),
    'final_original_price': (
        '판매가와 원가 순서', 'final_sku_price', 'original_sku_price',
        '판매가가 원가보다 크거나 같거나 할인율이 90% 이상입니다.', PRICE_FIELDS,
    ),
    'savings_missing': (
        '할인값 누락', 'savings', 'original_sku_price|final_sku_price',
        '할인율이 0.5% 이상인데 할인값(savings)이 없습니다.', PRICE_FIELDS,
    ),
    'original_missing': RULES['original_missing'],
    'final_missing': RULES['final_missing'],
}
ARGOS_RULES = {
    **RULES,
    'savings_missing': (
        '할인값 누락', 'savings', 'original_sku_price|final_sku_price',
        '원가가 판매가보다 큰데 할인값(savings)이 없습니다.', PRICE_FIELDS,
    ),
    'savings_amount_match': (
        '할인값 일치', 'savings', 'original_sku_price|final_sku_price',
        '£ 금액은 원가와 판매가의 차액, %는 정수로 반올림한 할인율과 일치해야 합니다.',
        PRICE_FIELDS,
    ),
}
AMAZON_NO_RATING_TEXTS = frozenset(('no customer reviews', 'no reviews', 'no ratings'))


def _present(value):
    return value is not None and str(value).strip().casefold() not in ('', 'null', 'none', '-')


def _number(value):
    if not _present(value):
        return None
    text = str(value).strip()
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text.replace(',', ''))
    except InvalidOperation:
        return None


def _money(value):
    if not _present(value):
        return None
    text = str(value).strip().replace('\u00a0', ' ')
    if text.startswith('\u00a3'):
        text = text[1:].strip()
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?', text):
        return None
    return Decimal(text.replace(',', ''))


def _amazon_present(value):
    return _present(value) and str(value).strip().casefold() != 'n/a'


def _evaluate_amazon(row):
    errors = set()
    rating_text = str(row.get('star_rating') or '').strip().casefold()
    count = row.get('count_of_star_ratings')
    rating = _number(row.get('star_rating'))
    stars = _number(count)
    no_stars = (count is None or not str(count).strip() or stars == 0
                or str(count).strip().casefold() in AMAZON_NO_RATING_TEXTS)
    if ((rating is not None and rating > 0 and no_stars)
            or (rating_text in AMAZON_NO_RATING_TEXTS and stars is not None and stars > 0)):
        errors.add('rating_count_presence')

    final_value = row.get('final_sku_price')
    original_value = row.get('original_sku_price')
    final = _money(final_value)
    original = _money(original_value)
    has_savings = _amazon_present(row.get('savings'))
    if not _amazon_present(final_value) and (_amazon_present(original_value) or has_savings):
        errors.add('final_missing')
    elif final is not None and has_savings and not _amazon_present(original_value):
        errors.add('original_missing')
    elif final is not None and original is not None:
        discount = original - final
        if final >= original or discount * 10 >= original * 9:
            errors.add('final_original_price')
        if original > 0 and not has_savings and discount * 200 >= original:
            errors.add('savings_missing')
    return errors


def _argos_savings_matches(value, original, difference):
    text = str(value).strip()
    if text.startswith('£'):
        amount = _money(text)
        return amount is None or amount == difference
    if re.fullmatch(r'\d+\s*%', text):
        expected_pct = (difference * 100 / original).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return Decimal(text[:-1].strip()) == expected_pct
    # Unrecognized units are handled by format validation.
    return True


def evaluate_seuk_row(row):
    """Invalid formats are left to Layer 2; dependent checks never cascade."""
    retailer = seuk_retailer_key(row.get('account_name'))
    if retailer == 'amazon':
        return _evaluate_amazon(row)

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
    expected = original - final
    if not savings_present:
        if expected > 0:
            errors.add('savings_missing')
    elif retailer == 'argos':
        if not _argos_savings_matches(row.get('savings'), original, expected):
            errors.add('savings_amount_match')
    else:
        displayed = _money(row.get('savings'))
        if displayed is not None and displayed != expected:
            errors.add('savings_amount_match')
    return errors


def _rows(cursor):
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], dict):
        return [dict(value) for value in values]
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, value)) for value in values]


def rule_definitions(retailer):
    if retailer == 'Amazon':
        return AMAZON_RULES
    if retailer == 'Argos':
        return ARGOS_RULES
    return RULES


def editable_columns(retailer):
    if seuk_retailer_key(retailer) == 'amazon':
        return tuple(column for column in EDITABLE_COLUMNS if column != 'count_of_reviews')
    return EDITABLE_COLUMNS


def table_columns(source, retailer):
    if source['source_key'] == 'seuk_tv':
        return (*source['columns'], 'is_redirect')
    return source['columns']


def load_active_rules(cursor, source):
    from apps.common.db import dx_table
    cursor.execute(f"""
        SELECT id, detail_code, validation_type, retailer
        FROM public.{dx_table('monitoring_validation_rules')}
        WHERE rule_type = 'crossfield' AND is_active IS TRUE
          AND section_code = %s AND table_name = %s
        ORDER BY sort_order, id
    """, (source['section_code'], source['table_name']))
    result = []
    for rule_id, detail_code, validation_type, retailer in cursor.fetchall():
        try:
            retailer = normalize_retailer(source, retailer)
        except ValueError:
            continue
        prefix = source['source_key'] + ('_' if retailer == RETAILER else '_' + retailer.lower() + '_')
        code = str(detail_code or '')
        key = code[len(prefix):] if code.startswith(prefix) else ''
        definitions = rule_definitions(retailer)
        if key not in definitions or validation_type != key:
            continue
        name, field1, field2, description, fields = definitions[key]
        result.append({
            'rule_id': rule_id, 'detail_code': code, 'rule_key': key,
            'validation_type': key, 'detail_name': name, 'guide_name': name,
            'guide_description': description, 'error_message': description,
            'field1': field1, 'field2': field2, 'select_fields': fields,
            'retailers': [retailer],
        })
    return result


def day_is_active(source, day, retailer):
    return str(day) >= str(retailer_start_date(source, retailer))


def _amazon_redirect_filter(retailers):
    if 'Amazon' not in retailers:
        return ''
    if len(retailers) == 1:
        return ' AND source.is_redirect IS NOT TRUE'
    return " AND (LOWER(BTRIM(source.account_name)) <> 'amazon' OR source.is_redirect IS NOT TRUE)"


def record_scope(source, day):
    """Select the latest batch per retailer for a review or edit on one source day."""
    retailers = source['retailers']
    if 'Amazon' in retailers:
        retailers = tuple(name for name in retailers if day_is_active(source, day, name))
        if not retailers:
            return '', f"FROM {source['table_name']} source WHERE FALSE", []
        source = {**source, 'retailers': retailers}
    retailer = retailers[0] if len(retailers) == 1 else None
    cte, scope, params = latest_scope(source, day, day, retailer)
    return cte, scope + _amazon_redirect_filter(retailers), params


def _load_rows(cursor, source, start, end, retailer=RETAILER):
    retailer = normalize_retailer(source, retailer)
    if not day_is_active(source, end, retailer):
        return []
    start = max(str(start), str(retailer_start_date(source, retailer)))
    cte, scope, params = latest_scope(source, start, end, retailer)
    scope += _amazon_redirect_filter((retailer,))
    cursor.execute(f"{cte} SELECT source.* {scope} ORDER BY source.item, source.id", params)
    return _rows(cursor)


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def display_query(source, source_date, days=3, items=None, retailer=RETAILER):
    retailer = normalize_retailer(source, retailer)
    end = date.fromisoformat(str(source_date))
    start = end - timedelta(days=min(30, max(1, int(days))) - 1)
    day = source_date_sql('anchor.crawl_datetime')
    source_day = source_date_sql('source.crawl_datetime')
    redirect_sql = _amazon_redirect_filter((retailer,))
    item_sql = ''
    if items is not None:
        item_sql = (' AND source.item IN (' + ', '.join(_literal(item) for item in sorted(set(items)))
                    + ')') if items else ' AND FALSE'
    return f"""WITH latest AS (
    SELECT DISTINCT ON ({day}) {day} AS source_date, anchor.batch_id
    FROM {source['table_name']} anchor
    WHERE {day} BETWEEN {_literal(max(start, retailer_start_date(source, retailer)))} AND {_literal(end)}
      AND LOWER(BTRIM(anchor.account_name)) = {_literal(retailer.lower())}
    ORDER BY {day}, anchor.id DESC
)
SELECT source.*
FROM {source['table_name']} source
JOIN latest ON {source_day} = latest.source_date
  AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
WHERE LOWER(BTRIM(source.account_name)) = {_literal(retailer.lower())}{redirect_sql}{item_sql}
ORDER BY source.item, source.crawl_datetime, source.id;"""


def _tv_review_columns(rule):
    selected = set(rule['select_fields'].split('|'))
    metrics = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
    prices = ('original_sku_price', 'final_sku_price', 'savings')
    if selected.intersection(metrics):
        selected.update(metrics)
    if rule['retailers'][0] == RETAILER:
        selected.add('count_of_star_ratings')
    selected.add('count_of_reviews')
    return (
        'id', 'item', 'crawl_datetime', *(field for field in metrics if field in selected),
        'retailer_sku_name', *(prices if selected.intersection(prices) else ()), 'product_url',
    )


def _tv_summary_query(source_date, rule, targets, raw_accounts):
    day = date.fromisoformat(source_date)
    retailer = rule['retailers'][0]
    findings = rule['findings']
    rows = findings or [row for row in targets if row['account_name'] == retailer]
    return tv_review_query(_tv_review_columns(rule), rows, day, day,
                           raw_accounts=raw_accounts, include_items=bool(findings))


def _result(cursor, inspection_date, product_line, from_date=None):
    key = product_line_for(product_line)
    if key is None:
        raise ValueError('Unsupported SEUK source')
    source = SEUK_SOURCE_CONFIG[key]
    mapping = resolve_monitoring_date(inspection_date, 'SEUK', source['source_key'])
    rules = load_active_rules(cursor, source)
    rules = [rule for rule in rules
             if rule['retailers'][0] not in ('Amazon', 'Argos')
             or day_is_active(source, mapping['source_date'], rule['retailers'][0])]
    result = {
        **mapping, 'date': mapping['inspection_date'], 'source': source,
        'product_line': source['source_key'].upper(), 'label': source['display_name'],
        'table_name': source['table_name'], 'date_col': source['date_column'],
        'configured': bool(rules), 'rules': rules, 'rows': [], 'raw_accounts': {},
        'corrections': [], 'page_exclusions': [],
    }
    if not rules:
        return result
    start = resolve_monitoring_date(from_date or inspection_date, 'SEUK', source['source_key'])['source_date']
    retailers = list(dict.fromkeys(r['retailers'][0] for r in rules))
    rows = [row for retailer in retailers
            for row in _load_rows(cursor, source, start, mapping['source_date'], retailer)]
    rows, exclusions = exclude_page_absent_records(
        cursor, inspection_date, rows, table_name=source['table_name'],
        country='SEUK', product_line=source['category'],
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
    if key == 'seuk_tv':
        result['raw_accounts'] = {row['id']: row['account_name'] for row in rows}
    for row in rows:
        row['account_name'] = normalize_retailer(source, row['account_name'])
    evaluated = {str(row['id']): evaluate_seuk_row(row) for row in rows}
    for rule in rules:
        findings = []
        for row in rows:
            if row['account_name'] not in rule['retailers']:
                continue
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


def get_seuk_cross_field_summary(cursor, inspection_date, product_line):
    result = _result(cursor, inspection_date, product_line)
    rows, rules = result['rows'], result['rules']
    targets = [row for row in rows if source_date_value(row.get('crawl_datetime')) == result['source_date']]
    failed = {str(row['id']) for rule in rules for row in rule['findings']}
    is_tv = result['source']['source_key'] == 'seuk_tv'
    summaries = [{
        **{key: value for key, value in rule.items() if key != 'findings'},
        'error_count': len(rule['findings']), 'review_count': 0,
        'query': (_tv_summary_query(result['source_date'], rule, targets, result['raw_accounts']) if is_tv else
                  display_query(result['source'], result['source_date'],
                                items=[row['item'] for row in rule['findings']] or None, retailer=rule['retailers'][0])),
    } for rule in rules]
    return {
        **{key: value for key, value in result.items()
           if key not in ('source', 'rows', 'rules', 'corrections', 'raw_accounts')},
        'total_checked': len(targets), 'failed_records': len(failed),
        'total_anomalies': sum(rule['error_count'] for rule in summaries),
        'passed_records': len(targets) - len(failed),
        'rule_summary': summaries, 'no_review_texts': '',
        'retailers': [dict(
            retailer=retailer,
            total_checked=sum(row['account_name'] == retailer for row in targets),
            failed_records=len({str(row['id']) for rule in rules for row in rule['findings']
                                if row['account_name'] == retailer}),
            total_errors=sum(rule['error_count'] for rule in summaries if retailer in rule['retailers']),
        ) for retailer in dict.fromkeys(r['retailers'][0] for r in rules)],
    }


def get_seuk_cross_field_rule_detail(cursor, inspection_date, product_line, rule_id, days=3):
    days = min(30, max(1, int(days)))
    result = _result(cursor, inspection_date, product_line,
                     from_date=inspection_date - timedelta(days=days - 1))
    rule = next((rule for rule in result['rules'] if str(rule['rule_id']) == str(rule_id)), None)
    if rule is None:
        return {'found': False}
    retailer = rule['retailers'][0]
    targets = rule['findings']
    anomalies = build_detail_history(
        [row for row in result['rows'] if row['account_name'] == retailer],
        targets, result['source_date'], result['date_col'], days,
        date_of=lambda row, column: source_date_value(row.get(column)),
    )
    corrections = [row for row in result['corrections'] if str(row['rule_id']) == str(rule_id)]
    normal_reviews = {}
    for correction in corrections:
        payload = {key: str(correction.get(key) or '') for key in ('memo', 'reason', 'created_id', 'created_at')}
        for column in editable_columns(retailer):
            normal_reviews[f"{correction['record_id']}_{column}"] = payload
    items = sorted({str(row['item']) for row in anomalies if _present(row.get('item'))})
    if result['source']['source_key'] == 'seuk_tv':
        end = date.fromisoformat(result['source_date'])
        start = max(end - timedelta(days=days - 1), retailer_start_date(result['source'], retailer))
        query = tv_review_query(_tv_review_columns(rule), anomalies, start, end,
                               raw_accounts=result['raw_accounts'])
    else:
        query = display_query(result['source'], result['source_date'], days, items, retailer)
    return {
        **{key: result[key] for key in ('date', 'inspection_date', 'source_date',
                                       'offset_days', 'product_line', 'table_name', 'date_col')},
        **{key: value for key, value in rule.items() if key != 'findings'},
        'found': True, 'days': days, 'anomalies': anomalies,
        'total_anomalies': len(targets), 'total_findings': len(targets),
        'retailer_summary': {retailer: {'count': len(targets), 'review_count': 0, 'items': items}},
        'editable_columns': list(editable_columns(retailer)),
        'retailer_columns': {retailer: list(table_columns(result['source'], retailer))},
        'retailer_editable_columns': {retailer: list(editable_columns(retailer))},
        'normal_reviews': normal_reviews, 'query': query, 'queries': {retailer: query},
    }
