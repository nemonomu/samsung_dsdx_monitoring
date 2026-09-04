"""SIEL TV/REF/LDY cross-field validation.

Rule metadata is enabled through ``monitoring_validation_rules``.  Stored SQL
is never executed: the application applies an allow-listed Python rule set to
the exact SIEL inspection-day/latest-MAIN-batch scope.
"""

from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.retail_validation import get_tv_validation_condition
from apps.common.siel_retail import (
    SIEL_BUSINESS_TIMEZONE,
    SIEL_RETAILERS,
    display_siel_retailer,
    get_siel_crossfield_editable_columns,
    get_siel_source,
    normalize_siel_product_line,
)


SIEL_NO_REVIEW_TEXT = 'No customer reviews'

SIEL_RULE_SPECS = OrderedDict((
    ('rating_count_presence', {
        'detail_name': '별점과 별점 수 존재 일치',
        'field1': 'star_rating',
        'field2': 'count_of_star_ratings',
        'retailers': ('Amazon', 'Flipkart'),
        'display_fields': (
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
        ),
        'error_message': (
            'star_rating의 0 여부와 count_of_star_ratings의 '
            'NULL·빈값·0 여부가 일치하지 않습니다.'
        ),
    }),
    ('no_review_rating_count', {
        'detail_name': '리뷰 없음 문구와 별점 수 일치',
        'field1': 'star_rating',
        'field2': 'count_of_star_ratings',
        'retailers': ('Amazon',),
        'display_fields': ('star_rating', 'count_of_star_ratings'),
        'error_message': (
            'star_rating이 No customer reviews인데 '
            'count_of_star_ratings가 1 이상입니다.'
        ),
    }),
    ('rating_range', {
        'detail_name': '별점 숫자 형식 및 5점 이하',
        'field1': 'star_rating',
        'field2': None,
        'retailers': ('Amazon', 'Flipkart'),
        'display_fields': ('star_rating', 'count_of_star_ratings'),
        'error_message': (
            'star_rating이 숫자가 아니거나 허용 범위 0~5를 벗어났습니다.'
        ),
    }),
    ('rank_page_type', {
        'detail_name': '페이지 유형과 순위 필드 일치',
        'field1': 'page_type',
        'field2': 'main_rank|bsr_rank',
        'retailers': ('Amazon',),
        'display_fields': ('page_type', 'main_rank', 'bsr_rank'),
        'error_message': (
            'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.'
        ),
    }),
    ('final_original_price', {
        'detail_name': '최종가와 원가 순서',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': ('Amazon', 'Flipkart'),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            'final_sku_price가 original_sku_price보다 큽니다.'
        ),
    }),
    ('discount_rate_90', {
        'detail_name': '90% 이상 할인 검증',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': ('Amazon',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '최종가와 원가로 계산한 할인율이 90% 이상입니다.'
        ),
    }),
    ('review_body_missing', {
        'detail_name': '리뷰 수 존재 시 리뷰본문 확인',
        'field1': 'count_of_reviews',
        'field2': 'detailed_review_content',
        'retailers': ('Flipkart',),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings',
            'detailed_review_content',
        ),
        'error_message': (
            'count_of_reviews가 1 이상인데 '
            'detailed_review_content가 NULL 또는 빈값입니다.'
        ),
    }),
    ('review_count_missing', {
        'detail_name': '리뷰본문 존재 시 리뷰 수 확인',
        'field1': 'detailed_review_content',
        'field2': 'count_of_reviews',
        'retailers': ('Flipkart',),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings',
            'detailed_review_content',
        ),
        'error_message': (
            'detailed_review_content가 있는데 '
            'count_of_reviews가 NULL·빈값 또는 0입니다.'
        ),
    }),
    ('review_star_count_missing', {
        'detail_name': '리뷰 수 존재 시 별점 수 확인',
        'field1': 'count_of_reviews',
        'field2': 'count_of_star_ratings',
        'retailers': ('Flipkart',),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings', 'star_rating',
        ),
        'error_message': (
            'count_of_reviews가 1 이상인데 '
            'count_of_star_ratings가 NULL·빈값 또는 0입니다.'
        ),
    }),
    ('review_gt_star_count', {
        'detail_name': '리뷰 수가 별점 수 이하',
        'field1': 'count_of_reviews',
        'field2': 'count_of_star_ratings',
        'retailers': ('Flipkart',),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings', 'star_rating',
        ),
        'error_message': (
            'count_of_reviews가 count_of_star_ratings보다 큽니다.'
        ),
    }),
    ('savings_missing', {
        'detail_name': '최종가·원가 존재 시 할인율 확인',
        'field1': 'savings',
        'field2': 'final_sku_price|original_sku_price',
        'retailers': ('Flipkart',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '최종가와 원가가 있는데 savings가 NULL 또는 빈값입니다.'
        ),
    }),
    ('original_missing', {
        'detail_name': '최종가·할인율 존재 시 원가 확인',
        'field1': 'original_sku_price',
        'field2': 'final_sku_price|savings',
        'retailers': ('Flipkart',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '최종가와 savings가 있는데 original_sku_price가 '
            'NULL 또는 빈값입니다.'
        ),
    }),
    ('savings_rate_match', {
        'detail_name': '표시 할인율과 가격 차이 일치',
        'field1': 'savings',
        'field2': 'original_sku_price|final_sku_price',
        'retailers': ('Flipkart',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            'savings와 (원가-최종가)/원가의 차이가 1%p를 초과합니다.'
        ),
    }),
))

