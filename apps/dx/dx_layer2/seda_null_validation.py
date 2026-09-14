"""SEDA NULL checks for the exact D-1 day and each latest MAIN batch."""

from collections.abc import Mapping
from datetime import date, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seda_retail import (
    SEDA_SOURCE_CONFIG, get_seda_null_columns,
    get_seda_null_select_columns, get_seda_product_line, seda_retailer_key,
)


product_line_for = get_seda_product_line
_REVIEW_COLUMNS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')


def missing(value):
    return value is None or str(value).strip() == ''


def _mapping(target_date, source):
    return resolve_monitoring_date(target_date, 'SEDA', source['source_key'])


def detail_columns(column):
    return list(dict.fromkeys((
        'id', 'crawl_strdatetime', 'item', 'sku', 'retailer_sku_name',
        *(_REVIEW_COLUMNS if column in _REVIEW_COLUMNS else (column,)),
        'product_url',
    )))


def _scope(source, start_date, end_date, retailer=None):
    """Use the Layer 1 MAIN anchor policy, including null batch IDs and aliases."""
    keys = [seda_retailer_key(retailer)] if retailer is not None else list(source['retailer_keys'])
    if any(key not in source['retailer_keys'] for key in keys):
        raise ValueError('Unsupported SEDA retailer')
    placeholders = ', '.join(['%s'] * len(keys))
    table = source['table_name']
    day = f"LEFT(BTRIM(anchor.{source['date_column']}), 10)"
    return f"""
        WITH ranked_main AS (
            SELECT anchor.batch_id, {day} AS source_date,
                   LOWER(REPLACE(BTRIM(anchor.account_name), ' ', '')) AS retailer_key,
                   ROW_NUMBER() OVER (
                       PARTITION BY {day}, LOWER(REPLACE(BTRIM(anchor.account_name), ' ', ''))
                       ORDER BY anchor.id DESC
                   ) AS batch_rank
            FROM {table} anchor
            WHERE {day} BETWEEN %s AND %s
              AND LOWER(REPLACE(BTRIM(anchor.account_name), ' ', '')) IN ({placeholders})
              AND LOWER(BTRIM(anchor.page_type)) = 'main'
        )
    """, f"""
        FROM {table} source
        JOIN ranked_main latest
          ON latest.batch_rank = 1
         AND LEFT(BTRIM(source.{source['date_column']}), 10) = latest.source_date
         AND LOWER(REPLACE(BTRIM(source.account_name), ' ', '')) = latest.retailer_key
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(source.page_type)) IN ('main', 'bsr')
    """, [str(start_date), str(end_date), *keys]


def _rows(cursor):
    columns = [entry[0] for entry in cursor.description]
    return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row))
            for row in cursor.fetchall()]


def latest_rows(cursor, target_date, source, retailer):
    mapping = _mapping(target_date, source)
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'], retailer)
    columns = ', '.join('source.' + col for col in get_seda_null_select_columns(source['source_key']))
    cursor.execute(f'{cte} SELECT {columns} {scope} ORDER BY source.id', params)
    return _rows(cursor), mapping


def _history_rows(cursor, source, retailer, start_date, end_date, items):
    if not items:
        return []
    cte, scope, params = _scope(source, start_date, end_date, retailer)
    placeholders = ', '.join(['%s'] * len(items))
    columns = ', '.join('source.' + col for col in get_seda_null_select_columns(source['source_key']))
    cursor.execute(f"""{cte} SELECT {columns} {scope}
        AND source.item IN ({placeholders})
        ORDER BY source.item, source.{source['date_column']}, source.id
    """, [*params, *items])
    return _rows(cursor)


def select_record(cursor, target_date, product_line, record_id, column, *, for_edit=False):
    if column not in get_seda_null_columns(product_line):
        raise ValueError('Unsupported SEDA NULL column')
    source = SEDA_SOURCE_CONFIG[product_line]
    mapping = _mapping(target_date, source)
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'])
    # Lock the same current row that will be edited or manually confirmed.
    cursor.execute(f"""{cte}
        SELECT source.{column}, source.account_name, source.item, source.batch_id
        {scope} AND source.id = %s FOR UPDATE OF source
    """, [*params, record_id])
    row = cursor.fetchone()
    if row and column not in get_seda_null_columns(product_line, row[1]):
        return None
    return row if for_edit else row[:3] if row else None


def _load_normal_reviews(cursor, target_date, source):
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s
          AND correction_type = 'null_check' AND status = 'normal'
    """, (source['table_name'], str(target_date)))
    return {
        f'{row[0]}_{row[1]}': {
            'memo': row[2], 'created_id': row[3],
            'created_at': row[4].isoformat() if hasattr(row[4], 'isoformat') else str(row[4] or ''),
            'reason': row[5],
        }
        for row in cursor.fetchall()
    }


def append_null_stats(cursor, target_date, validation):
    total = 0
    for product_line, source in SEDA_SOURCE_CONFIG.items():
        reviews = _load_normal_reviews(cursor, target_date, source)
        retailers = []
        for retailer in source['retailers']:
            rows, mapping = latest_rows(cursor, target_date, source, retailer)
            counts = {
                column: sum(missing(row.get(column)) and f"{row['id']}_{column}" not in reviews
                            for row in rows)
                for column in get_seda_null_columns(product_line, retailer)
            }
            count = sum(counts.values())
            retailers.append({
                'retailer': retailer, 'total': len(rows), 'total_null_count': count,
                'fields_detail': counts, 'status': 'CRITICAL' if count else 'OK',
                **mapping,
            })
        count = sum(retailer['total_null_count'] for retailer in retailers)
        validation['tables'].append({
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(retailer['total'] for retailer in retailers),
            'total_issues': count, 'status': 'CRITICAL' if count else 'OK',
            'fields': list(get_seda_null_columns(product_line)), 'retailers': retailers,
            **_mapping(target_date, source),
        })
        total += count
    return total


def null_detail(cursor, target_date, table, retailer, column, days=3):
    product_line = product_line_for(table)
    allowed = get_seda_null_columns(product_line, retailer)
    if product_line is None or retailer is None or column not in allowed:
        return {'results': [], 'display_config': {}, 'query_config': {}}
    source = SEDA_SOURCE_CONFIG[product_line]
    canonical_retailer = next(name for name in source['retailers']
                              if seda_retailer_key(name) == seda_retailer_key(retailer))
    rows, mapping = latest_rows(cursor, target_date, source, canonical_retailer)
    targets = [row for row in rows if missing(row.get(column))]
    days = min(30, max(1, int(days or 3)))
    source_day = date.fromisoformat(mapping['source_date'])
    history = []
    if days > 1 and targets:
        items = sorted({str(row['item']) for row in targets if not missing(row.get('item'))})
        history = _history_rows(cursor, source, canonical_retailer,
                                source_day - timedelta(days=days - 1),
                                source_day - timedelta(days=1), items)
    # Always retain today's findings, even when no comparison rows exist.
    results = [{**row, 'null_fields': [col for col in allowed if missing(row.get(col))]}
               for row in [*history, *targets]]
    display = detail_columns(column)
    return {
        'date': mapping['inspection_date'], 'results': results,
        'select_cols': list(get_seda_null_select_columns(product_line)),
        'editable_cols': list(allowed), 'actual_table': source['table_name'],
        'display_config': {column: {'select_columns': display}},
        'query_config': {column: display}, 'query_retailer': canonical_retailer,
        'normal_reviews': _load_normal_reviews(cursor, target_date, source),
        'supports_day_history': True, 'history_days': days,
        'date_column': source['date_column'], 'readonly': False,
        **mapping,
    }
