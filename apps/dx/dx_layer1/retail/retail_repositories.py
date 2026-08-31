"""DX Layer 1 SEA retail database queries."""

from apps.common.retail_validation import get_tv_validation_condition


def _timestamp_expression(date_field):
    return date_field if '::' in date_field else f'{date_field}::timestamp'


def _timestamp_range(date_field):
    expression = _timestamp_expression(date_field)
    return f"({expression}) >= %s::timestamp AND ({expression}) < %s::timestamp"


def _text_date_condition(date_column, alias=''):
    prefix = f'{alias}.' if alias else ''
    return (
        f"LEFT(BTRIM(CAST({prefix}{date_column} AS TEXT)), 10) = %s"
    )


def _normalized_account(alias=''):
    prefix = f'{alias}.' if alias else ''
    return f"LOWER(BTRIM(CAST({prefix}account_name AS TEXT)))"


def _normalized_page_type(alias=''):
    prefix = f'{alias}.' if alias else ''
    return f"LOWER(BTRIM(CAST({prefix}page_type AS TEXT)))"


def query_retail_counts(cursor, table_name, date_field, extra_rank_field,
                        slot_start, slot_end, daily_retailers=None):
    """Return inclusive SEA TV collection counts for one source-date range."""

    cursor.execute(f"""
        SELECT account_name,
               COUNT(*) as cnt,
               COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
               COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
               COUNT(CASE WHEN {extra_rank_field} IS NOT NULL THEN 1 END) as extra_count
        FROM {table_name}
        WHERE {_timestamp_range(date_field)}
        GROUP BY account_name
    """, (slot_start, slot_end))
    return cursor.fetchall()


def query_retail_counts_by_retailer(cursor, table_name, date_field,
                                    extra_rank_field, slot_start, slot_end,
                                    retailer):
    """Return inclusive SEA TV counts for one retailer and source date."""

    cursor.execute(f"""
        SELECT
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            COUNT(CASE WHEN {extra_rank_field} IS NOT NULL THEN 1 END) as extra_count,
            COUNT(*) as total
        FROM {table_name}
        WHERE {_timestamp_range(date_field)}
        AND LOWER(account_name) = LOWER(%s)
    """, (slot_start, slot_end, retailer))
    return cursor.fetchone()


def get_tv_retail_detail_list(cursor, target_date):
    cursor.execute("""
        SELECT
            account_name as retailer,
            COUNT(*) as total,
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            COUNT(CASE WHEN final_sku_price IS NOT NULL THEN 1 END) as price_count
        FROM public.tv_retail_com
        WHERE (crawl_datetime::timestamp) >= %s::date
          AND (crawl_datetime::timestamp) < (%s::date + INTERVAL '1 day')
        GROUP BY account_name
        ORDER BY account_name
    """, (str(target_date)[:10], str(target_date)[:10]))
    return cursor.fetchall()


def get_hhp_retail_detail_list(cursor, target_date):
    return []


def get_retail_summary_null_counts(cursor, table_name, date_field,
                                   check_columns, slot_start, slot_end,
                                   retailer, is_daily):
    """Count TV populated fields under the established redirect scope."""

    count_parts = [f"COUNT({col}) as {col}_cnt" for col in check_columns]
    query = f"""
        SELECT {', '.join(count_parts)}
        FROM {table_name}
        WHERE {_timestamp_range(date_field)}
        AND LOWER(account_name) = LOWER(%s)
        AND {get_tv_validation_condition()}
    """
    cursor.execute(query, (slot_start, slot_end, retailer))
    return cursor.fetchone()


def get_retailer_raw_data_list(cursor, table_name, columns, retailer,
                               date_column, start_time, end_time):
    """Return inclusive TV raw rows for the exact source-date range."""

    query = f"""
        SELECT {', '.join(columns)}
        FROM {table_name}
        WHERE LOWER(account_name) = LOWER(%s)
        AND {_timestamp_range(date_column)}
        ORDER BY id DESC
        LIMIT 500
    """
    cursor.execute(query, (retailer, start_time, end_time))
    return cursor.fetchall()


