"""Layer 2 validation for SEM Mexico Liverpool sources."""

import re
from collections import defaultdict
from datetime import datetime, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.sem_retail import (
    SEM_COUNTRY,
    SEM_RETAILER,
    SEM_SECTION_TO_PRODUCT_LINE,
    SEM_SOURCE_CONFIG,
    get_sem_editable_columns,
    get_sem_required_columns,
    get_sem_table_columns,
)


_MONEY_VALUE = r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})'
_PRICE = re.compile(rf'^{_MONEY_VALUE}(?:\s*/\s*{_MONEY_VALUE})*$')
_COUNT = re.compile(r'^\d+$')
_POSITIVE_INTEGER = re.compile(r'^[1-9]\d*$')
_RATING = re.compile(r'^(?:[0-4](?:\.\d)?|5(?:\.0)?)$')
_WEEK = re.compile(r'^[Ww](?:[1-9]|[1-4]\d|5[0-3])$')
_URL = re.compile(r'^https://(?:www\.)?liverpool\.com\.mx/tienda/pdp/', re.I)
_SIZE_VALUE = r'\d+(?:\.\d+)?\s+inch'
_SIZE = re.compile(rf'^{_SIZE_VALUE}(?:\s*/\s*{_SIZE_VALUE})*$', re.I)
_REF_CAPACITY_VALUE = r'\d+(?:\.\d+)?\s+(?:cu\s*ft|l|liters?)'
_REF_CAPACITY = re.compile(
    rf'^{_REF_CAPACITY_VALUE}(?:\s*/\s*{_REF_CAPACITY_VALUE})*$', re.I
)
_LDY_CAPACITY_VALUE = r'\d+(?:\.\d+)?\s+kg'
_LDY_CAPACITY = re.compile(
    rf'^{_LDY_CAPACITY_VALUE}(?:\s*/\s*{_LDY_CAPACITY_VALUE})*$', re.I
)
_REF_REFRIGERATOR_TYPES = {
    'Freezer',
    'Freezer-on-Bottom (Bottom Mount)',
    'Freezer-on-Top (Top Mount)',
    'French Door',
    'Side-by-Side',
}
_LDY_LOADING_TYPES = {'Front Load', 'Top Load'}
_REVIEW_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)


def product_line_for(value):
    key = str(value or '').strip().lower()
    if key in SEM_SOURCE_CONFIG:
        return key
    if key in SEM_SECTION_TO_PRODUCT_LINE:
        return SEM_SECTION_TO_PRODUCT_LINE[key]
    for product_line, source in SEM_SOURCE_CONFIG.items():
        names = {source['table_name'].lower(), source['table_name'].split('.')[-1].lower()}
        if key in names:
            return product_line
    return None


def _mapping(target_date, source):
    return resolve_monitoring_date(target_date, SEM_COUNTRY, source['source_key'])


def _latest_rows(cursor, target_date, source):
    mapping = _mapping(target_date, source)
    cursor.execute(f"""
        WITH latest_batch AS (
            SELECT batch_id
            FROM {source['table_name']}
            WHERE LEFT(BTRIM(crawl_datetime), 10) = %s
              AND LOWER(BTRIM(account_name)) = LOWER(%s)
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT source.*
        FROM {source['table_name']} source
        CROSS JOIN latest_batch
        WHERE LEFT(BTRIM(source.crawl_datetime), 10) = %s
          AND source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id
        ORDER BY source.id
    """, (mapping['source_date'], SEM_RETAILER,
          mapping['source_date']))
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()], mapping


