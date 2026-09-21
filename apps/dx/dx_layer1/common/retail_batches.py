"""Count daily batch IDs independently of the batch used for validation."""

from collections.abc import Mapping
from datetime import date, timedelta


RETAIL_CHECK_TYPES = frozenset({
    'retail', 'seda_retail', 'siel_retail', 'seg_retail',
    'sem_retail', 'tse_retail',
})


def _source(check_type, product_line):
    # Resolve identifiers through the existing fixed source registries.
    if check_type == 'retail':
        from apps.common.sea_retail import get_sea_retail_source
        return get_sea_retail_source(product_line)
    if check_type == 'seda_retail':
        from apps.common.seda_retail import get_seda_source
        return get_seda_source(product_line)
    if check_type == 'siel_retail':
        from apps.common.siel_retail import get_siel_source
        return get_siel_source(product_line)
    if check_type == 'seg_retail':
        from apps.common.seg_retail import get_seg_source
        return get_seg_source(product_line)
    if check_type == 'sem_retail':
        from apps.common.sem_retail import get_sem_source
        return get_sem_source(product_line)
    if check_type == 'tse_retail':
        from apps.common.tse_retail import get_tse_source
        return get_tse_source(product_line)
    raise ValueError('Unsupported retail check type')


def _retailer_key(value, check_type):
    key = str(value or '').strip().lower()
    return key.replace(' ', '') if check_type == 'seda_retail' else key


def _scope(check_type, product_line, source_date):
    source = _source(check_type, product_line)
    day = date.fromisoformat(str(source_date)[:10])
    column = source.get('date_column', 'crawl_datetime')
    account = 'LOWER(BTRIM(CAST(account_name AS TEXT)))'
    if check_type == 'seda_retail':
        account = "LOWER(REPLACE(BTRIM(CAST(account_name AS TEXT)), ' ', ''))"

    if check_type == 'siel_retail':
        from apps.common.siel_retail import SIEL_BUSINESS_TIMEZONE
        condition = f"""{column} >= (%s::date::timestamp AT TIME ZONE %s)
            AND {column} < ((%s::date + 1)::timestamp AT TIME ZONE %s)"""
        params = (str(day), SIEL_BUSINESS_TIMEZONE,
                  str(day), SIEL_BUSINESS_TIMEZONE)
    elif check_type == 'retail' and source['product_key'] == 'tv':
        condition = f'{column}::timestamp >= %s::timestamp AND {column}::timestamp < %s::timestamp'
        params = (str(day), str(day + timedelta(days=1)))
    elif check_type == 'retail':
        from apps.common.sea_dates import appliance_source_date_sql
        condition = f'({appliance_source_date_sql(column)}) = %s'
        params = (str(day),)
    else:
        condition = f'LEFT(BTRIM(CAST({column} AS TEXT)), 10) = %s'
        params = (str(day),)

    return source, account, condition, params


def fetch_batch_counts(cursor, check_type, product_line, source_date):
    source, account, condition, params = _scope(check_type, product_line, source_date)
    cursor.execute(f"""
        SELECT {account} AS retailer_key,
               COUNT(DISTINCT NULLIF(BTRIM(CAST(batch_id AS TEXT)), '')) AS batch_count
        FROM {source['table_name']}
        WHERE {condition}
        GROUP BY {account}
    """, params)
    result = {}
    for row in cursor.fetchall():
        key, count = ((row['retailer_key'], row['batch_count'])
                      if isinstance(row, Mapping) else row)
        result[key] = int(count or 0)
    return result


def add_batch_counts(cursor, check, target_date):
    """Attach metadata atomically, preserving counts and validation statuses."""
    check_type = check.get('check_type')
    if check_type not in RETAIL_CHECK_TYPES or not check.get('categories'):
        return
    updates = []
    cursor.execute('SAVEPOINT layer1_retail_batch_counts')
    try:
        for category in check['categories']:
            retailers = list(category.get('retailers', []))
            for slot in category.get('time_slots', []):
                retailers.extend(slot.get('retailers', []))
            if not retailers:
                continue
            counts = fetch_batch_counts(
                cursor, check_type, category['product_line'],
                category.get('source_date') or check.get('source_date') or target_date,
            )
            for retailer in retailers:
                key = _retailer_key(retailer.get('retailer'), check_type)
                context = {
                    'check_type': check_type,
                    'product_line': category['product_line'],
                    'source_date': str(category.get('source_date') or check.get('source_date') or target_date),
                    'retailer': retailer.get('retailer'),
                }
                updates.append((retailer, counts.get(key, 0), context))
    except Exception:
        cursor.execute('ROLLBACK TO SAVEPOINT layer1_retail_batch_counts')
        cursor.execute('RELEASE SAVEPOINT layer1_retail_batch_counts')
        raise
    cursor.execute('RELEASE SAVEPOINT layer1_retail_batch_counts')
    for retailer, count, context in updates:
        retailer['batch_count'] = count
        retailer['batch_context'] = context