def get_latest_appliance_main_batch(cursor, table_name, date_column,
                                    target_date, retailer):
    """Return the exact-date latest MAIN anchor batch for one retailer."""

    cursor.execute(f"""
        SELECT batch_id
        FROM {table_name}
        WHERE {_text_date_condition(date_column)}
          AND {_normalized_account()} = LOWER(BTRIM(%s))
          AND {_normalized_page_type()} = 'main'
        ORDER BY id DESC
        LIMIT 1
    """, (str(target_date)[:10], retailer))
    row = cursor.fetchone()
    return row[0] if row else None


def query_appliance_counts_by_retailer(cursor, table_name, date_column,
                                       target_date, retailer):
    """Return MAIN+BSR counts from one retailer's latest MAIN batch."""

    batch_id = get_latest_appliance_main_batch(
        cursor, table_name, date_column, target_date, retailer,
    )
    if batch_id is None:
        return (0, 0, 0, 0, None)

    cursor.execute(f"""
        SELECT
            COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
            COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
            0 as extra_count,
            COUNT(*) as total
        FROM {table_name}
        WHERE {_text_date_condition(date_column)}
          AND {_normalized_account()} = LOWER(BTRIM(%s))
          AND batch_id IS NOT DISTINCT FROM %s
          AND {_normalized_page_type()} IN ('main', 'bsr')
    """, (str(target_date)[:10], retailer, batch_id))
    row = cursor.fetchone() or (0, 0, 0, 0)
    return (
        int(row[0] or 0), int(row[1] or 0), int(row[2] or 0),
        int(row[3] or 0), batch_id,
    )


def query_appliance_counts(cursor, table_name, date_column, target_date,
                           retailers):
    """Return the legacy Layer1 row shape plus anchor batch metadata."""

    rows = []
    for retailer in retailers:
        main_count, bsr_count, extra_count, total, batch_id = (
            query_appliance_counts_by_retailer(
                cursor, table_name, date_column, target_date, retailer,
            )
        )
        rows.append((
            retailer, total, main_count, bsr_count, extra_count, batch_id,
        ))
    return rows


def get_appliance_retail_detail_list(cursor, table_name, date_column,
                                     target_date, retailers):
    """Return appliance detail rows scoped to each latest MAIN batch."""

    results = []
    for retailer in retailers:
        batch_id = get_latest_appliance_main_batch(
            cursor, table_name, date_column, target_date, retailer,
        )
        if batch_id is None:
            results.append((retailer, 0, 0, 0, 0, None))
            continue
        cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN main_rank IS NOT NULL THEN 1 END) as main_count,
                COUNT(CASE WHEN bsr_rank IS NOT NULL THEN 1 END) as bsr_count,
                COUNT(CASE WHEN final_sku_price IS NOT NULL THEN 1 END) as price_count
            FROM {table_name}
            WHERE {_text_date_condition(date_column)}
              AND {_normalized_account()} = LOWER(BTRIM(%s))
              AND batch_id IS NOT DISTINCT FROM %s
              AND {_normalized_page_type()} IN ('main', 'bsr')
        """, (str(target_date)[:10], retailer, batch_id))
        row = cursor.fetchone() or (0, 0, 0, 0)
        results.append((
            retailer, int(row[0] or 0), int(row[1] or 0),
            int(row[2] or 0), int(row[3] or 0), batch_id,
        ))
    return results


def get_appliance_raw_data_list(cursor, table_name, columns, retailer,
                                date_column, target_date):
    """Return safe raw columns from the exact anchor batch, without fallback."""

    batch_id = get_latest_appliance_main_batch(
        cursor, table_name, date_column, target_date, retailer,
    )
    if batch_id is None:
        return []
    cursor.execute(f"""
        SELECT {', '.join(columns)}
        FROM {table_name}
        WHERE {_text_date_condition(date_column)}
          AND {_normalized_account()} = LOWER(BTRIM(%s))
          AND batch_id IS NOT DISTINCT FROM %s
          AND {_normalized_page_type()} IN ('main', 'bsr')
        ORDER BY id DESC
        LIMIT 500
    """, (str(target_date)[:10], retailer, batch_id))
    return cursor.fetchall()
