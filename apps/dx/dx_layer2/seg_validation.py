"""Layer 2 NULL and duplicate validation for SEG Germany retail sources."""

from collections import defaultdict
from datetime import datetime, timedelta
import re

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seg_retail import (
    SEG_COUNTRY,
    SEG_SOURCE_CONFIG,
    get_seg_all_null_columns,
    get_seg_format_columns,
    get_seg_null_columns,
    get_seg_product_line,
    get_seg_table_columns,
)


_REVIEW_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)

_EURO_PRICE_PATTERN = re.compile(
    r'(?:0|[1-9]\d{0,2}(?:\.\d{3})*)'
    r'(?:,(?:\d{2}|–))?\s?€'
)
_NON_NEGATIVE_INTEGER_PATTERN = re.compile(
    r'(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)'
)
_POSITIVE_INTEGER_PATTERN = re.compile(r'[1-9]\d*')
_STAR_RATING_PATTERN = re.compile(r'(?:[0-4](?:\.\d)?|5(?:\.0)?)')
_SAVINGS_PATTERN = re.compile(r'-?\d+%')
_CALENDAR_WEEK_PATTERN = re.compile(r'w(?:[1-9]|[1-4]\d|5[0-3])')
_SCREEN_SIZE_PATTERN = re.compile(
    r'\d+(?:[.,]\d+)?(?:\s*(?:inches?|Zoll|Zentimeter|cm))?',
    re.IGNORECASE,
)
_REF_CAPACITY_PATTERN = re.compile(
    r'\d+(?:[.,]\d+)?\s*(?:L|Liter)', re.IGNORECASE
)
_LDY_CAPACITY_PATTERN = re.compile(
    r'\d+(?:[.,]\d+)?\s*kg', re.IGNORECASE
)
_LDY_LOADING_VALUES = {
    'mediamarkt': {'front load', 'top load'},
    'otto': {'front loader', 'top-loading'},
}
_REF_TYPE_VALUES = {
    'amazon': {
        'freezer-on-top', 'french door', 'fridge-freezer combination',
        'multi-door', 'no freezer compartment', 'side-by-side',
    },
    'mediamarkt': {
        'french door', 'fridge-freezer combination', 'side-by-side',
    },
    'otto': {
        'french door', 'fridge-freezer combination', 'multi door',
        'side by side',
    },
}
_FINAL_PRICE_ALLOWED_TEXT = {
    'Höherer Preis als üblich',
    'Derzeit nicht verfügbar.',
}
_STAR_RATING_ALLOWED_TEXT = {'No customer reviews'}


def product_line_for(value):
    return get_seg_product_line(value)


def _mapping(target_date, source):
    return resolve_monitoring_date(target_date, SEG_COUNTRY, source['source_key'])


def _redirect_scope(source, retailer, alias='source'):
    if source.get('has_redirect') and str(retailer).strip().casefold() == 'amazon':
        return f' AND {alias}.redirect IS NOT TRUE'
    return ''


def _latest_rows(cursor, target_date, source, retailer):
    mapping = _mapping(target_date, source)
    table_name = source['table_name']
    date_column = source['date_column']
    source_date = mapping['source_date']
    anchor_redirect = _redirect_scope(source, retailer, 'anchor')
    row_redirect = _redirect_scope(source, retailer, 'source')

    cursor.execute(f"""
        SELECT anchor.batch_id
        FROM {table_name} anchor
        WHERE LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10) = %s
          AND UPPER(BTRIM(CAST(anchor.country AS TEXT))) = %s
          AND LOWER(BTRIM(CAST(anchor.account_name AS TEXT))) = LOWER(%s)
          AND LOWER(BTRIM(CAST(anchor.page_type AS TEXT))) = 'main'
          {anchor_redirect}
        ORDER BY anchor.id DESC
        LIMIT 1
    """, (source_date, SEG_COUNTRY, retailer))
    anchor = cursor.fetchone()
    batch_id = anchor[0] if anchor else None
    mapping = {**mapping, 'batch_id': batch_id}
    if not anchor:
        return [], mapping

    cursor.execute(f"""
        SELECT source.*
        FROM {table_name} source
        WHERE LEFT(BTRIM(CAST(source.{date_column} AS TEXT)), 10) = %s
          AND UPPER(BTRIM(CAST(source.country AS TEXT))) = %s
          AND LOWER(BTRIM(CAST(source.account_name AS TEXT))) = LOWER(%s)
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          AND source.batch_id IS NOT DISTINCT FROM %s
          {row_redirect}
        ORDER BY source.id
    """, (source_date, SEG_COUNTRY, retailer, batch_id))
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()], mapping


