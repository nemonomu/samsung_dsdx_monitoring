"""SQL source-date expressions for SEA appliance collection timestamps."""


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
