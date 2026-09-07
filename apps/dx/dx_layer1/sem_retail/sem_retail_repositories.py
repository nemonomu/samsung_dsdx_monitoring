"""Read-only queries for Layer 1 SEM Liverpool monitoring."""

from collections.abc import Mapping

from apps.common.sem_retail import SEM_RETAILER, get_sem_source


def _rows(cursor):
    columns = [description[0] for description in cursor.description]
    return [
        dict(row) if isinstance(row, Mapping) else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def get_latest_batch_counts(cursor, product_line, target_date):
    source = get_sem_source(product_line)
    table_name = source['table_name']
    cursor.execute(f"""
        WITH latest_batch AS (
            SELECT batch_id
            FROM {table_name}
            WHERE LEFT(BTRIM(crawl_datetime), 10) = %s
              AND LOWER(BTRIM(account_name)) = LOWER(%s)
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT source.account_name AS retailer,
               source.batch_id,
               COUNT(*) AS actual_count,
               COUNT(source.main_rank) AS main_count,
               COUNT(source.bsr_rank) AS bsr_count
        FROM {table_name} source
        CROSS JOIN latest_batch
        WHERE LEFT(BTRIM(source.crawl_datetime), 10) = %s
          AND LOWER(BTRIM(source.account_name)) = LOWER(%s)
          AND source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id
        GROUP BY source.account_name, source.batch_id
    """, (str(target_date)[:10], SEM_RETAILER,
          str(target_date)[:10], SEM_RETAILER))
    rows = _rows(cursor)
    if not rows:
        return None
    row = rows[0]
    return {
        'retailer': row.get('retailer') or SEM_RETAILER,
        'batch_id': row.get('batch_id'),
        'actual_count': int(row.get('actual_count') or 0),
        'main_count': int(row.get('main_count') or 0),
        'bsr_count': int(row.get('bsr_count') or 0),
    }


def get_previous_main_counts(cursor, product_line, target_date, limit=7):
    source = get_sem_source(product_line)
    table_name = source['table_name']
    cursor.execute(f"""
        WITH retailer_rows AS (
            SELECT id, batch_id,
                   LEFT(BTRIM(crawl_datetime), 10) AS collection_date,
                   main_rank
            FROM {table_name}
            WHERE LOWER(BTRIM(account_name)) = LOWER(%s)
              AND LEFT(BTRIM(crawl_datetime), 10) < %s
        ),
        latest_batches AS (
            SELECT DISTINCT ON (collection_date) collection_date, batch_id
            FROM retailer_rows
            WHERE collection_date ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$'
            ORDER BY collection_date, id DESC
        )
        SELECT latest.collection_date, COUNT(rows.main_rank) AS main_count
        FROM latest_batches latest
        JOIN retailer_rows rows
          ON rows.collection_date = latest.collection_date
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        GROUP BY latest.collection_date
        HAVING COUNT(rows.main_rank) > 0
        ORDER BY latest.collection_date DESC
        LIMIT %s
    """, (SEM_RETAILER, str(target_date)[:10], int(limit)))
    return [
        {
            'collection_date': str(row['collection_date'])[:10],
            'main_count': int(row['main_count'] or 0),
        }
        for row in _rows(cursor)
    ]
