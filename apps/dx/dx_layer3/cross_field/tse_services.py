"""TSE retail cross-field validation.

The source tables and editable identifiers are resolved through the shared
TSE registry.  Validation SQL stored in ``monitoring_validation_rules`` is
metadata only for this service; it is never executed.  That keeps the TSE
rules deterministic and prevents arbitrary SQL from the monitoring tables
from reaching the source schema.
"""

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import re

from apps.common.retail_columns import (
    get_editable_columns,
    get_tse_retailer_columns,
)
from apps.common.tse_retail import (
    TSE_COUNTRY,
    TSE_LAZADA_RETAILER,
    TSE_LOTUSS_RETAILER,
    display_tse_retailer,
    get_tse_editable_columns,
    get_tse_source,
    normalize_tse_product_line,
    tse_crossfield_rule_supported,
)


TSE_RULE_SPECS = OrderedDict((
    ('review_count_match', {
        'detail_name': '리뷰 수와 별점 수 일치',
        'field1': 'count_of_reviews',
        'field2': 'count_of_star_ratings',
        'error_message': 'count_of_reviews와 count_of_star_ratings가 다릅니다.',
    }),
    ('review_zero_pair', {
        'detail_name': '별점 0과 별점 수 0 일치',
        'field1': 'star_rating',
        'field2': 'count_of_star_ratings',
        'error_message': 'star_rating의 0 여부와 count_of_star_ratings의 0 여부가 다릅니다.',
    }),
    ('final_original_price', {
        'detail_name': '최종가와 원가 순서',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'error_message': 'final_sku_price가 original_sku_price보다 큽니다.',
    }),
    ('savings_requires_original', {
        'detail_name': '할인 정보와 원가 존재',
        'field1': 'savings',
        'field2': 'original_sku_price',
        'error_message': 'savings가 있지만 original_sku_price가 없습니다.',
    }),
    ('savings_format', {
        'detail_name': '할인 정보 형식',
        'field1': 'savings',
        'field2': None,
        'error_message': 'savings를 할인 금액 또는 할인율로 변환할 수 없습니다.',
    }),
    ('original_price_zero', {
        'detail_name': '원가 0 검사',
        'field1': 'original_sku_price',
        'field2': None,
        'error_message': 'original_sku_price가 0입니다.',
    }),
    ('savings_amount_match', {
        'detail_name': '할인 금액 일치',
        'field1': 'savings',
        'field2': 'original_sku_price|final_sku_price',
        'error_message': '표시 할인 금액이 original_sku_price-final_sku_price와 다릅니다.',
    }),
    ('savings_rate_match', {
        'detail_name': '할인율 일치',
        'field1': 'savings',
        'field2': 'original_sku_price|final_sku_price',
        'error_message': '표시 할인율이 FLOOR((원가-최종가)/원가*100)과 다릅니다.',
    }),
))

_TSE_DISPLAY_QUERY_COLUMNS = {
    'id', 'batch_id', 'country', 'account_name', 'item', 'crawl_datetime',
    'sku', 'retailer_sku_name',
    'count_of_reviews', 'count_of_star_ratings', 'star_rating',
    'final_sku_price', 'original_sku_price', 'savings', 'product_url',
}


_RULE_ALIASES = {
    'review_count_mismatch': 'review_count_match',
    'review_rating_count_match': 'review_count_match',
    'rating_zero_pair': 'review_zero_pair',
    'review_zero_mismatch': 'review_zero_pair',
    'price_order': 'final_original_price',
    'price_reverse': 'final_original_price',
    'savings_without_original': 'savings_requires_original',
    'savings_parse': 'savings_format',
    'original_zero': 'original_price_zero',
    'savings_amount': 'savings_amount_match',
    'savings_rate': 'savings_rate_match',
}


def _has_value(value):
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '-', 'none', 'null', 'n/a')