_RULE_ALIASES = {
    'rating_count_required': 'rating_count_presence',
    'review_zero_pair': 'rating_count_presence',
    'no_review_count': 'no_review_rating_count',
    'star_rating_range': 'rating_range',
    'page_type_rank': 'rank_page_type',
    'price_order': 'final_original_price',
    'discount_rate': 'discount_rate_90',
    'review_without_body': 'review_body_missing',
    'body_without_review_count': 'review_count_missing',
    'review_without_star_count': 'review_star_count_missing',
    'review_count_over_star_count': 'review_gt_star_count',
    'savings_required': 'savings_missing',
    'original_required': 'original_missing',
    'savings_rate': 'savings_rate_match',
}

_DISPLAY_QUERY_COLUMNS = {
    'id', 'country', 'product', 'account_name', 'page_type', 'item',
    'sku', 'retailer_sku_name', 'main_rank', 'bsr_rank',
    'count_of_reviews', 'count_of_star_ratings', 'star_rating',
    'detailed_review_content', 'final_sku_price', 'original_sku_price',
    'savings', 'crawl_datetime', 'batch_id', 'product_url',
}


def _has_value(value):
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '-', 'none', 'null', 'n/a')


def parse_siel_number(value):
    if not _has_value(value):
        return None
    text = str(value).strip().replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_siel_money(value):
    if not _has_value(value):
        return None
    text = str(value).strip()
    text = re.sub(r'(?i)\bINR\b', '', text)
    text = text.replace('₹', '').replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_siel_savings_rate(value):
    if not _has_value(value):
        return None
    match = re.fullmatch(
        r'([+-]?\d+(?:\.\d+)?)\s*%', str(value).strip()
    )
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def evaluate_siel_row(row):
    """Return canonical SIEL rule keys failed by one source row."""
    errors = set()
    retailer = display_siel_retailer(row.get('account_name'))
    if retailer not in SIEL_RETAILERS:
        return errors

    rating_text = str(row.get('star_rating') or '').strip()
    rating = parse_siel_number(row.get('star_rating'))
    star_count = parse_siel_number(row.get('count_of_star_ratings'))
    review_count = parse_siel_number(row.get('count_of_reviews'))

    allowed_no_review = (
        retailer == 'Amazon'
        and rating_text.casefold() == SIEL_NO_REVIEW_TEXT.casefold()
    )
    if rating is not None:
        if star_count is None:
            if rating > 0:
                errors.add('rating_count_presence')
        elif (rating == 0) != (star_count == 0):
            errors.add('rating_count_presence')
        if rating < 0 or rating > 5:
            errors.add('rating_range')
    elif _has_value(row.get('star_rating')) and not allowed_no_review:
        errors.add('rating_range')

    if (
        retailer == 'Amazon'
        and allowed_no_review
        and star_count is not None
        and star_count > 0
    ):
        errors.add('no_review_rating_count')

    if retailer == 'Amazon':
        page_type = str(row.get('page_type') or '').strip().lower()
        if page_type == 'main' and not _has_value(row.get('main_rank')):
            errors.add('rank_page_type')
        if page_type == 'bsr' and not _has_value(row.get('bsr_rank')):
            errors.add('rank_page_type')

    final_present = _has_value(row.get('final_sku_price'))
    original_present = _has_value(row.get('original_sku_price'))
    savings_present = _has_value(row.get('savings'))
    final_price = parse_siel_money(row.get('final_sku_price'))
    original_price = parse_siel_money(row.get('original_sku_price'))

    if final_price is not None and original_price is not None:
        if final_price > original_price:
            errors.add('final_original_price')
        if (
            retailer == 'Amazon'
            and final_price > 0
            and original_price > 0
            and ((original_price - final_price) / original_price) * 100 >= 90
        ):
            errors.add('discount_rate_90')

    if retailer == 'Flipkart':
        body_present = _has_value(row.get('detailed_review_content'))
        if review_count is not None and review_count > 0 and not body_present:
            errors.add('review_body_missing')
        if body_present and (review_count is None or review_count == 0):
            errors.add('review_count_missing')
        if (
            review_count is not None
            and review_count > 0
            and (star_count is None or star_count == 0)
        ):
            errors.add('review_star_count_missing')
        if (
            review_count is not None
            and star_count is not None
            and review_count > star_count
        ):
            errors.add('review_gt_star_count')

        if final_present and original_present and not savings_present:
            errors.add('savings_missing')
        if final_present and savings_present and not original_present:
            errors.add('original_missing')

        if (
            final_present
            and original_present
            and savings_present
            and final_price is not None
            and original_price is not None
            and original_price > 0
            and final_price <= original_price
        ):
            savings_rate = parse_siel_savings_rate(row.get('savings'))
            calculated_rate = (
                (original_price - final_price) / original_price
            ) * Decimal('100')
            if (
                savings_rate is None
                or abs(savings_rate - calculated_rate) > Decimal('1')
            ):
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
    for candidate in (rule.get('validation_type'), rule.get('detail_code')):
        key = str(candidate or '').strip().lower()
        for prefix in ('siel_tv_', 'siel_ref_', 'siel_ldy_', 'siel_'):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        key = _RULE_ALIASES.get(key, key)
        if key in SIEL_RULE_SPECS:
            return key
    return None


