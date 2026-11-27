"""Count daily batch IDs independently of the batch used for validation."""

from collections.abc import Mapping
from datetime import date, timedelta

from apps.common.source_dates import source_date_sql
from apps.common.sem_retail import sem_start_date, sem_tv_observation_retailer
from apps.dx.dx_layer1.siel_retail import jiomart


RETAIL_CHECK_TYPES = frozenset({
    'retail', 'seda_retail', 'siel_retail', 'seg_retail',
    'sem_retail', 'tse_retail', 'seib_retail', 'seuk_retail',
})


def _source(check_type, product_line):
    # Resolve identifiers through the existing fixed source registries.
    if check_type == 'retail':
        from apps.dx.dx_layer1.retail.retail_services import _get_layer1_source
        return _get_layer1_source(product_line)
    if check_type == 'seda_retail':
        from apps.common.seda_retail import get_seda_source
        return get_seda_source(product_line)
    if check_type == 'siel_retail':
        from apps.common.siel_retail import get_siel_source
        return get_siel_source(product_line)
    if check_type == 'seg_retail':
        from apps.dx.dx_layer1.seg_retail.sources import get_seg_source
        return get_seg_source(product_line)
    if check_type == 'seuk_retail':
        from apps.common.seuk_retail import get_seuk_source
        return get_seuk_source(product_line)
    if check_type == 'seib_retail':
        from apps.common.seib_retail import get_seib_source
        return get_seib_source(product_line)
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
        stamp = f"CASE WHEN {account} = 'costco' THEN ({source_date_sql(column)})::timestamp ELSE {column}::timestamp END"
        condition = f'{stamp} >= %s::timestamp AND {stamp} < %s::timestamp'
        params = (str(day), str(day + timedelta(days=1)))
    else:
        # Monitoring membership uses the recorded day, independently of the
        # time zone used to display a batch's start/end timestamps below.
        condition = f'{source_date_sql(column)} = %s'
        params = (str(day),)

    return source, account, condition, params


def _batch_count_query(check_type, product_line, source_date, *, scope_id=None):
    source, account, condition, params = _scope(check_type, product_line, source_date)
    scope_column = '%s AS scope_id, ' if scope_id is not None else ''
    sql = f"""
        SELECT {scope_column}{account} AS retailer_key,
               COUNT(DISTINCT NULLIF(BTRIM(CAST(batch_id AS TEXT)), '')) AS batch_count
        FROM {source['table_name']}
        WHERE {condition}
        GROUP BY {account}
    """
    return sql, (scope_id, *params) if scope_id is not None else params


def fetch_batch_counts(cursor, check_type, product_line, source_date):
    sql, params = _batch_count_query(check_type, product_line, source_date)
    cursor.execute(sql, params)
    result = {}
    for row in cursor.fetchall():
        key, count = ((row['retailer_key'], row['batch_count'])
                      if isinstance(row, Mapping) else row)
        result[key] = int(count or 0)
    if check_type == 'siel_retail':
        result.pop('jiomart', None)
        day = date.fromisoformat(str(source_date))
        if day >= jiomart.START or jiomart.preview(day):
            source = _source(check_type, product_line)
            ctes, p = jiomart.scope_sql(source['table_name'], day, day,
                                        include_preview=jiomart.preview(day))
            cursor.execute(f"WITH {ctes} SELECT COUNT(DISTINCT NULLIF(BTRIM(batch_id), '')) AS batch_count FROM scoped", p)
            row = cursor.fetchone()
            result['jiomart'] = int(row['batch_count'] if isinstance(row, Mapping) else row[0])
    return result


def _fetch_batch_counts_for_scopes(cursor, check_type, scopes):
    if len(scopes) < 2 or check_type == 'siel_retail':
        return [fetch_batch_counts(cursor, check_type, *scope) for scope in scopes]

    statements = [_batch_count_query(check_type, *scope, scope_id=index)
                  for index, scope in enumerate(scopes)]
    cursor.execute(' UNION ALL '.join(sql for sql, _ in statements),
                   tuple(value for _, params in statements for value in params))
    counts = [{} for _ in scopes]
    for row in cursor.fetchall():
        index, key, count = ((row['scope_id'], row['retailer_key'], row['batch_count'])
                             if isinstance(row, Mapping) else row)
        counts[index][key] = int(count or 0)
    return counts


