"""SEDA D-1 format checks, history and scoped review/edit selection."""
from collections import Counter
from datetime import date, timedelta

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seda_retail import SEDA_SOURCE_CONFIG, display_seda_retailer, get_seda_product_line, seda_retailer_key
from .seda_null_validation import _scope, _rows
from . import seda_format_rules as rules

product_line_for = get_seda_product_line
get_format_columns = rules.columns


def select_columns(product):
    return tuple(dict.fromkeys(('id', 'item', 'sku', 'retailer_sku_name', 'batch_id',
                               'crawl_strdatetime', *rules.columns(product), 'savings')))


def scope(source, start, end, retailer=None):
    cte, where, params = _scope(source, start, end)
    # Keep invalid page/account values visible when a unique MAIN batch anchors
    # them. Never assign an unknown retailer to an ambiguous shared batch.
    account = "LOWER(REPLACE(BTRIM(source.account_name), ' ', ''))"
    where = where.replace(f'{account} = latest.retailer_key', f"""(
        {account} = latest.retailer_key OR (
            COALESCE({account}, '') NOT IN ('magalu', 'casasbahia')
            AND NOT EXISTS (
                SELECT 1 FROM ranked_main other
                WHERE other.batch_rank = 1 AND other.source_date = latest.source_date
                  AND other.batch_id IS NOT DISTINCT FROM latest.batch_id
                  AND other.retailer_key <> latest.retailer_key
            )
        ))""")
    where = where.replace("WHERE LOWER(BTRIM(source.page_type)) IN ('main', 'bsr')", 'WHERE 1 = 1')
    if retailer is not None:
        key = seda_retailer_key(retailer)
        if key not in source['retailer_keys']:
            raise ValueError('Unsupported SEDA retailer')
        where += ' AND latest.retailer_key = %s'
        params.append(key)
    return cte, where, params


def load_rows(cursor, source, start, end, retailer, items=None):
    cte, where, params = scope(source, start, end, retailer)
    if items is not None:
        if not items:
            return []
        where += ' AND source.item IN (' + ', '.join('%s' for _ in items) + ')'
        params.extend(items)
    projection = ', '.join('source.' + col for col in select_columns(source['source_key']))
    cursor.execute(f'{cte} SELECT {projection} {where} ORDER BY source.item, source.crawl_strdatetime, source.id', params)
    return _rows(cursor)


def normal_reviews(cursor, target_date, source):
    cursor.execute('''SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections WHERE table_name = %s AND crawl_date = %s
        AND correction_type = 'format_check' AND status = 'normal' ''',
        (source['table_name'], str(target_date)))
    return {f'{row[0]}_{row[1]}': {'memo': row[2], 'created_id': row[3],
            'created_at': str(row[4]) if row[4] else None, 'reason': row[5]} for row in cursor.fetchall()}


def annotate(row, product, retailer, reviews):
    errors = rules.evaluate(row, product, retailer)
    return {**row, 'error_fields': [field for field in errors if f"{row['id']}_{field}" not in reviews],
            'error_details': {field: {'rule': 'SEDA 형식 검증', 'reason': reason}
                              for field, reason in errors.items()}}


def append_format_stats(cursor, target_date, validation, category=None):
    total = 0
    for product, source in SEDA_SOURCE_CONFIG.items():
        if category and category != source['section_code']:
            continue
        mapping = resolve_monitoring_date(target_date, 'SEDA', product)
        reviews = normal_reviews(cursor, target_date, source)
        retailers = []
        for retailer in source['retailers']:
            rows = load_rows(cursor, source, mapping['source_date'], mapping['source_date'], retailer)
            count = sum(len(annotate(row, product, retailer, reviews)['error_fields']) for row in rows)
            retailers.append({'retailer': retailer, 'total': len(rows), 'issue_count': count,
                              'status': 'CRITICAL' if count else 'OK', **mapping})
        count = sum(retailer['issue_count'] for retailer in retailers)
        validation['tables'].append({'table': source['section_code'], 'table_name': source['display_name'],
            'total_checked': sum(retailer['total'] for retailer in retailers), 'total_issues': count,
            'status': 'CRITICAL' if count else 'OK', 'retailers': retailers, **mapping})
        total += count
    return total


