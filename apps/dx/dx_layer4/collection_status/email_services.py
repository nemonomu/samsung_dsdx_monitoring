"""DB-configured collection counts for the Layer 4 email report."""

import re

from apps.common.db import dx_connection

from .email_registry import EMAIL_REPORT_SOURCES


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_CONFIG_TABLE = 'monitoring_retail_columns'
_MAIN_SCOPE = "LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'"
_BSR_SCOPE = "LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'bsr'"


class EmailConfigurationError(ValueError):
    """Raised when an email source has no safe active column settings."""


def _normalize_name(value):
    return str(value or '').strip().lower()


def _date_condition(source, alias='source'):
    column = source['date_column']
    if source['date_mode'] == 'batch':
        return (
            f"substring(COALESCE(CAST({alias}.{column} AS TEXT), '') "
            "from '([0-9]{8})') = %s"
        )
    if source['date_mode'] == 'text':
        return f"LEFT(BTRIM(CAST({alias}.{column} AS TEXT)), 10) = %s"
    if source.get('business_timezone'):
        return (
            f"{alias}.{column} >= "
            f"(%s::date::timestamp AT TIME ZONE "
            f"'{source['business_timezone']}') AND "
            f"{alias}.{column} < "
            f"((%s::date + 1)::timestamp AT TIME ZONE "
            f"'{source['business_timezone']}')"
        )
    return f"DATE({alias}.{column}::timestamp) = %s"


def _date_params(source, target_date):
    value = str(target_date)[:10]
    if source['date_mode'] == 'batch':
        return [value.replace('-', '')]
    if source.get('business_timezone'):
        return [value, value]
    return [value]


def _retailer_condition(source, retailer, alias='source', *,
                        include_unassigned=True):
    account_column = source['account_column']
    placeholders = ', '.join(['%s'] * len(retailer['aliases']))
    condition = (
        f"LOWER(BTRIM(CAST({alias}.{account_column} AS TEXT))) "
        f"IN ({placeholders})"
    )
    if source.get('include_unassigned') and include_unassigned:
        condition = (
            f"({condition} OR {alias}.{account_column} IS NULL "
            f"OR BTRIM(CAST({alias}.{account_column} AS TEXT)) = '')"
        )
    return condition


def _retailer_params(retailer):
    return [_normalize_name(alias) for alias in retailer['aliases']]


def _source_scope(source, retailer, *, include_excluded=False,
                  include_unassigned=True):
    clauses = [
        _retailer_condition(
            source, retailer, include_unassigned=include_unassigned,
        ),
        _date_condition(source),
    ]
    if retailer.get('exclude_redirect') and not include_excluded:
        clauses.append('COALESCE(source.redirect, FALSE) IS NOT TRUE')
    return ' AND '.join(clauses)


def _configured_retailers(cursor, source):
    """Load the source's active Missing columns from the existing DB table."""
    cursor.execute(
        f"""
        SELECT column_name, retailer
        FROM {_CONFIG_TABLE}
        WHERE LOWER(BTRIM(CAST(product_line AS TEXT))) = %s
          AND is_active IS TRUE
          AND COALESCE(is_del, FALSE) IS FALSE
          AND COALESCE(skip_missing_check, FALSE) IS FALSE
        ORDER BY id
        """,
        [_normalize_name(source['product_line'])],
    )
    rows = cursor.fetchall()

    configured = []
    for retailer in source['retailers']:
        accepted_names = {
            _normalize_name(alias) for alias in retailer['aliases']
        }
        columns = []
        for row in rows:
            if isinstance(row, dict):
                column_name = row.get('column_name')
                retailer_name = row.get('retailer')
            else:
                column_name, retailer_name = row[0], row[1]
            if _normalize_name(retailer_name) not in accepted_names:
                continue
            column_name = str(column_name or '').strip()
            if not _IDENTIFIER.fullmatch(column_name):
                raise EmailConfigurationError(
                    f"Unsafe configured column for {source['key']}"
                )
            if column_name not in columns:
                columns.append(column_name)

        if not columns:
            raise EmailConfigurationError(
                f"No active columns for {source['key']}/{retailer['name']}"
            )
        configured.append({**retailer, 'columns': tuple(columns)})
    return configured


def _count_when(condition):
    return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"


def _missing(column):
    return (
        f"(source.{column} IS NULL OR "
        f"BTRIM(CAST(source.{column} AS TEXT)) = '')"
    )


def _present(column):
    return f"NOT {_missing(column)}"


def _column_metrics(source, retailer, column):
    """Return SQL expressions for the real denominator and Missing count."""
    missing = _missing(column)

    if source.get('has_page_type') and column == 'bsr_rank':
        return (
            _count_when(_BSR_SCOPE),
            _count_when(f"{_BSR_SCOPE} AND {missing}"),
            'BSR 페이지 실제 수집 건수',
        )

    if source.get('special_rules') == 'sea_tv':
        retailer_key = _normalize_name(retailer['name'])
        if column == 'original_sku_price' and retailer_key in {
                'bestbuy', 'walmart'}:
            denominator = _present('savings')
            return (
                _count_when(denominator),
                _count_when(f"{denominator} AND {missing}"),
                '할인가 존재 시에만 원본가 존재 (Amazon 제외)',
            )
        if column == 'trend_rank':
            return (
                _count_when(_present(column)),
                '0',
                '트렌드 수집 항목',
            )
        if column in {'promotion_type', 'promotion_position'}:
            denominator = _present('promotion_position')
            return (
                _count_when(denominator),
                (
                    f"GREATEST({_count_when(denominator)} - "
                    f"{_count_when(_present(column))}, 0)"
                ),
                '프로모션 페이지 수집 항목',
            )

    if source.get('has_page_type') and source['collection_scope'] == 'main':
        return (
            _count_when(_MAIN_SCOPE),
            _count_when(f"{_MAIN_SCOPE} AND {missing}"),
            '',
        )
    return ('COUNT(*)', _count_when(missing), '')