def _history_rows(cursor, source, retailer, start_date, end_date, items,
                  include_missing_item=False):
    conditions = []
    item_params = []
    if items:
        placeholders = ', '.join(['%s'] * len(items))
        conditions.append(f'source.item IN ({placeholders})')
        item_params.extend(items)
    if include_missing_item:
        conditions.append(
            "(source.item IS NULL OR BTRIM(CAST(source.item AS TEXT)) = '')"
        )
    if not conditions:
        return []

    table_name = source['table_name']
    date_column = source['date_column']
    anchor_redirect = _redirect_scope(source, retailer, 'anchor')
    row_redirect = _redirect_scope(source, retailer, 'source')
    date_expression = f"LEFT(BTRIM(CAST(source.{date_column} AS TEXT)), 10)"
    cursor.execute(f"""
        WITH latest_batches AS (
            SELECT DISTINCT ON (
                       LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10)
                   )
                   LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10)
                       AS source_date,
                   anchor.batch_id,
                   anchor.id
            FROM {table_name} anchor
            WHERE LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10) >= %s
              AND LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10) <= %s
              AND UPPER(BTRIM(CAST(anchor.country AS TEXT))) = %s
              AND LOWER(BTRIM(CAST(anchor.account_name AS TEXT))) = LOWER(%s)
              AND LOWER(BTRIM(CAST(anchor.page_type AS TEXT))) = 'main'
              {anchor_redirect}
            ORDER BY source_date, anchor.id DESC
        )
        SELECT source.*
        FROM {table_name} source
        JOIN latest_batches latest
          ON {date_expression} = latest.source_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE UPPER(BTRIM(CAST(source.country AS TEXT))) = %s
          AND LOWER(BTRIM(CAST(source.account_name AS TEXT))) = LOWER(%s)
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          AND ({' OR '.join(conditions)})
          {row_redirect}
        ORDER BY source.item, {date_expression}, source.id
    """, (
        str(start_date), str(end_date), SEG_COUNTRY, retailer,
        SEG_COUNTRY, retailer, *item_params,
    ))
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _missing(value):
    return value is None or str(value).strip() == ''


