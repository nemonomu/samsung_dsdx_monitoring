"""Layer 2 NULL validation for SEG Germany retail sources."""

from datetime import datetime, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seg_retail import (
    SEG_COUNTRY,
    SEG_SOURCE_CONFIG,
    get_seg_all_null_columns,
    get_seg_null_columns,
    get_seg_product_line,
    get_seg_table_columns,
)


_REVIEW_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)


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


def get_review_allowed_columns(product_line, retailer):
    return get_seg_null_columns(product_line, retailer)


def fetch_review_record(cursor, target_date, product_line, record_id, column):
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
    if row and column not in get_seg_null_columns(product_line, row[1]):
        return None
    return row