def fetch_batch_details(cursor, check_type, product_line, source_date, retailer):
    """Read all daily batches, using the same anchor/page rules as Layer 1."""
    source, account, condition, params = _scope(check_type, product_line, source_date)
    key = _retailer_key(retailer, check_type)
    if not key or len(key) > 200:
        raise ValueError('Invalid retailer')
    column = source.get('date_column', 'crawl_datetime')
    all_batches = check_type == 'retail' and source['product_key'] == 'tv'
    appliance = check_type == 'retail' and not all_batches
    main_anchor = check_type in {'siel_retail', 'seg_retail', 'seda_retail'} or (appliance and key != 'homedepot')
    page = "LOWER(BTRIM(CAST(page_type AS TEXT)))"
    anchor = f"{page} = 'main'" if main_anchor else 'TRUE'
    page_scope = f"{page} IN ('main', 'bsr')" if main_anchor else 'TRUE'
    applied = 'TRUE' if all_batches else 'batch_id IS NOT DISTINCT FROM (SELECT batch_id FROM latest)'
    if not all_batches:
        applied = f'EXISTS (SELECT 1 FROM latest) AND ({applied})'
    # SEA appliance counts treat a NULL anchor as no selected batch.
    if appliance:
        applied += ' AND (SELECT batch_id FROM latest) IS NOT NULL'
        if key == 'homedepot':
            from apps.common.sea_collection import homedepot_source_enabled
            if not homedepot_source_enabled(source_date):
                applied = 'FALSE'

    time_value = f"NULLIF(BTRIM(CAST({column} AS TEXT)), '')"
    time_basis = '원본 기록 시각'
    if check_type == 'siel_retail':
        time_value = f"TO_CHAR({column} AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS')"
        time_basis = 'KST'
    elif appliance and key == 'homedepot':
        time_value = f"TO_CHAR(NULLIF(BTRIM(CAST({column} AS TEXT)), '')::timestamptz AT TIME ZONE 'America/New_York', 'YYYY-MM-DD HH24:MI:SS')"
        time_basis = '미국 뉴욕 시각'

    normalized_batch = "NULLIF(BTRIM(CAST(batch_id AS TEXT)), '')"
    cursor.execute(f"""
        WITH dated_rows AS (
            SELECT * FROM {source['table_name']}
            WHERE {condition} AND {account} = %s
        ), latest AS (
            SELECT batch_id FROM dated_rows WHERE {anchor} ORDER BY id DESC LIMIT 1
        )
        SELECT {normalized_batch} AS batch_id,
               MIN({time_value}) AS started_at, MAX({time_value}) AS ended_at,
               COUNT(main_rank) FILTER (WHERE {page_scope}) AS main_count,
               COUNT(bsr_rank) FILTER (WHERE {page_scope}) AS bsr_count,
               BOOL_OR({applied}) AS applied,
               COUNT(*) AS raw_count
        FROM dated_rows
        GROUP BY {normalized_batch}
        ORDER BY MIN(id), {normalized_batch}
    """, (*params, key))
    fields = ('batch_id', 'started_at', 'ended_at', 'main_count', 'bsr_count', 'applied', 'raw_count')
    rows = [dict(row) if isinstance(row, Mapping) else dict(zip(fields, row)) for row in cursor.fetchall()]
    for row in rows:
        # Keep SQL date/retailer/batch scope identical to the detail query. IDs
        # containing commas or quotes remain a single safely quoted ID.
        query = f"""SELECT *
FROM {source['table_name']}
WHERE {condition}
  AND {account} = %s
  AND {normalized_batch} IS NOT DISTINCT FROM %s
ORDER BY id;"""
        row['sql'] = cursor.mogrify(query, (*params, key, row['batch_id'])).decode('utf-8')
    return {
        'retailer': retailer, 'source_date': str(source_date),
        'time_basis': time_basis, 'batches': rows,
        'aggregation_basis': '당일 전체 배치 반영' if all_batches else '최신 MAIN 배치 반영' if main_anchor else '최신 배치 반영',
    }