def _history_rows(cursor, source, start_date, end_date, items,
                  include_missing_item=False):
    """Load the latest Liverpool batch per day for target error items."""
    conditions = []
    params = [str(start_date), str(end_date), SEM_RETAILER, SEM_COUNTRY]
    if items:
        placeholders = ', '.join(['%s'] * len(items))
        conditions.append(f'source.item IN ({placeholders})')
        params.extend(items)
    if include_missing_item:
        conditions.append(
            "(source.item IS NULL OR BTRIM(CAST(source.item AS TEXT)) = '')"
        )
    if not conditions:
        return []

    date_expression = "LEFT(BTRIM(source.crawl_datetime), 10)"
    cursor.execute(f"""
        WITH latest_batches AS (
            SELECT DISTINCT ON (LEFT(BTRIM(crawl_datetime), 10))
                   LEFT(BTRIM(crawl_datetime), 10) AS source_date,
                   batch_id,
                   id
            FROM {source['table_name']}
            WHERE LEFT(BTRIM(crawl_datetime), 10) >= %s
              AND LEFT(BTRIM(crawl_datetime), 10) <= %s
              AND LOWER(BTRIM(account_name)) = LOWER(%s)
              AND UPPER(BTRIM(country)) = %s
            ORDER BY source_date, id DESC
        )
        SELECT source.*
        FROM {source['table_name']} source
        JOIN latest_batches latest
          ON {date_expression} = latest.source_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE ({' OR '.join(conditions)})
        ORDER BY source.item, {date_expression}, source.id
    """, (*params[:4], *params[4:]))
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _null_detail_columns(column):
    columns = [
        'id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name',
    ]
    columns.extend(_REVIEW_COLUMNS if column in _REVIEW_COLUMNS else (column,))
    columns.append('product_url')
    return list(dict.fromkeys(columns))


def _missing(value):
    return value is None or str(value).strip() == ''


def _valid_datetime(value):
    if isinstance(value, datetime):
        return True
    try:
        datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    return True


def evaluate_format(row, product_line):
    errors = []
    checks = {
        'country': lambda value: str(value).strip().upper() == SEM_COUNTRY,
        'account_name': lambda value: str(value).strip().casefold() == SEM_RETAILER.casefold(),
        'item': lambda value: bool(_POSITIVE_INTEGER.fullmatch(str(value).strip())),
        'crawl_datetime': _valid_datetime,
        'calendar_week': lambda value: bool(_WEEK.fullmatch(str(value).strip())),
        'product_url': lambda value: bool(_URL.match(str(value).strip())),
        'final_sku_price': lambda value: bool(_PRICE.fullmatch(str(value).strip())),
        'original_sku_price': lambda value: bool(_PRICE.fullmatch(str(value).strip())),
        'star_rating': lambda value: bool(_RATING.fullmatch(str(value).strip())),
        'count_of_reviews': lambda value: bool(_COUNT.fullmatch(str(value).strip())),
        'count_of_star_ratings': lambda value: bool(_COUNT.fullmatch(str(value).strip())),
        'main_rank': lambda value: bool(_POSITIVE_INTEGER.fullmatch(str(value).strip())),
        'bsr_rank': lambda value: bool(_POSITIVE_INTEGER.fullmatch(str(value).strip())),
    }
    if product_line == 'sem_tv':
        checks['screen_size'] = lambda value: bool(_SIZE.fullmatch(str(value).strip()))
    elif product_line == 'sem_ref':
        checks['ref_capacity'] = lambda value: bool(_REF_CAPACITY.fullmatch(str(value).strip()))
        checks['ref_refrigerator_type'] = (
            lambda value: str(value).strip() in _REF_REFRIGERATOR_TYPES
        )
    elif product_line == 'sem_ldy':
        checks['ldy_capacity'] = lambda value: bool(_LDY_CAPACITY.fullmatch(str(value).strip()))
        checks['ldy_loading_type'] = (
            lambda value: str(value).strip() in _LDY_LOADING_TYPES
        )

    for field, validator in checks.items():
        value = row.get(field)
        # Missing-value validation is a separate Layer 2 check. Format rules
        # only inspect values that are actually present.
        if _missing(value):
            continue
        if not validator(value):
            errors.append(field)
    return errors


def _serialize(row, product_line):
    result = dict(row)
    result['error_fields'] = evaluate_format(row, product_line)
    result['error_field'] = ', '.join(result['error_fields'])
    return result


