"""Read-only SEDA collection queries for one exact source date."""

from collections.abc import Mapping
from datetime import date

from apps.common.seda_retail import get_seda_source


def latest_main_counts_query(product_line, source_date):
    source = get_seda_source(product_line)
    day = date.fromisoformat(str(source_date)).isoformat()
    retailer_keys = list(source['retailer_keys'])
    placeholders = ', '.join(['%s'] * len(retailer_keys))
    query = f"""
        WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type, main_rank, bsr_rank
            FROM {source['table_name']}
            WHERE LEFT(BTRIM({source['date_column']}), 10) = %s
              AND LOWER(REPLACE(BTRIM(account_name), ' ', ''))
                  IN ({placeholders})
        ), latest_main_batches AS (
            SELECT DISTINCT ON (
                       LOWER(REPLACE(BTRIM(account_name), ' ', ''))
                   )
                   LOWER(REPLACE(BTRIM(account_name), ' ', ''))
                       AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(page_type)) = 'main'
            ORDER BY LOWER(REPLACE(BTRIM(account_name), ' ', '')), id DESC
        )
        SELECT latest.account_name AS retailer, latest.batch_id,
               COUNT(*) AS actual_count,
               COUNT(rows.main_rank) AS main_count,
               COUNT(rows.bsr_rank) AS bsr_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(REPLACE(BTRIM(rows.account_name), ' ', '')) =
             latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key
    """
    return query, [day, *retailer_keys]


def get_latest_main_batch_counts(cursor, product_line, source_date):
    query, params = latest_main_counts_query(product_line, source_date)
    cursor.execute(query, params)
    fields = ('retailer', 'batch_id', 'actual_count', 'main_count', 'bsr_count')
    result = []
    for raw in cursor.fetchall():
        row = dict(raw) if isinstance(raw, Mapping) else dict(zip(fields, raw))
        for key in fields[2:]:
            row[key] = int(row.get(key) or 0)
        result.append(row)
    return result


def get_previous_main_counts(cursor, product_line, source_date, limit=7):
    source = get_seda_source(product_line)
    day = date.fromisoformat(str(source_date)).isoformat()
    retailer_keys = list(source['retailer_keys'])
    placeholders = ', '.join(['%s'] * len(retailer_keys))
    cursor.execute(f"""
        WITH dated_rows AS (
            SELECT id, batch_id,
                   LOWER(REPLACE(BTRIM(account_name), ' ', '')) AS retailer,
                   LOWER(BTRIM(page_type)) AS page_type, main_rank,
                   LEFT(BTRIM({source['date_column']}), 10) AS source_date
            FROM {source['table_name']}
            WHERE LEFT(BTRIM({source['date_column']}), 10) < %s
              AND LEFT(BTRIM({source['date_column']}), 10)
                  ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$'
              AND LOWER(REPLACE(BTRIM(account_name), ' ', ''))
                  IN ({placeholders})
        ), batch_counts AS (
            SELECT retailer, source_date, batch_id,
                   MAX(id) FILTER (WHERE page_type = 'main') AS latest_main_id,
                   COUNT(main_rank) FILTER (
                       WHERE page_type IN ('main', 'bsr')
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
    """, [day, *retailer_keys, int(limit)])
    fields = ('retailer', 'source_date', 'main_count')
    return [
        dict(row) if isinstance(row, Mapping) else dict(zip(fields, row))
        for row in cursor.fetchall()
    ]
