"""SEUK NULL checks for the original same-day date and latest daily batch."""

from collections.abc import Mapping
from datetime import date, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.dryer_onboarding import config as onboarding_config, is_preview, OPERATIONAL_FROM
from apps.common.null_review_evidence import uses_new_policy
from apps.common.retail_price import PRICE_EDITABLE_COLUMNS
from apps.common.seuk_retail import (
    SEUK_COUNTRY, SEUK_SOURCE_CONFIG as COMMON_SOURCES, enabled, latest_scope,
    retailer_start_date as common_start_date, normalize_retailer, product_line_for,
)
from apps.dx.dx_layer1.seuk_retail.sources import TV_START, TV_RETAILERS
from apps.dx.dx_layer2.null_review_state import add_review_totals, review_state


_REVIEW_COLUMNS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
_AMAZON_NULL_COLUMNS = (
    'item', 'screen_size', 'final_sku_price', 'retailer_sku_name', 'star_rating',
    'count_of_star_ratings', 'country', 'account_name', 'product_url',
)
SEUK_SOURCE_CONFIG = {
    **COMMON_SOURCES,
    'seuk_tv': {**COMMON_SOURCES['seuk_tv'],
                'retailers': (*COMMON_SOURCES['seuk_tv']['retailers'], *TV_RETAILERS)},
}


def retailer_start_date(source, retailer):
    retailer = normalize_retailer(source, retailer)
    if source['source_key'] == 'seuk_tv' and retailer in TV_RETAILERS:
        return TV_START
    return common_start_date(source, retailer)


def get_seuk_null_columns(value, retailer=None):
    key = product_line_for(value)
    if key is None:
        raise ValueError('Unsupported SEUK source')
    source = SEUK_SOURCE_CONFIG[key]
    if retailer is not None:
        retailer = normalize_retailer(source, retailer)
        if source['source_key'] == 'seuk_tv' and retailer == 'Amazon':
            return _AMAZON_NULL_COLUMNS
    return source['required_columns']


def missing(value):
    return value is None or str(value).strip() == ''


def _mapping(target_date, source):
    return resolve_monitoring_date(target_date, 'SEUK', source['source_key'])


def detail_columns(column):
    identity_columns = (('item', 'retailer_sku_name', 'sku') if column == 'sku'
                        else ('item', 'sku', 'retailer_sku_name'))
    return list(dict.fromkeys((
        'id', 'crawl_datetime', *identity_columns,
        *(_REVIEW_COLUMNS if column in _REVIEW_COLUMNS else (column,)),
        'product_url',
    )))


def _scope(source, start_date, end_date, retailer=None):
    retailer = normalize_retailer(source, retailer or 'Currys')
    start_date = max(str(start_date), str(retailer_start_date(source, retailer)))
    cte, scope, params = latest_scope(source, start_date, end_date, retailer)
    if source['source_key'] == 'seuk_tv' and retailer == 'Amazon':
        scope += ' AND source.is_redirect IS NOT TRUE'
    return cte, scope, params


def _rows(cursor):
    columns = [entry[0] for entry in cursor.description]
    return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row))
            for row in cursor.fetchall()]


def latest_rows(cursor, target_date, source, retailer):
    mapping = _mapping(target_date, source)
    cte, scope, params = _scope(source, mapping['source_date'], mapping['source_date'], retailer)
    columns = ', '.join('source.' + col for col in source['columns'])
    cursor.execute(f'{cte} SELECT {columns} {scope} ORDER BY source.id', params)
    return _rows(cursor), mapping


def _history_rows(cursor, source, retailer, start_date, end_date, items):
    if not items:
        return []
    cte, scope, params = _scope(source, start_date, end_date, retailer)
    placeholders = ', '.join(['%s'] * len(items))
    columns = ', '.join('source.' + col for col in source['columns'])
    cursor.execute(f"""{cte} SELECT {columns} {scope}
        AND source.item IN ({placeholders})
        ORDER BY source.item, source.{source['date_column']}, source.id
    """, [*params, *items])
    return _rows(cursor)


def _detail_query(cursor, source, retailer, start, end, rows):
    cte, scope, params = _scope(source, start, end, retailer)
    ids = [row['id'] for row in rows]
    return cursor.mogrify(f"""{cte}
        SELECT source.* {scope}
        AND source.id = ANY(%s)
        ORDER BY source.item, source.{source['date_column']}, source.id;""",
                          [*params, ids]).decode('utf-8')


def select_record(cursor, target_date, product_line, record_id, column, *, for_edit=False, format_columns=None):
    allowed = tuple(format_columns) if format_columns is not None else get_seuk_null_columns(product_line)
    if (column not in allowed
            and not (for_edit and column in PRICE_EDITABLE_COLUMNS)):
        raise ValueError('Unsupported SEUK validation column')
    source = SEUK_SOURCE_CONFIG[product_line]
    mapping = _mapping(target_date, source)
    day = mapping['source_date']
    if format_columns is not None:
        cte, scope, params = _scope(COMMON_SOURCES[product_line], day, day)
    elif product_line == 'seuk_tv':
        retailers = tuple(name for name in source['retailers']
                          if day >= str(retailer_start_date(source, name))
                          and (column in get_seuk_null_columns(product_line, name)
                               or (for_edit and column in PRICE_EDITABLE_COLUMNS)))
        if not retailers:
            return None
        if len(retailers) == 1:
            cte, scope, params = _scope(source, day, day, retailers[0])
        else:
            cte, scope, params = latest_scope({**source, 'retailers': retailers}, day, day, None)
            if 'Amazon' in retailers:
                scope += " AND (LOWER(BTRIM(source.account_name)) <> 'amazon' OR source.is_redirect IS NOT TRUE)"
    elif len(source['retailers']) > 1:
        cte, scope, params = latest_scope(source, day, day, None)
    else:
        cte, scope, params = _scope(source, day, day)
    # Lock the same current row that will be edited or manually confirmed.
    cursor.execute(f"""{cte}
        SELECT source.{column}, source.account_name, source.item, source.batch_id
        {scope} AND source.id = %s FOR UPDATE OF source
    """, [*params, record_id])
    row = cursor.fetchone()
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