def evaluate_format_row(row, product_line, retailer):
    """Return SEG format errors for populated fields only."""
    fields = set(get_seg_format_columns(product_line, retailer))
    retailer_key = str(retailer or '').strip().casefold()
    errors = {}

    def check_pattern(field, pattern, reason, allowed=()):
        value = row.get(field)
        if _missing(value):
            return
        text = str(value).strip()
        if text not in allowed and not pattern.fullmatch(text):
            errors[field] = reason

    if 'final_sku_price' in fields:
        allowed = (
            _FINAL_PRICE_ALLOWED_TEXT if retailer_key == 'amazon' else ()
        )
        check_pattern(
            'final_sku_price', _EURO_PRICE_PATTERN,
            '독일 유로 금액 또는 허용된 Amazon 가격 상태가 아닙니다.',
            allowed,
        )
    if 'original_sku_price' in fields:
        check_pattern(
            'original_sku_price', _EURO_PRICE_PATTERN,
            '독일 유로 금액 형식이 아닙니다.',
        )
    if 'savings' in fields:
        check_pattern(
            'savings', _SAVINGS_PATTERN,
            '정수 퍼센트 형식이 아닙니다.',
        )
    if 'star_rating' in fields:
        allowed = (
            _STAR_RATING_ALLOWED_TEXT if retailer_key == 'amazon' else ()
        )
        check_pattern(
            'star_rating', _STAR_RATING_PATTERN,
            '0~5 숫자 또는 허용된 리뷰 없음 상태가 아닙니다.',
            allowed,
        )
    for field in ('count_of_star_ratings', 'count_of_reviews'):
        if field in fields:
            check_pattern(
                field, _NON_NEGATIVE_INTEGER_PATTERN,
                '0 이상의 정수 형식이 아닙니다.',
            )
    for field in ('main_rank', 'bsr_rank'):
        if field in fields:
            check_pattern(
                field, _POSITIVE_INTEGER_PATTERN,
                '1 이상의 정수 형식이 아닙니다.',
            )
    if 'calendar_week' in fields:
        check_pattern(
            'calendar_week', _CALENDAR_WEEK_PATTERN,
            'w1~w53 형식이 아닙니다.',
        )
    if 'screen_size' in fields:
        check_pattern(
            'screen_size', _SCREEN_SIZE_PATTERN,
            '숫자와 허용된 화면 크기 단위 형식이 아닙니다.',
        )
    if 'ref_capacity' in fields:
        check_pattern(
            'ref_capacity', _REF_CAPACITY_PATTERN,
            '숫자와 L 또는 Liter 단위 형식이 아닙니다.',
        )
    if 'ldy_capacity' in fields:
        check_pattern(
            'ldy_capacity', _LDY_CAPACITY_PATTERN,
            '숫자와 kg 단위 형식이 아닙니다.',
        )

    refrigerator_type = row.get('ref_refrigerator_type')
    if (
        'ref_refrigerator_type' in fields
        and not _missing(refrigerator_type)
        and str(refrigerator_type).strip().casefold()
        not in _REF_TYPE_VALUES.get(retailer_key, set())
    ):
        errors['ref_refrigerator_type'] = (
            'CSV에서 확인된 리테일러별 냉장고 타입이 아닙니다.'
        )

    loading_type = row.get('ldy_loading_type')
    if (
        'ldy_loading_type' in fields
        and not _missing(loading_type)
        and str(loading_type).strip().casefold()
        not in _LDY_LOADING_VALUES.get(retailer_key, set())
    ):
        errors['ldy_loading_type'] = (
            'CSV에서 확인된 리테일러별 세탁기 타입이 아닙니다.'
        )
    return errors


def _serialize_format_row(row, product_line, retailer):
    record = {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }
    error_map = evaluate_format_row(row, product_line, retailer)
    record['error_fields'] = list(error_map)
    record['error_details'] = {
        field: {'rule': 'SEG 형식 검증', 'reason': reason}
        for field, reason in error_map.items()
    }
    return record


_FORMAT_RULE_DETAILS = {
    'final_sku_price': {
        'field': 'final_sku_price',
        'description': '독일 유로 금액 또는 허용된 Amazon 가격 상태',
        'pattern': (
            '1.099,00 € / 1.099,– € / Höherer Preis als üblich / '
            'Derzeit nicht verfügbar.'
        ),
    },
    'original_sku_price': {
        'field': 'original_sku_price',
        'description': '값이 있으면 독일 유로 금액 형식',
        'pattern': '1.099,00 € / 1.099,– € / 1.099,00€',
    },
    'savings': {
        'field': 'savings', 'description': '값이 있으면 정수 할인율',
        'pattern': '-10% / 0%',
    },
    'star_rating': {
        'field': 'star_rating',
        'description': '0~5 숫자 또는 Amazon 리뷰 없음 상태',
        'pattern': '0 / 4.5 / 5.0 / No customer reviews',
    },
    'count_of_star_ratings': {
        'field': 'count_of_star_ratings',
        'description': '값이 있으면 0 이상의 정수',
        'pattern': '0 / 128 / 1,018',
    },
    'count_of_reviews': {
        'field': 'count_of_reviews',
        'description': '값이 있으면 0 이상의 정수',
        'pattern': '0 / 128 / 1,018',
    },
    'main_rank': {
        'field': 'main_rank', 'description': '값이 있으면 1 이상의 정수',
        'pattern': '1 / 100 / 300',
    },
    'bsr_rank': {
        'field': 'bsr_rank', 'description': '값이 있으면 1 이상의 정수',
        'pattern': '1 / 50 / 100',
    },
    'calendar_week': {
        'field': 'calendar_week', 'description': '연중 주차 표기',
        'pattern': 'w1~w53',
    },
    'screen_size': {
        'field': 'screen_size', 'description': '화면 크기와 선택 단위',
        'pattern': '55 inches / 345 cm / 65',
    },
    'ref_capacity': {
        'field': 'ref_capacity', 'description': '냉장고 용량',
        'pattern': '160.2L / 4,5 Liter / 1000 l',
    },
    'ref_refrigerator_type': {
        'field': 'ref_refrigerator_type',
        'description': '리테일러별 냉장고 타입',
        'pattern': 'French Door / Multi-Door / Side-by-Side 등',
    },
    'ldy_capacity': {
        'field': 'ldy_capacity', 'description': '세탁 용량',
        'pattern': '10.0kg / 10,5 kg',
    },
    'ldy_loading_type': {
        'field': 'ldy_loading_type',
        'description': '리테일러별 세탁기 타입',
        'pattern': 'Front load / Front loader / Top load / Top-loading',
    },
}


