"""Read-only SEG collection queries using the recorded RDP calendar date."""

from collections.abc import Mapping
from datetime import date

from apps.common.seg_retail import get_seg_source


def latest_main_counts_query(product_line, source_date):
    source = get_seg_source(product_line)
    day = date.fromisoformat(str(source_date)).isoformat()
    retailers = [name.lower() for name in source['retailers']]
    placeholders = ', '.join(['%s'] * len(retailers))
    redirect_column = ', redirect' if source['has_redirect'] else ''
    redirect_count = (
        "COUNT(*) FILTER (WHERE latest.retailer_key = 'amazon' "
        "AND rows.redirect IS TRUE)"
        if source['has_redirect'] else '0'
    )
    query = f"""
        WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type, main_rank, bsr_rank
                   {redirect_column}
            FROM {source['table_name']}
            WHERE LEFT(BTRIM({source['date_column']}), 10) = %s
              AND LOWER(BTRIM(account_name)) IN ({placeholders})
        ), latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(account_name)))
                   LOWER(BTRIM(account_name)) AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(page_type)) = 'main'
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
        WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key
    """
    return query, [day, *retailers]


def get_latest_main_batch_counts(cursor, product_line, source_date):
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
    retailers = [name.lower() for name in source['retailers']]
    placeholders = ', '.join(['%s'] * len(retailers))
    cursor.execute(f"""
        WITH dated_rows AS (
            SELECT id, batch_id, LOWER(BTRIM(account_name)) AS retailer,
                   LOWER(BTRIM(page_type)) AS page_type, main_rank,
                   LEFT(BTRIM(crawl_strdatetime), 10) AS source_date
            FROM {source['table_name']}
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) < %s
              AND LEFT(BTRIM(crawl_strdatetime), 10)
                  ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$'
              AND LOWER(BTRIM(account_name)) IN ({placeholders})
        ), latest_main_batches AS (
            SELECT DISTINCT ON (retailer, source_date)
                   retailer, source_date, batch_id
            FROM dated_rows
            WHERE page_type = 'main'
            ORDER BY retailer, source_date, id DESC
        ), daily_counts AS (
            SELECT latest.retailer, latest.source_date,
                   COUNT(rows.main_rank) AS main_count
            FROM latest_main_batches latest
            JOIN dated_rows rows
              ON rows.retailer = latest.retailer
             AND rows.source_date = latest.source_date
             AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
            WHERE rows.page_type IN ('main', 'bsr')
            GROUP BY latest.retailer, latest.source_date
            HAVING COUNT(rows.main_rank) > 0
        ), ranked_days AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY retailer ORDER BY source_date DESC
            ) AS day_rank
            FROM daily_counts
        )
        SELECT retailer, source_date, main_count
        FROM ranked_days
        WHERE day_rank <= %s
        ORDER BY retailer, source_date DESC
    """, [day, *retailers, int(limit)])
    fields = ('retailer', 'source_date', 'main_count')
    return [dict(row) if isinstance(row, Mapping) else dict(zip(fields, row))
            for row in cursor.fetchall()]
