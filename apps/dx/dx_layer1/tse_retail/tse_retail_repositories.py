"""Read-only queries for Layer 1 TSE retail collection monitoring."""

from collections.abc import Mapping

from apps.common.tse_retail import get_tse_source


def get_latest_batch_counts(cursor, product_line, target_date):
    """Return the latest batch count for every retailer on ``target_date``.

    The latest batch is selected from the row with the greatest ``id`` for
    each retailer.  ``batch_id`` is intentionally not sorted because its text
    value does not define execution order.
    """
    source = get_tse_source(product_line)
    table_name = source['table_name']
    query = f"""
        WITH dated_rows AS (
            SELECT id, batch_id, account_name, main_rank, bsr_rank
            FROM {table_name}
            WHERE LEFT(TRIM(crawl_datetime), 10) = %s
              AND NULLIF(TRIM(account_name), '') IS NOT NULL
        ),
        latest_batches AS (
            SELECT DISTINCT ON (LOWER(TRIM(account_name)))
                   LOWER(TRIM(account_name)) AS retailer_key,
                   account_name,
                   batch_id
            FROM dated_rows
            ORDER BY LOWER(TRIM(account_name)), id DESC
        )
        SELECT latest.account_name,
               latest.batch_id,
               COUNT(rows.id) AS actual_count,
               COUNT(rows.id) FILTER (
                   WHERE rows.main_rank IS NOT NULL
               ) AS main_count,
               COUNT(rows.id) FILTER (
                   WHERE rows.bsr_rank IS NOT NULL
               ) AS bsr_count
        FROM latest_batches latest
        JOIN dated_rows rows
          ON LOWER(TRIM(rows.account_name)) = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key
    """
    cursor.execute(query, (str(target_date)[:10],))

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
