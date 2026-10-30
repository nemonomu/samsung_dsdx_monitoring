"""Casas Bahia D-DAY receipt only; SEDA D-1 inspection stays independent."""
from datetime import date, datetime, time

from apps.common.db import dx_connection
from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.common.sea_collection import KST
from apps.common.source_dates import source_date_sql


def fetch_collection(cursor, source, target_date):
    day = source_date_sql('source.' + source['date_column'])
    account = "LOWER(REPLACE(BTRIM(source.account_name), ' ', ''))"
    cursor.execute(f"""
        WITH dated AS (
            SELECT source.* FROM {source['table_name']} source
            WHERE {day} = %s AND {account} = 'casasbahia'
              AND LOWER(BTRIM(source.page_type)) IN ('main', 'bsr')
        ), latest AS (
            SELECT batch_id FROM dated ORDER BY id DESC LIMIT 1
        )
        SELECT COUNT(*), MAX(source.{source['date_column']}), MAX(source.batch_id),
               COUNT(source.main_rank), COUNT(source.bsr_rank)
        FROM dated source JOIN latest
          ON source.batch_id IS NOT DISTINCT FROM latest.batch_id
    """, [str(target_date)])
    return cursor.fetchone() or (0, None, None, 0, 0)


def get_collection_status(target_date, now):
    day = date.fromisoformat(str(target_date))
    start = datetime.combine(day, time(9), KST)
    end = datetime.combine(day, time(15), KST)
    current = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    phase = 'pending' if current < start else 'collecting' if current < end else 'complete'
    rows = []
    for source in SEDA_SOURCE_CONFIG.values():
        row = dict(country='SEDA', retailer='Casas Bahia', product=source['category'],
                   source_date=str(day), scheduled_at=start.isoformat(), scheduled_end_at=end.isoformat(),
                   collection_phase=phase, count=0, main_count=0, bsr_count=0,
                   last_collected_at=None, last_collected_timezone='DB 원본', batch_id=None)
        try:
            with dx_connection() as (_, cursor):
                count, stamp, batch, main, bsr = fetch_collection(cursor, source, day)
            row.update(count=int(count or 0), main_count=int(main or 0), bsr_count=int(bsr or 0),
                       last_collected_at=stamp, batch_id=batch)
            row['status'] = ('received' if row['count'] else 'uncollected' if phase == 'complete'
                             else 'scheduled' if phase == 'pending' else 'waiting')
        except Exception:
            row.update(status='error', count=None, main_count=None, bsr_count=None)
        rows.append(row)
    return dict(country='SEDA', source_date=str(day), retailers=rows,
                display_time_basis='DB 원본', collection_window='KST 09:00~15:00')
