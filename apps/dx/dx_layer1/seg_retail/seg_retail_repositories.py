"""Read-only SEG collection queries using the recorded RDP calendar date."""

from collections.abc import Mapping
from datetime import date

from .sources import EXPERT_START_DATE, active_retailers, get_seg_source


def latest_main_counts_query(product_line, source_date):
    source = get_seg_source(product_line)
    day = date.fromisoformat(str(source_date)).isoformat()
    retailers = [name.lower() for name in active_retailers(source, day)]
    placeholders = ', '.join(['%s'] * len(retailers))
    has_page = source.get('has_page_type', True)
    page_column = ', page_type' if has_page else ''
    anchor = "LOWER(BTRIM(page_type)) = 'main'" if has_page else 'TRUE'
    scope = "LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')" if has_page else 'TRUE'
    if has_page and 'expert' in retailers:
        anchor += " OR LOWER(BTRIM(account_name)) = 'expert'"
        scope += " OR latest.retailer_key = 'expert'"
    redirect_column = ', redirect' if source['has_redirect'] else ''
    redirect_count = (
        "COUNT(*) FILTER (WHERE latest.retailer_key = 'amazon' "
        "AND rows.redirect IS TRUE)"
        if source['has_redirect'] else '0'
    )
    query = f"""
        WITH dated_rows AS (
            SELECT id, batch_id, account_name{page_column}, main_rank, bsr_rank
                   {redirect_column}
            FROM {source['table_name']}
            WHERE LEFT(BTRIM({source['date_column']}), 10) = %s
              AND LOWER(BTRIM(account_name)) IN ({placeholders or 'NULL'})
        ), latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(account_name)))
                   LOWER(BTRIM(account_name)) AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE {anchor}
            ORDER BY LOWER(BTRIM(account_name)), id DESC
        )
        SELECT latest.account_name AS retailer, latest.batch_id,
               COUNT(*) AS actual_count,
               COUNT(rows.main_rank) AS main_count,
               COUNT(rows.bsr_rank) AS bsr_count,
               {redirect_count} AS redirect_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(BTRIM(rows.account_name)) = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE {scope}
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key
    """
    return query, [day, *retailers]


def get_latest_main_batch_counts(cursor, product_line, source_date):
    if not active_retailers(get_seg_source(product_line), source_date):
        return []
    query, params = latest_main_counts_query(product_line, source_date)
    cursor.execute(query, params)
    fields = ('retailer', 'batch_id', 'actual_count', 'main_count',
              'bsr_count', 'redirect_count')
    result = []
    for raw in cursor.fetchall():
        row = dict(raw) if isinstance(raw, Mapping) else dict(zip(fields, raw))
        for key in fields[2:]:
            row[key] = int(row.get(key) or 0)
        result.append(row)
    return result


def get_previous_main_counts(cursor, product_line, source_date, limit=7):
    source = get_seg_source(product_line)
    day = date.fromisoformat(str(source_date)).isoformat()
    retailers = [name.lower() for name in active_retailers(source, day)]
    if not retailers:
        return []
    placeholders = ', '.join(['%s'] * len(retailers))
    date_column = source['date_column']
    has_page = source.get('has_page_type', True)
    page_column = "LOWER(BTRIM(page_type)) AS page_type," if has_page else ''
    anchor = "page_type = 'main'" if has_page else 'TRUE'
    scope = "page_type IN ('main', 'bsr')" if has_page else 'TRUE'
    expert_date_scope = ''
    if 'expert' in retailers:
        if has_page:
            anchor += " OR retailer = 'expert'"
            scope += " OR retailer = 'expert'"
        expert_date_scope = (
            "AND (LOWER(BTRIM(account_name)) <> 'expert' OR "
            f"LEFT(BTRIM({date_column}), 10) >= '{EXPERT_START_DATE.isoformat()}')"
        )
    cursor.execute(f"""
        WITH dated_rows AS (
            SELECT id, batch_id, LOWER(BTRIM(account_name)) AS retailer,
                   {page_column} main_rank,
                   LEFT(BTRIM({date_column}), 10) AS source_date
            FROM {source['table_name']}
            WHERE LEFT(BTRIM({date_column}), 10) < %s
              AND LEFT(BTRIM({date_column}), 10)
                  ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$'
              AND LOWER(BTRIM(account_name)) IN ({placeholders})
              {expert_date_scope}
        ), batch_counts AS (
            SELECT retailer, source_date, batch_id,
                   MAX(id) FILTER (WHERE {anchor}) AS latest_main_id,
                   COUNT(main_rank) FILTER (
                       WHERE {scope}
                   ) AS main_count
            FROM dated_rows
            GROUP BY retailer, source_date, batch_id
        ), daily_counts AS (
            SELECT DISTINCT ON (retailer, source_date)
                   retailer, source_date, main_count
            FROM batch_counts
            WHERE latest_main_id IS NOT NULL
            ORDER BY retailer, source_date, latest_main_id DESC
        ), ranked_days AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY retailer ORDER BY source_date DESC
            ) AS day_rank
            FROM daily_counts
            WHERE main_count > 0
        )
        SELECT retailer, source_date, main_count
        FROM ranked_days
        WHERE day_rank <= %s
        ORDER BY retailer, source_date DESC
    """, [day, *retailers, int(limit)])
    fields = ('retailer', 'source_date', 'main_count')
    return [dict(row) if isinstance(row, Mapping) else dict(zip(fields, row))
            for row in cursor.fetchall()]
