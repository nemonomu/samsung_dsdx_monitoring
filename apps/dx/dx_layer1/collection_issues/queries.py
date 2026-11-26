"""Allow-listed SELECTs for monitoring dates, across every batch."""
from datetime import date
import hashlib
from django.core.cache import cache
from apps.common.db import dx_connection
from apps.common.seib_retail import ECI_APPLIANCE_START, is_eci_appliance
from apps.common.sem_retail import sem_tv_observation_retailer
from apps.dx.dx_layer1.column_statistics.dates import active_from, day_range_sql, day_sql, date_column
from apps.dx.dx_layer1.column_statistics.services import select_source
from apps.dx.dx_layer1.seuk_retail.sources import TV_START, new_tv_retailer
from apps.dx.dx_layer1.siel_retail import jiomart
from apps.dx.dx_layer4.collection_status.email_services import _retailer_condition, _retailer_params


def selection(country, product, retailer):
    source = select_source(country, product, retailer)
    account = next(r for r in source['retailers'] if r['name'] == retailer)
    return source, account


def raw_counts(country, product, retailer, start, end):
    source, account = selection(country, product, retailer)
    if jiomart.matches(country, product, retailer):
        with dx_connection() as (_, cursor):
            cursor.execute("SET LOCAL statement_timeout = '20s'")
            ctes, params = jiomart.scope_sql(source['table_name'], start, end, include_preview=jiomart.preview(end))
            cursor.execute(f'WITH {ctes} SELECT source_day, COUNT(*) FROM scoped GROUP BY 1', params)
            return {str(day): int(count) for day, count in cursor.fetchall()}
    if country == 'SEUK':
        from apps.common.seuk_retail import FIRST_SOURCE_DATE
        start = max(start, TV_START if new_tv_retailer(country, product, retailer) else FIRST_SOURCE_DATE)
    if country == 'SEIB' and is_eci_appliance(product, retailer):
        start = max(start, ECI_APPLIANCE_START)
    sem_tv = sem_tv_observation_retailer(source['key'], retailer)
    if sem_tv:
        start = max(start, active_from(source, retailer))
    if start > end:
        return {}
    day = day_sql(source)
    batch_scope = "AND NULLIF(BTRIM(source.batch_id), '') IS NOT NULL " if sem_tv else ''
    sql = (f"SELECT {day}, COUNT(*) FROM {source['table_name']} source "
           f"WHERE {_retailer_condition(source, account, include_unassigned=False)} "
           f"AND {day_range_sql(source)} {batch_scope}GROUP BY 1 ORDER BY 1")
    with dx_connection() as (_, cursor):
        cursor.execute("SET LOCAL statement_timeout = '20s'")
        cursor.execute(sql, _retailer_params(account) + [str(start), str(end)])
        return {str(day): int(count) for day, count in cursor.fetchall()}


def daily_batch_ids(country, product, retailer, start, end):
    source, account = selection(country, product, retailer)
    if jiomart.matches(country, product, retailer):
        with dx_connection() as (_, cursor):
            cursor.execute("SET LOCAL statement_timeout = '20s'")
            ctes, params = jiomart.scope_sql(source['table_name'], start, end)
            cursor.execute(f'''WITH {ctes} SELECT source_day, ARRAY_AGG(DISTINCT batch_id ORDER BY batch_id)
                FROM scoped WHERE NULLIF(BTRIM(batch_id), '') IS NOT NULL GROUP BY 1''', params)
            return {str(day): list(ids or []) for day, ids in cursor.fetchall()}
    if new_tv_retailer(country, product, retailer):
        start = max(start, TV_START)
    if sem_tv_observation_retailer(source['key'], retailer):
        start = max(start, active_from(source, retailer))
    if country == 'SEIB' and is_eci_appliance(product, retailer):
        start = max(start, ECI_APPLIANCE_START)
    if start > end:
        return {}
    day = day_sql(source)
    batch = "NULLIF(BTRIM(CAST(source.batch_id AS TEXT)), '')"
    with dx_connection() as (_, cursor):
        cursor.execute("SET LOCAL statement_timeout = '20s'")
        cursor.execute(
            f"SELECT {day}, ARRAY_AGG(DISTINCT {batch} ORDER BY {batch}) FILTER (WHERE {batch} IS NOT NULL) "
            f"FROM {source['table_name']} source WHERE {_retailer_condition(source, account, include_unassigned=False)} "
            f"AND ({day}) BETWEEN %s AND %s GROUP BY 1 ORDER BY 1",
            _retailer_params(account) + [str(start), str(end)])
        return {str(day): list(ids or []) for day, ids in cursor.fetchall()}


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
    if jiomart.matches(country, product, retailer):
        from apps.dx.dx_layer1.siel_retail.jiomart import copy_queries
        return copy_queries(source['table_name'], date.fromisoformat(str(source_date)))
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
