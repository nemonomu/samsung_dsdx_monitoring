"""SEG TV/REF/LDY cross-field validation.

Rule metadata is enabled through ``monitoring_validation_rules``.  Stored SQL
is never executed: the application applies an allow-listed Python rule set to
the exact SEG inspection-day/latest-MAIN-batch scope.
"""

from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seg_retail import (
    SEG_RETAILERS,
    display_seg_retailer,
    get_seg_crossfield_editable_columns,
    get_seg_collection_phase,
    get_seg_source,
    normalize_seg_product_line,
)


SEG_NO_REVIEW_TEXT = 'No customer reviews'
SEG_EQUAL_REVIEW_RETAILERS = ('Mediamarkt', 'OTTO')
SEG_REVIEW_BODY_LIMIT = 20
_KST = timezone(timedelta(hours=9))

SEG_PRICE_STATUS_TEXTS = {
    'Höherer Preis als üblich',
    'Derzeit nicht verfügbar.',
}

SEG_RULE_SPECS = OrderedDict((
    ('rating_count_presence', {
        'detail_name': '별점과 별점 수 존재 일치',
        'field1': 'star_rating',
        'field2': 'count_of_star_ratings',
        'retailers': SEG_RETAILERS,
        'display_fields': (
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
        ),
        'error_message': '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.',
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
        'retailers': ('Amazon',),
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
        'error_message': 'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.',
    }),
    ('final_original_price', {
        'detail_name': '최종가와 원가 순서',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': SEG_RETAILERS,
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': 'final_sku_price가 original_sku_price보다 크거나 같습니다.',
    }),
    ('discount_rate_90', {
        'detail_name': '90% 이상 할인 검증',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price',
        'retailers': ('Amazon',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': '최종가와 원가로 계산한 할인율이 90% 이상입니다.',
    }),
    ('savings_missing', {
        'detail_name': '할인 가격 존재 시 savings 확인',
        'field1': 'savings',
        'field2': 'final_sku_price|original_sku_price',
        'retailers': SEG_RETAILERS,
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '할인 가격인데 savings가 없습니다. Mediamarkt는 할인율 10% 이하를 제외합니다.'
        ),
    }),
    ('original_missing', {
        'detail_name': '판매가·savings 존재 시 원가 확인',
        'field1': 'original_sku_price',
        'field2': 'final_sku_price|savings',
        'retailers': SEG_RETAILERS,
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '판매가와 savings가 있는데 original_sku_price가 '
            'NULL 또는 빈값입니다.'
        ),
    }),
    ('final_missing', {
        'detail_name': '원가·savings 존재 시 판매가 확인',
        'field1': 'final_sku_price',
        'field2': 'original_sku_price|savings',
        'retailers': SEG_RETAILERS,
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            '원가 또는 savings가 있는데 final_sku_price가 '
            'NULL 또는 빈값입니다.'
        ),
    }),
    ('savings_amount_match', {
        'detail_name': 'Amazon 할인 금액 일치',
        'field1': 'savings',
        'field2': 'original_sku_price|final_sku_price',
        'retailers': ('Amazon',),
        'display_fields': (
            'final_sku_price', 'original_sku_price', 'savings',
        ),
        'error_message': (
            'savings가 original_sku_price-final_sku_price와 '
            '센트 단위까지 일치하지 않습니다.'
        ),
    }),
    ('review_count_match', {
        'detail_name': '리뷰 수와 별점 수 일치',
        'field1': 'count_of_reviews', 'field2': 'count_of_star_ratings',
        'retailers': SEG_EQUAL_REVIEW_RETAILERS,
        'display_fields': ('count_of_reviews', 'count_of_star_ratings', 'star_rating'),
        'error_message': 'count_of_reviews와 count_of_star_ratings가 다릅니다.',
    }),
    ('review_body_count', {
        'detail_name': '리뷰 수와 본문 확인',
        'field1': 'count_of_reviews', 'field2': 'detailed_review_content',
        'retailers': SEG_EQUAL_REVIEW_RETAILERS,
        'display_fields': ('count_of_reviews', 'count_of_star_ratings', 'detailed_review_content', 'review_body_count', 'issue_type'),
        'error_message': '두 카운트가 0인데 본문이 남았는지 확인합니다. OTTO는 기존 본문 네 가지 조건도 확인합니다.',
    }),
    ('review_body_decrease', {
        'detail_name': '전날 대비 리뷰본문 감소',
        'field1': 'detailed_review_content', 'field2': None,
        'retailers': SEG_EQUAL_REVIEW_RETAILERS,
        'display_fields': ('count_of_reviews', 'count_of_star_ratings', 'detailed_review_content', 'review_body_count', 'previous_review_body_count', 'previous_source_date'),
        'error_message': '수집 완료 후 카운트 변화와 최대 20개 수집 기준으로 설명되지 않는 전날 대비 리뷰본문 감소입니다.',
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
    'savings_required': 'savings_missing',
    'original_required': 'original_missing',
    'final_required': 'final_missing',
    'savings_amount': 'savings_amount_match',
}

_DISPLAY_QUERY_COLUMNS = {
    'id', 'country', 'product', 'account_name', 'page_type', 'item',
    'sku', 'retailer_sku_name', 'main_rank', 'bsr_rank',
    'count_of_reviews', 'count_of_star_ratings', 'star_rating',
    'final_sku_price', 'original_sku_price', 'savings',
    'crawl_strdatetime', 'batch_id', 'product_url',
    'detailed_review_content',
}


def _has_value(value):
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '-', 'none', 'null', 'n/a')