def _retailer_supported(rule_key, retailer):
    supported = SIEL_RULE_SPECS[rule_key]['retailers']
    retailer_key = str(retailer or '').strip().casefold()
    return retailer_key in {value.casefold() for value in supported}


def _rule_applies_to_retailer(rule, retailer):
    if not _retailer_supported(rule['rule_key'], retailer):
        return False
    if rule.get('_all_retailers'):
        return True
    retailer_key = str(retailer or '').strip().casefold()
    return retailer_key in {
        str(value or '').strip().casefold()
        for value in rule.get('_retailers', [])
    }


def load_active_siel_rules(cursor, product_line):
    """Load active SIEL metadata; stored query text is never executed."""
    key = normalize_siel_product_line(product_line)
    source = get_siel_source(key)
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
        'rule_id', 'detail_code', 'detail_name', 'section_code',
        'section_name', 'table_name', 'date_column', 'product_line',
        'retailer', 'field1', 'field2', 'validation_type', 'error_message',
        'select_fields', 'query', 'sort_order',
    )
    rules_by_key = OrderedDict()
    for raw in cursor.fetchall():
        row = dict(raw) if isinstance(raw, dict) else dict(zip(columns, raw))
        if 'rule_id' not in row and 'id' in row:
            row['rule_id'] = row['id']
        rule_key = _resolve_rule_key(row)
        if not rule_key:
            continue

        spec = SIEL_RULE_SPECS[rule_key]
        configured_retailer = str(row.get('retailer') or 'ALL').strip()
        if (
            configured_retailer.upper() != 'ALL'
            and not _retailer_supported(rule_key, configured_retailer)
        ):
            continue

        configured_fields = [
            field.strip()
            for field in str(row.get('select_fields') or '').split('|')
            if field.strip()
        ]
        display_fields = []
        for field_group in configured_fields + list(spec['display_fields']):
            for field in str(field_group or '').split('|'):
                field = field.strip()
                if field and field not in display_fields:
                    display_fields.append(field)

        row.update({
            'rule_key': rule_key,
            'detail_name': row.get('detail_name') or spec['detail_name'],
            'field1': row.get('field1') or spec['field1'],
            'field2': row.get('field2') or spec['field2'],
            'validation_type': rule_key,
            'error_message': row.get('error_message') or spec['error_message'],
            'select_fields': '|'.join(display_fields),
            '_source_rule_ids': [row['rule_id']],
            '_all_retailers': configured_retailer.upper() == 'ALL',
            '_retailers': (
                [] if configured_retailer.upper() == 'ALL'
                else [configured_retailer]
            ),
        })
        existing = rules_by_key.get(rule_key)
        if existing is None:
            rules_by_key[rule_key] = row
            continue

        if row['rule_id'] not in existing['_source_rule_ids']:
            existing['_source_rule_ids'].append(row['rule_id'])
        existing['_all_retailers'] = (
            existing['_all_retailers'] or row['_all_retailers']
        )
        for retailer in row['_retailers']:
            if retailer.casefold() not in {
                value.casefold() for value in existing['_retailers']
            }:
                existing['_retailers'].append(retailer)
        merged_fields = existing['select_fields'].split('|')
        for field in display_fields:
            if field not in merged_fields:
                merged_fields.append(field)
        existing['select_fields'] = '|'.join(filter(None, merged_fields))

    return list(rules_by_key.values())