def append_null_stats(cursor, target_date, validation):
    total_issues = 0
    for product_line, source in SEM_SOURCE_CONFIG.items():
        rows, mapping = _latest_rows(cursor, target_date, source)
        fields = list(get_sem_required_columns(product_line))
        field_counts = {
            field: sum(1 for row in rows if _missing(row.get(field)))
            for field in fields
        }
        issue_count = sum(field_counts.values())
        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_records': len(rows),
            'total_issues': issue_count,
            'status': 'OK' if issue_count == 0 else 'CRITICAL',
            'fields': fields,
            'retailers': [{
                'retailer': SEM_RETAILER,
                'total': len(rows),
                'total_null_count': issue_count,
                'fields_detail': field_counts,
                'status': 'OK' if issue_count == 0 else 'CRITICAL',
            }],
            **mapping,
        })
        total_issues += issue_count
    return total_issues


def null_detail(cursor, target_date, table, column, days=1):
    product_line = product_line_for(table)
    source = SEM_SOURCE_CONFIG.get(product_line)
    if not source or column not in get_sem_required_columns(product_line):
        return {'results': [], 'display_config': {}, 'query_config': {}}
    rows, mapping = _latest_rows(cursor, target_date, source)
    target_results = []
    for row in rows:
        null_fields = [
            field for field in get_sem_required_columns(product_line)
            if _missing(row.get(field))
        ]
        if column in null_fields:
            target_results.append({**row, 'null_fields': null_fields})

    history_days = min(max(int(days or 1), 1), 30)
    results = target_results
    if history_days > 1 and target_results:
        items = sorted({
            str(row.get('item')) for row in target_results
            if not _missing(row.get('item'))
        })
        include_missing_item = any(
            _missing(row.get('item')) for row in target_results
        )
        source_date = datetime.strptime(
            mapping['source_date'], '%Y-%m-%d'
        ).date()
        history_rows = _history_rows(
            cursor,
            source,
            source_date - timedelta(days=history_days - 1),
            source_date,
            items,
            include_missing_item=include_missing_item,
        )
        if history_rows:
            results = []
            for row in history_rows:
                null_fields = [
                    field for field in get_sem_required_columns(product_line)
                    if _missing(row.get(field))
                ]
                results.append({**row, 'null_fields': null_fields})

    display = _null_detail_columns(column)
    all_columns = list(get_sem_table_columns(product_line))
    editable = list(get_sem_editable_columns(product_line))
    return {
        'date': mapping['inspection_date'],
        'results': results,
        'select_cols': all_columns,
        'editable_cols': editable,
        'actual_table': source['table_name'],
        'display_config': {column: {'select_columns': display}},
        'query_config': {column: display},
        'query_retailer': SEM_RETAILER,
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': source['date_column'],
        'readonly': False,
        **mapping,
    }


def append_format_stats(cursor, target_date, validation):
    total_issues = 0
    for product_line, source in SEM_SOURCE_CONFIG.items():
        rows, mapping = _latest_rows(cursor, target_date, source)
        issue_count = sum(len(evaluate_format(row, product_line)) for row in rows)
        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_checked': len(rows),
            'total_issues': issue_count,
            'status': 'OK' if issue_count == 0 else 'CRITICAL',
            'retailers': [{
                'retailer': SEM_RETAILER,
                'total': len(rows),
                'issue_count': issue_count,
                'status': 'OK' if issue_count == 0 else 'CRITICAL',
            }],
            **mapping,
        })
        total_issues += issue_count
    return total_issues