def parse_tse_number(value):
    """Parse a plain decimal/count value, returning ``None`` on bad input."""
    if not _has_value(value):
        return None
    text = str(value).strip().replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_tse_money(value):
    """Parse Thai baht text such as ``฿10,820`` into ``Decimal``."""
    if not _has_value(value):
        return None
    text = str(value).strip()
    text = re.sub(r'(?i)\bTHB\b', '', text)
    text = text.replace('฿', '').replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_tse_savings(value):
    """Return ``(valid, amount, percentage)`` for a savings display value.

    Either an amount or percentage is sufficient.  A negative displayed
    percentage (for example ``-30%``) is preserved here and compared by its
    absolute value by the validator.
    """
    if not _has_value(value):
        return False, None, None

    text = str(value).strip()
    percent_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', text)
    percentage = None
    if percent_match:
        try:
            percentage = Decimal(percent_match.group(1))
        except InvalidOperation:
            return False, None, None

    amount_text = re.sub(
        r'\(?\s*[+-]?\d+(?:\.\d+)?\s*%\s*\)?',
        ' ',
        text,
    )
    amount_text = re.sub(r'(?i)\b(save|saving|savings)\b\s*:?', ' ', amount_text)
    amount_text = amount_text.strip(' ()')

    amount = None
    if amount_text:
        amount = parse_tse_money(amount_text)
        if amount is None:
            return False, None, None

    if amount is None and percentage is None:
        return False, None, None
    return True, amount, percentage


def evaluate_tse_row(row):
    """Return the set of canonical TSE rule keys failed by one source row.

    NULL/format prerequisites handled by Layer 2 do not cascade into several
    Layer 3 findings.  Price reversal and zero-original findings also stop
    downstream savings comparisons for that row.
    """
    errors = set()
    retailer_key = str(row.get('account_name') or '').strip().casefold()

    review_count = parse_tse_number(row.get('count_of_reviews'))
    star_count = parse_tse_number(row.get('count_of_star_ratings'))
    rating = parse_tse_number(row.get('star_rating'))

    if review_count is not None and star_count is not None:
        if review_count != star_count:
            errors.add('review_count_match')
    if rating is not None and star_count is not None:
        if (rating == 0) != (star_count == 0):
            errors.add('review_zero_pair')

    savings_present = _has_value(row.get('savings'))
    original_present = _has_value(row.get('original_sku_price'))
    if savings_present and not original_present:
        errors.add('savings_requires_original')
        return errors

    savings_valid = False
    savings_amount = None
    savings_rate = None
    if savings_present:
        savings_valid, savings_amount, savings_rate = parse_tse_savings(row.get('savings'))
        if not savings_valid:
            errors.add('savings_format')

    final_price = parse_tse_money(row.get('final_sku_price'))
    original_price = parse_tse_money(row.get('original_sku_price'))
    if original_present and original_price == 0:
        errors.add('original_price_zero')
        return errors

    if final_price is None or original_price is None:
        return errors
    if final_price > original_price:
        errors.add('final_original_price')
        return errors

    if not savings_present or not savings_valid:
        return errors

    difference = original_price - final_price
    if savings_amount is not None and abs(savings_amount) != difference:
        errors.add('savings_amount_match')
    if savings_rate is not None:
        raw_rate = (difference / original_price) * Decimal('100')
        if retailer_key == TSE_LAZADA_RETAILER:
            # Lazada calculates the displayed percentage before its displayed
            # prices are rounded.  The CSV can therefore differ by less than
            # one percentage point from a calculation using displayed prices.
            if abs(abs(savings_rate) - raw_rate) > Decimal('1'):
                errors.add('savings_rate_match')
        else:
            calculated_rate = raw_rate.to_integral_value(
                rounding=ROUND_FLOOR
            )
            if abs(savings_rate) != calculated_rate:
                errors.add('savings_rate_match')

    return errors


def _rows_as_dicts(cursor):
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _resolve_rule_key(rule):
    candidates = (rule.get('validation_type'), rule.get('detail_code'))
    for candidate in candidates:
        key = str(candidate or '').strip().lower()
        for prefix in ('tse_tv_', 'tse_ref_', 'tse_ldy_', 'tse_'):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        key = _RULE_ALIASES.get(key, key)
        if key in TSE_RULE_SPECS:
            return key
    return None


