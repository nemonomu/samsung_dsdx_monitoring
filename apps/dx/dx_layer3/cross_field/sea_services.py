"""SEA REF/LDY cross-field validation.

Database rows in ``monitoring_validation_rules`` enable and describe rules.
Validation itself stays allow-listed here so a stored query cannot widen the
exact D-1/latest-MAIN-batch scope used by the SEA monitoring contract.
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.retail_columns import get_editable_columns
from apps.common.sea_retail import get_sea_retail_source


SEA_PRODUCT_KEYS = {
    'sea_ref': 'ref',
    'sea_ldy': 'ldy',
}

SEA_RULE_SPECS = OrderedDict((
    ('review_count_match', {
        'detail_name': '리뷰 수와 별점 수 일치',
        'field1': 'count_of_reviews',
        'field2': 'count_of_star_ratings',
        'retailers': ('Bestbuy', 'Lowes'),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings',
            'detailed_review_content',
        ),
        'error_message': 'count_of_reviews와 count_of_star_ratings가 다릅니다.',
    }),
    ('rating_count_presence', {
        'detail_name': '별점 0과 별점 수 0 일치',
        'field1': 'star_rating',
        'field2': 'count_of_star_ratings',
        'retailers': ('Bestbuy', 'Lowes'),
        'display_fields': (
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
        ),
        'error_message': 'star_rating의 0 여부와 count_of_star_ratings의 0 여부가 다릅니다.',
    }),
    ('rank_page_type', {
        'detail_name': '페이지 유형과 순위 필드 일치',
        'field1': 'page_type',
        'field2': 'main_rank|bsr_rank',
        'retailers': ('Bestbuy',),
        'display_fields': ('page_type', 'main_rank', 'bsr_rank'),
        'error_message': 'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.',
    }),
    ('final_original_price', {
        'detail_name': '최종가와 원가 순서',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': ('Bestbuy', 'Lowes'),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '최종가와 원가의 가격 관계가 올바르지 않습니다.',
    }),
    ('discount_rate_90', {
        'detail_name': '90% 이상 할인 검사',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': ('Bestbuy',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '최종가와 원가로 계산한 할인율이 90% 이상입니다.',
    }),
    ('review_body_count', {
        'detail_name': '리뷰 수와 리뷰 본문 개수 일치',
        'field1': 'count_of_reviews',
        'field2': 'detailed_review_content',
        'retailers': ('Bestbuy', 'Lowes'),
        'display_fields': (
            'count_of_reviews', 'count_of_star_ratings',
            'detailed_review_content',
        ),
        'error_message': '리뷰 수와 detailed_review_content의 reviewN 범위가 맞지 않습니다.',
    }),
    ('savings_missing', {
        'detail_name': '최종가·원가 존재 시 savings 확인',
        'field1': 'savings',
        'field2': 'final_sku_price|original_sku_price',
        'retailers': ('Lowes',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '최종가와 원가가 있는데 savings가 없습니다.',
    }),
    ('original_missing', {
        'detail_name': '최종가·savings 존재 시 원가 확인',
        'field1': 'original_sku_price',
        'field2': 'final_sku_price|savings',
        'retailers': ('Lowes',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '최종가와 savings가 있는데 original_sku_price가 없습니다.',
    }),
    ('savings_amount_match', {
        'detail_name': '할인 금액 일치',
        'field1': 'savings',
        'field2': 'original_sku_price|final_sku_price',
        'retailers': ('Lowes',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': 'original_sku_price-final_sku_price와 savings가 다릅니다.',
    }),
    ('final_missing', {
        'detail_name': '원가·savings 존재 시 최종가 확인',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price|savings',
        'retailers': ('Lowes',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '원가 또는 savings가 있는데 final_sku_price가 없습니다.',
    }),
    ('recommendation_intent', {
        'detail_name': '추천 의향 형식',
        'field1': 'recommendation_intent',
        'field2': 'count_of_reviews',
        'retailers': ('Bestbuy', 'Lowes'),
        'display_fields': (
            'count_of_reviews', 'recommendation_intent',
            'detailed_review_content',
        ),
        'error_message': '리테일러별 recommendation_intent 문구 또는 0~100% 범위가 올바르지 않습니다.',
    }),
))

_RULE_ALIASES = {
    'review_count_mismatch': 'review_count_match',
    'review_rating_count_match': 'review_count_match',
    'rating_count_required': 'rating_count_presence',
    'page_type_rank': 'rank_page_type',
    'price_order': 'final_original_price',
    'price_reverse': 'final_original_price',
    'discount_rate': 'discount_rate_90',
    'review_detail_match': 'review_body_count',
    'review_body_over_count': 'review_body_count',
    'savings_required': 'savings_missing',
    'original_required': 'original_missing',
    'savings_amount': 'savings_amount_match',
    'final_required': 'final_missing',
    'recommendation_format': 'recommendation_intent',
}

_DISPLAY_QUERY_COLUMNS = {
    'id', 'country', 'product', 'account_name', 'page_type', 'item',
    'sku', 'retailer_sku_name', 'main_rank', 'bsr_rank',
    'count_of_reviews', 'count_of_star_ratings', 'star_rating',
    'detailed_review_content', 'recommendation_intent',
    'final_sku_price', 'original_sku_price', 'savings',
    'crawl_strdatetime', 'batch_id', 'product_url',
}


def normalize_sea_product_line(value):
    key = str(value or '').strip().lower()
    if key not in SEA_PRODUCT_KEYS:
        raise ValueError(f'허용되지 않은 SEA 크로스필드 제품군: {value}')
    return key


def _source_for_product_line(product_line):
    key = normalize_sea_product_line(product_line)
    return get_sea_retail_source(SEA_PRODUCT_KEYS[key])


def _has_value(value):
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '-', 'none', 'null', 'n/a')


def parse_sea_number(value):
    if not _has_value(value):
        return None
    text = str(value).strip().replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_sea_money(value):
    if not _has_value(value):
        return None
    text = str(value).strip().replace('$', '').replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _review_body_max(value):
    if not _has_value(value):
        return 0
    numbers = [
        int(number)
        for number in re.findall(r'(?i)\breview\s*(\d+)\s*-', str(value))
    ]
    return max(numbers, default=0)


def _recommendation_valid(retailer, review_count, value):
    has_recommendation = _has_value(value)
    if review_count == 0:
        return not has_recommendation
    if review_count is None or review_count < 0:
        return True
    if not has_recommendation:
        return False

    text = str(value).strip()
    if retailer == 'Bestbuy':
        match = re.fullmatch(r'(\d{1,3})% would recommend to a friend', text)
    else:
        match = re.fullmatch(r'(\d{1,3})% Recommend this product', text)
    return bool(match and 0 <= int(match.group(1)) <= 100)


def evaluate_sea_row(row):
    """Return canonical SEA rule keys failed by one REF/LDY source row."""
    errors = set()
    retailer = str(row.get('account_name') or '').strip().title()
    if retailer not in ('Bestbuy', 'Lowes'):
        return errors

    review_count = parse_sea_number(row.get('count_of_reviews'))
    star_count = parse_sea_number(row.get('count_of_star_ratings'))
    rating = parse_sea_number(row.get('star_rating'))

    if review_count is not None and star_count is not None:
        if review_count != star_count:
            errors.add('review_count_match')

    if rating is not None and star_count is not None:
        if (rating == 0) != (star_count == 0):
            errors.add('rating_count_presence')

    if retailer == 'Bestbuy':
        page_type = str(row.get('page_type') or '').strip().upper()
        if page_type == 'MAIN' and not _has_value(row.get('main_rank')):
            errors.add('rank_page_type')
        if page_type == 'BSR' and not _has_value(row.get('bsr_rank')):
            errors.add('rank_page_type')

    final_present = _has_value(row.get('final_sku_price'))
    original_present = _has_value(row.get('original_sku_price'))
    savings_present = _has_value(row.get('savings'))
    final_price = parse_sea_money(row.get('final_sku_price'))
    original_price = parse_sea_money(row.get('original_sku_price'))
    savings = parse_sea_money(row.get('savings'))

    if final_price is not None and original_price is not None:
        if retailer == 'Lowes' and final_price >= original_price:
            errors.add('final_original_price')
        elif retailer == 'Bestbuy' and final_price > original_price:
            errors.add('final_original_price')

        if (
            retailer == 'Bestbuy'
            and original_price > 0
            and ((original_price - final_price) / original_price) * 100 >= 90
        ):
            errors.add('discount_rate_90')

    body_max = _review_body_max(row.get('detailed_review_content'))
    if review_count is not None:
        if retailer == 'Bestbuy' and review_count > 0:
            if body_max < min(int(review_count), 20):
                errors.add('review_body_count')
        elif retailer == 'Lowes' and body_max > review_count:
            # Confirmed Lowes policy: report only review-count < body-count.
            errors.add('review_body_count')

        if not _recommendation_valid(
                retailer, review_count, row.get('recommendation_intent')):
            errors.add('recommendation_intent')

    if retailer == 'Lowes':
        if final_present and original_present and not savings_present:
            errors.add('savings_missing')
        if final_present and savings_present and not original_present:
            errors.add('original_missing')
        if not final_present and (original_present or savings_present):
            errors.add('final_missing')
        if (
            final_present and original_present and savings_present
            and final_price is not None
            and original_price is not None
            and savings is not None
            and original_price - final_price != savings
        ):
            errors.add('savings_amount_match')

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
        for prefix in ('sea_ref_', 'sea_ldy_', 'sea_'):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        key = _RULE_ALIASES.get(key, key)
        if key in SEA_RULE_SPECS:
            return key
    return None


def _retailer_supported(rule_key, retailer):
    supported = SEA_RULE_SPECS[rule_key]['retailers']
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


def load_active_sea_rules(cursor, product_line):
    """Load active SEA rule metadata; stored query text is never executed."""
    key = normalize_sea_product_line(product_line)
    source = _source_for_product_line(key)
    section_code = f'{key}_retail'
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
    """, (section_code, source['table_name']))
    columns = (
        'rule_id', 'detail_code', 'detail_name', 'section_code', 'section_name',
        'table_name', 'date_column', 'product_line', 'retailer', 'field1',
        'field2', 'validation_type', 'error_message', 'select_fields', 'query',
        'sort_order',
    )
    rules_by_key = OrderedDict()
    for raw in cursor.fetchall():
        row = dict(raw) if isinstance(raw, dict) else dict(zip(columns, raw))
        if 'rule_id' not in row and 'id' in row:
            row['rule_id'] = row['id']
        rule_key = _resolve_rule_key(row)
        if not rule_key:
            continue

        spec = SEA_RULE_SPECS[rule_key]
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
                    value.casefold() for value in existing['_retailers']}:
                existing['_retailers'].append(retailer)
        merged_fields = existing['select_fields'].split('|')
        for field in display_fields:
            if field not in merged_fields:
                merged_fields.append(field)
        existing['select_fields'] = '|'.join(filter(None, merged_fields))

    return list(rules_by_key.values())