def get_format_rule_details(product_line, retailer):
    rules = [
        dict(_FORMAT_RULE_DETAILS[field])
        for field in get_seg_format_columns(product_line, retailer)
        if field in _FORMAT_RULE_DETAILS
    ]
    if str(retailer or '').strip().casefold() != 'amazon':
        for rule in rules:
            if rule['field'] == 'final_sku_price':
                rule['description'] = '독일 유로 금액 형식'
                rule['pattern'] = '1.099,00 € / 1.099,– €'
            elif rule['field'] == 'star_rating':
                rule['description'] = '0~5 범위 숫자'
                rule['pattern'] = '0 / 4.5 / 5.0'
    return rules


def _null_detail_columns(column):
    columns = [
        'id', 'crawl_strdatetime', 'item', 'sku', 'retailer_sku_name',
    ]
    columns.extend(_REVIEW_COLUMNS if column in _REVIEW_COLUMNS else (column,))
    columns.append('product_url')
    return list(dict.fromkeys(columns))


def _load_normal_reviews(cursor, target_date, product_line,
                         correction_type='null_check', column=None):
    source = SEG_SOURCE_CONFIG[product_line]
    mapping = _mapping(target_date, source)
    params = [
        source['table_name'], mapping['inspection_date'], correction_type,
    ]
    column_clause = ''
    if column:
        column_clause = ' AND column_name = %s'
        params.append(column)
    cursor.execute(f"""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s
          AND crawl_date = %s
          AND correction_type = %s
          AND status = 'normal'
          {column_clause}
    """, params)
    reviews = {}
    for row in cursor.fetchall():
        created_at = row[4]
        reviews[f'{row[0]}_{row[1]}'] = {
            'memo': row[2],
            'created_id': row[3],
            'created_at': (
                created_at.strftime('%Y-%m-%d %H:%M:%S')
                if created_at else None
            ),
            'reason': row[5],
        }
    return reviews


def append_null_stats(cursor, target_date, validation):
    total_issues = 0
    for product_line, source in SEG_SOURCE_CONFIG.items():
        table_retailers = []
        table_fields = []
        table_records = 0
        table_issues = 0
        table_mapping = _mapping(target_date, source)

        for retailer in source['retailers']:
            rows, mapping = _latest_rows(cursor, target_date, source, retailer)
            normal_reviews = _load_normal_reviews(
                cursor, target_date, product_line, 'null_check'
            )
            fields = list(get_seg_null_columns(product_line, retailer))
            for field in fields:
                if field not in table_fields:
                    table_fields.append(field)
            field_counts = {
                field: sum(
                    1 for row in rows
                    if _missing(row.get(field))
                    and f"{row.get('id')}_{field}" not in normal_reviews
                )
                for field in fields
            }
            issue_count = sum(field_counts.values())
            table_retailers.append({
                'retailer': retailer,
                'total': len(rows),
                'total_null_count': issue_count,
                'fields_detail': field_counts,
                'status': 'OK' if issue_count == 0 else 'CRITICAL',
                **mapping,
            })
            table_records += len(rows)
            table_issues += issue_count

        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_records': table_records,
            'total_issues': table_issues,
            'status': 'OK' if table_issues == 0 else 'CRITICAL',
            'fields': table_fields,
            'retailers': table_retailers,
            **table_mapping,
        })
        total_issues += table_issues
    return total_issues