def _date_contract(inspection_date, source):
    contract = resolve_monitoring_date(
        inspection_date, 'SIEL', source['source_key']
    )
    contract['source_date_value'] = date.fromisoformat(contract['source_date'])
    return contract


def _date_range_sql(alias, date_column):
    return f"""{alias}.{date_column} >= (
                 %s::date::timestamp AT TIME ZONE '{SIEL_BUSINESS_TIMEZONE}'
             )
             AND {alias}.{date_column} < (
                 (%s::date + 1)::timestamp AT TIME ZONE
                 '{SIEL_BUSINESS_TIMEZONE}'
             )"""


def load_latest_siel_rows(
        cursor, inspection_date, product_line, from_date=None):
    """Load each KST day's latest retailer MAIN batch and its MAIN+BSR rows."""
    key = normalize_siel_product_line(product_line)
    source = get_siel_source(key)
    end_contract = _date_contract(inspection_date, source)
    start_contract = _date_contract(from_date or inspection_date, source)
    start_date = start_contract['source_date']
    end_date = end_contract['source_date']
    table_name = source['table_name']
    date_column = source['date_column']
    local_date = (
        f"(source.{date_column} AT TIME ZONE "
        f"'{SIEL_BUSINESS_TIMEZONE}')::date"
    )
    anchor_range = _date_range_sql('source', date_column)
    result_range = _date_range_sql('source', date_column)
    cursor.execute(f"""
        WITH main_batches AS (
            SELECT
                {local_date} AS source_date,
                source.account_name,
                source.batch_id,
                MAX(source.id) AS max_id
            FROM {table_name} source
            WHERE {anchor_range}
              AND LOWER(BTRIM(CAST(source.account_name AS TEXT)))
                  IN ('amazon', 'flipkart')
              AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'
              AND {get_tv_validation_condition('source')}
            GROUP BY {local_date}, source.account_name, source.batch_id
        ), ranked_batches AS (
            SELECT source_date, account_name, batch_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_date,
                                    LOWER(BTRIM(CAST(account_name AS TEXT)))
                       ORDER BY max_id DESC
                   ) AS batch_rank
            FROM main_batches
        )
        SELECT source.*
        FROM {table_name} source
        JOIN ranked_batches latest
          ON latest.source_date = {local_date}
         AND LOWER(BTRIM(CAST(latest.account_name AS TEXT))) =
             LOWER(BTRIM(CAST(source.account_name AS TEXT)))
         AND latest.batch_id IS NOT DISTINCT FROM source.batch_id
         AND latest.batch_rank = 1
        WHERE {result_range}
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          AND {get_tv_validation_condition('source')}
        ORDER BY {local_date},
                 LOWER(BTRIM(CAST(source.account_name AS TEXT))), source.id
    """, (start_date, end_date, start_date, end_date))
    return _rows_as_dicts(cursor)


