from datetime import datetime

from apps.common.db import dx_connection
from apps.common.sea_collection import (
    KST, collection_schedule, homedepot_source_enabled,
)
from .collection_repositories import SOURCES, fetch_collection


def get_collection_status(target_date, now=None):
    current = now or datetime.now(KST)
    current = current.replace(tzinfo=KST) if current.tzinfo is None else current.astimezone(KST)
    rows = []
    for source in SOURCES:
        retailer, product, _table, _column = source
        scheduled = collection_schedule(target_date, retailer)
        row = {'retailer': retailer, 'product': product,
               'source_date': str(target_date), 'scheduled_at': scheduled.isoformat(),
               'count': 0, 'main_count': 0, 'bsr_count': 0,
               'last_collected_at': None, 'batch_id': None,
               'status': 'scheduled' if current < scheduled else 'waiting'}
        enabled = retailer != 'HomeDepot' or homedepot_source_enabled(target_date)
        if enabled:
            try:
                with dx_connection() as (_conn, cursor):
                    count, last_at, batch, main_count, bsr_count = fetch_collection(cursor, source, target_date)
                row.update(count=int(count or 0), main_count=int(main_count or 0),
                           bsr_count=int(bsr_count or 0), last_collected_at=last_at, batch_id=batch)
                if row['count']:
                    row['status'] = 'received'
            except Exception:
                row.update(status='error', count=None, main_count=None, bsr_count=None)
        else:
            row['status'] = 'scheduled'
        rows.append(row)
    return {'source_date': str(target_date), 'timezone': 'Asia/Seoul',
            'checked_at': current.isoformat(), 'retailers': rows}
