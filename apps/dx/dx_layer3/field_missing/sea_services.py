"""SEA REF/LDY field-missing validation.

The source scope follows the unified SEA contract: inspection date D-1 and,
for each source date/retailer, only the newest MAIN anchor batch plus rows from
that same MAIN/BSR batch.
"""

from datetime import timedelta
import re

from apps.common.sea_retail import get_sea_retail_source


SEA_FIELD_MISSING_COLUMNS = {
    'sea_ref': (
        'ref_capacity',
        'ref_refrigerator_type',
        'sku',
        'recommendation_intent',
    ),
    'sea_ldy': (
        'ldy_capacity',
        'ldy_loading_type',
        'sku',
    ),
}

SEA_FIELD_MISSING_RELATED_COLUMNS = {
    'recommendation_intent': (
        'detailed_review_content',
        'count_of_reviews',
        'count_of_star_ratings',
    ),
}

_PRODUCT_ALIASES = {
    'ref': 'sea_ref',
    'sea_ref': 'sea_ref',
    'ldy': 'sea_ldy',
    'sea_ldy': 'sea_ldy',
}

_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def normalize_product_line(product_line):
    key = str(product_line or '').strip().lower()
    canonical = _PRODUCT_ALIASES.get(key)
    if canonical is None:
        raise ValueError(f'허용되지 않은 SEA 필드 누락 제품군: {product_line}')
    return canonical


def is_sea_product_line(product_line):
    return str(product_line or '').strip().lower() in _PRODUCT_ALIASES


def get_validation_columns(product_line):
    if not is_sea_product_line(product_line):
        return []
    return list(SEA_FIELD_MISSING_COLUMNS[normalize_product_line(product_line)])


def get_default_related_columns(product_line, field):
    if not is_sea_product_line(product_line):
        return []
    return list(SEA_FIELD_MISSING_RELATED_COLUMNS.get(field, ()))


def get_retailers(product_line):
    key = normalize_product_line(product_line)
    return list(get_sea_retail_source(key)['retailers'])


def get_source_key(product_line):
    return _source(product_line)['source_key']


def _source(product_line):
    return get_sea_retail_source(normalize_product_line(product_line))


def _has_value(value):
    return value is not None and str(value).strip() != ''


def _safe_columns(columns):
    result = []
    for column in columns or []:
        name = str(column or '').strip()
        if (
            name
            and name not in result
            and name != 'batch_id'
            and _IDENTIFIER_RE.fullmatch(name)
        ):
            result.append(name)
    return result


def _rows_as_dicts(cursor):
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _source_date(row, date_column):
    return str(row.get(date_column) or '').strip()[:10]


def _retailer_name(value):
    text = str(value or '').strip()
    for expected in ('Bestbuy', 'Lowes'):
        if text.casefold() == expected.casefold():
            return expected
    return text