def load_active_tse_rules(cursor, product_line):
    """Load active metadata for one canonical TSE source.

    Stored ``query`` text is returned for display only and is never executed.
    """
    key = normalize_tse_product_line(product_line)
    source = get_tse_source(key)
    cursor.execute("""
        SELECT id, detail_code, detail_name, section_code, section_name,
               table_name, date_column, product_line, retailer,
               field1, field2, validation_type,
               error_message, select_fields, query, sort_order
        FROM monitoring_validation_rules
        WHERE rule_type = 'crossfield'
          AND is_active = TRUE
          AND section_code = %s
          AND table_name = %s
        ORDER BY sort_order, id
    """, (source['section_code'], source['table_name']))
    columns = (
        'rule_id', 'detail_code', 'detail_name', 'section_code', 'section_name',
        'table_name', 'date_column', 'product_line', 'retailer', 'field1',
        'field2', 'validation_type', 'error_message', 'select_fields', 'query',
        'sort_order',
    )
    rows = cursor.fetchall()
    rules = []
    for raw in rows:
        row = dict(raw) if isinstance(raw, dict) else dict(zip(columns, raw))
        if 'rule_id' not in row and 'id' in row:
            row['rule_id'] = row['id']
        rule_key = _resolve_rule_key(row)
        if not rule_key:
            continue
        spec = TSE_RULE_SPECS[rule_key]
        row.update({
            'rule_key': rule_key,
            'detail_name': row.get('detail_name') or spec['detail_name'],
            'field1': row.get('field1') or spec['field1'],
            'field2': row.get('field2') or spec['field2'],
            'validation_type': rule_key,
            'error_message': row.get('error_message') or spec['error_message'],
            'select_fields': row.get('select_fields') or '|'.join(filter(None, (
                spec['field1'], spec['field2'], 'crawl_datetime',
            ))),
        })
        rules.append(row)
    return rules


def load_latest_tse_rows(cursor, target_date, product_line, from_date=None):
    """Load only the greatest-id batch per date and retailer."""
    source = get_tse_source(product_line)
    table_name = source['table_name']
    start_date = str(from_date or target_date)
    end_date = str(target_date)
    cursor.execute(f"""
        WITH batches AS (
            SELECT
                LEFT(TRIM(crawl_datetime), 10) AS collection_date,
                account_name,
                batch_id,
                MAX(id) AS max_id
            FROM {table_name}
            WHERE LEFT(TRIM(crawl_datetime), 10) BETWEEN %s AND %s
              AND country = %s
              AND NULLIF(TRIM(account_name), '') IS NOT NULL
              AND NULLIF(TRIM(batch_id), '') IS NOT NULL
            GROUP BY LEFT(TRIM(crawl_datetime), 10), account_name, batch_id
        ), ranked_batches AS (
            SELECT collection_date, account_name, batch_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY collection_date, LOWER(TRIM(account_name))
                       ORDER BY max_id DESC
                   ) AS batch_rank
            FROM batches
        )
        SELECT source.*
        FROM {table_name} source
        JOIN ranked_batches latest
          ON latest.collection_date = LEFT(TRIM(source.crawl_datetime), 10)
         AND LOWER(TRIM(latest.account_name)) = LOWER(TRIM(source.account_name))
         AND latest.batch_id = source.batch_id
         AND latest.batch_rank = 1
        WHERE LEFT(TRIM(source.crawl_datetime), 10) BETWEEN %s AND %s
          AND source.country = %s
        ORDER BY LEFT(TRIM(source.crawl_datetime), 10),
                 LOWER(TRIM(source.account_name)), source.id
    """, (start_date, end_date, TSE_COUNTRY, start_date, end_date, TSE_COUNTRY))
    return _rows_as_dicts(cursor)


def _display_sql_literal(value):
    """Return one safely quoted SQL literal for copy-only display SQL."""
    return "'" + str(value).replace("'", "''") + "'"