def add_batch_counts(cursor, check, target_date):
    """Attach metadata atomically, preserving counts and validation statuses."""
    check_type = check.get('check_type')
    if check_type not in RETAIL_CHECK_TYPES or not check.get('categories'):
        return
    updates = []
    cursor.execute('SAVEPOINT layer1_retail_batch_counts')
    try:
        scopes = []
        category_retailers = []
        for category in check['categories']:
            retailers = list(category.get('retailers', []))
            for slot in category.get('time_slots', []):
                retailers.extend(slot.get('retailers', []))
            if retailers:
                scopes.append((category['product_line'],
                               category.get('source_date') or check.get('source_date') or target_date))
                category_retailers.append(retailers)
        all_counts = _fetch_batch_counts_for_scopes(cursor, check_type, scopes)
        for (product_line, source_date), retailers, counts in zip(scopes, category_retailers, all_counts):
            for retailer in retailers:
                key = _retailer_key(retailer.get('retailer'), check_type)
                context = {
                    'check_type': check_type,
                    'product_line': product_line,
                    'source_date': str(source_date),
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
    if check_type == 'siel_retail' and key == 'jiomart':
        day = date.fromisoformat(str(source_date))
        ctes, args = jiomart.scope_sql(source['table_name'], day, day, include_preview=jiomart.preview(day))
        cursor.execute(f'''WITH {ctes}
            SELECT source.batch_id,
                   TO_CHAR(MIN(source.crawl_datetime) AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') AS started_at,
                   TO_CHAR(MAX(source.crawl_datetime) AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') AS ended_at,
                   COUNT(source.main_rank) AS main_count, COUNT(source.bsr_rank) AS bsr_count,
                   BOOL_OR(latest.source_day IS NOT NULL) AS applied, COUNT(*) AS raw_count,
                   ARRAY_AGG(DISTINCT source.account_name ORDER BY source.account_name) AS account_names
            FROM scoped source LEFT JOIN latest ON source.source_day = latest.source_day
               AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
            GROUP BY source.batch_id ORDER BY MIN(source.crawl_datetime)''', args)
        fields = ('batch_id', 'started_at', 'ended_at', 'main_count', 'bsr_count', 'applied', 'raw_count', 'account_names')
        batches = [dict(row) if isinstance(row, Mapping) else dict(zip(fields, row)) for row in cursor.fetchall()]
        for batch in batches:
            batch['sql'] = jiomart.copy_batch_query(
                source['table_name'], day, batch['batch_id'], batch.pop('account_names'),
            )
        return {'retailer': retailer, 'source_date': str(day), 'time_basis': 'KST', 'batches': batches,
                'aggregation_basis': 'crawl_datetime이 가장 늦은 배치'}
    if check_type == 'seib_retail':
        from apps.common.seib_retail import ECI_APPLIANCE_PREVIEW_FROM, is_eci_appliance
        if is_eci_appliance(product_line, retailer) and str(source_date) < str(ECI_APPLIANCE_PREVIEW_FROM):
            return {'retailer': retailer, 'source_date': str(source_date), 'batches': [],
                    'time_basis': '원본 기록 시각', 'aggregation_basis': '운영 시작 전'}
    if check_type == 'seuk_retail':
        from apps.dx.dx_layer1.seuk_retail.sources import TV_START, new_tv_retailer
        if new_tv_retailer('SEUK', source['category'], retailer) and str(source_date) < str(TV_START):
            return {'retailer': retailer, 'source_date': str(source_date), 'batches': [],
                    'time_basis': '원본 기록 시각', 'aggregation_basis': '운영 시작 전'}
    sem_tv = check_type == 'sem_retail' and sem_tv_observation_retailer(product_line, retailer)
    if sem_tv and str(source_date) < str(sem_start_date(product_line, retailer)):
        return {'retailer': retailer, 'source_date': str(source_date), 'batches': [],
                'time_basis': '원본 기록 시각', 'aggregation_basis': '운영 시작 전'}
    column = source.get('date_column', 'crawl_datetime')
    is_costco = check_type == 'retail' and key == 'costco'
    all_batches = check_type == 'retail' and source['product_key'] == 'tv' and not is_costco
    appliance = check_type == 'retail' and source['product_key'] != 'tv'
    main_anchor = check_type in {'siel_retail', 'seg_retail', 'seda_retail'} or (appliance and source['product_key'] != 'ldy_dryer' and key not in ('homedepot', 'costco'))
    if check_type == 'seg_retail' and (key == 'expert' or not source.get('has_page_type', True)):
        main_anchor = False
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
    if is_costco:
        time_value = f"TO_CHAR(NULLIF(BTRIM(CAST({column} AS TEXT)), '')::timestamptz AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS')"
        time_basis = 'KST'
    elif check_type == 'siel_retail':
        time_value = f"TO_CHAR({column} AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS')"
        time_basis = 'KST'
    elif appliance and key == 'homedepot':
        time_value = f"TO_CHAR(NULLIF(BTRIM(CAST({column} AS TEXT)), '')::timestamptz AT TIME ZONE 'America/New_York', 'YYYY-MM-DD HH24:MI:SS')"
        time_basis = '미국 뉴욕 시각'

    normalized_batch = "NULLIF(BTRIM(CAST(batch_id AS TEXT)), '')"
    if sem_tv:
        anchor += f' AND {normalized_batch} IS NOT NULL'
    latest_order = 'id DESC'
    if check_type == 'sem_retail':
        from apps.common.sem_retail import sem_batch_order
        latest_order = sem_batch_order(product_line, retailer)
    cursor.execute(f"""
        WITH dated_rows AS (
            SELECT * FROM {source['table_name']}
            WHERE {condition} AND {account} = %s
        ), latest AS (
            SELECT batch_id FROM dated_rows WHERE {anchor} ORDER BY {latest_order} LIMIT 1
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
        # Copy-only raw lookup: keep values and date columns directly readable.
        query_params = [str(source_date),
                        'CasasBahia' if check_type == 'seda_retail' and retailer == 'Casas Bahia' else retailer]
        if check_type == 'seg_retail' and key == 'expert':
            query_params[1] = 'expert'
        batch_filter = 'batch_id IS NULL' if row['batch_id'] is None else 'batch_id = %s'
        if row['batch_id'] is not None:
            query_params.append(row['batch_id'])
        copy_date_scope = f'{column} >= %s'
        if check_type == 'seuk_retail' and source['product_key'] == 'tv':
            copy_date_scope += f'\n  AND {column} < %s'
            query_params.insert(1, str(date.fromisoformat(str(source_date)) + timedelta(days=1)))
        elif check_type in ('seib_retail', 'seuk_retail') or (check_type == 'seg_retail' and product_line == 'seg_ldy_dryer'):
            copy_date_scope = f'{source_date_sql(column)} = %s'
        if check_type == 'retail' and (key in ('costco', 'homedepot') or source['product_key'] == 'ldy_dryer'):
            # Reproduce the displayed batch's monitoring date in its copy SQL.
            copy_date_scope = f'{source_date_sql(column)} = %s'
        copy_account_scope = 'account_name = %s'
        if sem_tv:
            copy_date_scope = f'{source_date_sql(column)} = %s'
            copy_account_scope = f'{account} = LOWER(%s)'
            batch_filter = f'{normalized_batch} IS NULL' if row['batch_id'] is None else f'{normalized_batch} = %s'
        query = f"""SELECT *
FROM {source['table_name']}
WHERE {copy_date_scope}
  AND {copy_account_scope}
  AND {batch_filter}
ORDER BY item, {column};"""
        row['sql'] = cursor.mogrify(query, tuple(query_params)).decode('utf-8')
    return {
        'retailer': retailer, 'source_date': str(source_date),
        'time_basis': time_basis, 'batches': rows,
        'aggregation_basis': '당일 전체 배치 반영' if all_batches else '최신 MAIN 배치 반영' if main_anchor else '최신 배치 반영',
    }
