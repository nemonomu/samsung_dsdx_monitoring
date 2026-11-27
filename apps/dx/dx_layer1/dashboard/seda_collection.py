"""Casas Bahia D-DAY receipt only; SEDA D-1 inspection stays independent."""
from datetime import date, datetime, time

from django.conf import settings

from apps.common.db import dx_connection
from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql
from .collection_receipts import receipt_state

from .collection_revisions import batch_revision


def fetch_collection(cursor, source, target_date, *, revision_only=False, with_revision=False):
    day = source_date_sql('source.' + source['date_column'])
    account = "LOWER(REPLACE(BTRIM(source.account_name), ' ', ''))"
    revision = batch_revision(source['date_column'], page_type=True) if revision_only or with_revision else ''
    counts = (f"COUNT(*), MAX(source.{source['date_column']}), MAX(source.batch_id), "
              "COUNT(source.main_rank), COUNT(source.bsr_rank)")
    projection = revision if revision_only else f"{counts}, {revision}" if with_revision else counts
    cursor.execute(f"""
        WITH dated AS (
            SELECT source.* FROM {source['table_name']} source
            WHERE {day} = %s AND {account} = 'casasbahia'
              AND LOWER(BTRIM(source.page_type)) IN ('main', 'bsr')
        ), latest AS (
            SELECT batch_id FROM dated ORDER BY id DESC LIMIT 1
        )
        SELECT {projection}
        FROM dated source JOIN latest
          ON source.batch_id IS NOT DISTINCT FROM latest.batch_id
    """, [str(target_date)])
    values = cursor.fetchone()
    if revision_only:
        return values[0]
    return values or (0, None, None, 0, 0)


def get_collection_status(target_date, now, *, read=None):
    day = date.fromisoformat(str(target_date))
    start = datetime.combine(day, time(9), KST)
    end = datetime.combine(day, time(15), KST)
    current = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    phase = 'pending' if current < start else 'collecting' if current < end else 'complete'
    rows = []
    for source in SEDA_SOURCE_CONFIG.values():
        row = dict(country='SEDA', retailer='Casas Bahia', product=source['category'],
                   source_date=str(day), scheduled_at=start.isoformat(), scheduled_end_at=end.isoformat(),
                   schedule_phase=phase, count=0, main_count=0, bsr_count=0,
                   last_collected_at=None, last_collected_timezone='DB 원본', batch_id=None)
        try:
            if read:
                counts = read(fetch_collection, source, ('SEDA', row['product'], row['retailer']), phase == 'complete')
            else:
                with dx_connection() as (_, cursor):
                    counts = fetch_collection(cursor, source, day)
            count, stamp, batch, main, bsr = counts
            row.update(count=int(count or 0), main_count=int(main or 0), bsr_count=int(bsr or 0),
                       last_collected_at=stamp, batch_id=batch)
            receipt = receipt_state('SEDA', row['product'], row['retailer'], day, current, counts)
            if not receipt and not getattr(settings, 'DX_DDAY_RECEIPTS_DIR', None):
                row['status'] = ('received' if row['count'] else 'uncollected' if phase == 'complete'
                                 else 'scheduled' if phase == 'pending' else 'waiting')
                row['collection_phase'] = phase
            elif receipt == 'committed':
                row['status'] = 'received' if row['count'] else 'uncollected'
                row['collection_phase'] = 'complete'
            else:
                row['status'] = ('collecting' if receipt == 'running' else 'unconfirmed' if current >= end else 'collecting' if row['count']
                                 else 'scheduled' if phase == 'pending' else 'waiting')
                row['collection_phase'] = row['status']
        except Exception:
            row.update(status='error', count=None, main_count=None, bsr_count=None)
        rows.append(row)
    return dict(country='SEDA', source_date=str(day), retailers=rows,
                display_time_basis='DB 원본', collection_window='KST 09:00~15:00')