def build_tse_display_query(
        target_date, product_line, rule, days=1, retailer=None,
        retailers=None, items=None, retailer_item_pairs=None):
    """Build a compact, correction-friendly query for a TSE rule.

    The application never executes this display SQL.  The validation engine
    still uses :func:`load_latest_tse_rows` and Python rule evaluation.
    """
    key = normalize_tse_product_line(product_line)
    source = get_tse_source(key)
    rule_key = rule.get('rule_key') or _resolve_rule_key(rule)
    spec = TSE_RULE_SPECS.get(rule_key, {})
    day_count = min(30, max(1, int(days)))
    start_date = target_date - timedelta(days=day_count - 1)

    select_columns = [
        'id', 'item', 'sku', 'retailer_sku_name', 'final_sku_price',
    ]
    field_groups = (
        spec.get('field1'), spec.get('field2'),
        'crawl_datetime', 'product_url',
    )
    for field_group in field_groups:
        for column in str(field_group or '').split('|'):
            column = column.strip()
            if (
                column in _TSE_DISPLAY_QUERY_COLUMNS
                and column not in select_columns
            ):
                select_columns.append(column)
    select_sql = ',\n'.join(f'    {column}' for column in select_columns)

    pair_values = set()
    for pair in retailer_item_pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        pair_retailer = str(pair[0] or '').strip()
        if not pair_retailer:
            continue
        pair_item = (
            None if pair[1] is None or str(pair[1]) == ''
            else str(pair[1])
        )
        pair_values.add((pair_retailer, pair_item))
    pair_values = sorted(
        pair_values, key=lambda pair: (pair[0].lower(), pair[1] or '')
    )

    retailer_values = []
    if retailer is not None:
        retailer_values = [retailer]
    elif retailers is not None:
        retailer_values = list(retailers)
    else:
        configured_retailer = str(rule.get('retailer') or 'ALL').strip()
        if configured_retailer and configured_retailer.upper() != 'ALL':
            retailer_values = [configured_retailer]
    retailer_values.extend(pair[0] for pair in pair_values)

    retailer_values = sorted({
        str(value).strip() for value in retailer_values
        if value is not None
        and str(value).strip()
        and str(value).strip().upper() != 'ALL'
    })

    scope_filters = []
    if pair_values:
        pair_clauses = []
        for pair_retailer, pair_item in pair_values:
            retailer_literal = _display_sql_literal(pair_retailer)
            item_scope = (
                "(item IS NULL OR TRIM(CAST(item AS TEXT)) = '')"
                if pair_item is None
                else f'item = {_display_sql_literal(pair_item)}'
            )
            pair_clauses.append(
                '(LOWER(TRIM(account_name)) = '
                f'LOWER(TRIM({retailer_literal})) AND {item_scope})'
            )
        scope_filters.append(
            '(\n      ' + '\n   OR '.join(pair_clauses) + '\n  )'
        )
    else:
        if len(retailer_values) == 1:
            retailer_literal = _display_sql_literal(retailer_values[0])
            scope_filters.append(
                'LOWER(TRIM(account_name)) = '
                f'LOWER(TRIM({retailer_literal}))'
            )
        elif retailer_values:
            retailer_literals = ', '.join(
                f'LOWER(TRIM({_display_sql_literal(value)}))'
                for value in retailer_values
            )
            scope_filters.append(
                f'LOWER(TRIM(account_name)) IN ({retailer_literals})'
            )

        item_values = sorted({
            str(item) for item in (items or [])
            if item is not None and str(item) != ''
        })
        if item_values:
            item_literals = ',\n'.join(
                f'      {_display_sql_literal(item)}' for item in item_values
            )
            scope_filters.append(f'item IN (\n{item_literals}\n  )')

    start_literal = _display_sql_literal(start_date)
    end_literal = _display_sql_literal(target_date + timedelta(days=1))
    country_literal = _display_sql_literal(TSE_COUNTRY)
    where_filters = [f'country = {country_literal}', *scope_filters]
    where_filters.extend((
        f'DATE(crawl_datetime::timestamp) >= DATE {start_literal}',
        f'DATE(crawl_datetime::timestamp) <= DATE {end_literal}',
    ))
    where_sql = '\n  AND '.join(where_filters)

    return f"""SELECT
{select_sql}
FROM {source['table_name']}
WHERE {where_sql}
ORDER BY item, crawl_datetime;"""