def format_detail(cursor, target_date, table, days=1):
    product_line = product_line_for(table)
    source = SEM_SOURCE_CONFIG.get(product_line)
    if not source:
        return {'results': [], 'column_names': [], 'actual_table': ''}
    rows, mapping = _latest_rows(cursor, target_date, source)
    target_records = [_serialize(row, product_line) for row in rows]
    target_records = [row for row in target_records if row['error_fields']]
    field_counts = defaultdict(int)
    for row in target_records:
        for field in row['error_fields']:
            field_counts[field] += 1

    history_days = min(max(int(days or 1), 1), 30)
    records = target_records
    if history_days > 1 and target_records:
        items = sorted({
            str(row.get('item')) for row in target_records
            if not _missing(row.get('item'))
        })
        source_date = datetime.strptime(
            mapping['source_date'], '%Y-%m-%d'
        ).date()
        history_rows = _history_rows(
            cursor,
            source,
            source_date - timedelta(days=history_days - 1),
            source_date,
            items,
        )
        if history_rows:
            records = [_serialize(row, product_line) for row in history_rows]
    columns = list(dict.fromkeys((
        'id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name',
        *source['extra_format_columns'], 'final_sku_price',
        'original_sku_price', 'star_rating', 'count_of_star_ratings',
        'count_of_reviews', 'calendar_week', 'product_url',
    )))
    editable = list(get_sem_editable_columns(product_line))
    return {
        'date': mapping['inspection_date'],
        'table': source['section_code'],
        'retailer': SEM_RETAILER,
        'column_names': columns,
        'select_cols': list(get_sem_table_columns(product_line)),
        'editable_cols': editable,
        'actual_table': source['table_name'],
        'normal_reviews': {},
        'results': records,
        'field_counts': dict(field_counts),
        'total_format_count': sum(field_counts.values()),
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': source['date_column'],
        'readonly': False,
        **mapping,
    }


def _duplicate_groups(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row.get('item') or '').strip()].append(row)
    return [
        {
            'duplicate_type': 'item 중복',
            'item': item,
            'retailer_sku_name': ', '.join(sorted({
                str(row.get('retailer_sku_name') or '') for row in records
            })),
            'dup_count': len(records),
            'reason': f'최신 배치에 동일 item이 {len(records)}건 수집됨',
            'records': records,
        }
        for item, records in grouped.items()
        if item and len(records) > 1
    ]


def append_duplicate_stats(cursor, target_date, validation):
    total_issues = 0
    for _product_line, source in SEM_SOURCE_CONFIG.items():
        rows, mapping = _latest_rows(cursor, target_date, source)
        groups = _duplicate_groups(rows)
        validation['tables'].append({
            'table': source['section_code'],
            'table_name': source['display_name'],
            'total_records': len(rows),
            'total_issues': len(groups),
            'duplicate_groups': len(groups),
            'duplicate_keys': ['item'],
            'status': 'OK' if not groups else 'CRITICAL',
            'retailers': [{
                'retailer': SEM_RETAILER,
                'total': len(rows),
                'duplicate_groups': len(groups),
                'duplicate_keys': ['item'],
                'status': 'OK' if not groups else 'CRITICAL',
            }],
            **mapping,
        })
        total_issues += len(groups)
    return total_issues


def duplicate_detail(cursor, target_date, table, page=1, page_size=50):
    product_line = product_line_for(table)
    source = SEM_SOURCE_CONFIG.get(product_line)
    if not source:
        return {'results': {'duplicates': [], 'total_groups': 0}}
    rows, mapping = _latest_rows(cursor, target_date, source)
    groups = _duplicate_groups(rows)
    start = (page - 1) * page_size
    total_pages = (len(groups) + page_size - 1) // page_size if groups else 0
    editable = list(get_sem_editable_columns(product_line))
    return {
        'date': mapping['inspection_date'],
        'table': source['section_code'],
        'retailer': SEM_RETAILER,
        'select_cols': {
            'group': ['duplicate_type', 'item', 'retailer_sku_name', 'dup_count', 'reason'],
            'record': ['id', 'sku', 'retailer_sku_name', 'final_sku_price', 'crawl_datetime', 'product_url'],
        },
        'editable_cols': editable,
        'actual_table': source['table_name'],
        'readonly': False,
        'results': {
            'duplicates': groups[start:start + page_size],
            'total_groups': len(groups),
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
        },
        **mapping,
    }
