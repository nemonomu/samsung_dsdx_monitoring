"""SEIB NULL checks for the original same-day date and latest daily batch."""

from collections.abc import Mapping
from datetime import date, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.null_review_evidence import uses_new_policy
from apps.common.retail_price import PRICE_EDITABLE_COLUMNS
from apps.common.seib_retail import (
    SEIB_COUNTRY, SEIB_SOURCE_CONFIG, enabled, latest_scope,
    get_seib_null_columns,
    get_seib_null_select_columns, product_line_for, seib_retailer_key,
)
from apps.dx.dx_layer2.null_review_state import add_review_totals, review_state


_REVIEW_COLUMNS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')


def missing(value):
    return value is None or str(value).strip() == ''


def _mapping(target_date, source):
    return resolve_monitoring_date(target_date, 'SEIB', source['source_key'])


def detail_columns(column):
    identity_columns = (('item', 'retailer_sku_name', 'sku') if column == 'sku'
                        else ('item', 'sku', 'retailer_sku_name'))
    return list(dict.fromkeys((
        'id', 'crawl_datetime', *identity_columns,
        *(_REVIEW_COLUMNS if column in _REVIEW_COLUMNS else (column,)),
        'product_url',
    )))


def _scope(source, start_date, end_date, retailer=None):
    return latest_scope(source, start_date, end_date, retailer or 'MediaMarkt')


def _rows(cursor):
    columns = [entry[0] for entry in cursor.description]
    return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row))
            for row in cursor.fetchall()]


def latest_rows(cursor, target_date, source, retailer):
    mapping = _mapping(target_date, source)
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'], retailer)
    columns = ', '.join('source.' + col for col in get_seib_null_select_columns(source['source_key']))
    cursor.execute(f'{cte} SELECT {columns} {scope} ORDER BY source.id', params)
    return _rows(cursor), mapping


def _history_rows(cursor, source, retailer, start_date, end_date, items):
    if not items:
        return []
    cte, scope, params = _scope(source, start_date, end_date, retailer)
    placeholders = ', '.join(['%s'] * len(items))
    columns = ', '.join('source.' + col for col in get_seib_null_select_columns(source['source_key']))
    cursor.execute(f"""{cte} SELECT {columns} {scope}
        AND source.item IN ({placeholders})
        ORDER BY source.item, source.{source['date_column']}, source.id
    """, [*params, *items])
    return _rows(cursor)


def select_record(cursor, target_date, product_line, record_id, column, *, for_edit=False,
                  format_columns=None):
    allowed = tuple(format_columns) if format_columns is not None else get_seib_null_columns(product_line)
    if (column not in allowed
            and not (for_edit and column in PRICE_EDITABLE_COLUMNS)):
        raise ValueError('Unsupported SEIB validation column')
    source = SEIB_SOURCE_CONFIG[product_line]
    mapping = _mapping(target_date, source)
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'])
    # Lock the same current row that will be edited or manually confirmed.
    cursor.execute(f"""{cte}
        SELECT source.{column}, source.account_name, source.item, source.batch_id
        {scope} AND source.id = %s FOR UPDATE OF source
    """, [*params, record_id])
    row = cursor.fetchone()
    if (row and column not in allowed
            and not (for_edit and column in PRICE_EDITABLE_COLUMNS)):
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


def append_null_stats(cursor, target_date, validation, category=None):
    total = 0
    for product_line, source in SEIB_SOURCE_CONFIG.items():
        if not enabled(target_date):
            continue
        if category and category != source['section_code']:
            continue
        normal_reviews = _load_normal_reviews(cursor, target_date, source)
        retailers = []
        for retailer in source['retailers']:
            rows, mapping = latest_rows(cursor, target_date, source, retailer)
            fields = list(get_seib_null_columns(product_line, retailer))
            reviews = normal_reviews
            review_stats = {}
            if uses_new_policy(target_date, SEIB_COUNTRY):
                reviews, review_stats, auto_logs = review_state(
                    cursor, target_date, rows, fields, normal_reviews,
                    table_name=source['table_name'], country=SEIB_COUNTRY,
                    product_line=product_line, retailer=retailer,
                    is_null=lambda value, _field: missing(value),
                )
                validation.setdefault('auto_null_reviews', []).extend(auto_logs)
            counts = {
                column: sum(missing(row.get(column)) and f"{row['id']}_{column}" not in reviews
                            for row in rows)
                for column in fields
            }
            count = sum(counts.values())
            retailers.append({
                'retailer': retailer, 'total': len(rows), 'total_null_count': count,
                'fields_detail': counts, 'status': 'CRITICAL' if count else 'OK',
                **mapping, **review_stats,
            })
        count = sum(retailer['total_null_count'] for retailer in retailers)
        table_stats = {
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(retailer['total'] for retailer in retailers),
            'total_issues': count, 'status': 'CRITICAL' if count else 'OK',
            'fields': list(get_seib_null_columns(product_line)), 'retailers': retailers,
            **_mapping(target_date, source),
        }
        add_review_totals(table_stats, retailers)
        validation['tables'].append(table_stats)
        total += count
    return total


def null_detail(cursor, target_date, table, retailer, column, days=3):
    product_line = product_line_for(table)
    if product_line is None:
        return {'results': [], 'display_config': {}, 'query_config': {}}
    allowed = get_seib_null_columns(product_line, retailer)
    if product_line is None or retailer is None or column not in allowed:
        return {'results': [], 'display_config': {}, 'query_config': {}}
    source = SEIB_SOURCE_CONFIG[product_line]
    canonical_retailer = next(name for name in source['retailers']
                              if seib_retailer_key(name) == seib_retailer_key(retailer))
    rows, mapping = latest_rows(cursor, target_date, source, canonical_retailer)
    normal_reviews = _load_normal_reviews(cursor, target_date, source)
    review_stats = {}
    if uses_new_policy(target_date, SEIB_COUNTRY):
        normal_reviews, review_stats, _auto_logs = review_state(
            cursor, target_date, rows, [column], normal_reviews,
            table_name=source['table_name'], country=SEIB_COUNTRY,
            product_line=product_line, retailer=canonical_retailer,
            is_null=lambda value, _field: missing(value),
        )
    targets = [row for row in rows if missing(row.get(column))]
    days = min(30, max(1, int(days or 3)))
    source_day = date.fromisoformat(mapping['source_date'])
    history = []
    if days > 1 and targets:
        items = sorted({str(row['item']) for row in targets if not missing(row.get('item'))})
        history = _history_rows(cursor, source, canonical_retailer,
                                source_day - timedelta(days=days - 1),
                                source_day, items)
    # History includes the selected source date so normal and NULL rows for the
    # target items are both visible. Keep current findings with a missing item,
    # which cannot be selected by the item-based history query.
    result_rows = list(history) if history else list(targets)
    result_ids = {row.get('id') for row in result_rows}
    result_rows.extend(row for row in targets if row.get('id') not in result_ids)
    results = [{**row, 'null_fields': [col for col in allowed if missing(row.get(col))]}
               for row in result_rows]
    display = detail_columns(column)
    return {
        'date': mapping['inspection_date'], 'results': results,
        'select_cols': list(get_seib_null_select_columns(product_line)),
        'editable_cols': list(allowed), 'actual_table': source['table_name'],
        'display_config': {column: {'select_columns': display}},
        'query_config': {column: display}, 'query_retailer': canonical_retailer,
        'normal_reviews': normal_reviews, **review_stats,
        'supports_day_history': True, 'history_days': days,
        'date_column': source['date_column'], 'readonly': False,
        **mapping,
    }
