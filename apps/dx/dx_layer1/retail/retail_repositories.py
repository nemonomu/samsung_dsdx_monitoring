"""
DX Layer 1 Retail Repositories: 데이터베이스 I/O 쿼리 전담 계층
"""

from apps.common.retail_validation import get_tv_validation_condition

BATCH_DATE_EXPR = "substring(COALESCE(batch_id, '') from '([0-9]{8})')"


def _batch_date_key(date_value):
    return str(date_value)[:10].replace('-', '')


def _batch_date_from_slot(slot_start):
    return _batch_date_key(slot_start)


def query_retail_counts(cursor, table_name, date_field, extra_rank_field, slot_start, slot_end, daily_retailers=None):
    batch_date = _batch_date_from_slot(slot_start)
    cursor.execute(f"""
        SELECT account_name,
               COUNT(*) as cnt,
               COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
               COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
               COUNT(CASE WHEN {extra_rank_field} IS NOT NULL THEN 1 END) as extra_count
        FROM {table_name}
        WHERE {BATCH_DATE_EXPR} = %s
        GROUP BY account_name
    """, (batch_date,))
    return cursor.fetchall()


def query_retail_counts_by_retailer(cursor, table_name, date_field, extra_rank_field, slot_start, slot_end, retailer):
    batch_date = _batch_date_from_slot(slot_start)
    cursor.execute(f"""
        SELECT
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            COUNT(CASE WHEN {extra_rank_field} IS NOT NULL THEN 1 END) as extra_count,
            COUNT(*) as total
        FROM {table_name}
        WHERE {BATCH_DATE_EXPR} = %s
        AND LOWER(account_name) = LOWER(%s)
    """, (batch_date, retailer))
    return cursor.fetchone()


def get_tv_retail_detail_list(cursor, target_date):
    cursor.execute(f"""
        SELECT
            account_name as retailer,
            COUNT(*) as total,
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            COUNT(CASE WHEN final_sku_price IS NOT NULL THEN 1 END) as price_count
        FROM tv_retail_com
        WHERE {BATCH_DATE_EXPR} = %s
        GROUP BY account_name
        ORDER BY account_name
    """, (_batch_date_key(target_date),))
    return cursor.fetchall()


def get_hhp_retail_detail_list(cursor, target_date):
    return []

    cursor.execute("""
        SELECT
            account_name as retailer,
            COUNT(*) as total,
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            COUNT(CASE WHEN final_sku_price IS NOT NULL THEN 1 END) as price_count
        FROM hhp_retail_com
        WHERE DATE(crawl_strdatetime::timestamp) = %s
        GROUP BY account_name
        ORDER BY account_name
    """, (target_date,))
    return cursor.fetchall()


def get_retail_summary_null_counts(cursor, table_name, date_field, check_columns, slot_start, slot_end, retailer, is_daily):
    count_parts = [f"COUNT({col}) as {col}_cnt" for col in check_columns]
    batch_date = _batch_date_from_slot(slot_start)
    query = f"""
        SELECT {', '.join(count_parts)}
        FROM {table_name}
        WHERE {BATCH_DATE_EXPR} = %s
        AND LOWER(account_name) = LOWER(%s)
        AND {get_tv_validation_condition()}
    """
    cursor.execute(query, (batch_date, retailer))
    return cursor.fetchone()


def get_retailer_raw_data_list(cursor, table_name, columns, retailer, date_column, start_time, end_time):
    batch_date = _batch_date_from_slot(start_time)
    query = f"""
        SELECT {', '.join(columns)}
        FROM {table_name}
        WHERE LOWER(account_name) = LOWER(%s)
        AND {BATCH_DATE_EXPR} = %s
        ORDER BY id DESC
        LIMIT 500
    """
    cursor.execute(query, (retailer, batch_date))
    return cursor.fetchall()