def _load_normal_corrections(
        cursor, inspection_date, table_name, rule_ids=None):
    params = [str(inspection_date), table_name]
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
    return [
        dict(raw) if isinstance(raw, dict) else dict(zip(columns, raw))
        for raw in cursor.fetchall()
    ]


def build_siel_crossfield_result(
        cursor, inspection_date, product_line, from_date=None):
    key = normalize_siel_product_line(product_line)
    source = get_siel_source(key)
    contract = _date_contract(inspection_date, source)
    rules = load_active_siel_rules(cursor, key)
    rows = load_latest_siel_rows(
        cursor, inspection_date, key, from_date=from_date
    )
    rule_ids = [
        rule_id
        for rule in rules
        for rule_id in rule.get('_source_rule_ids', [rule['rule_id']])
    ]
    corrections = _load_normal_corrections(
        cursor, inspection_date, source['table_name'], rule_ids,
    ) if rules else []
    normal_pairs = {
        (str(correction['record_id']), str(correction['rule_id']))
        for correction in corrections
    }

    evaluations = {
        str(row.get('id')): evaluate_siel_row(row)
        for row in rows
    }
    retailer_rows = {}
    for row in rows:
        retailer = display_siel_retailer(row.get('account_name')) or 'Unknown'
        row['account_name'] = retailer
        retailer_rows.setdefault(retailer, []).append(row)

    rule_results = []
    finding_count = 0
    failed_record_ids = set()
    for rule in rules:
        error_details = []
        for row in rows:
            retailer = display_siel_retailer(
                row.get('account_name')
            ) or 'Unknown'
            row_id = str(row.get('id'))
            if not _rule_applies_to_retailer(rule, retailer):
                continue
            if rule['rule_key'] not in evaluations[row_id]:
                continue
            source_rule_ids = {
                str(rule_id)
                for rule_id in rule.get(
                    '_source_rule_ids', [rule['rule_id']]
                )
            }
            if any((row_id, rule_id) in normal_pairs
                   for rule_id in source_rule_ids):
                continue
            detail = dict(row)
            detail['validation_tag'] = rule['error_message']
            detail['rule_key'] = rule['rule_key']
            detail['finding_level'] = 'anomaly'
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
            if not _retailer_supported(result['rule_key'], retailer):
                continue
            details = [
                detail for detail in result['error_details']
                if detail.get('account_name') == retailer
            ]
            retailer_error_count += len(details)
            retailer_failed_records.update(
                str(detail.get('id')) for detail in details
            )
            rules_summary.append({
                'rule_id': result['rule_id'],
                'detail_code': result['detail_code'],
                'detail_name': result['detail_name'],
                'error_count': len(details),
            })
        batch_ids = sorted({
            str(row.get('batch_id') or '') for row in source_rows
        })
        retailer_summaries.append({
            'retailer': retailer,
            'batch_id': batch_ids[-1] if batch_ids else '',
            'total_checked': len(source_rows),
            'failed_records': len(retailer_failed_records),
            'total_errors': retailer_error_count,
            'rules': rules_summary,
        })

    return {
        'date': str(inspection_date),
        'inspection_date': contract['inspection_date'],
        'source_date': contract['source_date'],
        'offset_days': contract['offset_days'],
        'configured': bool(rules),
        'product_line': key,
        'label': source['display_name'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'total_checked': len(rows),
        'failed_records': len(failed_record_ids),
        'total_anomalies': finding_count,
        'passed_records': max(0, len(rows) - len(failed_record_ids)),
        'rule_results': rule_results,
        'retailers': retailer_summaries,
        'normal_corrections': corrections,
    }


def _display_sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_siel_display_query(
        inspection_date, product_line, rule, days=1, retailer=None,
        retailers=None, retailer_item_pairs=None):
    """Build a compact copy-only SIEL item-history query."""
    key = normalize_siel_product_line(product_line)
    source = get_siel_source(key)
    day_count = min(30, max(1, int(days)))
    date_column = source['date_column']

    select_columns = ['id', 'item', 'sku', 'retailer_sku_name']
    spec = SIEL_RULE_SPECS[rule['rule_key']]
    for field_group in (
        *spec['display_fields'], date_column, 'product_url'
    ):
        for column in str(field_group or '').split('|'):
            column = column.strip()
            if column in _DISPLAY_QUERY_COLUMNS and column not in select_columns:
                select_columns.append(column)
    select_sql = ',\n'.join(f'    {column}' for column in select_columns)

    pair_values = sorted({
        (
            str(pair[0]).strip(),
            None if pair[1] is None or str(pair[1]) == '' else str(pair[1]),
        )
        for pair in (retailer_item_pairs or [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
        and str(pair[0] or '').strip()
    }, key=lambda pair: (pair[0].lower(), pair[1] or ''))
    retailer_values = [retailer] if retailer is not None else list(
        retailers or []
    )
    retailer_values.extend(pair[0] for pair in pair_values)
    retailer_values = sorted({
        str(value).strip() for value in retailer_values
        if str(value or '').strip()
    })

    filters = []
    if pair_values:
        pair_groups = OrderedDict()
        for pair_retailer, item in pair_values:
            pair_groups.setdefault(pair_retailer, []).append(item)
        pair_clauses = []
        for pair_retailer, pair_items in pair_groups.items():
            item_values = sorted({
                item for item in pair_items if item is not None
            })
            item_clauses = []
            if item_values:
                literals = ', '.join(
                    _display_sql_literal(item) for item in item_values
                )
                item_clauses.append(f'item IN ({literals})')
            if any(item is None for item in pair_items):
                item_clauses.append(
                    "(item IS NULL OR TRIM(item) = '')"
                )
            item_scope = ' OR '.join(item_clauses)
            retailer_scope = (
                f"TRIM(account_name) ILIKE "
                f"{_display_sql_literal(pair_retailer)}"
            )
            pair_clauses.append(f'({retailer_scope} AND ({item_scope}))')
        if len(pair_clauses) == 1:
            pair_retailer, pair_items = next(iter(pair_groups.items()))
            filters.append(
                f'TRIM(account_name) ILIKE '
                f'{_display_sql_literal(pair_retailer)}'
            )
            item_values = sorted({
                item for item in pair_items if item is not None
            })
            if item_values:
                filters.append('item IN (' + ', '.join(
                    _display_sql_literal(item) for item in item_values
                ) + ')')
            if any(item is None for item in pair_items):
                filters.append("(item IS NULL OR TRIM(item) = '')")
        else:
            filters.append('(\n    ' + '\n OR '.join(pair_clauses) + '\n  )')
    elif retailer_values:
        retailer_clauses = [
            f'TRIM(account_name) ILIKE {_display_sql_literal(value)}'
            for value in retailer_values
        ]
        filters.append('(' + ' OR '.join(retailer_clauses) + ')')

    scope_sql = ''
    if filters:
        scope_sql = '\n  AND ' + '\n  AND '.join(filters)

    start_offset = day_count - 1
    return f"""SELECT
{select_sql}
FROM {source['table_name']}
WHERE {date_column} >= CURRENT_DATE - INTERVAL '{start_offset} days'
  AND {date_column} < CURRENT_DATE + INTERVAL '1 day'{scope_sql}
ORDER BY item, {date_column}, id;"""


def get_siel_cross_field_summary(cursor, inspection_date, product_line):
    result = build_siel_crossfield_result(
        cursor, inspection_date, product_line
    )
    rule_summary = []
    available_retailers = [
        summary['retailer'] for summary in result['retailers']
        if summary.get('retailer')
    ]
    for rule in result['rule_results']:
        error_rows = rule.get('error_details') or []
        pairs = [
            (
                str(row.get('account_name')).strip(),
                None if row.get('item') is None or str(row.get('item')) == ''
                else str(row.get('item')),
            )
            for row in error_rows
            if str(row.get('account_name') or '').strip()
        ]
        scoped_retailers = sorted({pair[0] for pair in pairs})
        if not scoped_retailers:
            scoped_retailers = [
                retailer for retailer in available_retailers
                if _rule_applies_to_retailer(rule, retailer)
            ]
        if not pairs and not scoped_retailers:
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
            'query': build_siel_display_query(
                inspection_date, result['product_line'], rule,
                days=3,
                retailers=[] if pairs else scoped_retailers,
                retailer_item_pairs=pairs,
            ),
            'select_fields': rule.get('select_fields') or '',
        })

    return {
        'date': result['date'],
        'inspection_date': result['inspection_date'],
        'source_date': result['source_date'],
        'offset_days': result['offset_days'],
        'configured': result['configured'],
        'product_line': result['product_line'].upper(),
        'label': result['label'],
        'total_checked': result['total_checked'],
        'failed_records': result['failed_records'],
        'total_anomalies': result['total_anomalies'],
        'passed_records': result['passed_records'],
        'rule_summary': rule_summary,
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'no_review_texts': SIEL_NO_REVIEW_TEXT,
        'retailers': result['retailers'],
    }


def _detail_row_source_date(row, date_column):
    value = row.get(date_column)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(SIEL_BUSINESS_TIMEZONE))
        return value.date().isoformat()
    return str(value or '').strip()[:10]