def _load_normal_corrections(cursor, target_date, table_name, rule_ids=None):
    params = [str(target_date), table_name]
    rule_filter = ''
    if rule_ids:
        placeholders = ', '.join(['%s'] * len(rule_ids))
        rule_filter = f' AND rule_id IN ({placeholders})'
        params.extend(rule_ids)
    cursor.execute(f"""
        SELECT record_id, column_name, memo, reason, created_id, created_at,
               rule_id
        FROM monitoring_corrections
        WHERE layer = 3
          AND correction_type = 'cross_field'
          AND crawl_date = %s
          AND status = 'normal'
          AND table_name = %s
          {rule_filter}
    """, params)
    columns = (
        'record_id', 'column_name', 'memo', 'reason', 'created_id',
        'created_at', 'rule_id',
    )
    corrections = []
    for raw in cursor.fetchall():
        corrections.append(
            dict(raw) if isinstance(raw, dict) else dict(zip(columns, raw))
        )
    return corrections


def _rule_applies_to_retailer(rule, retailer):
    configured = str(rule.get('retailer') or 'ALL').strip()
    return configured.upper() == 'ALL' or configured.lower() == str(retailer).strip().lower()


def _retailer_key(value):
    return str(value or '').strip().casefold()


def _lotuss_monitoring_active(product_line):
    """Return whether Lotuss has active column configuration for a source."""
    for display_name, config in get_tse_retailer_columns(product_line).items():
        retailer = config.get('retailer') or display_name
        if _retailer_key(retailer) == TSE_LOTUSS_RETAILER:
            return True
    return False


def build_tse_crossfield_result(cursor, target_date, product_line, from_date=None):
    """Return summary and detail material for one TSE product line."""
    key = normalize_tse_product_line(product_line)
    source = get_tse_source(key)
    rules = load_active_tse_rules(cursor, key)
    rows = load_latest_tse_rows(cursor, target_date, key, from_date=from_date)
    if not _lotuss_monitoring_active(key):
        rules = [
            rule for rule in rules
            if _retailer_key(rule.get('retailer')) != TSE_LOTUSS_RETAILER
        ]
        rows = [
            row for row in rows
            if _retailer_key(row.get('account_name')) != TSE_LOTUSS_RETAILER
        ]
    rule_ids = [rule['rule_id'] for rule in rules]
    corrections = _load_normal_corrections(
        cursor, target_date, source['table_name'], rule_ids,
    ) if rules else []
    normal_pairs = {
        (str(correction['record_id']), str(correction['rule_id']))
        for correction in corrections
    }

    evaluations = {
        str(row.get('id')): evaluate_tse_row(row)
        for row in rows
    }
    retailer_rows = {}
    for row in rows:
        retailer = display_tse_retailer(row.get('account_name')) or 'Unknown'
        retailer_rows.setdefault(retailer, []).append(row)

    rule_results = []
    finding_count = 0
    failed_record_ids = set()
    for rule in rules:
        error_details = []
        for row in rows:
            retailer = display_tse_retailer(row.get('account_name')) or 'Unknown'
            row_id = str(row.get('id'))
            if not _rule_applies_to_retailer(rule, retailer):
                continue
            if not tse_crossfield_rule_supported(
                    key, retailer, rule['rule_key']):
                continue
            if rule['rule_key'] not in evaluations[row_id]:
                continue
            if (row_id, str(rule['rule_id'])) in normal_pairs:
                continue
            detail = dict(row)
            detail['account_name'] = retailer
            detail['validation_tag'] = rule['error_message']
            detail['rule_key'] = rule['rule_key']
            error_details.append(detail)
            failed_record_ids.add(row_id)

        result = dict(rule)
        result['error_details'] = error_details
        result['error_count'] = len(error_details)
        rule_results.append(result)
        finding_count += len(error_details)

    retailer_summaries = []
    for retailer, source_rows in sorted(retailer_rows.items()):
        rules_summary = []
        retailer_error_count = 0
        retailer_failed_records = set()
        for result in rule_results:
            if not tse_crossfield_rule_supported(
                    key, retailer, result['rule_key']):
                continue
            count = sum(
                1 for detail in result['error_details']
                if display_tse_retailer(detail.get('account_name')) == retailer
            )
            retailer_error_count += count
            retailer_failed_records.update(
                str(detail.get('id')) for detail in result['error_details']
                if display_tse_retailer(detail.get('account_name')) == retailer
            )
            rules_summary.append({
                'rule_id': result['rule_id'],
                'detail_code': result['detail_code'],
                'detail_name': result['detail_name'],
                'error_count': count,
            })
        batch_ids = sorted({str(row.get('batch_id') or '') for row in source_rows})
        retailer_summaries.append({
            'retailer': retailer,
            'batch_id': batch_ids[-1] if batch_ids else '',
            'total_checked': len(source_rows),
            'failed_records': len(retailer_failed_records),
            'total_errors': retailer_error_count,
            'rules': rules_summary,
        })

    return {
        'date': str(target_date),
        'configured': bool(rules),
        'product_line': key,
        'label': source['display_name'],
        'table_name': source['table_name'],
        'date_col': 'crawl_datetime',
        'total_checked': len(rows),
        'failed_records': len(failed_record_ids),
        'total_anomalies': finding_count,
        'rule_results': rule_results,
        'retailers': retailer_summaries,
        'normal_corrections': corrections,
    }