def format_detail(cursor, target_date, table, retailer, days=3):
    product = product_line_for(table)
    source = SEDA_SOURCE_CONFIG.get(product)
    retailer = display_seda_retailer(retailer)
    if not source or retailer not in source['retailers']:
        return {'results': [], 'field_counts': {}, 'total_format_count': 0}
    mapping = resolve_monitoring_date(target_date, 'SEDA', product)
    source_day = date.fromisoformat(mapping['source_date'])
    reviews = normal_reviews(cursor, target_date, source)
    rows = load_rows(cursor, source, source_day, source_day, retailer)
    targets = [record for row in rows if (record := annotate(row, product, retailer, reviews))['error_fields']]
    counts = Counter(field for record in targets for field in record['error_fields'])
    days = min(30, max(1, int(days or 3)))
    history = []
    if days > 1 and targets:
        items = sorted({str(row['item']) for row in targets if row.get('item')})
        history = load_rows(cursor, source, source_day - timedelta(days=days-1), source_day, retailer, items)
    results = [annotate(row, product, retailer, reviews if str(row['crawl_strdatetime'])[:10] == str(source_day) else {}) for row in history] if history else targets
    ids = {row['id'] for row in results}
    results.extend(row for row in targets if row['id'] not in ids)
    display = {field: rules.expand_fields([field]) for field in rules.columns(product, retailer)}
    queries = {}
    for field in counts:
        items = sorted({str(row['item']) for row in targets if field in row['error_fields'] and row.get('item')})
        cte, where, params = scope(source, source_day - timedelta(days=days-1), source_day, retailer)
        filters = []
        if items:
            filters.append('source.item IN (' + ', '.join('%s' for _ in items) + ')')
            params.extend(items)
        ids = [row['id'] for row in targets if field in row['error_fields'] and not row.get('item')]
        if ids:
            filters.append('source.id IN (' + ', '.join('%s' for _ in ids) + ')')
            params.extend(ids)
        projection = ', '.join('source.' + col for col in dict.fromkeys(
            ['id', 'item', 'sku', 'retailer_sku_name', 'batch_id', 'crawl_strdatetime', *display[field], 'product_url']))
        query = f'{cte} SELECT {projection} {where} AND ({" OR ".join(filters)}) ORDER BY source.item, source.crawl_strdatetime, source.id;'
        # Render parameter values only into the copyable read-only SQL, never execute it.
        parts = query.split('%s')
        queries[field] = ''.join(part + ("'" + str(params[index]).replace("'", "''") + "'" if index < len(params) else '')
                                 for index, part in enumerate(parts))
    return {'date': mapping['inspection_date'], 'table': source['section_code'], 'retailer': retailer,
            'column_names': list(select_columns(product)), 'select_cols': list(select_columns(product)),
            'editable_cols': list(rules.columns(product, retailer)), 'actual_table': source['table_name'],
            'normal_reviews': reviews, 'results': results, 'field_counts': dict(counts),
            'total_format_count': sum(counts.values()), 'supports_day_history': True, 'history_days': days,
            'date_column': source['date_column'], 'editable_date': mapping['source_date'],
            'field_display_columns': display, 'field_queries': queries, 'readonly': False, **mapping}


def select_record(cursor, target_date, product, record_id, column, *, for_edit=False):
    if column not in rules.columns(product):
        raise ValueError('Unsupported SEDA format column')
    source = SEDA_SOURCE_CONFIG[product]
    mapping = resolve_monitoring_date(target_date, 'SEDA', product)
    cte, where, params = scope(source, mapping['source_date'], mapping['source_date'])
    cursor.execute(f'''{cte} SELECT source.{column}, latest.retailer_key, source.item, source.batch_id
        {where} AND source.id = %s FOR UPDATE OF source''', [*params, record_id])
    row = cursor.fetchone()
    if not row:
        return None
    row = (row[0], display_seda_retailer(row[1]), *row[2:])
    return row if for_edit else row[:3]


def get_format_rule_details(product, retailer):
    return [rules.rule_details(product, retailer, field) for field in rules.columns(product, retailer)]