def parse_seg_number(value):
    if not _has_value(value):
        return None
    text = str(value).strip().replace(',', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_seg_money(value):
    """Parse one German euro amount without discarding cents."""
    if not _has_value(value):
        return None
    text = str(value).strip().replace('€', '').replace(' ', '')
    if not re.fullmatch(
            r'[+-]?(?:0|[1-9]\d{0,2}(?:\.\d{3})*|[1-9]\d*)'
            r'(?:,\d{2})?', text):
        return None
    normalized = text.replace('.', '').replace(',', '.')
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def evaluate_seg_row(row):
    """Return canonical SEG rule keys failed by one source row."""
    errors = set()
    retailer = display_seg_retailer(row.get('account_name'))
    if retailer not in SEG_RETAILERS:
        return errors

    rating_text = str(row.get('star_rating') or '').strip()
    rating = parse_seg_number(row.get('star_rating'))
    star_count = parse_seg_number(row.get('count_of_star_ratings'))
    review_count = parse_seg_number(row.get('count_of_reviews'))
    allowed_no_review = (
        retailer == 'Amazon'
        and rating_text.casefold() == SEG_NO_REVIEW_TEXT.casefold()
    )
    if rating is not None:
        if star_count is None:
            if rating > 0:
                errors.add('rating_count_presence')
        elif (rating == 0) != (star_count == 0):
            errors.add('rating_count_presence')
        if retailer in SEG_EQUAL_REVIEW_RETAILERS and review_count is not None:
            if (rating == 0) != (review_count == 0):
                errors.add('rating_count_presence')
        if retailer == 'Amazon' and (rating < 0 or rating > 5):
            errors.add('rating_range')
    elif retailer == 'Amazon' and _has_value(row.get('star_rating')) and not allowed_no_review:
        errors.add('rating_range')

    if retailer in SEG_EQUAL_REVIEW_RETAILERS:
        if review_count is not None and star_count is not None and review_count != star_count:
            errors.add('review_count_match')

    if allowed_no_review and star_count is not None and star_count > 0:
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
    final_text = str(row.get('final_sku_price') or '').strip()
    if retailer == 'Amazon' and final_text in SEG_PRICE_STATUS_TEXTS:
        return errors

    final_price = parse_seg_money(row.get('final_sku_price'))
    original_price = parse_seg_money(row.get('original_sku_price'))
    savings_amount = parse_seg_money(row.get('savings'))

    if final_price is not None and original_price is not None:
        if final_price >= original_price:
            errors.add('final_original_price')
        if (
            retailer == 'Amazon'
            and final_price > 0
            and original_price > 0
            and ((original_price - final_price) / original_price) * 100 >= 90
        ):
            errors.add('discount_rate_90')
        if original_price > final_price and not savings_present:
            small_mediamarkt_discount = (
                retailer == 'Mediamarkt' and original_price > 0
                and (original_price - final_price) * 100 <= original_price * 10
            )
            if not small_mediamarkt_discount:
                errors.add('savings_missing')

    if final_price is not None and savings_present and not original_present:
        errors.add('original_missing')
    if not final_present and (original_present or savings_present):
        errors.add('final_missing')

    if (
        retailer == 'Amazon'
        and final_price is not None
        and original_price is not None
        and original_price > final_price
        and savings_present
        and savings_amount is not None
        and original_price - final_price != savings_amount
    ):
        errors.add('savings_amount_match')

    return errors


def _review_numbers(value):
    return sorted({int(n) for n in re.findall(r'(?i)\breview\s*(\d+)\s*-', str(value or ''))})


def _body_count(row):
    body = row.get('detailed_review_content')
    if not _has_value(body):
        return 0
    numbers = _review_numbers(body)
    # An unrecognized nonempty body is not evidence of zero collected reviews.
    return len(numbers) if numbers else None


def evaluate_otto_review_body(row):
    if display_seg_retailer(row.get('account_name')) != 'OTTO':
        return None
    count = parse_seg_number(row.get('count_of_reviews'))
    if count is None:
        return None
    present = _has_value(row.get('detailed_review_content'))
    maximum = max(_review_numbers(row.get('detailed_review_content')), default=0)
    if count > 0 and not present:
        return '리뷰 수 있음 · 리뷰본문 없음'
    if count == 0 and present:
        return '리뷰 수 0 · 리뷰본문 있음'
    if maximum > count:
        return '리뷰본문 번호가 리뷰 수보다 큼'
    if count >= 20 and maximum < 20:
        return 'review20 없음'
    return None


def _review_counts(row):
    counts = tuple(parse_seg_number(row.get(column)) for column in (
        'count_of_reviews', 'count_of_star_ratings',
    ))
    if any(value is None or value < 0 or value != value.to_integral_value()
           for value in counts):
        return None
    return counts


def evaluate_seg_review_body(row):
    if display_seg_retailer(row.get('account_name')) not in SEG_EQUAL_REVIEW_RETAILERS:
        return None
    if _review_counts(row) == (0, 0) and _has_value(row.get('detailed_review_content')):
        return '리뷰 수·별점 수 0 · 리뷰본문 있음'
    return evaluate_otto_review_body(row)


def _review_body_decrease_level(row, previous):
    if not previous:
        return None
    current_body, previous_body = _body_count(row), _body_count(previous)
    if current_body is None or previous_body is None or current_body >= previous_body:
        return None
    if (current_body == 0 and parse_seg_number(row.get('count_of_reviews')) == 0
            or parse_seg_number(previous.get('count_of_reviews')) == 0):
        return 'review_needed'
    current_counts, previous_counts = _review_counts(row), _review_counts(previous)
    if current_counts is None or previous_counts is None:
        return None
    # Zero counts with remaining body belong to the body-consistency rule.
    if current_counts == (0, 0):
        return None
    if current_counts[0] != current_counts[1]:
        return 'anomaly'
    if any(current >= prior for current, prior in zip(current_counts, previous_counts)):
        return 'anomaly'
    # Both counts fell: allow a smaller body only if today's collection target
    # is still met (all reviews below 20, otherwise 20).
    return ('anomaly' if current_body < min(SEG_REVIEW_BODY_LIMIT, max(current_counts))
            else None)


def _review_collection_complete(source_day, now):
    local_now = now.astimezone(_KST)
    today = local_now.date().isoformat()
    return source_day < today or (
        source_day == today
        and get_seg_collection_phase(local_now.time()) == 'complete'
    )


def _previous_body_rows(rows, date_column):
    daily = {}
    for row in rows:
        identity = _detail_row_item_key(row)
        if identity is None:
            continue
        key = (identity, _detail_row_source_date(row, date_column))
        priority = (str(row.get('page_type') or '').strip().lower() == 'main', int(row.get('id') or 0))
        if key not in daily or priority > daily[key][0]:
            daily[key] = (priority, row)
    previous = {}
    for row in rows:
        if display_seg_retailer(row.get('account_name')) not in SEG_EQUAL_REVIEW_RETAILERS:
            continue
        day = date.fromisoformat(_detail_row_source_date(row, date_column))
        candidate = daily.get((_detail_row_item_key(row), str(day - timedelta(days=1))))
        if candidate:
            previous[str(row['id'])] = candidate[1]
    return previous


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
        for prefix in ('seg_tv_', 'seg_ref_', 'seg_ldy_', 'seg_'):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        key = _RULE_ALIASES.get(key, key)
        if key in SEG_RULE_SPECS:
            return key
    return None


def _retailer_supported(rule_key, retailer):
    supported = SEG_RULE_SPECS[rule_key]['retailers']
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


def load_active_seg_rules(cursor, product_line):
    """Load active SEG metadata; stored query text is never executed."""
    key = normalize_seg_product_line(product_line)
    source = get_seg_source(key)
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

        spec = SEG_RULE_SPECS[rule_key]
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
        inspection_date, 'SEG', source['source_key']
    )
    contract['source_date_value'] = date.fromisoformat(contract['source_date'])
    return contract


