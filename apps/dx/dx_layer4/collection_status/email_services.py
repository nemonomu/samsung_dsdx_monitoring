"""Email-only collection counts and missing-value summaries."""

from apps.common.db import dx_connection

from .email_registry import EMAIL_REPORT_SOURCES


def _date_condition(source, alias='source'):
    column = source['date_column']
    if source['date_mode'] == 'text':
        return (
            f"LEFT(BTRIM(CAST({alias}.{column} AS TEXT)), 10) = %s"
        )
    return f"DATE({alias}.{column}::timestamp) = %s"


def _retailer_condition(source, retailer, alias='source'):
    account_column = source['account_column']
    placeholders = ', '.join(['%s'] * len(retailer['aliases']))
    condition = (
        f"LOWER(BTRIM(CAST({alias}.{account_column} AS TEXT))) "
        f"IN ({placeholders})"
    )
    if source.get('include_unassigned'):
        condition = (
            f"({condition} OR {alias}.{account_column} IS NULL "
            f"OR BTRIM(CAST({alias}.{account_column} AS TEXT)) = '')"
        )
    return condition


def _retailer_params(retailer):
    return [str(alias).strip().lower() for alias in retailer['aliases']]


def _source_scope(source, retailer):
    clauses = [
        _retailer_condition(source, retailer),
        _date_condition(source),
    ]
    if retailer.get('exclude_redirect'):
        clauses.append('COALESCE(source.redirect, FALSE) IS NOT TRUE')
    return ' AND '.join(clauses)


def _empty_retailer(retailer):
    return {
        'retailer': retailer['name'],
        'aliases': list(retailer['aliases']),
        'expected_count': retailer['expected_count'],
        'total_count': 0,
        'collected_count': 0,
        'batch_id': '',
        'has_data': False,
        'columns': [
            {'column': column, 'total_count': 0, 'null_count': 0}
            for column in retailer['columns']
        ],
    }


def _query_retailer(cursor, source, retailer, target_date):
    """Return one retailer's latest batch and raw whitespace-aware NULLs."""
    table_name = source['table_name']
    id_column = source['id_column']
    batch_column = source['batch_column']
    scope = _source_scope(source, retailer)
    base_params = _retailer_params(retailer) + [str(target_date)]

    cursor.execute(
        f"SELECT source.{batch_column} "
        f"FROM {table_name} source "
        f"WHERE {scope} "
        f"ORDER BY source.{id_column} DESC LIMIT 1",
        base_params,
    )
    latest_row = cursor.fetchone()
    if latest_row is None:
        return _empty_retailer(retailer)

    batch_id = latest_row[0]
    has_page_type = source.get('has_page_type', True)
    main_scope = "LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'"
    total_expr = (
        f"SUM(CASE WHEN {main_scope} THEN 1 ELSE 0 END)"
        if has_page_type else 'COUNT(*)'
    )
    metric_parts = []
    for column in retailer['columns']:
        missing = (
            f"(source.{column} IS NULL OR "
            f"BTRIM(CAST(source.{column} AS TEXT)) = '')"
        )
        if has_page_type and column == 'bsr_rank':
            metric_parts.append(
                f"SUM(CASE WHEN NOT {missing} THEN 1 ELSE 0 END)"
            )
        elif has_page_type:
            metric_parts.append(
                f"SUM(CASE WHEN {main_scope} AND {missing} THEN 1 ELSE 0 END)"
            )
        else:
            metric_parts.append(
                f"SUM(CASE WHEN {missing} THEN 1 ELSE 0 END)"
            )
    select_parts = [total_expr] + metric_parts
    cursor.execute(
        f"SELECT {', '.join(select_parts)} "
        f"FROM {table_name} source "
        f"WHERE {scope} "
        f"AND source.{batch_column} IS NOT DISTINCT FROM %s",
        base_params + [batch_id],
    )
    row = cursor.fetchone()
    total_count = int((row[0] if row else 0) or 0)
    columns = []
    for index, column in enumerate(retailer['columns'], start=1):
        raw_metric = int((row[index] if row else 0) or 0)
        if has_page_type and column == 'bsr_rank':
            column_total = 100
            null_count = max(column_total - raw_metric, 0)
        else:
            column_total = total_count
            null_count = raw_metric
        columns.append({
            'column': column,
            'total_count': column_total,
            'null_count': null_count,
        })

    return {
        'retailer': retailer['name'],
        'aliases': list(retailer['aliases']),
        'expected_count': retailer['expected_count'],
        'total_count': total_count,
        'collected_count': total_count,
        'batch_id': '' if batch_id is None else str(batch_id),
        'has_data': total_count > 0,
        'columns': columns,
    }


