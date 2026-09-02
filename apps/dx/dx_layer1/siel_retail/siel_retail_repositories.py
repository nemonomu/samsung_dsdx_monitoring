"""Read-only queries for Layer 1 SIEL retail collection monitoring."""

from collections.abc import Mapping

from apps.common.siel_retail import (
    SIEL_BUSINESS_TIMEZONE,
    get_siel_source,
)


def get_latest_main_batch_counts(cursor, product_line, source_date):
    """Return each retailer's latest MAIN batch and its MAIN+BSR counts.

    The source date is bounded by KST calendar-day boundaries. The anchor
    batch comes from the greatest ``id`` among MAIN rows for each retailer;
    only MAIN and BSR rows from that same batch are counted. No other date or
    batch is used as a fallback.
    """
    source = get_siel_source(product_line)
    table_name = source['table_name']
    date_column = source['date_column']
    retailer_keys = [name.lower() for name in source['retailers']]
    placeholders = ', '.join(['%s'] * len(retailer_keys))
    query = f"""
        WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type
            FROM {table_name}
            WHERE {date_column} >= (
                    %s::date::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                  )
              AND {date_column} < (
                    (%s::date + 1)::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                  )
              AND LOWER(BTRIM(CAST(account_name AS TEXT)))
                  IN ({placeholders})
        ),
        latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(CAST(account_name AS TEXT))))
                   LOWER(BTRIM(CAST(account_name AS TEXT))) AS retailer_key,
                   account_name,
                   batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(CAST(page_type AS TEXT))) = 'main'
            ORDER BY LOWER(BTRIM(CAST(account_name AS TEXT))), id DESC
        )
        SELECT latest.account_name,
               latest.batch_id,
               COUNT(rows.id) FILTER (
                   WHERE LOWER(BTRIM(CAST(rows.page_type AS TEXT)))
                         IN ('main', 'bsr')
               ) AS actual_count,
               COUNT(rows.id) FILTER (
                   WHERE LOWER(BTRIM(CAST(rows.page_type AS TEXT))) = 'main'
               ) AS main_count,
               COUNT(rows.id) FILTER (
                   WHERE LOWER(BTRIM(CAST(rows.page_type AS TEXT))) = 'bsr'
               ) AS bsr_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(BTRIM(CAST(rows.account_name AS TEXT)))
             = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key
    """
    date_value = str(source_date)[:10]
    cursor.execute(query, [date_value, date_value, *retailer_keys])

    results = []
    for row in cursor.fetchall():
        if isinstance(row, Mapping):
            retailer = row.get('account_name')
            batch_id = row.get('batch_id')
            actual_count = row.get('actual_count')
            main_count = row.get('main_count')
            bsr_count = row.get('bsr_count')
        else:
            retailer, batch_id, actual_count, main_count, bsr_count = row[:5]
        results.append({
            'retailer': retailer,
            'batch_id': batch_id,
            'actual_count': int(actual_count or 0),
            'main_count': int(main_count or 0),
            'bsr_count': int(bsr_count or 0),
        })
    return results
