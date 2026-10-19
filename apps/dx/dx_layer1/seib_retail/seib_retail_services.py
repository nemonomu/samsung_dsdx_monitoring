"""SEIB Layer 1 receipt checks; historical volume comparison is shared."""
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seib_retail import (
    SEIB_SOURCE_CONFIG, RETAILER, collection_phase, enabled, latest_scope,
)


def get_layer1_stats(cursor, target_date, now=None):
    phase = collection_phase(target_date, now)
    categories, failed = [], []
    for key, source in SEIB_SOURCE_CONFIG.items():
        mapping = resolve_monitoring_date(target_date, 'SEIB', key)
        total = main = bsr = 0
        batch = None
        if enabled(target_date):
            cte, scope, params = latest_scope(source, mapping['source_date'], mapping['source_date'])
            cursor.execute(f'{cte} SELECT COUNT(*), COUNT(source.main_rank), COUNT(source.bsr_rank), MAX(source.batch_id) {scope}', params)
            total, main, bsr, batch = cursor.fetchone()
        status = ('PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting'
                  else 'OK' if total else 'CRITICAL')
        row = dict(retailer=RETAILER, actual=total, count=total, raw_count=total,
                   main_count=main, bsr_count=bsr, batch_id=batch, expected=None,
                   collection_phase=phase, status=status, status_basis='historical_volume')
        categories.append(dict(name=source['category'], category=source['category'], product_line=key,
                               table_name=source['table_name'], actual=total, total=total,
                               main_count=main, bsr_count=bsr, expected=None, status=status,
                               retailers=[row] if enabled(target_date) else [], **mapping))
        if status == 'CRITICAL':
            failed.append(dict(source=source['display_name'] + ' (MediaMarkt)',
                               error_type='수집 데이터 없음', expected=None, actual=0,
                               timestamp=mapping['source_date']))
    status = ('PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting'
              else 'CRITICAL' if failed else 'OK')
    return {'check': dict(name='SEIB Retail', description='스페인 MediaMarkt TV/REF/LDY/LDY_DRYER 당일 수집',
                          check_type='seib_retail', country='SEIB', status=status, phase=phase,
                          collection_window='KST 01:00~04:00', expected=None,
                          actual=sum(c['actual'] for c in categories), total=sum(c['total'] for c in categories),
                          categories=categories, inspection_date=str(target_date), source_date=str(target_date),
                          offset_days=0, source_keys=list(SEIB_SOURCE_CONFIG)), 'failed_items': failed}