def append_format_stats(cursor, target_date, validation):
    total_issues = 0
    for product_line, source in SEG_SOURCE_CONFIG.items():
        retailer_rows = []
        table_checked = 0
        table_issues = 0
        table_mapping = _mapping(target_date, source)
        normal_reviews = _load_normal_reviews(
            cursor, target_date, product_line, 'format_check'
        )

        for retailer in source['retailers']:
            rows, mapping = _latest_rows(cursor, target_date, source, retailer)
            issue_count = sum(
                1
                for row in rows
                for field in evaluate_format_row(row, product_line, retailer)
                if f"{row.get('id')}_{field}" not in normal_reviews
            )
            retailer_rows.append({
                'retailer': retailer,
                'total': len(rows),
                'issue_count': issue_count,
                'status': 'OK' if issue_count == 0 else 'CRITICAL',
                **mapping,
            })
            table_checked += len(rows)
            table_issues += issue_count

        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_checked': table_checked,
            'total_issues': table_issues,
            'status': 'OK' if table_issues == 0 else 'CRITICAL',
            'retailers': retailer_rows,
            **table_mapping,
        })
        total_issues += table_issues
    return total_issues


def null_detail(cursor, target_date, table, retailer, column, days=3):
    product_line = product_line_for(table)
    source = SEG_SOURCE_CONFIG.get(product_line)
    allowed = get_seg_null_columns(product_line, retailer)
    if not source or retailer not in source['retailers'] or column not in allowed:
        return {'results': [], 'display_config': {}, 'query_config': {}}

    rows, mapping = _latest_rows(cursor, target_date, source, retailer)
    normal_reviews = _load_normal_reviews(
        cursor, target_date, product_line, 'null_check', column
    )
    target_results = []
    for row in rows:
        null_fields = [field for field in allowed if _missing(row.get(field))]
        if column in null_fields:
            target_results.append({**row, 'null_fields': null_fields})

    history_days = min(max(int(days or 3), 1), 30)
    results = target_results
    if history_days > 1 and target_results:
        items = sorted({
            str(row.get('item')) for row in target_results
            if not _missing(row.get('item'))
        })
        include_missing_item = any(
            _missing(row.get('item')) for row in target_results
        )
        source_date = datetime.strptime(mapping['source_date'], '%Y-%m-%d').date()
        history_rows = _history_rows(
            cursor, source, retailer,
            source_date - timedelta(days=history_days - 1),
            source_date, items,
            include_missing_item=include_missing_item,
        )
        if history_rows:
            results = [
                {
                    **row,
                    'null_fields': [
                        field for field in allowed if _missing(row.get(field))
                    ],
                }
                for row in history_rows
            ]

    display = _null_detail_columns(column)
    return {
        'date': mapping['inspection_date'],
        'results': results,
        'select_cols': list(get_seg_table_columns(product_line)),
        'editable_cols': list(allowed),
        'actual_table': source['table_name'],
        'display_config': {column: {'select_columns': display}},
        'query_config': {column: display},
        'query_retailer': retailer,
        'normal_reviews': normal_reviews,
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': source['date_column'],
        'readonly': False,
        **mapping,
    }


