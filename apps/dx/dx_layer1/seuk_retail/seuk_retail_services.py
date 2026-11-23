"""SEUK Layer 1 receipt checks; historical volume comparison is shared."""
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.dryer_onboarding import decorate_row
from apps.common.seuk_retail import FIRST_SOURCE_DATE
from .sources import (
    SEUK_SOURCE_CONFIG, TV_START, COLLECTION_WINDOW, collection_phase, latest_scope, new_tv_retailer,
    retailer_start_date,
)


def get_layer1_stats(cursor, target_date, now=None):
    phase = collection_phase(target_date, now)
    categories, failed = [], []
    for key, source in SEUK_SOURCE_CONFIG.items():
        mapping = resolve_monitoring_date(target_date, 'SEUK', key)
        retailers = []
        for retailer in source['retailers']:
            active_from = str(retailer_start_date(source, retailer))
            if mapping['source_date'] < active_from:
                continue
            cte, scope, params = latest_scope(source, mapping['source_date'], mapping['source_date'], retailer)
            cursor.execute(f'{cte} SELECT COUNT(*), COUNT(source.main_rank), COUNT(source.bsr_rank), MAX(source.batch_id) {scope}', params)
            total, main, bsr, batch = cursor.fetchone()
            status = ('PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting'
                      else 'OK' if total else 'CRITICAL')
            row = dict(retailer=retailer, actual=total, count=total, raw_count=total,
                       main_count=main, bsr_count=bsr, batch_id=batch, expected=None,
                       collection_phase=phase, active_from=active_from, status=status,
                       status_basis='historical_volume')
            if new_tv_retailer('SEUK', source['category'], retailer):
                row['missing_by_raw_count'] = True
            decorate_row(row, 'SEUK', source['category'], target_date)
            retailers.append(row)
            if row['status'] == 'CRITICAL':
                failed.append(dict(source=source['display_name'] + f' ({retailer})',
                                   error_type='수집 데이터 없음', expected=None, actual=0,
                                   timestamp=mapping['source_date']))
        total = sum(r['actual'] for r in retailers)
        main = sum(r['main_count'] for r in retailers)
        bsr = sum(r['bsr_count'] for r in retailers)
        status = ('PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting'
                  else 'CRITICAL' if any(r['status'] == 'CRITICAL' for r in retailers) else 'OK')
        categories.append(dict(name=source['category'], category=source['category'], product_line=key,
                               table_name=source['table_name'], actual=total, total=total,
                               main_count=main, bsr_count=bsr, expected=None, status=status,
                               retailers=retailers, **mapping))
    status = ('PENDING' if phase == 'pending' else 'COLLECTING' if phase == 'collecting'
              else 'CRITICAL' if failed else 'OK')
    return {'check': dict(name='SEUK Retail', description=(
                          f'영국 Currys TV/REF/LDY/LDY_DRYER · {FIRST_SOURCE_DATE} 시작 / '
                          f'AO REF/LDY/LDY_DRYER · 2026-11-01 시작 / Amazon·Argos TV · {TV_START} 시작'),
                          check_type='seuk_retail', country='SEUK', status=status, phase=phase,
                          collection_window=COLLECTION_WINDOW, expected=None,
                          actual=sum(c['actual'] for c in categories), total=sum(c['total'] for c in categories),
                          categories=categories, inspection_date=str(target_date), source_date=str(target_date),
                          offset_days=0, active_from=str(FIRST_SOURCE_DATE), source_keys=list(SEUK_SOURCE_CONFIG)), 'failed_items': failed}
