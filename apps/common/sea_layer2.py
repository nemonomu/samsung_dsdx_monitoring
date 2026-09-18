"""Layer 2-only HomeDepot policy; other SEA layers keep their own rollout."""

from datetime import datetime
from zoneinfo import ZoneInfo

from apps.common.sea_dates import appliance_source_date_sql
from apps.common.sea_collection import homedepot_launch_scope_sql


HOMEDEPOT = 'HomeDepot'
HOMEDEPOT_NULL_COMMON = (
    'country', 'account_name', 'item', 'sku', 'product_url',
    'retailer_sku_name', 'final_sku_price', 'star_rating',
    'count_of_star_ratings', 'count_of_reviews',
)
HOMEDEPOT_FORMAT_COMMON = (
    'account_name', 'calendar_week', 'country', 'product',
    'final_sku_price', 'original_sku_price', 'savings',
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)


def is_homedepot(retailer):
    return str(retailer or '').strip().casefold() == 'homedepot'


def layer2_sources(sources):
    result = dict(sources)
    for key in ('ref', 'ldy'):
        if key in sources:
            result[key] = dict(sources[key])
            result[key]['retailers'] = tuple(dict.fromkeys(
                (*sources[key].get('retailers', ()), HOMEDEPOT)))
    return result


def homedepot_null_columns(product):
    return (*HOMEDEPOT_NULL_COMMON, f'{product}_capacity')


def homedepot_format_columns(product):
    return (*HOMEDEPOT_FORMAT_COMMON, f'{product}_capacity')


def source_date_sql(column, alias='', retailer=None, account_column=None):
    prefix = f'{alias}.' if alias else ''
    if retailer is not None and not is_homedepot(retailer):
        return f'LEFT(TRIM(CAST({prefix}{column} AS TEXT)), 10)'
    account = account_column or prefix + 'account_name'
    if is_homedepot(retailer):
        account = f"COALESCE(NULLIF(TRIM({account}), ''), 'HomeDepot')"
    return f"({appliance_source_date_sql(prefix + column, account)})"


def page_scope_sql(alias='', *, anchor=False, retailer=None):
    prefix = f'{alias}.' if alias else ''
    page = f"UPPER(TRIM(COALESCE({prefix}page_type, '')))"
    legacy = f"{page} = 'MAIN'" if anchor else f"{page} IN ('MAIN', 'BSR')"
    if retailer is not None:
        if not is_homedepot(retailer):
            return legacy
        return homedepot_launch_scope_sql(
            source_date_sql('crawl_strdatetime', alias, retailer), "'HomeDepot'")
    return (f"(LOWER(TRIM({prefix}account_name)) = 'homedepot' OR {legacy}) AND "
            + homedepot_launch_scope_sql(
                source_date_sql('crawl_strdatetime', alias), prefix + 'account_name'))


def annotate_source_date(row, retailer=None):
    if is_homedepot(row.get('account_name') or retailer) and row.get('crawl_strdatetime'):
        raw = str(row['crawl_strdatetime']).strip()
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        row['_source_date'] = (stamp.astimezone(ZoneInfo('America/New_York')).date().isoformat()
                               if stamp.tzinfo else stamp.date().isoformat())
    return row