def format_detail(cursor, target_date, table, retailer, days=3):
    product_line = product_line_for(table)
    source = SEG_SOURCE_CONFIG.get(product_line)
    if not source or retailer not in source['retailers']:
        return {
            'results': [], 'column_names': [], 'editable_cols': [],
            'actual_table': '', 'field_counts': {},
            'total_format_count': 0,
        }

    rows, mapping = _latest_rows(cursor, target_date, source, retailer)
    normal_reviews = _load_normal_reviews(
        cursor, target_date, product_line, 'format_check'
    )
    target_records = []
    for row in rows:
        record = _serialize_format_row(row, product_line, retailer)
        record['error_fields'] = [
            field for field in record['error_fields']
            if f"{record.get('id')}_{field}" not in normal_reviews
        ]
        if record['error_fields']:
            target_records.append(record)

    history_days = min(max(int(days or 3), 1), 30)
    results = target_records
    if history_days > 1 and target_records:
        items = sorted({
            str(record.get('item')).strip()
            for record in target_records if not _missing(record.get('item'))
        })
        source_date = datetime.strptime(
            mapping['source_date'], '%Y-%m-%d'
        ).date()
        history_rows = _history_rows(
            cursor, source, retailer,
            source_date - timedelta(days=history_days - 1),
            source_date, items,
        )
        if history_rows:
            results = [
                _serialize_format_row(row, product_line, retailer)
                for row in history_rows
            ]

    field_counts = defaultdict(int)
    for record in target_records:
        for field in record['error_fields']:
            field_counts[field] += 1

    format_fields = list(get_seg_format_columns(product_line, retailer))
    date_column = source['date_column']
    column_names = list(dict.fromkeys((
        'id', date_column, 'item', 'sku', 'retailer_sku_name',
        *format_fields, 'product_url',
    )))
    return {
        'date': mapping['inspection_date'],
        'table': source['section_code'],
        'retailer': retailer,
        'column_names': column_names,
        'select_cols': list(get_seg_table_columns(product_line)),
        'editable_cols': format_fields,
        'actual_table': source['table_name'],
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': dict(field_counts),
        'total_format_count': sum(field_counts.values()),
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': date_column,
        'editable_date': mapping['source_date'],
        'readonly': False,
        **mapping,
    }


def _duplicate_text(value):
    return str(value or '').strip()


def _duplicate_key(value):
    return _duplicate_text(value).casefold()


def _serialize_duplicate_row(row):
    return {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }


def build_duplicate_groups(rows):
    """Group duplicates within the same page_type and item."""
    grouped = defaultdict(list)
    for row in rows:
        page_type_key = _duplicate_key(row.get('page_type'))
        item_key = _duplicate_key(row.get('item'))
        if page_type_key and item_key:
            grouped[(page_type_key, item_key)].append(row)

    groups = []
    for duplicate_rows in grouped.values():
        if len(duplicate_rows) <= 1:
            continue
        first = duplicate_rows[0]
        sku_values = {
            _duplicate_key(row.get('sku')) or '' for row in duplicate_rows
        }
        name_values = {
            _duplicate_key(row.get('retailer_sku_name')) or ''
            for row in duplicate_rows
        }
        mapping_conflict = len(sku_values) > 1 or len(name_values) > 1
        page_type = _duplicate_text(first.get('page_type')).upper()
        item = _duplicate_text(first.get('item'))
        groups.append({
            'duplicate_type': (
                '상품 매핑 충돌' if mapping_conflict else '완전 중복'
            ),
            'page_type': page_type,
            'item': item,
            'retailer_sku_name': ', '.join(sorted({
                _duplicate_text(row.get('retailer_sku_name'))
                for row in duplicate_rows
                if _duplicate_text(row.get('retailer_sku_name'))
            })),
            'dup_count': len(duplicate_rows),
            'reason': (
                f'{page_type}의 동일 item에 서로 다른 SKU/상품명이 '
                f'{len(duplicate_rows)}건 연결됨'
                if mapping_conflict else
                f'{page_type}의 동일 item이 최신 배치에 '
                f'{len(duplicate_rows)}건 수집됨'
            ),
            'records': [
                _serialize_duplicate_row(row) for row in duplicate_rows
            ],
        })
    groups.sort(key=lambda group: (
        group['page_type'], group['item'], group['duplicate_type']
    ))
    return groups