def append_null_stats(cursor, target_date, validation, category=None, review_filter=None):
    total = 0
    for product_line, source in SEUK_SOURCE_CONFIG.items():
        if not enabled(target_date):
            continue
        if category and category != source['section_code']:
            continue
        if review_filter is not None and not review_filter(source['table_name']):
            continue
        normal_reviews = _load_normal_reviews(cursor, target_date, source)
        retailers = []
        for retailer in source['retailers']:
            if review_filter is not None and not review_filter(source['table_name'], retailer):
                continue
            if str(target_date) < str(retailer_start_date(source, retailer)):
                continue
            rows, mapping = latest_rows(cursor, target_date, source, retailer)
            fields = list(get_seuk_null_columns(product_line, retailer))
            reviews = normal_reviews
            review_stats = {}
            if uses_new_policy(target_date, SEUK_COUNTRY):
                reviews, review_stats, auto_logs = review_state(
                    cursor, target_date, rows, fields, normal_reviews,
                    table_name=source['table_name'], country=SEUK_COUNTRY,
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
            new_tv_empty = retailer in TV_RETAILERS and not rows
            retailers.append({
                'retailer': retailer, 'total': len(rows), 'total_null_count': count,
                'fields_detail': counts, 'status': ('PENDING' if new_tv_empty or (retailer == 'AO' and not rows)
                                                   else 'CRITICAL' if count else 'OK'),
                **({'validation_label': '검증할 데이터 없음'} if new_tv_empty else {}),
                **mapping, **review_stats,
            })
        count = sum(retailer['total_null_count'] for retailer in retailers)
        table_stats = {
            'table': source['section_code'], 'table_name': source['display_name'],
            'total_records': sum(retailer['total'] for retailer in retailers),
            'total_issues': count, 'status': 'CRITICAL' if count else 'OK',
            'fields': list(get_seuk_null_columns(product_line)), 'retailers': retailers,
            **_mapping(target_date, source),
        }
        add_review_totals(table_stats, retailers)
        validation['tables'].append(table_stats)
        total += count
    return total


def null_detail(cursor, target_date, table, retailer, column, days=3):
    product_line = product_line_for(table)
    if product_line is None or retailer is None:
        return {'results': [], 'display_config': {}, 'query_config': {}}
    allowed = get_seuk_null_columns(product_line, retailer)
    if column not in allowed:
        return {'results': [], 'display_config': {}, 'query_config': {}}
    source = SEUK_SOURCE_CONFIG[product_line]
    canonical_retailer = normalize_retailer(source, retailer)
    rows, mapping = latest_rows(cursor, target_date, source, canonical_retailer)
    normal_reviews = _load_normal_reviews(cursor, target_date, source)
    review_stats = {}
    if uses_new_policy(target_date, SEUK_COUNTRY):
        normal_reviews, review_stats, _auto_logs = review_state(
            cursor, target_date, rows, [column], normal_reviews,
            table_name=source['table_name'], country=SEUK_COUNTRY,
            product_line=product_line, retailer=canonical_retailer,
            is_null=lambda value, _field: missing(value),
        )
    targets = [row for row in rows if missing(row.get(column))]
    days = min(30, max(1, int(days or 3)))
    source_day = date.fromisoformat(mapping['source_date'])
    start_day = source_day - timedelta(days=days - 1)
    history = []
    if days > 1 and targets:
        items = sorted({str(row['item']) for row in targets if not missing(row.get('item'))})
        history = _history_rows(cursor, source, canonical_retailer,
                                start_day, source_day, items)
    # History includes the selected source date so normal and NULL rows for the
    # target items are both visible. Keep current findings with a missing item,
    # which cannot be selected by the item-based history query.
    result_rows = list(history) if history else list(targets)
    result_ids = {row.get('id') for row in result_rows}
    result_rows.extend(row for row in targets if row.get('id') not in result_ids)
    results = [{**row, 'null_fields': [col for col in allowed if missing(row.get(col))]}
               for row in result_rows]
    display = detail_columns(column)
    query = (_detail_query(cursor, source, canonical_retailer, start_day, source_day, results)
             if product_line == 'seuk_tv' and canonical_retailer in TV_RETAILERS and results else '')
    return {
        'date': mapping['inspection_date'], 'results': results,
        'select_cols': list(source['columns']),
        'editable_cols': list(allowed), 'actual_table': source['table_name'],
        'display_config': {column: {'select_columns': display}},
        'query_config': {column: display}, 'query_retailer': canonical_retailer,
        **({'query_sql': query} if query else {}),
        'normal_reviews': normal_reviews, **review_stats,
        'supports_day_history': True, 'history_days': days,
        'date_column': source['date_column'], 'readonly': False,
        'active_from': str(OPERATIONAL_FROM if onboarding_config('SEUK', product_line, canonical_retailer)
                           else retailer_start_date(source, canonical_retailer)),
        'preview_mode': is_preview('SEUK', product_line, canonical_retailer, target_date),
        **mapping,
    }
