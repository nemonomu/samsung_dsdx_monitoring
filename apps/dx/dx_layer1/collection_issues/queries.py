"""Allow-listed SELECTs for original collection dates, across every batch."""
from datetime import date
import hashlib
from django.core.cache import cache
from apps.common.db import dx_connection
from apps.dx.dx_layer1.column_statistics.dates import day_sql, date_column
from apps.dx.dx_layer1.column_statistics.services import select_source
from apps.dx.dx_layer4.collection_status.email_services import _retailer_condition, _retailer_params


def selection(country, product, retailer):
    source = select_source(country, product, retailer)
    account = next(r for r in source['retailers'] if r['name'] == retailer)
    return source, account


def raw_counts(country, product, retailer, start, end):
    source, account = selection(country, product, retailer)
    day = day_sql(source)
    sql = (f"SELECT {day}, COUNT(*) FROM {source['table_name']} source "
           f"WHERE {_retailer_condition(source, account, include_unassigned=False)} "
           f"AND ({day}) BETWEEN %s AND %s GROUP BY 1 ORDER BY 1")
    with dx_connection() as (_, cursor):
        cursor.execute("SET LOCAL statement_timeout = '20s'")
        cursor.execute(sql, _retailer_params(account) + [str(start), str(end)])
        return {str(day): int(count) for day, count in cursor.fetchall()}


def first_observed(country, product, retailer):
    """Earliest surviving original day; not proof of an authoritative launch date."""
    key = 'collection-first-original:v1:' + hashlib.sha256(
        repr((country,product,retailer)).encode()).hexdigest()
    cached = cache.get(key)
    if cached:
        return date.fromisoformat(cached)
    source, account = selection(country, product, retailer)
    day = day_sql(source)
    with dx_connection() as (_, cursor):
        cursor.execute("SET LOCAL statement_timeout = '20s'")
        cursor.execute(
            f"SELECT MIN({day}) FROM {source['table_name']} source "
            f"WHERE {_retailer_condition(source,account,include_unassigned=False)} "
            f"AND ({day}) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'",
            _retailer_params(account))
        value = cursor.fetchone()[0]
    if not value:
        return None
    parsed = date.fromisoformat(value)
    cache.set(key, str(parsed), 3600)
    return parsed


def sql_queries(country, product, retailer, source_date):
    source, account = selection(country, product, retailer)
    # All identifiers come from the registry; only normalized aliases and dates
    # become SQL literals. These queries are displayed/copied, never executed here.
    literal = lambda v: "'" + str(v).replace("'", "''") + "'"
    aliases = ', '.join(literal(v) for v in dict.fromkeys(_retailer_params(account)))
    where = (f"FROM {source['table_name']} AS source\n"
             f"WHERE LOWER(BTRIM(CAST(source.{source['account_column']} AS TEXT))) IN ({aliases})\n"
             f"  AND {day_sql(source)} = {literal(source_date)}")
    column = date_column(source)
    return {
        'count': f'SELECT COUNT(*) AS collected_rows\n{where};',
        'rows': f'SELECT source.*\n{where}\nORDER BY source.{column}, source.batch_id;',
        'batches': ("SELECT source.batch_id, COUNT(*) AS collected_rows,\n"
                    f"       MIN(CAST(source.{column} AS TEXT)) AS first_collection_timestamp,\n"
                    f"       MAX(CAST(source.{column} AS TEXT)) AS last_collection_timestamp\n"
                    f"{where}\nGROUP BY source.batch_id\nORDER BY source.batch_id;"),
    }