def append_duplicate_stats(cursor, target_date, validation):
    total_issues = 0
    for _product_line, source in SEG_SOURCE_CONFIG.items():
        retailer_rows = []
        table_records = 0
        table_issues = 0
        table_mapping = _mapping(target_date, source)

        for retailer in source['retailers']:
            rows, mapping = _latest_rows(
                cursor, target_date, source, retailer
            )
            groups = build_duplicate_groups(rows)
            issue_count = len(groups)
            retailer_rows.append({
                'retailer': retailer,
                'total': len(rows),
                'duplicate_groups': issue_count,
                'duplicate_keys': ['page_type + item'],
                'status': 'OK' if issue_count == 0 else 'CRITICAL',
                **mapping,
            })
            table_records += len(rows)
            table_issues += issue_count

        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_records': table_records,
            'total_issues': table_issues,
            'duplicate_groups': table_issues,
            'duplicate_keys': ['page_type + item'],
            'status': 'OK' if table_issues == 0 else 'CRITICAL',
            'retailers': retailer_rows,
            **table_mapping,
        })
        total_issues += table_issues
    return total_issues


def duplicate_detail(cursor, target_date, table, retailer, page=1,
                     page_size=50):
    product_line = product_line_for(table)
    source = SEG_SOURCE_CONFIG.get(product_line)
    if not source or retailer not in source['retailers']:
        return {
            'results': {
                'duplicates': [], 'total_groups': 0, 'total_pages': 0,
                'page': page, 'page_size': page_size,
            },
            'readonly': True,
        }

    rows, mapping = _latest_rows(cursor, target_date, source, retailer)
    groups = build_duplicate_groups(rows)
    start = (page - 1) * page_size
    total_pages = (
        (len(groups) + page_size - 1) // page_size if groups else 0
    )
    return {
        'date': mapping['inspection_date'],
        'table': source['section_code'],
        'retailer': retailer,
        'select_cols': {
            'group': [
                'duplicate_type', 'page_type', 'item',
                'retailer_sku_name', 'dup_count', 'reason',
            ],
            'record': [
                'id', 'sku', 'retailer_sku_name', 'final_sku_price',
                source['date_column'], 'product_url',
            ],
        },
        'editable_cols': [],
        'actual_table': source['table_name'],
        'readonly': True,
        'readonly_message': (
            'SEG 중복 검증은 확인 전용이며 자동 삭제하지 않습니다.'
        ),
        'results': {
            'duplicates': groups[start:start + page_size],
            'total_groups': len(groups),
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
        },
        **mapping,
    }


def get_review_allowed_columns(product_line, retailer,
                               correction_type='null_check'):
    if correction_type == 'format_check':
        return get_seg_format_columns(product_line, retailer)
    return get_seg_null_columns(product_line, retailer)


def fetch_review_record(cursor, target_date, product_line, record_id, column,
                        correction_type='null_check'):
    source = SEG_SOURCE_CONFIG[product_line]
    mapping = _mapping(target_date, source)
    table_name = source['table_name']
    date_column = source['date_column']
    redirect_scope = (
        ' AND NOT (LOWER(BTRIM(CAST(source.account_name AS TEXT))) = '
        "'amazon' AND source.redirect IS TRUE)"
        if source.get('has_redirect') else ''
    )
    cursor.execute(f"""
        SELECT source.{column}, source.account_name, source.item
        FROM {table_name} source
        WHERE source.id = %s
          AND LEFT(BTRIM(CAST(source.{date_column} AS TEXT)), 10) = %s
          AND UPPER(BTRIM(CAST(source.country AS TEXT))) = %s
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          {redirect_scope}
          AND source.batch_id IS NOT DISTINCT FROM (
              SELECT anchor.batch_id
              FROM {table_name} anchor
              WHERE LEFT(BTRIM(CAST(anchor.{date_column} AS TEXT)), 10) = %s
                AND LOWER(BTRIM(CAST(anchor.account_name AS TEXT))) =
                    LOWER(BTRIM(CAST(source.account_name AS TEXT)))
                AND LOWER(BTRIM(CAST(anchor.page_type AS TEXT))) = 'main'
                {redirect_scope.replace('source.', 'anchor.')}
              ORDER BY anchor.id DESC
              LIMIT 1
          )
    """, (
        record_id, mapping['source_date'], SEG_COUNTRY,
        mapping['source_date'],
    ))
    row = cursor.fetchone()
    if row and column not in get_review_allowed_columns(
            product_line, row[1], correction_type):
        return None
    return row