def _detail_row_item_key(row):
    retailer = str(row.get('account_name') or '').strip().casefold()
    item = str(row.get('item') or '').strip()
    if not retailer or not item:
        return None
    return retailer, item


def _detail_row_sort_key(row, date_column):
    retailer = str(row.get('account_name') or '').strip().casefold()
    item = str(row.get('item') or '').strip().casefold()
    source_date = _detail_row_source_date(row, date_column)
    row_id = str(row.get('id') or '')
    return retailer, item, source_date, row_id.zfill(20)


def get_siel_cross_field_rule_detail(
        cursor, inspection_date, product_line, rule_id, days=1):
    day_count = min(30, max(1, int(days)))
    from_date = inspection_date - timedelta(days=day_count - 1)
    result = build_siel_crossfield_result(
        cursor, inspection_date, product_line, from_date=from_date,
    )
    selected = next((
        rule for rule in result['rule_results']
        if str(rule['rule_id']) == str(rule_id)
    ), None)
    if not selected:
        return {'found': False}

    target_source_date = result['source_date']
    target_findings = [
        row for row in selected['error_details']
        if _detail_row_source_date(row, result['date_col'])
        == target_source_date
    ]
    target_item_keys = {
        item_key for item_key in (
            _detail_row_item_key(row) for row in target_findings
        ) if item_key is not None
    }
    anomalies = []
    for row in selected['error_details']:
        row_source_date = _detail_row_source_date(row, result['date_col'])
        detail = dict(row)
        # PostgreSQL timestamptz는 JSON에서 UTC로 직렬화될 수 있으므로,
        # 화면에는 KST로 확정한 데이터일을 별도로 전달한다.
        detail['row_source_date'] = row_source_date
        if row_source_date == target_source_date:
            detail['row_role'] = 'target'
        elif _detail_row_item_key(row) in target_item_keys:
            detail['row_role'] = 'comparison_history'
        else:
            detail['row_role'] = 'past_finding'
        anomalies.append(detail)
    anomalies.sort(key=lambda row: _detail_row_sort_key(
        row, result['date_col'],
    ))

    retailers = sorted({
        display_siel_retailer(row.get('account_name')) or 'Unknown'
        for row in anomalies
    })
    editable_columns = set()
    retailer_columns = {}
    for retailer in retailers:
        columns = set(get_siel_crossfield_editable_columns(
            result['product_line'], retailer,
        ))
        editable_columns.update(columns)
        retailer_columns[retailer] = sorted(columns)

    selected_rule_ids = {
        str(source_rule_id)
        for source_rule_id in selected.get(
            '_source_rule_ids', [selected['rule_id']]
        )
    }
    corrections = [
        correction for correction in result['normal_corrections']
        if str(correction['rule_id']) in selected_rule_ids
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
        normal_reviews[
            f"{record_id}_{correction['column_name']}"
        ] = payload
        for column in editable_columns:
            normal_reviews.setdefault(f'{record_id}_{column}', payload)

    retailer_summary = {}
    for row in anomalies:
        retailer = display_siel_retailer(
            row.get('account_name')
        ) or 'Unknown'
        summary = retailer_summary.setdefault(
            retailer, {'count': 0, 'items': []}
        )
        item = str(row.get('item') or '')
        if item and item not in summary['items']:
            summary['items'].append(item)
        if (
            row.get('row_role') == 'target'
            and str(row.get('id')) not in normal_record_ids
        ):
            summary['count'] += 1

    retailer_pairs = {retailer: [] for retailer in retailer_summary}
    for row in anomalies:
        retailer = display_siel_retailer(
            row.get('account_name')
        ) or 'Unknown'
        retailer_pairs.setdefault(retailer, []).append((
            retailer,
            None if row.get('item') is None or str(row.get('item')) == ''
            else str(row.get('item')),
        ))
    display_queries = {
        retailer: build_siel_display_query(
            inspection_date, result['product_line'], selected,
            days=day_count, retailer=retailer,
            retailer_item_pairs=retailer_pairs.get(retailer, []),
        )
        for retailer in retailer_summary
    }

    return {
        'found': True,
        'date': result['date'],
        'inspection_date': result['inspection_date'],
        'source_date': result['source_date'],
        'offset_days': result['offset_days'],
        'days': day_count,
        'product_line': result['product_line'].upper(),
        'rule_id': selected['rule_id'],
        'detail_code': selected['detail_code'],
        'field1': selected['field1'],
        'field2': selected.get('field2'),
        'validation_type': selected['rule_key'],
        'error_message': selected['error_message'],
        'total_anomalies': sum(
            item['count'] for item in retailer_summary.values()
        ),
        'retailer_summary': retailer_summary,
        'anomalies': anomalies,
        'select_fields': selected.get('select_fields') or '',
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'editable_columns': sorted(editable_columns),
        'normal_reviews': normal_reviews,
        'retailer_columns': retailer_columns,
        'query': build_siel_display_query(
            inspection_date, result['product_line'], selected,
            days=day_count,
        ),
        'queries': display_queries,
    }