def _load_latest_rows(
        cursor, start_date, end_date, product_line, retailer, columns):
    """Load newest MAIN-anchor rows for every source day in the range."""
    source = _source(product_line)
    table_name = source['table_name']
    date_column = source['date_column']
    selected = _safe_columns(columns)
    base_columns = ['id', 'account_name', 'page_type', 'item', date_column]
    selected = [column for column in selected if column not in base_columns]
    if 'product_url' not in selected:
        selected.append('product_url')
    select_sql = ',\n               '.join(
        [f'source.{column}' for column in base_columns + selected]
    )

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
              AND LOWER(TRIM(account_name)) = LOWER(TRIM(%s))
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
        SELECT {select_sql}
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
          AND LOWER(TRIM(source.account_name)) = LOWER(TRIM(%s))
          AND UPPER(TRIM(COALESCE(source.page_type, '')))
              IN ('MAIN', 'BSR')
        ORDER BY source.item, source.{date_column}, source.id
    """, (
        str(start_date), str(end_date), retailer,
        str(start_date), str(end_date), retailer,
    ))
    rows = _rows_as_dicts(cursor)
    for row in rows:
        row['account_name'] = _retailer_name(row.get('account_name'))
    return rows


def _item_groups(rows):
    groups = {}
    for row in rows:
        retailer = _retailer_name(row.get('account_name'))
        item = row.get('item')
        if not retailer or item is None or str(item).strip() == '':
            continue
        groups.setdefault((retailer.casefold(), str(item)), []).append(row)
    return groups


def _classify_missing(rows, target_date, columns, date_column):
    """Classify existing-item gaps and first-seen NULL items by field."""
    target_text = str(target_date)
    stats = {
        column: {
            'prev_count': 0,
            'missing_count': 0,
            'today_null_rows': 0,
            'new_count': 0,
            'existing_count': 0,
            'findings': [],
        }
        for column in columns
    }

    for (_retailer_key, item), item_rows in _item_groups(rows).items():
        target_rows = [
            row for row in item_rows
            if _source_date(row, date_column) == target_text
        ]
        if not target_rows:
            continue
        previous_rows = [
            row for row in item_rows
            if _source_date(row, date_column) != target_text
        ]
        is_new = not previous_rows

        for column in columns:
            previous_has_value = any(
                _has_value(row.get(column)) for row in previous_rows
            )
            if previous_has_value:
                stats[column]['prev_count'] += 1

            null_target_rows = [
                row for row in target_rows if not _has_value(row.get(column))
            ]
            if not null_target_rows or not (is_new or previous_has_value):
                continue

            finding_type = 'new' if is_new else 'missing'
            stats[column]['missing_count'] += 1
            stats[column]['today_null_rows'] += len(null_target_rows)
            stats[column][
                'new_count' if is_new else 'existing_count'
            ] += 1
            stats[column]['findings'].append({
                'item': item,
                'retailer': _retailer_name(target_rows[0].get('account_name')),
                'finding_type': finding_type,
                'rows': item_rows,
                'target_rows': target_rows,
            })
    return stats


def _empty_summary(target_date, product_line, retailer):
    source = _source(product_line)
    return {
        'date': str(target_date),
        'product_line': source['category'],
        'retailer': retailer,
        'prev_dates': [
            str(target_date - timedelta(days=1)),
            str(target_date - timedelta(days=2)),
        ],
        'summary': {
            'total_missing_cases': 0,
            'fields_with_issues': 0,
            'status': 'OK',
        },
        'missing_fields': [],
    }


def field_missing_detection(
        cursor, target_date, product_line, retailer, inspection_date=None):
    key = normalize_product_line(product_line)
    source = _source(key)
    columns = get_validation_columns(key)
    result = _empty_summary(target_date, key, retailer)
    retailers = (
        get_retailers(key) if str(retailer).lower() == 'all' else [retailer]
    )
    total_missing = 0

    for current_retailer in retailers:
        if current_retailer not in source['retailers']:
            continue
        rows = _load_latest_rows(
            cursor, target_date - timedelta(days=2), target_date,
            key, current_retailer, columns,
        )
        field_stats = _classify_missing(
            rows, target_date, columns, source['date_column']
        )

        try:
            cursor.execute("""
                SELECT column_name, COUNT(DISTINCT item)
                FROM monitoring_corrections
                WHERE layer = 3 AND correction_type = 'field_missing'
                  AND table_name = %s AND crawl_date = %s
                  AND retailer = %s AND status = 'normal'
                GROUP BY column_name
            """, (
                source['table_name'], str(inspection_date or target_date),
                current_retailer,
            ))
            for column, count in cursor.fetchall():
                if column in field_stats:
                    field_stats[column]['missing_count'] = max(
                        0, field_stats[column]['missing_count'] - count
                    )
        except Exception:
            pass

        for column in columns:
            stats = field_stats[column]
            if stats['missing_count'] <= 0:
                continue
            total_missing += stats['missing_count']
            result['missing_fields'].append({
                'retailer': current_retailer,
                'column': column,
                'prev_had_value_items': stats['prev_count'],
                'today_missing_items': stats['missing_count'],
                'today_null_rows': stats['today_null_rows'],
                'new_items': stats['new_count'],
                'existing_missing_items': stats['existing_count'],
                'missing_rate': (
                    round(
                        stats['existing_count'] / stats['prev_count'] * 100,
                        2,
                    ) if stats['prev_count'] > 0 else 0
                ),
            })

    result['summary'] = {
        'total_missing_cases': total_missing,
        'fields_with_issues': len(result['missing_fields']),
        'status': (
            'OK' if total_missing == 0
            else 'WARNING' if total_missing < 10
            else 'CRITICAL'
        ),
    }
    return result


def field_missing_detail_all(
        cursor, target_date, product_line, retailer, display_fields,
        offset, limit):
    key = normalize_product_line(product_line)
    source = _source(key)
    fields = _safe_columns(display_fields or get_validation_columns(key))
    rows = _load_latest_rows(
        cursor, target_date - timedelta(days=2), target_date,
        key, retailer, fields,
    )
    date_column = source['date_column']
    columns = ['id', date_column, 'item']
    columns.extend(column for column in fields if column not in columns)
    if 'product_url' not in columns:
        columns.append('product_url')
    page_rows = rows[offset:offset + limit]
    data = [
        {column: row.get(column) for column in columns}
        for row in page_rows
    ]
    result = {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [
            str(target_date - timedelta(days=2)),
            str(target_date - timedelta(days=1)),
        ],
        'product_line': source['category'],
        'retailer': retailer,
        'columns': columns,
        'display_fields': fields,
        'offset': offset,
        'limit': limit,
        'fetched_rows': len(data),
        'has_more': offset + len(data) < len(rows),
        'data': data,
        'table_name': source['table_name'],
        'date_column': date_column,
    }
    if offset == 0:
        result['total_count'] = len(rows)
    return result


def _value_on_date(rows, date_column, source_date, field):
    values = [
        row.get(field) for row in rows
        if _source_date(row, date_column) == str(source_date)
        and _has_value(row.get(field))
    ]
    return values[-1] if values else None


def field_missing_detail_problem(
        cursor, target_date, product_line, retailer, columns_to_check,
        offset, limit):
    key = normalize_product_line(product_line)
    source = _source(key)
    columns = [
        column for column in get_validation_columns(key)
        if column in columns_to_check
    ]
    rows = _load_latest_rows(
        cursor, target_date - timedelta(days=2), target_date,
        key, retailer, columns,
    )
    stats = _classify_missing(
        rows, target_date, columns, source['date_column']
    )
    data = []
    for column in columns:
        for finding in stats[column]['findings']:
            data.append({
                'item': finding['item'],
                'account_name': finding['retailer'],
                'field_name': column,
                'd2_value': _value_on_date(
                    finding['rows'], source['date_column'],
                    target_date - timedelta(days=2), column,
                ),
                'd1_value': _value_on_date(
                    finding['rows'], source['date_column'],
                    target_date - timedelta(days=1), column,
                ),
                'today_value': None,
                'today_has_value': False,
                'finding_type': finding['finding_type'],
            })
    data.sort(key=lambda row: (row['field_name'], str(row['item'])))
    total_count = len(data)
    page = data[offset:offset + limit]
    return {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [
            str(target_date - timedelta(days=1)),
            str(target_date - timedelta(days=2)),
        ],
        'product_line': source['category'],
        'retailer': retailer,
        'fields': columns,
        'total_count': total_count,
        'offset': offset,
        'limit': limit,
        'has_more': offset + len(page) < total_count,
        'data': page,
    }


def _normal_reviews(cursor, inspection_date, table_name):
    reviews = {}
    try:
        cursor.execute("""
            SELECT record_id, column_name, reason, memo, created_id
            FROM monitoring_corrections
            WHERE layer = 3 AND correction_type = 'field_missing'
              AND table_name = %s AND crawl_date = %s
              AND status = 'normal'
        """, (table_name, str(inspection_date)))
        for row in cursor.fetchall():
            key = f'{row[0]}_{row[1]}'
            reviews[key] = {
                'reason': row[2] or '',
                'memo': row[3] or '',
                'created_id': row[4] or '',
            }
    except Exception:
        pass
    return reviews


def field_missing_detail_by_field(
        cursor, target_date, product_line, retailer, field, days,
        columns_info, display_fields, related_columns, editable_cols,
        inspection_date=None):
    key = normalize_product_line(product_line)
    source = _source(key)
    validation_columns = get_validation_columns(key)
    if field not in validation_columns:
        return {
            'status': 'success',
            'date': str(target_date),
            'product_line': source['category'],
            'retailer': retailer,
            'field': field,
            'total_count': 0,
            'data': [],
            'normal_reviews': {},
        }

    display_start = target_date - timedelta(days=max(1, days) - 1)
    validation_start = target_date - timedelta(days=2)
    query_start = min(display_start, validation_start)
    fields = _safe_columns(display_fields)
    if field not in fields:
        fields.append(field)
    for related_column in _safe_columns(related_columns):
        if related_column not in fields:
            fields.append(related_column)
    rows = _load_latest_rows(
        cursor, query_start, target_date, key, retailer, fields,
    )
    stats = _classify_missing(
        rows, target_date, [field], source['date_column']
    )[field]
    finding_types = {
        finding['item']: finding['finding_type']
        for finding in stats['findings']
    }

    detail_rows = []
    today_null_count = 0
    for row in rows:
        item_key = str(row.get('item'))
        row_date = _source_date(row, source['date_column'])
        if item_key not in finding_types or row_date < str(display_start):
            continue
        detail = dict(row)
        detail['finding_type'] = finding_types[item_key]
        detail_rows.append(detail)
        if row_date == str(target_date) and not _has_value(row.get(field)):
            today_null_count += 1

    date_column = source['date_column']
    columns = ['id', date_column, 'item']
    default_display = []
    for column in related_columns or [field]:
        if column in fields and column not in default_display:
            default_display.append(column)
    if field not in default_display:
        default_display.insert(0, field)
    columns.extend(column for column in default_display if column not in columns)
    columns.extend(column for column in fields if column not in columns)
    if 'product_url' not in columns:
        columns.append('product_url')

    data = []
    for row in detail_rows:
        detail = {column: row.get(column) for column in columns}
        detail['finding_type'] = row['finding_type']
        data.append(detail)

    return {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [
            str(target_date - timedelta(days=index))
            for index in range(1, max(1, days))
        ],
        'product_line': source['category'],
        'retailer': retailer,
        'field': field,
        'columns': columns,
        'display_fields': [
            column for column in fields
            if column not in ('id', 'item', 'account_name', 'page_type',
                              date_column, 'product_url')
        ],
        'total_rows': len(data),
        'missing_item_count': len(finding_types),
        'today_null_count': today_null_count,
        'new_item_count': sum(
            finding_type == 'new'
            for finding_type in finding_types.values()
        ),
        'data': data,
        'table_name': source['table_name'],
        'date_column': date_column,
        'editable_columns': editable_cols,
        'normal_reviews': _normal_reviews(
            cursor, inspection_date or target_date, source['table_name']
        ),
        'default_columns': (
            ['id', date_column, 'item'] + default_display + ['product_url']
        ),
    }