def _date_contract(inspection_date, source):
    contract = resolve_monitoring_date(
        inspection_date, 'SEA', source['source_key']
    )
    contract['source_date_value'] = date.fromisoformat(contract['source_date'])
    return contract


def load_latest_sea_rows(cursor, inspection_date, product_line, from_date=None):
    """Load exact D-1 rows from each retailer's newest MAIN anchor batch."""
    source = _source_for_product_line(product_line)
    end_contract = _date_contract(inspection_date, source)
    start_contract = _date_contract(from_date or inspection_date, source)
    start_date = start_contract['source_date']
    end_date = end_contract['source_date']
    table_name = source['table_name']
    date_column = source['date_column']
    cursor.execute(f"""
        WITH main_batches AS (
            SELECT
                LEFT(TRIM(CAST({date_column} AS TEXT)), 10) AS source_date,
                account_name,
                batch_id,
                MAX(id) AS max_id
            FROM {table_name}
            WHERE LEFT(TRIM(CAST({date_column} AS TEXT)), 10)
                      BETWEEN %s AND %s
              AND LOWER(TRIM(account_name)) IN ('bestbuy', 'lowes')
              AND UPPER(TRIM(COALESCE(page_type, ''))) = 'MAIN'
              AND NULLIF(TRIM(batch_id), '') IS NOT NULL
            GROUP BY LEFT(TRIM(CAST({date_column} AS TEXT)), 10),
                     account_name, batch_id
        ), ranked_batches AS (
            SELECT source_date, account_name, batch_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_date, LOWER(TRIM(account_name))
                       ORDER BY max_id DESC
                   ) AS batch_rank
            FROM main_batches
        )
        SELECT source.*
        FROM {table_name} source
        JOIN ranked_batches anchor
          ON anchor.source_date =
             LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10)
         AND LOWER(TRIM(anchor.account_name)) =
             LOWER(TRIM(source.account_name))
         AND anchor.batch_id = source.batch_id
         AND anchor.batch_rank = 1
        WHERE LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10)
                  BETWEEN %s AND %s
          AND UPPER(TRIM(COALESCE(source.page_type, ''))) IN ('MAIN', 'BSR')
        ORDER BY LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10),
                 LOWER(TRIM(source.account_name)), source.id
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


def build_sea_crossfield_result(
        cursor, inspection_date, product_line, from_date=None):
    key = normalize_sea_product_line(product_line)
    source = _source_for_product_line(key)
    contract = _date_contract(inspection_date, source)
    rules = load_active_sea_rules(cursor, key)
    rows = load_latest_sea_rows(
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
        str(row.get('id')): evaluate_sea_row(row)
        for row in rows
    }

    retailer_rows = {}
    for row in rows:
        retailer = str(row.get('account_name') or 'Unknown').strip().title()
        row['account_name'] = retailer
        retailer_rows.setdefault(retailer, []).append(row)

    rule_results = []
    finding_count = 0
    failed_record_ids = set()
    for rule in rules:
        error_details = []
        for row in rows:
            retailer = str(row.get('account_name') or 'Unknown').strip().title()
            row_id = str(row.get('id'))
            if not _rule_applies_to_retailer(rule, retailer):
                continue
            if rule['rule_key'] not in evaluations[row_id]:
                continue
            source_rule_ids = {
                str(rule_id)
                for rule_id in rule.get('_source_rule_ids', [rule['rule_id']])
            }
            if any((row_id, rule_id) in normal_pairs
                   for rule_id in source_rule_ids):
                continue
            detail = dict(row)
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
        retailer_failed_records = set()
        retailer_error_count = 0
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
        'date': str(inspection_date),
        'inspection_date': contract['inspection_date'],
        'source_date': contract['source_date'],
        'offset_days': contract['offset_days'],
        'configured': bool(rules),
        'product_line': key,
        'label': f"SEA {source['category']}",
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'total_checked': len(rows),
        'failed_records': len(failed_record_ids),
        'total_anomalies': finding_count,
        'rule_results': rule_results,
        'retailers': retailer_summaries,
        'normal_corrections': corrections,
    }


def _display_sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_sea_display_query(
        inspection_date, product_line, rule, days=1, retailer=None,
        retailers=None, retailer_item_pairs=None):
    """Build copy-only SQL with the same D-1/latest-anchor scope."""
    key = normalize_sea_product_line(product_line)
    source = _source_for_product_line(key)
    day_count = min(30, max(1, int(days)))
    start_inspection = inspection_date - timedelta(days=day_count - 1)
    start_source = _date_contract(start_inspection, source)['source_date']
    end_source = _date_contract(inspection_date, source)['source_date']
    date_column = source['date_column']

    select_columns = ['id', 'item', 'sku', 'retailer_sku_name']
    spec = SEA_RULE_SPECS[rule['rule_key']]
    for field_group in (*spec['display_fields'], date_column, 'batch_id', 'product_url'):
        for column in str(field_group or '').split('|'):
            column = column.strip()
            if column in _DISPLAY_QUERY_COLUMNS and column not in select_columns:
                select_columns.append(column)
    select_sql = ',\n'.join(f'    source.{column}' for column in select_columns)

    pair_values = sorted({
        (
            str(pair[0]).strip(),
            None if pair[1] is None or str(pair[1]) == '' else str(pair[1]),
        )
        for pair in (retailer_item_pairs or [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
        and str(pair[0] or '').strip()
    }, key=lambda pair: (pair[0].lower(), pair[1] or ''))
    retailer_values = [retailer] if retailer is not None else list(retailers or [])
    retailer_values.extend(pair[0] for pair in pair_values)
    retailer_values = sorted({
        str(value).strip() for value in retailer_values
        if str(value or '').strip()
    })

    filters = []
    if pair_values:
        pair_clauses = []
        for pair_retailer, item in pair_values:
            item_scope = (
                "(source.item IS NULL OR TRIM(CAST(source.item AS TEXT)) = '')"
                if item is None else f'source.item = {_display_sql_literal(item)}'
            )
            pair_clauses.append(
                '(LOWER(TRIM(source.account_name)) = LOWER(TRIM('
                f'{_display_sql_literal(pair_retailer)})) AND {item_scope})'
            )
        filters.append('(\n      ' + '\n   OR '.join(pair_clauses) + '\n  )')
    elif retailer_values:
        literals = ', '.join(
            f'LOWER(TRIM({_display_sql_literal(value)}))'
            for value in retailer_values
        )
        filters.append(f'LOWER(TRIM(source.account_name)) IN ({literals})')

    scope_sql = ''
    if filters:
        scope_sql = '\n  AND ' + '\n  AND '.join(filters)

    return f"""WITH main_batches AS (
    SELECT
        LEFT(TRIM(CAST({date_column} AS TEXT)), 10) AS source_date,
        account_name,
        batch_id,
        MAX(id) AS max_id
    FROM {source['table_name']}
    WHERE LEFT(TRIM(CAST({date_column} AS TEXT)), 10)
              BETWEEN {_display_sql_literal(start_source)}
                  AND {_display_sql_literal(end_source)}
      AND UPPER(TRIM(COALESCE(page_type, ''))) = 'MAIN'
    GROUP BY LEFT(TRIM(CAST({date_column} AS TEXT)), 10),
             account_name, batch_id
), ranked_batches AS (
    SELECT source_date, account_name, batch_id,
           ROW_NUMBER() OVER (
               PARTITION BY source_date, LOWER(TRIM(account_name))
               ORDER BY max_id DESC
           ) AS batch_rank
    FROM main_batches
)
SELECT
{select_sql}
FROM {source['table_name']} source
JOIN ranked_batches anchor
  ON anchor.source_date =
     LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10)
 AND LOWER(TRIM(anchor.account_name)) = LOWER(TRIM(source.account_name))
 AND anchor.batch_id = source.batch_id
 AND anchor.batch_rank = 1
