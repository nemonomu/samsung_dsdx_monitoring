from datetime import datetime, timedelta

from apps.common.db import dx_connection
from apps.common.sea_collection import (
    KST, collection_schedule, homedepot_source_enabled,
    AFTERNOON_RETAILERS, afternoon_collection_phase,
)
from .collection_repositories import SOURCES, fetch_collection
from apps.dx.dx_layer1.retail import costco, homedepot_dryer


def get_collection_status(target_date, now=None):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    rows = []
    for source in SOURCES:
        retailer, product, _table, _column = source
        afternoon = retailer.casefold() in AFTERNOON_RETAILERS
        phase = afternoon_collection_phase(target_date, retailer, current)
        if afternoon and phase is None:
            continue
        if retailer == 'Costco' and not costco.enabled(target_date, product):
            continue
        home_dryer = homedepot_dryer.matches(product, retailer)
        if home_dryer and not homedepot_dryer.enabled(target_date):
            continue
        scheduled = collection_schedule(target_date, retailer)
        row = {'retailer': retailer, 'product': product,
               'source_date': str(target_date), 'scheduled_at': scheduled.isoformat() if scheduled else None,
               'count': 0, 'main_count': 0, 'bsr_count': 0,
               'last_collected_at': None, 'batch_id': None,
               'status': 'scheduled' if scheduled and current < scheduled else 'waiting'}
        if afternoon:
            row['scheduled_end_at'] = (scheduled + timedelta(hours=5)).isoformat()
            row['collection_phase'] = phase
        enabled = retailer != 'HomeDepot' or homedepot_source_enabled(target_date)
        if enabled:
            try:
                with dx_connection() as (_conn, cursor):
                    count, last_at, batch, main_count, bsr_count = fetch_collection(cursor, source, target_date)
                row.update(count=int(count or 0), main_count=int(main_count or 0),
                           bsr_count=int(bsr_count or 0), last_collected_at=last_at, batch_id=batch)
                if 0 <= row['main_count'] < row['bsr_count']:
                    row.update(status='rank_mismatch',
                               status_reason=f"MAIN {row['main_count']}건 / BSR {row['bsr_count']}건 / MAIN이 BSR보다 적음")
                    rows.append(row)
                    continue
                if afternoon:
                    # Receipt is independent of the collection window and volume validation.
                    row['status'] = ('received' if row['count'] else
                                     'uncollected' if phase == 'complete' else
                                     'scheduled' if phase == 'pending' else 'waiting')
                    rows.append(row)
                    continue
                if row['count']:
                    row['status'] = 'received'
                    if retailer == 'Costco' and product.upper() != 'TV' and row['bsr_count'] != 100:
                        row['status'] = 'abnormal' if costco.complete(target_date, current) else 'partial'
                elif retailer == 'Costco' and costco.complete(target_date, current):
                    row['status'] = 'uncollected'
            except Exception:
                row.update(status='error', count=None, main_count=None, bsr_count=None)
        else:
            row['status'] = 'scheduled'
        rows.append(row)
    return {'source_date': str(target_date), 'timezone': 'Asia/Seoul',
            'checked_at': current.isoformat(), 'retailers': rows}


def get_dday_collection_status(target_date, now=None):
    from . import seda_collection

    current = now or datetime.now(KST)
    sea = get_collection_status(target_date, current)
    return {**sea, 'countries': [
        dict(country='SEA', source_date=str(target_date), retailers=sea['retailers']),
        seda_collection.get_collection_status(target_date, current),
    ]}