def get_tse_cross_field_summary(cursor, target_date, product_line):
    result = build_tse_crossfield_result(cursor, target_date, product_line)
    rule_summary = []
    available_retailers = [
        summary['retailer'] for summary in result['retailers']
        if summary.get('retailer')
    ]
    for rule in result['rule_results']:
        error_rows = rule.get('error_details') or []
        supported_retailers = [
            retailer for retailer in available_retailers
            if tse_crossfield_rule_supported(
                result['product_line'], retailer, rule['rule_key'],
            )
        ]
        scoped_pairs = [
            (
                str(row.get('account_name')).strip(),
                None if row.get('item') is None or str(row.get('item')) == ''
                else str(row.get('item')),
            )
            for row in error_rows
            if str(row.get('account_name') or '').strip()
        ]
        scoped_retailers = sorted({
            str(row.get('account_name')).strip()
            for row in error_rows if str(row.get('account_name') or '').strip()
        })
        if not scoped_retailers:
            configured_retailer = str(rule.get('retailer') or 'ALL').strip()
            if configured_retailer and configured_retailer.upper() != 'ALL':
                if tse_crossfield_rule_supported(
                    result['product_line'], configured_retailer,
                    rule['rule_key'],
                ):
                    scoped_retailers = [configured_retailer]
            else:
                scoped_retailers = supported_retailers
        if not scoped_pairs and not scoped_retailers:
            continue
        rule_summary.append({
            'rule_id': rule['rule_id'],
            'detail_code': rule['detail_code'],
            'detail_name': rule['detail_name'],
            'field1': rule['field1'],
            'field2': rule.get('field2'),
            'validation_type': rule['rule_key'],
            'error_message': rule['error_message'],
            'error_count': rule['error_count'],
            'query': build_tse_display_query(
                target_date, result['product_line'], rule,
                retailers=[] if scoped_pairs else scoped_retailers,
                retailer_item_pairs=scoped_pairs,
            ),
            'select_fields': rule.get('select_fields') or '',
        })

    return {
        'date': result['date'],
        'configured': result['configured'],
        'product_line': result['product_line'].upper(),
        'label': result['label'],
        'total_checked': result['total_checked'],
        'failed_records': result['failed_records'],
        'total_anomalies': result['total_anomalies'],
        'rule_summary': rule_summary,
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'no_review_texts': '',
        'retailers': result['retailers'],
    }


