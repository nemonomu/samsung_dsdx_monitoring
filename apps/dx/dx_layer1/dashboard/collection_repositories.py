from apps.common.db import dx_table
from apps.common.sea_dates import appliance_source_date_sql


SOURCES = (
    ('Amazon', 'TV', 'tv_retail_com', 'crawl_datetime'),
    ('Walmart', 'TV', 'tv_retail_com', 'crawl_datetime'),
    ('HomeDepot', 'REF', 'ref_retail_com', 'crawl_strdatetime'),
    ('HomeDepot', 'LDY', 'ldy_retail_com', 'crawl_strdatetime'),
)


def fetch_collection(cursor, source, target_date):
    retailer, _product, table, column = source
    table = 'public.' + dx_table(table)
    if retailer == 'HomeDepot':
        day = appliance_source_date_sql('source.' + column, 'source.account_name')
        stamp = f"NULLIF(TRIM(CAST(source.{column} AS TEXT)), '')::timestamptz"
    else:
        day = f"LEFT(TRIM(CAST(source.{column} AS TEXT)), 10)"
        stamp = f"source.{column}::timestamp AT TIME ZONE 'America/New_York'"
    cursor.execute(f"""
        WITH latest AS (
            SELECT source.batch_id FROM {table} source
            WHERE ({day}) = %s
              AND LOWER(TRIM(source.account_name)) = LOWER(%s)
            ORDER BY source.id DESC LIMIT 1
        )
        SELECT COUNT(*),
               TO_CHAR(MAX({stamp}) AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS'),
               MAX(source.batch_id)
        FROM {table} source JOIN latest
          ON source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE ({day}) = %s
          AND LOWER(TRIM(source.account_name)) = LOWER(%s)
    """, (str(target_date), retailer, str(target_date), retailer))
    return cursor.fetchone() or (0, None, None)
