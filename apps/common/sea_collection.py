"""SEA collection launch policy, separate from the D-1 inspection date."""

from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))
HOMEDEPOT_FIRST_SOURCE_DATE = date(2026, 9, 20)
HOMEDEPOT_FIRST_INSPECTION_DATE = HOMEDEPOT_FIRST_SOURCE_DATE + timedelta(days=1)


def homedepot_source_enabled(source_date):
    return str(source_date)[:10] >= HOMEDEPOT_FIRST_SOURCE_DATE.isoformat()


def homedepot_inspection_label(inspection_date, count=0):
    if str(inspection_date)[:10] < HOMEDEPOT_FIRST_INSPECTION_DATE.isoformat():
        return '9/20 수집 예정'
    return '수집 확인 · 건수 기준 미정' if count else '수집 대기'


def collection_schedule(target_date, retailer):
    day = date.fromisoformat(str(target_date)[:10])
    if retailer == 'HomeDepot':
        day = max(day, HOMEDEPOT_FIRST_SOURCE_DATE)
    return datetime.combine(day, time(13), KST)


def homedepot_launch_scope_sql(date_expression, account_column='account_name'):
    # Both arguments are identifiers/expressions from the fixed SEA registry.
    return (
        f"(LOWER(TRIM(COALESCE({account_column}, ''))) <> 'homedepot' "
        f"OR ({date_expression}) >= '{HOMEDEPOT_FIRST_SOURCE_DATE.isoformat()}')"
    )