def get_tse_cross_field_rule_detail(
        cursor, target_date, product_line, rule_id, days=1):
    from_date = target_date - timedelta(days=max(1, int(days)) - 1)
    result = build_tse_crossfield_result(
        cursor, target_date, product_line, from_date=from_date,
    )
    selected = next((
        rule for rule in result['rule_results']
        if str(rule['rule_id']) == str(rule_id)
    ), None)
    if not selected:
        return {'found': False}

    anomalies = selected['error_details']
    retailers = sorted({
        display_tse_retailer(row.get('account_name')) or 'Unknown'
        for row in anomalies
    })
    static_editable = set(get_tse_editable_columns(result['product_line']))
    editable_columns = set()
    retailer_columns = {}
    configured = get_tse_retailer_columns(result['product_line'])
    for retailer in retailers:
        columns = set(get_editable_columns(result['product_line'], retailer))
        columns &= static_editable
        editable_columns.update(columns)
        retailer_config = next((
            config for name, config in configured.items()
            if name.lower() == retailer.lower()
        ), {})
        retailer_columns[retailer] = sorted(set(
            retailer_config.get('required_columns', [])
            + retailer_config.get('editable_columns', [])
        ) & static_editable)

    corrections = [
        correction for correction in result['normal_corrections']
        if str(correction['rule_id']) == str(rule_id)
    ]
    normal_reviews = {}
    normal_record_ids = set()
    for correction in corrections:
        record_id = str(correction['record_id'])
        normal_record_ids.add(record_id)
        payload = {
            'memo': correction.get('memo') or '',
            'reason': correction.get('reason') or '',
            'created_id': correction.get('created_id') or '',
            'created_at': str(correction.get('created_at') or ''),
        }
        normal_reviews[f"{record_id}_{correction['column_name']}"] = payload
        # Existing Layer 3 UI removes a row when any editable key is normal.
        # Mirror the same normal marker across allowed keys for this response.
        for column in editable_columns:
            normal_reviews.setdefault(f'{record_id}_{column}', payload)

    retailer_summary = {}
    for row in anomalies:
        retailer = display_tse_retailer(row.get('account_name')) or 'Unknown'
        summary = retailer_summary.setdefault(retailer, {'count': 0, 'items': []})
        if str(row.get('id')) not in normal_record_ids:
            summary['count'] += 1
        item = str(row.get('item') or '')
        if item and item not in summary['items']:
            summary['items'].append(item)

    retailer_pairs = {retailer: [] for retailer in retailer_summary}
    for row in anomalies:
        retailer = display_tse_retailer(row.get('account_name')) or 'Unknown'
        retailer_pairs.setdefault(retailer, []).append((
            retailer,
            None if row.get('item') is None or str(row.get('item')) == ''
            else str(row.get('item')),
        ))
    display_queries = {
        retailer: build_tse_display_query(
            target_date, result['product_line'], selected, days=days,
            retailer=retailer,
            retailer_item_pairs=retailer_pairs.get(retailer, []),
        )
        for retailer in retailer_summary
    }

    return {
        'found': True,
        'date': str(target_date),
        'days': days,
        'product_line': result['product_line'].upper(),
        'rule_id': selected['rule_id'],
        'detail_code': selected['detail_code'],
        'field1': selected['field1'],
        'field2': selected.get('field2'),
        'validation_type': selected['rule_key'],
        'error_message': selected['error_message'],
        'total_anomalies': sum(item['count'] for item in retailer_summary.values()),
        'retailer_summary': retailer_summary,
        'anomalies': anomalies,
        'select_fields': selected.get('select_fields') or '',
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'editable_columns': sorted(editable_columns),
        'normal_reviews': normal_reviews,
        'retailer_columns': retailer_columns,
        'query': build_tse_display_query(
            target_date, result['product_line'], selected, days=days,
        ),
        'queries': display_queries,
    }
