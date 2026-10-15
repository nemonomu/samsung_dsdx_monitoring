"""SQL source-date expressions for SEA appliance collection timestamps."""

from apps.common.source_dates import source_date_sql, source_date_value
from apps.common.sea_collection import homedepot_launch_scope_sql


def appliance_source_date_value(row, date_column='crawl_strdatetime'):
    return source_date_value(row.get(date_column))


def appliance_page_scope_sql(alias='', *, anchor=False):
    prefix = f'{alias}.' if alias else ''
    page = f"UPPER(TRIM(COALESCE({prefix}page_type, '')))"
    legacy = f"{page} = 'MAIN'" if anchor else f"{page} IN ('MAIN', 'BSR')"
    return (f"(LOWER(TRIM({prefix}account_name)) = 'homedepot' OR {legacy}) AND "
            + homedepot_launch_scope_sql(
                appliance_source_date_sql(prefix + 'crawl_strdatetime', prefix + 'account_name'),
                prefix + 'account_name'))


def appliance_source_date_sql(date_column, account_column='account_name'):
    """All SEA appliances use the date recorded in the source timestamp."""
    return source_date_sql(date_column)


def appliance_query_date_sql(date_column, account_column='account_name'):
    """Preserve the existing date conversion in the separate batch lookup UI."""
    return f"""CASE
        WHEN LOWER(BTRIM(CAST({account_column} AS TEXT))) = 'homedepot'
        THEN TO_CHAR(
            NULLIF(BTRIM(CAST({date_column} AS TEXT)), '')::timestamptz
                AT TIME ZONE 'America/New_York', 'YYYY-MM-DD')
        ELSE LEFT(BTRIM(CAST({date_column} AS TEXT)), 10)
    END"""