def _query_source(source, target_date):
    with dx_connection() as (_conn, cursor):
        retailers = [
            _query_retailer(cursor, source, retailer, target_date)
            for retailer in source['retailers']
        ]

    column_order = []
    for retailer in retailers:
        for item in retailer['columns']:
            if item['column'] not in column_order:
                column_order.append(item['column'])

    return {
        'key': source['key'],
        'country': source['country'],
        'product': source['product'],
        'label': source['label'],
        'table_name': source['table_name'],
        'expected_count': sum(row['expected_count'] for row in retailers),
        'total_count': sum(row['total_count'] for row in retailers),
        'collected_count': sum(row['collected_count'] for row in retailers),
        'column_order': column_order,
        'retailers': retailers,
    }


def _legacy_sea_tv(target_date):
    """Adapt the established SEA TV email rules without changing its counts."""
    # Local import avoids making the standalone service tests load SMTP/config.
    from .services import get_collection_status

    result = get_collection_status(target_date, 'tv')
    retailers = []
    column_order = []
    for row in result.get('retailers', []):
        columns = []
        for item in row.get('columns', []):
            column = item['column']
            if column not in column_order:
                column_order.append(column)
            columns.append({
                'column': column,
                'total_count': int(item.get('total_count') or 0),
                'null_count': int(item.get('null_count') or 0),
                **({'remark': item['remark']} if item.get('remark') else {}),
            })
        total_count = int(row.get('total_count') or 0)
        retailers.append({
            'retailer': row['retailer'],
            'aliases': [row['retailer']],
            'expected_count': 300,
            'total_count': total_count,
            'collected_count': total_count,
            'redirect_true_count': int(row.get('redirect_true_count') or 0),
            'batch_id': '',
            'has_data': total_count > 0,
            'columns': columns,
        })
    return {
        'key': 'sea_tv',
        'country': 'SEA',
        'product': 'TV',
        'label': 'SEA TV 수집 데이터',
        'table_name': 'tv_retail_com',
        'expected_count': sum(row['expected_count'] for row in retailers),
        'total_count': sum(row['total_count'] for row in retailers),
        'collected_count': sum(row['collected_count'] for row in retailers),
        'column_order': column_order,
        'retailers': retailers,
    }


def get_email_report_data(target_date, sources=None):
    """Return all email sources while keeping partial failures explicit.

    A query failure for one source never turns the remaining data into an
    apparently complete email.  The caller must use ``complete`` to disable
    email sending until every configured source has been read successfully.
    """
    configured_sources = EMAIL_REPORT_SOURCES if sources is None else sources
    rows = []
    errors = []
    for source in configured_sources:
        try:
            if source['key'] == 'sea_tv' and sources is None:
                rows.append(_legacy_sea_tv(target_date))
            else:
                rows.append(_query_source(source, target_date))
        except Exception as error:
            # Keep database details server-side.  The source key is enough for
            # the UI to identify which section needs attention.
            print(f"[ERROR] email report source {source['key']}: {error}")
            errors.append({
                'source': source['key'],
                'message': '데이터 조회에 실패했습니다.',
            })

    return {
        'success': not errors,
        'complete': not errors,
        'date': str(target_date),
        'sources': rows,
        'errors': errors,
    }
