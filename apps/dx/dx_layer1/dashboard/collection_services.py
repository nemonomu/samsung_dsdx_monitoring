import logging
from datetime import date, datetime, timedelta

from django.conf import settings
from psycopg2 import Error
from time import monotonic

from apps.common.db import dx_connection
from apps.common.sea_collection import (
    KST, collection_schedule, homedepot_source_enabled,
    AFTERNOON_RETAILERS, afternoon_collection_phase,
)
from apps.dx.dx_layer1.retail import costco, homedepot_dryer
from .collection_receipts import receipt_state
from .collection_repositories import SOURCES, fetch_collection


logger = logging.getLogger(__name__)


def get_collection_status(target_date, now=None, *, read=None):
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
            row['schedule_phase'] = phase
        if retailer == 'Costco':
            row['scheduled_end_at'] = (scheduled + timedelta(hours=2)).isoformat()
        elif retailer == 'HomeDepot' and not home_dryer:
            row['scheduled_end_at'] = (scheduled + timedelta(hours=1)).isoformat()
        enabled = retailer != 'HomeDepot' or homedepot_source_enabled(target_date)
        if enabled:
            try:
                if read:
                    complete = (phase == 'complete' or date.fromisoformat(str(target_date)) < current.date()
                                or (retailer == 'Costco' and costco.complete(target_date, current)))
                    counts = read(fetch_collection, source, ('SEA', product, retailer), complete)
                else:
                    with dx_connection() as (_conn, cursor):
                        counts = fetch_collection(cursor, source, target_date)
                count, last_at, batch, main_count, bsr_count = counts
                row.update(count=int(count or 0), main_count=int(main_count or 0),
                           bsr_count=int(bsr_count or 0), last_collected_at=last_at, batch_id=batch)
                receipt = receipt_state('SEA', product, retailer, target_date, current, counts)
                if not receipt and not getattr(settings, 'DX_DDAY_RECEIPTS_DIR', None):
                    if 0 <= row['main_count'] < row['bsr_count']:
                        row.update(status='rank_mismatch',
                                   status_reason=f"MAIN {row['main_count']}건 / BSR {row['bsr_count']}건 / MAIN이 BSR보다 적음")
                    elif afternoon:
                        row['status'] = ('received' if row['count'] else
                                         'uncollected' if phase == 'complete' else
                                         'scheduled' if phase == 'pending' else 'waiting')
                    elif row['count']:
                        row['status'] = 'received'
                        if retailer == 'Costco' and product.upper() == 'REF' and row['bsr_count'] != 100:
                            row['status'] = 'abnormal' if costco.complete(target_date, current) else 'partial'
                    elif retailer == 'Costco' and costco.complete(target_date, current):
                        row['status'] = 'uncollected'
                elif receipt != 'committed':
                    end = datetime.fromisoformat(row['scheduled_end_at']) if row.get('scheduled_end_at') else None
                    if receipt == 'running':
                        row['status'] = 'collecting'
                    elif (end and current >= end) or current.date() > target_date:
                        row['status'] = 'unconfirmed'
                    elif row['count']:
                        row['status'] = 'collecting'
                elif not row['count']:
                    row['status'] = 'uncollected'
                elif 0 <= row['main_count'] < row['bsr_count']:
                    row.update(status='rank_mismatch',
                               status_reason=f"MAIN {row['main_count']}건 / BSR {row['bsr_count']}건 / MAIN이 BSR보다 적음")
                elif retailer == 'Costco' and product.upper() == 'REF' and row['bsr_count'] != 100:
                    row['status'] = 'abnormal'
                else:
                    row['status'] = 'received'
                row['collection_phase'] = ('complete' if row['status'] in
                                           ('received', 'uncollected', 'rank_mismatch', 'abnormal')
                                           else row['status'])
            except Exception:
                row.update(status='error', count=None, main_count=None, bsr_count=None)
        else:
            row['status'] = 'scheduled'
        rows.append(row)
    return {'source_date': str(target_date), 'timezone': 'Asia/Seoul',
            'checked_at': current.isoformat(), 'retailers': rows}


def get_dday_collection_status(target_date, now=None, *, reuse_normal=False):
    from . import seda_collection
    from .collection_revisions import CollectionReads

    current = now or datetime.now(KST)
    deadline = monotonic() + 18
    with dx_connection(connect_timeout=3) as (connection, cursor):
        connection.autocommit = True
        cursor.execute('SET default_transaction_read_only = on')
        cursor.execute("SET statement_timeout = '1500ms'")
        revisions = (CollectionReads(target_date, cursor)
                     if reuse_normal and getattr(settings, 'DX_DDAY_COLLECTION_REVISIONS', False) else None)

        def read(fetch, source, scope, complete):
            if monotonic() >= deadline:
                raise TimeoutError('D-DAY query budget exhausted')
            if revisions:
                return revisions.read(fetch, source, scope, complete)
            return fetch(cursor, source, target_date)

        seda = seda_collection.get_collection_status(target_date, current, read=read)
        sea = get_collection_status(target_date, current, read=read)
        countries = [dict(country='SEA', source_date=str(target_date), retailers=sea['retailers']), seda]
        result = {**sea, 'countries': countries}
        if revisions:
            try:
                revisions.store(countries)
                result.update(revision_reused=revisions.reused, source_reads=revisions.source_reads)
            except (Error, OSError, ValueError):
                logger.warning("Could not retain D-DAY collection counts", exc_info=True)
        return result
