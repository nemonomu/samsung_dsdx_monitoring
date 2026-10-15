"""Default retail collection-date policy: the date recorded in the source DB."""


def source_date_value(value):
    """Extract the recorded date without converting a timestamp's UTC offset."""
    return str(value or '').strip()[:10]


def source_date_sql(column):
    """Use a trusted raw collection timestamp column, never user input."""
    return f"LEFT(BTRIM(CAST({column} AS TEXT)), 10)"