def _empty_retailer(retailer):
    return {
        'retailer': retailer['name'],
        'aliases': list(retailer['aliases']),
        'total_count': 0,
        'collected_count': 0,
        'batch_id': '',
        'has_data': False,
        'columns': [
            {'column': column, 'total_count': 0, 'null_count': 0}
            for column in retailer['columns']
        ],
    }


def _query_redirect_count(cursor, source, retailer, target_date):
    if not retailer.get('exclude_redirect'):
        return 0
    scope = _source_scope(source, retailer, include_excluded=True)
    params = _retailer_params(retailer) + _date_params(source, target_date)
    cursor.execute(
        f"SELECT COUNT(*) FROM {source['table_name']} source "
        f"WHERE {scope} AND source.redirect IS TRUE",
        params,
    )
    row = cursor.fetchone()
    return int((row[0] if row else 0) or 0)


def _query_retailer(cursor, source, retailer, target_date):
    """Return one retailer's actual collection and Missing quantities."""
    table_name = source['table_name']
    scope = _source_scope(source, retailer)
    base_params = _retailer_params(retailer) + _date_params(
        source, target_date,
    )
    batch_id = None

    if source.get('latest_batch', True):
        # TSE rows with a blank account belong to Homepro's batch, but the
        # anchor batch itself must be selected from an explicitly named row.
        latest_scope = _source_scope(
            source, retailer, include_unassigned=False,
        )
        if (
            source.get('has_page_type')
            and source['collection_scope'] == 'main'
        ):
            latest_scope = f"{latest_scope} AND {_MAIN_SCOPE}"
        cursor.execute(
            f"SELECT source.{source['batch_column']} "
            f"FROM {table_name} source "
            f"WHERE {latest_scope} "
            f"ORDER BY source.{source['id_column']} DESC LIMIT 1",
            base_params,
        )
        latest_row = cursor.fetchone()
        if latest_row is None:
            return _empty_retailer(retailer)
        batch_id = latest_row[0]

    total_expr = (
        _count_when(_MAIN_SCOPE)
        if source.get('has_page_type')
        and source['collection_scope'] == 'main'
        else 'COUNT(*)'
    )
    metric_specs = [
        (column, *_column_metrics(source, retailer, column))
        for column in retailer['columns']
    ]
    select_parts = [total_expr]
    for _column, denominator, missing_count, _remark in metric_specs:
        select_parts.extend((denominator, missing_count))

    batch_clause = ''
    query_params = list(base_params)
    if source.get('latest_batch', True):
        batch_clause = (
            f" AND source.{source['batch_column']} IS NOT DISTINCT FROM %s"
        )
        query_params.append(batch_id)
    cursor.execute(
        f"SELECT {', '.join(select_parts)} "
        f"FROM {table_name} source "
        f"WHERE {scope}{batch_clause}",
        query_params,
    )
    row = cursor.fetchone()
    total_count = int((row[0] if row else 0) or 0)
    columns = []
    for index, (column, _denominator, _missing_count, remark) in enumerate(
            metric_specs):
        column_total = int((row[1 + index * 2] if row else 0) or 0)
        null_count = int((row[2 + index * 2] if row else 0) or 0)
        item = {
            'column': column,
            'total_count': column_total,
            'null_count': null_count,
        }
        if remark:
            item['remark'] = remark
        columns.append(item)

    redirect_true_count = _query_redirect_count(
        cursor, source, retailer, target_date,
    )
    has_data = total_count > 0 or any(
        column['total_count'] > 0 for column in columns
    )
    result = {
        'retailer': retailer['name'],
        'aliases': list(retailer['aliases']),
        'total_count': total_count,
        'collected_count': total_count,
        'batch_id': '' if batch_id is None else str(batch_id),
        'has_data': has_data,
        'columns': columns,
    }
    if retailer.get('exclude_redirect'):
        result['redirect_true_count'] = redirect_true_count
    return result


def _query_source(source, target_date):
    with dx_connection() as (_conn, cursor):
        configured_retailers = _configured_retailers(cursor, source)
        retailers = [
            _query_retailer(cursor, source, retailer, target_date)
            for retailer in configured_retailers
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
        'total_count': sum(row['total_count'] for row in retailers),
        'collected_count': sum(row['collected_count'] for row in retailers),
        'column_order': column_order,
        'retailers': retailers,
    }


def get_email_report_data(target_date, sources=None):
    """Read each allow-listed source, preserving explicit partial failures."""
    configured_sources = EMAIL_REPORT_SOURCES if sources is None else sources
    rows = []
    errors = []
    for source in configured_sources:
        try:
            rows.append(_query_source(source, target_date))
        except Exception as error:
            # SQL/config details remain server-side; the UI only needs the key.
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
