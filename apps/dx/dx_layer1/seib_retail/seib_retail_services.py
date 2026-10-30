"""SEIB receipt checks, with independent retailer batches and deadlines."""
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.dryer_onboarding import decorate_row
from apps.common.seib_retail import (
    SEIB_SOURCE_CONFIG, collection_phase, enabled, latest_scope, active_retailers,
)

_PRIORITY = {'OK': 0, 'PENDING': 1, 'COLLECTING': 2, 'CRITICAL': 3}


def _status(rows, fallback):
    return max((r['status'] for r in rows), key=_PRIORITY.get, default=fallback)


def get_layer1_stats(cursor, target_date, now=None):
    phase = collection_phase(target_date, now)
    fallback = 'PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting' else 'OK'
    categories, failed = [], []
    for key, source in SEIB_SOURCE_CONFIG.items():
        mapping = resolve_monitoring_date(target_date, 'SEIB', key)
        retailers = []
        for name in active_retailers(source, mapping['source_date']):
            row_phase = collection_phase(target_date, now, source=source, retailer=name)
            cte, scope, params = latest_scope(source, mapping['source_date'], mapping['source_date'], name)
            cursor.execute(f'{cte} SELECT COUNT(*), COUNT(source.main_rank), COUNT(source.bsr_rank), MAX(source.batch_id) {scope}', params)
            total, main, bsr, batch = cursor.fetchone()
            status = ('PENDING' if row_phase == 'pending' else 'COLLECTING' if row_phase == 'collecting'
                      else 'OK' if total else 'CRITICAL')
            row = decorate_row(dict(retailer=name, actual=total, count=total, raw_count=total,
                       main_count=main, bsr_count=bsr, batch_id=batch, expected=None,
                       collection_phase=row_phase, status=status, status_basis='historical_volume'),
                       'SEIB', key, mapping['source_date'])
            if name == 'ECI':
                row['collection_window'] = 'KST 08:00~09:00'
            retailers.append(row)
            if row['status'] == 'CRITICAL':
                failed.append(dict(source=source['display_name'] + f' ({name})',
                                   error_type='수집 데이터 없음', expected=None, actual=0,
                                   timestamp=mapping['source_date']))
        total = sum(r['raw_count'] for r in retailers)
        categories.append(dict(name=source['category'], category=source['category'], product_line=key,
                               table_name=source['table_name'], actual=total, total=total,
                               main_count=sum(r['main_count'] for r in retailers),
                               bsr_count=sum(r['bsr_count'] for r in retailers), expected=None,
                               status=_status(retailers, fallback), retailers=retailers, **mapping))
    return {'check': dict(name='SEIB Retail', description='스페인 Retail TV/REF/LDY/LDY_DRYER 당일 수집',
                          check_type='seib_retail', country='SEIB', status=_status(categories, fallback), phase=phase,
                          collection_window='KST 01:00~04:00 (MediaMarkt)', expected=None,
                          actual=sum(c['actual'] for c in categories), total=sum(c['total'] for c in categories),
                          categories=categories, inspection_date=str(target_date), source_date=str(target_date),
                          offset_days=0, source_keys=list(SEIB_SOURCE_CONFIG)), 'failed_items': failed}