WHERE UPPER(TRIM(COALESCE(source.page_type, ''))) IN ('MAIN', 'BSR'){scope_sql}
ORDER BY source.item, source.{date_column};"""


def get_sea_cross_field_summary(cursor, inspection_date, product_line):
    result = build_sea_crossfield_result(
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
            'query': build_sea_display_query(
                inspection_date, result['product_line'], rule,
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
        'rule_summary': rule_summary,
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'no_review_texts': '',
        'retailers': result['retailers'],
    }


def get_sea_cross_field_rule_detail(
        cursor, inspection_date, product_line, rule_id, days=1):
    from_date = inspection_date - timedelta(days=max(1, int(days)) - 1)
    result = build_sea_crossfield_result(
        cursor, inspection_date, product_line, from_date=from_date,
    )
    selected = next((
        rule for rule in result['rule_results']
        if str(rule['rule_id']) == str(rule_id)
    ), None)
    if not selected:
        return {'found': False}

    anomalies = selected['error_details']
    retailers = sorted({
        str(row.get('account_name') or 'Unknown').strip().title()
        for row in anomalies
    })
    editable_columns = set()
    retailer_columns = {}
    for retailer in retailers:
        columns = set(get_editable_columns(result['product_line'], retailer))
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
        normal_reviews[f"{record_id}_{correction['column_name']}"] = payload
        for column in editable_columns:
            normal_reviews.setdefault(f'{record_id}_{column}', payload)

    retailer_summary = {}
    for row in anomalies:
        retailer = str(row.get('account_name') or 'Unknown').strip().title()
        summary = retailer_summary.setdefault(retailer, {'count': 0, 'items': []})
        if str(row.get('id')) not in normal_record_ids:
            summary['count'] += 1
        item = str(row.get('item') or '')
        if item and item not in summary['items']:
            summary['items'].append(item)

    retailer_pairs = {retailer: [] for retailer in retailer_summary}
    for row in anomalies:
        retailer = str(row.get('account_name') or 'Unknown').strip().title()
        retailer_pairs.setdefault(retailer, []).append((
            retailer,
            None if row.get('item') is None or str(row.get('item')) == ''
            else str(row.get('item')),
        ))
    display_queries = {
        retailer: build_sea_display_query(
            inspection_date, result['product_line'], selected, days=days,
            retailer=retailer,
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
        'days': days,
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
        'query': build_sea_display_query(
            inspection_date, result['product_line'], selected, days=days,
        ),
        'queries': display_queries,
    }