def load_latest_seg_rows(
        cursor, inspection_date, product_line, from_date=None):
    """Load each source day's latest retailer MAIN batch and MAIN+BSR rows."""
    key = normalize_seg_product_line(product_line)
    source = get_seg_source(key)
    end_contract = _date_contract(inspection_date, source)
    start_contract = _date_contract(from_date or inspection_date, source)
    start_date = start_contract['source_date']
    end_date = end_contract['source_date']
    table_name = source['table_name']
    date_column = source['date_column']
    source_date_sql = (
        f"LEFT(BTRIM(CAST(source.{date_column} AS TEXT)), 10)"
    )
    retailers_sql = ', '.join(
        "'" + retailer.casefold().replace("'", "''") + "'"
        for retailer in source['retailers']
    )
    redirect_scope = (
        "AND (LOWER(BTRIM(CAST(source.account_name AS TEXT))) <> 'amazon' "
        "OR source.redirect IS NOT TRUE)"
        if source.get('has_redirect') else ''
    )
    cursor.execute(f"""
        WITH main_batches AS (
            SELECT
                {source_date_sql} AS source_date,
                source.account_name,
                source.batch_id,
                MAX(source.id) AS max_id
            FROM {table_name} source
            WHERE {source_date_sql} >= %s
              AND {source_date_sql} <= %s
              AND UPPER(BTRIM(CAST(source.country AS TEXT))) = 'SEG'
              AND LOWER(BTRIM(CAST(source.account_name AS TEXT)))
                  IN ({retailers_sql})
              AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'
              {redirect_scope}
            GROUP BY {source_date_sql}, source.account_name, source.batch_id
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
          ON latest.source_date = {source_date_sql}
         AND LOWER(BTRIM(CAST(latest.account_name AS TEXT))) =
             LOWER(BTRIM(CAST(source.account_name AS TEXT)))
         AND latest.batch_id IS NOT DISTINCT FROM source.batch_id
         AND latest.batch_rank = 1
        WHERE {source_date_sql} >= %s
          AND {source_date_sql} <= %s
          AND UPPER(BTRIM(CAST(source.country AS TEXT))) = 'SEG'
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          {redirect_scope}
        ORDER BY {source_date_sql},
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


def build_seg_crossfield_result(
        cursor, inspection_date, product_line, from_date=None):
    key = normalize_seg_product_line(product_line)
    source = get_seg_source(key)
    contract = _date_contract(inspection_date, source)
    rules = load_active_seg_rules(cursor, key)
    start_day = from_date or inspection_date
    needs_previous = any(rule['rule_key'] == 'review_body_decrease' for rule in rules)
    rows = load_latest_seg_rows(
        cursor, inspection_date, key,
        from_date=start_day - timedelta(days=1) if needs_previous else from_date,
    )
    previous_rows = _previous_body_rows(rows, source['date_column']) if needs_previous else {}
    rows = [row for row in rows if _detail_row_source_date(row, source['date_column']) >= str(start_day)]
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
        str(row.get('id')): evaluate_seg_row(row)
        for row in rows
    }
    retailer_rows = {}
    for row in rows:
        retailer = display_seg_retailer(row.get('account_name')) or 'Unknown'
        row['account_name'] = retailer
        retailer_rows.setdefault(retailer, []).append(row)

    rule_results = []
    finding_count = 0
    failed_record_ids = set()
    review_record_ids = set()
    review_finding_count = 0
    now = datetime.now(_KST)
    for rule in rules:
        error_details = []
        review_details = []
        comparison_rows = {}
        for row in rows:
            retailer = display_seg_retailer(
                row.get('account_name')
            ) or 'Unknown'
            row_id = str(row.get('id'))
            if not _rule_applies_to_retailer(rule, retailer):
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
            if rule['rule_key'] == 'review_body_count':
                issue = evaluate_seg_review_body(row)
                if not issue:
                    continue
                detail.update({
                    'issue_type': issue, 'review_body_count': _body_count(row),
                    'validation_tag': f'확인 필요: {issue}',
                    'rule_key': rule['rule_key'], 'finding_level': 'review_needed',
                })
                review_details.append(detail)
                review_record_ids.add(row_id)
                continue
            if rule['rule_key'] == 'review_body_decrease':
                previous = previous_rows.get(row_id)
                finding_level = _review_body_decrease_level(row, previous)
                if not _review_collection_complete(
                    _detail_row_source_date(row, source['date_column']), now,
                ) or not finding_level:
                    continue
                current_count = _body_count(row)
                previous_count = _body_count(previous) if previous else None
                detail.update({
                    'review_body_count': current_count,
                    'previous_review_body_count': previous_count,
                    'previous_source_date': _detail_row_source_date(previous, source['date_column']),
                })
                comparison_rows[str(previous['id'])] = {
                    **previous, 'review_body_count': previous_count,
                }
                if finding_level == 'review_needed':
                    issue = ('리뷰 수 0 · 리뷰본문 0으로 감소' if current_count == 0
                             and parse_seg_number(row.get('count_of_reviews')) == 0
                             else '비교일 리뷰 수 0 · 본문 감소 확인')
                    detail.update({
                        'issue_type': issue, 'validation_tag': f'확인 필요: {issue}',
                        'rule_key': rule['rule_key'], 'finding_level': finding_level,
                    })
                    review_details.append(detail)
                    review_record_ids.add(row_id)
                    continue
            elif rule['rule_key'] not in evaluations[row_id]:
                continue
            detail['validation_tag'] = rule['error_message']
            detail['rule_key'] = rule['rule_key']
            detail['finding_level'] = 'anomaly'
            error_details.append(detail)
            failed_record_ids.add(row_id)

        result = dict(rule)
        result['error_details'] = error_details
        result['error_count'] = len(error_details)
        result['review_details'] = review_details
        result['review_count'] = len(review_details)
        result['comparison_rows'] = list(comparison_rows.values())
        rule_results.append(result)
        finding_count += len(error_details)
        review_finding_count += len(review_details)

    retailer_summaries = []
    for retailer, source_rows in sorted(retailer_rows.items()):
        rules_summary = []
        retailer_error_count = 0
        retailer_failed_records = set()
        retailer_review_records = set()
        retailer_review_count = 0
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
            review_details = [detail for detail in result['review_details']
                              if detail.get('account_name') == retailer]
            retailer_review_count += len(review_details)
            retailer_review_records.update(str(detail['id']) for detail in review_details)
            rules_summary.append({
                'rule_id': result['rule_id'],
                'detail_code': result['detail_code'],
                'detail_name': result['detail_name'],
                'error_count': len(details),
                'review_count': len(review_details),
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
            'review_needed_records': len(retailer_review_records - retailer_failed_records),
            'total_review_needed': retailer_review_count,
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
        'review_needed_records': len(review_record_ids - failed_record_ids),
        'total_review_needed': review_finding_count,
        'passed_records': max(0, len(rows) - len(failed_record_ids | review_record_ids)),
        'rule_results': rule_results,
        'retailers': retailer_summaries,
        'normal_corrections': corrections,
    }


def _display_sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_seg_display_query(
        inspection_date, product_line, rule, days=1, retailer=None,
        retailers=None, retailer_item_pairs=None):
    """Build a compact copy-only SEG item-history query."""
    key = normalize_seg_product_line(product_line)
    source = get_seg_source(key)
    day_count = min(30, max(1, int(days)))
    date_column = source['date_column']

    select_columns = ['id', 'item', 'sku', 'retailer_sku_name']
    spec = SEG_RULE_SPECS[rule['rule_key']]
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

    target_day = date.fromisoformat(str(inspection_date))
    start_day = target_day - timedelta(days=day_count - 1)
    date_expr = f"LEFT(BTRIM(CAST({date_column} AS TEXT)), 10)"
    filters.insert(0, "UPPER(BTRIM(CAST(country AS TEXT))) = 'SEG'")
    if source.get('has_redirect'):
        filters.append(
            "(LOWER(BTRIM(CAST(account_name AS TEXT))) <> 'amazon' "
            "OR redirect IS NOT TRUE)"
        )
    scope_sql = '\n  AND ' + '\n  AND '.join(filters)
    return f"""SELECT
{select_sql}
FROM {source['table_name']}
WHERE {date_expr} >= '{start_day.isoformat()}'
  AND {date_expr} <= '{target_day.isoformat()}'{scope_sql}
ORDER BY item, {date_column}, id;"""


def get_seg_cross_field_summary(cursor, inspection_date, product_line):
    result = build_seg_crossfield_result(
        cursor, inspection_date, product_line
    )
    rule_summary = []
    available_retailers = [
        summary['retailer'] for summary in result['retailers']
        if summary.get('retailer')
    ]
    for rule in result['rule_results']:
        error_rows = (rule.get('error_details') or []) + (rule.get('review_details') or [])
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
            'review_count': rule['review_count'],
            'query': build_seg_display_query(
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
        'review_needed_records': result['review_needed_records'],
        'total_review_needed': result['total_review_needed'],
        'passed_records': result['passed_records'],
        'rule_summary': rule_summary,
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'no_review_texts': SEG_NO_REVIEW_TEXT,
        'retailers': result['retailers'],
    }


def _detail_row_source_date(row, date_column):
    value = row.get(date_column)
    if isinstance(value, datetime):
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


def get_seg_cross_field_rule_detail(
        cursor, inspection_date, product_line, rule_id, days=1):
    day_count = min(30, max(1, int(days)))
    from_date = inspection_date - timedelta(days=day_count - 1)
    result = build_seg_crossfield_result(
        cursor, inspection_date, product_line, from_date=from_date,
    )
    selected = next((
        rule for rule in result['rule_results']
        if str(rule['rule_id']) == str(rule_id)
    ), None)
    if not selected:
        return {'found': False}

    all_findings = selected['error_details'] + selected['review_details']
    # Include the actual previous row even if it had no finding of its own.
    finding_ids = {str(row['id']) for row in all_findings}
    comparison_rows = [row for row in selected['comparison_rows'] if str(row['id']) not in finding_ids]
    comparison_ids = {str(row['id']) for row in comparison_rows}
    target_source_date = result['source_date']
    target_findings = [
        row for row in all_findings
        if _detail_row_source_date(row, result['date_col'])
        == target_source_date
    ]
    target_item_keys = {
        item_key for item_key in (
            _detail_row_item_key(row) for row in target_findings
        ) if item_key is not None
    }
    anomalies = []
    for row in all_findings + comparison_rows:
        row_source_date = _detail_row_source_date(row, result['date_col'])
        detail = dict(row)
        # PostgreSQL timestamptz는 JSON에서 UTC로 직렬화될 수 있으므로,
        # 화면에는 KST로 확정한 데이터일을 별도로 전달한다.
        detail['row_source_date'] = row_source_date
        if row_source_date == target_source_date:
            detail['row_role'] = 'target'
        elif str(row['id']) in comparison_ids or _detail_row_item_key(row) in target_item_keys:
            detail['row_role'] = 'comparison_history'
        else:
            detail['row_role'] = 'past_finding'
        anomalies.append(detail)
    anomalies.sort(key=lambda row: _detail_row_sort_key(
        row, result['date_col'],
    ))

    retailers = sorted({
        display_seg_retailer(row.get('account_name')) or 'Unknown'
        for row in anomalies
    })
    editable_columns = set()
    retailer_columns = {}
    for retailer in retailers:
        columns = set(get_seg_crossfield_editable_columns(
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
        retailer = display_seg_retailer(
            row.get('account_name')
        ) or 'Unknown'
        summary = retailer_summary.setdefault(
            retailer, {'count': 0, 'review_count': 0, 'items': []}
        )
        item = str(row.get('item') or '')
        if item and item not in summary['items']:
            summary['items'].append(item)
        if (
            row.get('row_role') == 'target'
            and str(row.get('id')) not in normal_record_ids
        ):
            count_key = 'review_count' if row.get('finding_level') == 'review_needed' else 'count'
            summary[count_key] += 1

    retailer_pairs = {retailer: [] for retailer in retailer_summary}
    for row in anomalies:
        retailer = display_seg_retailer(
            row.get('account_name')
        ) or 'Unknown'
        retailer_pairs.setdefault(retailer, []).append((
            retailer,
            None if row.get('item') is None or str(row.get('item')) == ''
            else str(row.get('item')),
        ))
    display_queries = {
        retailer: build_seg_display_query(
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
        'total_review_needed': sum(item['review_count'] for item in retailer_summary.values()),
        'total_findings': sum(item['count'] + item['review_count'] for item in retailer_summary.values()),
        'retailer_summary': retailer_summary,
        'anomalies': anomalies,
        'select_fields': selected.get('select_fields') or '',
        'table_name': result['table_name'],
        'date_col': result['date_col'],
        'editable_columns': sorted(editable_columns),
        'normal_reviews': normal_reviews,
        'retailer_columns': retailer_columns,
        'query': build_seg_display_query(
            inspection_date, result['product_line'], selected,
            days=day_count,
        ),
        'queries': display_queries,
    }
