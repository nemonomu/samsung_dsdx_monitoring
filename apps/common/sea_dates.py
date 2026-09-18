"""SQL source-date expressions for SEA appliance collection timestamps."""

from datetime import datetime
from zoneinfo import ZoneInfo
from apps.common.sea_collection import homedepot_launch_scope_sql


def appliance_source_date_value(row, date_column='crawl_strdatetime'):
    raw = str(row.get(date_column) or '').strip()
    if str(row.get('account_name') or '').strip().casefold() == 'homedepot' and raw:
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if stamp.tzinfo:
            return stamp.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    return raw[:10]


def appliance_page_scope_sql(alias='', *, anchor=False):
    prefix = f'{alias}.' if alias else ''
    page = f"UPPER(TRIM(COALESCE({prefix}page_type, '')))"
    legacy = f"{page} = 'MAIN'" if anchor else f"{page} IN ('MAIN', 'BSR')"
    return (f"(LOWER(TRIM({prefix}account_name)) = 'homedepot' OR {legacy}) AND "
            + homedepot_launch_scope_sql(
                appliance_source_date_sql(prefix + 'crawl_strdatetime', prefix + 'account_name'),
                prefix + 'account_name'))


def appliance_source_date_sql(date_column, account_column='account_name'):
    """Use New York dates for HomeDepot's offset-bearing UTC timestamps.

    Other retailers already store their source date in the text prefix.  Keep
    the cast inside CASE so their non-ISO timestamps are never parsed as UTC.
    Column names must come from the fixed source registry, never request data.
    """
    return f"""CASE
        WHEN LOWER(BTRIM(CAST({account_column} AS TEXT))) = 'homedepot'
        THEN TO_CHAR(
            NULLIF(BTRIM(CAST({date_column} AS TEXT)), '')::timestamptz
                AT TIME ZONE 'America/New_York', 'YYYY-MM-DD')
        ELSE LEFT(BTRIM(CAST({date_column} AS TEXT)), 10)
    END"""
