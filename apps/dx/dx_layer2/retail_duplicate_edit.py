"""SKU edits scoped to the same source rows as the duplicate detail."""
from datetime import date, datetime

from apps.common.inspection_dates import resolve_monitoring_date


def source_for_table(table):
    # Lazy imports keep the detail service and edit service independent at import.
    from .anomaly_validation import services as detail
    from . import seib_null_validation

    registries = (
        ('SEA', detail.SEA_RETAIL_SOURCES),
        ('SIEL', detail.SIEL_SOURCE_CONFIG),
        ('TSE', detail.TSE_SOURCE_CONFIG),
        ('SEDA', detail.seda_duplicate_validation.SEDA_SOURCE_CONFIG),
        ('SEM', detail.sem_validation.SEM_SOURCE_CONFIG),
        ('SEIB', seib_null_validation.SEIB_SOURCE_CONFIG),
    )
    canonical = table if '.' in table else 'public.' + table
    for country, registry in registries:
        for key, source in registry.items():
            actual = source['table_name']
            actual = actual if '.' in actual else 'public.' + actual
            if canonical == actual:
                return country, {'source_key': key, **source, 'table_name': actual}
    return None


def scoped_rows(cursor, inspection_date, country, source, retailer):
    """Reuse source-specific date, page, redirect, and latest-batch policies."""
    from .anomaly_validation import services as detail
    from . import seib_null_validation

    if country == 'SEDA':
        return detail.seda_duplicate_validation.latest_rows(
            cursor, inspection_date, source, retailer)[0]
    if country == 'SEM':
        return detail.sem_validation._latest_rows(
            cursor, inspection_date, source, retailer)[0]
    if country == 'SEIB':
        return seib_null_validation.latest_rows(
            cursor, inspection_date, source, retailer)[0]
    if country == 'TSE':
        resolved = detail._resolve_tse_duplicate_retailer(source['source_key'], retailer)
        if not resolved:
            return []
        retailer = resolved[1]['retailer']
        return detail._fetch_tse_duplicate_rows(
            cursor, inspection_date, source, retailer,
            detail.tse_retailer_include_unassigned(retailer))
    mapping = resolve_monitoring_date(inspection_date, country, source['source_key'])
    resolve = (detail._resolve_sea_duplicate_retailer if country == 'SEA'
               else detail._resolve_siel_duplicate_retailer)
    retailer = resolve(source, retailer)
    if not retailer:
        return []
    fetch = (detail._fetch_sea_duplicate_rows if country == 'SEA'
             else detail._fetch_siel_duplicate_rows)
    return fetch(cursor, date.fromisoformat(mapping['source_date']), source, retailer)


def update_sku(cursor, conn, context, row_id, column, value,
               inspection_date, username, memo):
    country, source = context
    if source['table_name'] == 'public.tv_retail_com':
        return {'error': 'SEA TV 원본에는 SKU 컬럼이 없습니다', 'status': 403}
    if column != 'sku':
        return {'error': '중복 검증에서는 SKU만 수정할 수 있습니다', 'status': 403}
    if not isinstance(value, str) or not value.strip():
        return {'error': 'SKU 값을 입력하세요', 'status': 400}
    try:
        date.fromisoformat(str(inspection_date))
    except (TypeError, ValueError):
        return {'error': '검수일이 올바르지 않습니다', 'status': 400}
    table = source['table_name']
    cursor.execute(f"""
        SELECT sku, account_name, item FROM {table}
        WHERE id = %s FOR UPDATE
    """, (row_id,))
    record = cursor.fetchone()
    if not record:
        return {'error': '해당 레코드가 없습니다', 'status': 404}
    old_value, account, item = record
    # Unassigned accounts are only accepted when the existing source scope
    # explicitly includes them. Never infer their country/date from a batch ID.
    retailers = [account] if account and str(account).strip() else source.get('retailers', ())
    matching = None
    try:
        for retailer in retailers:
            matching = next((row for row in scoped_rows(
                cursor, inspection_date, country, source, retailer)
                if str(row['id']) == str(row_id)), None)
            if matching:
                break
    except ValueError:
        return {'error': '지원하지 않는 리테일러입니다', 'status': 403}
    if matching is None:
        return {'error': '현재 검수일의 최신 수집 대상이 아닙니다. 다시 조회하세요', 'status': 404}
    old_text = str(old_value) if old_value is not None else ''
    if old_text == value:
        return {'success': True, 'message': '변경 없음'}
    try:
        cursor.execute(f'UPDATE {table} SET sku = %s WHERE id = %s', (value, row_id))
        cursor.execute("""
            INSERT INTO monitoring_corrections
                (layer, correction_type, table_name, record_id, column_name,
                 old_value, new_value, crawl_date, created_id, created_at,
                 status, memo, retailer, item)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (2, 'duplicate_check', table, row_id, 'sku',
              None if old_value is None else str(old_value), value,
              inspection_date, username, datetime.now(), 'corrected', memo,
              account or retailer, str(item) if item is not None else None))
    except Exception:
        conn.rollback()
        raise
    return {'success': True, 'old_value': old_text, 'new_value': value}
