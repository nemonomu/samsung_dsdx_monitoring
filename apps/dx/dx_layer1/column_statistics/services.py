"""Bounded, read-only aggregation using the email report's collection policy."""
from datetime import timedelta

from apps.common.db import dx_connection
from apps.common.sea_dates import appliance_source_date_sql
from apps.dx.dx_layer4.collection_status.email_registry import EMAIL_REPORT_SOURCES
from apps.dx.dx_layer4.collection_status.email_services import (
    _configured_retailers, _present, _retailer_condition, _retailer_params,
)

FIRST_COLUMNS = (
    'item', 'sku', 'retailer_sku_name', 'count_of_reviews', 'star_rating',
    'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'savings',
)
EXCLUDED_COLUMNS = frozenset((
    'main_rank', 'bsr_rank', 'main', 'bsr', 'id', 'country', 'account_name',
    'calendar_week', 'crawl_datetime', 'crawl_strdatetime', 'batch_id', 'page_type',
))


def ordered_columns(columns):
    available = set(columns) - EXCLUDED_COLUMNS
    return [c for c in FIRST_COLUMNS if c in available] + sorted(available - set(FIRST_COLUMNS))


def catalog():
    return [{'country': s['country'], 'product': s['product'],
             'retailers': [r['name'] for r in s['retailers']]}
            for s in EMAIL_REPORT_SOURCES]


def select_source(country, product, retailer):
    for source in EMAIL_REPORT_SOURCES:
        if source['country'] == country and source['product'] == product:
            if any(r['name'] == retailer for r in source['retailers']):
                return source
    raise ValueError('Invalid collection selection')


def query_spec(source, retailer, columns, start, end):
    """Only registry/configuration identifiers enter SQL; filter values are bound."""
    home_depot = source['key'] in ('sea_ref', 'sea_ldy') and retailer['name'] == 'HomeDepot'
    col = 'source.' + source['date_column']
    if home_depot:
        day = appliance_source_date_sql(col)
    elif source['date_mode'] == 'batch':
        raw = f"substring(CAST({col} AS TEXT) from '([0-9]{{8}})')"
        day = f"substring({raw}, 1, 4) || '-' || substring({raw}, 5, 2) || '-' || substring({raw}, 7, 2)"
    elif source.get('business_timezone'):
        day = f"TO_CHAR({col} AT TIME ZONE '{source['business_timezone']}', 'YYYY-MM-DD')"
    else:
        day = f"LEFT(BTRIM(CAST({col} AS TEXT)), 10)"
    clauses = [_retailer_condition(source, retailer), f'({day}) BETWEEN %s AND %s']
    params = _retailer_params(retailer) + [str(start), str(end)]
    if retailer.get('exclude_redirect'):
        clauses.append('COALESCE(source.redirect, FALSE) IS NOT TRUE')
    if home_depot:
        clauses.append(f"({day}) >= '2026-09-20'")
    main_scope = source['has_page_type'] and source['collection_scope'] == 'main' and not home_depot
    ctes = [f"scoped AS (SELECT source.*, ({day}) AS stats_day FROM {source['table_name']} source WHERE {' AND '.join(clauses)})"]
    master_sku = source['key'] == 'sea_tv' and 'sku' in columns
    if master_sku:
        # Uncorrelated membership subqueries can be hashed once. A correlated
        # EXISTS in the aggregate rescans the master for every collected row.
        ctes.append("sku_keys AS MATERIALIZED (SELECT item, "
                    "LOWER(BTRIM(CAST(account_name AS TEXT))) AS account_name "
                    "FROM public.tv_item_mst WHERE sku IS NOT NULL "
                    "AND BTRIM(CAST(sku AS TEXT)) <> '')")
    join = ''
    if source['latest_batch']:
        anchor = _retailer_condition(source, retailer, include_unassigned=False)
        params += _retailer_params(retailer)
        if main_scope:
            anchor += " AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'"
        ctes.append(f"latest AS (SELECT DISTINCT ON (stats_day) stats_day, {source['batch_column']} AS chosen_batch FROM scoped source WHERE {anchor} ORDER BY stats_day, {source['id_column']} DESC)")
        join = f" JOIN latest ON latest.stats_day = source.stats_day AND source.{source['batch_column']} IS NOT DISTINCT FROM latest.chosen_batch"
    expressions = []
    for column in columns:
        present = _present(column)
        if master_sku and column == 'sku':
            account = 'LOWER(BTRIM(CAST(source.account_name AS TEXT)))'
            # Preserve IS NOT DISTINCT FROM item semantics, including NULL item,
            # and ordinary equality for accounts. IN never multiplies rows.
            present = (f"CASE WHEN source.item IS NULL THEN {account} IN "
                       "(SELECT account_name FROM sku_keys WHERE item IS NULL) "
                       f"ELSE (source.item, {account}) IN "
                       "(SELECT item, account_name FROM sku_keys WHERE item IS NOT NULL) END")
        expressions.append(f'COUNT(*) FILTER (WHERE {present}) AS "{column}"')
    where = " WHERE LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')" if main_scope else ''
    sql = (f"WITH {', '.join(ctes)} SELECT source.stats_day, COUNT(*) AS total, "
           f"{', '.join(expressions)} FROM scoped source{join}{where} "
           "GROUP BY source.stats_day ORDER BY source.stats_day")
    return sql, params


def daily_counts(country, product, retailer_name, end, days):
    source = select_source(country, product, retailer_name)
    start = end - timedelta(days=days - 1)
    with dx_connection() as (_connection, cursor):
        cursor.execute("SET LOCAL statement_timeout = '20s'")
        # A selection must not fail because an unrelated retailer lacks settings.
        selected = {**source, 'retailers': tuple(r for r in source['retailers'] if r['name'] == retailer_name)}
        retailers = _configured_retailers(cursor, selected)
        if not retailers:
            raise ValueError('No configured collection fields')
        retailer = retailers[0]
        columns = ordered_columns(retailer['columns'])
        sql, params = query_spec(source, retailer, columns, start, end)
        cursor.execute(sql, params)
        records = cursor.fetchall()
    by_day = {}
    for record in records:
        values = list(record.values()) if isinstance(record, dict) else record
        by_day[str(values[0])] = {'total': int(values[1]),
                                'counts': {c: int(v) for c, v in zip(columns, values[2:])}}
    dates = [str(start + timedelta(days=i)) for i in range(days)]
    return {'country': country, 'product': product, 'retailer': retailer_name,
            'columns': columns, 'dates': dates,
            'daily': [{'date': day, **by_day.get(day, {'total': 0, 'counts': {c: 0 for c in columns}})} for day in dates],
            'sku_from_master': source['key'] == 'sea_tv'}
