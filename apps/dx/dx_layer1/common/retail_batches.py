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


def fetch_batch_counts(cursor, check_type, product_line, source_date):
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
                updates.append((retailer, counts.get(key, 0)))
    except Exception:
        cursor.execute('ROLLBACK TO SAVEPOINT layer1_retail_batch_counts')
        cursor.execute('RELEASE SAVEPOINT layer1_retail_batch_counts')
        raise
    cursor.execute('RELEASE SAVEPOINT layer1_retail_batch_counts')
    for retailer, count in updates:
        retailer['batch_count'] = count
