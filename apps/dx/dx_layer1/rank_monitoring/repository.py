"""Read three daily snapshots. Never repair or rewrite collected data."""
from datetime import timedelta

from apps.common.db import dx_connection
from apps.common.sem_retail import sem_batch_order
from apps.dx.dx_layer1.column_statistics.dates import day_sql, date_column
from apps.dx.dx_layer4.collection_status.email_services import _retailer_condition, _retailer_params

MAX_ROWS = 15000


def query_spec(source, retailer, columns, day):
    """Identifiers come only from fixed registries; dates/accounts are parameters."""
    stamp = date_column(source)
    required = {'id', 'item', 'account_name', 'retailer_sku_name', 'product_url',
                'batch_id', 'main_rank', stamp}
    if not required.issubset(columns):
        raise ValueError('Source is missing rank comparison columns')
    if columns[stamp] == 'timestamp with time zone' and source['country'] != 'SIEL':
        # PostgreSQL discarded the original offset. A new source needs an
        # authoritative recorded-date column before it can join monitoring.
        raise ValueError('An authoritative original collection date is required')
    main_page = ('page_type' in columns and source['has_page_type'] and
                 retailer['name'].casefold() not in ('costco', 'expert', 'homedepot'))
    clauses = [_retailer_condition(source, retailer, include_unassigned=False),
               f'({day_sql(source)}) BETWEEN %s AND %s']
    if main_page:
        clauses.append("LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'")
    if retailer.get('exclude_redirect') and 'redirect' in columns:
        clauses.append('COALESCE(source.redirect, FALSE) IS NOT TRUE')
    sku = 'source.sku' if 'sku' in columns else 'NULL::text'
    ordering = sem_batch_order(source['key'], retailer['name'], 'source')
    sql = f"""
        WITH scoped AS MATERIALIZED (
            SELECT source.id, source.item, source.account_name,
                   source.retailer_sku_name, source.product_url, {sku} AS sku,
                   source.main_rank, source.batch_id,
                   CAST(source.{stamp} AS TEXT) AS collected_at,
                   ({day_sql(source)}) AS source_day
                   {', source.crawl_datetime' if source['key'] == 'sem_ldy_dryer' else ''}
            FROM {source['table_name']} source
            WHERE {' AND '.join(clauses)}
        ), latest AS (
            SELECT DISTINCT ON (source_day) source_day, batch_id
            FROM scoped source ORDER BY source_day, {ordering}
        )
        SELECT source.source_day, source.id, source.item, source.sku,
               source.retailer_sku_name, source.product_url, source.main_rank,
               source.batch_id, source.collected_at
        FROM scoped source JOIN latest chosen ON chosen.source_day = source.source_day
             AND chosen.batch_id IS NOT DISTINCT FROM source.batch_id
        ORDER BY source.source_day, source.id DESC LIMIT {MAX_ROWS + 1}
    """
    params = _retailer_params(retailer) + [str(day - timedelta(days=1)), str(day + timedelta(days=1))]
    return sql, params, '날짜별 최신 MAIN 배치' if main_page else '날짜별 최신 배치'


def load_snapshots(source, retailer, day):
    with dx_connection(connect_timeout=3) as (connection, cursor):
        connection.set_session(readonly=True)
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        schema, table = source['table_name'].split('.')
        cursor.execute('SELECT column_name, data_type FROM information_schema.columns '
                       'WHERE table_schema = %s AND table_name = %s', (schema, table))
        columns = dict(cursor.fetchall())
        sql, params, basis = query_spec(source, retailer, columns, day)
        cursor.execute(sql, params)
        names = ('date', 'id', 'item', 'sku', 'name', 'url', 'rank', 'batch_id', 'collected_at')
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        if len(rows) > MAX_ROWS:
            raise ValueError('Snapshot exceeds the safe comparison size')
        sku_from_master = source['key'] == 'sea_tv'
        if sku_from_master:
            # SEA TV has no physical sku column. Use the existing item master,
            # with one deterministic row per item, without multiplying crawls.
            items = sorted({r['item'] for r in rows if r['item']})
            if items:
                cursor.execute("""
                    SELECT DISTINCT ON (item) item, sku
                    FROM public.tv_item_mst
                    WHERE item = ANY(%s) AND LOWER(BTRIM(account_name)) = ANY(%s)
                    ORDER BY item, id DESC
                """, (items, _retailer_params(retailer)))
                skus = dict(cursor.fetchall())
                for row in rows:
                    row['sku'] = skus.get(row['item'])
    return {'rows': rows, 'basis': basis, 'sku_from_master': sku_from_master}
