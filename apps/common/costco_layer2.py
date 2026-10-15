"""Costco NULL, duplicate, and format validation policy."""
from datetime import datetime, timezone
from apps.common import sea_layer2
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer1.retail import costco, bestbuy_dryer

METRICS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
PRICES = ('final_sku_price', 'original_sku_price', 'savings')
COMMON = ('country', 'account_name', 'item', 'retailer_sku_name',
          'product_url', 'final_sku_price', *METRICS)
NULL_COLUMNS = {'tv': (*COMMON, 'screen_size'),
                'ref': (*COMMON, 'sku', 'ref_capacity'),
                'ldy': (*COMMON, 'sku', 'ldy_capacity'),
                'ldy_dryer': (*COMMON, 'capacity')}
FORMAT_COMMON = ('account_name', 'country', 'calendar_week', *METRICS, *PRICES)
FORMAT_COLUMNS = {
    'tv': (*FORMAT_COMMON, 'screen_size'),
    'ref': (*FORMAT_COMMON, 'product', 'ref_capacity', 'ref_refrigerator_type'),
    'ldy': (*FORMAT_COMMON, 'product', 'ldy_capacity', 'ldy_loading_type'),
}


def is_costco(retailer):
    return str(retailer or '').strip().casefold() == 'costco'


def dryer_source():
    return {**costco.DRYER_SOURCE, 'retailers': ('Bestbuy', 'Costco'), 'backup_table': None}


def sources(registry, *, include_dryer=False):
    result = {key: {**source, 'retailers': tuple(dict.fromkeys((*source['retailers'], 'Costco')))}
            for key, source in registry.items()}
    if include_dryer:
        result['ldy_dryer'] = dryer_source()
    return result


def tv_source(registry):
    return {**registry['tv'], 'retailers': ('Costco',), 'latest_main_batch': True}


def source_date_sql(column, alias='', retailer=None, account_column=None, product='', *, query_scope=False):
    prefix = f'{alias}.' if alias else ''
    if bestbuy_dryer.matches(product, retailer):
        return bestbuy_dryer.source_date_sql(prefix + column)
    date_sql = costco.query_date_sql if query_scope else costco.source_date_sql
    day = date_sql(prefix + column)
    day = f"CASE WHEN {day} >= '{costco.first_source_date(product)}' THEN {day} END"
    if is_costco(retailer):
        return f'({day})'
    legacy = sea_layer2.source_date_sql(column, alias, retailer, account_column)
    if retailer is not None:
        return legacy
    account = account_column or prefix + 'account_name'
    if product == 'ldy_dryer':
        legacy = bestbuy_dryer.source_date_sql(prefix + column)
    return f"(CASE WHEN LOWER(TRIM({account})) = 'costco' THEN {day} ELSE {legacy} END)"


def page_scope_sql(alias='', *, anchor=False, retailer=None, product=''):
    if product == 'ldy_dryer' or is_costco(retailer):
        return 'TRUE'
    legacy = sea_layer2.page_scope_sql(alias, anchor=anchor, retailer=retailer)
    if retailer is not None:
        return legacy
    prefix = f'{alias}.' if alias else ''
    return f"(LOWER(TRIM({prefix}account_name)) = 'costco' OR ({legacy}))"


def annotate_source_date(row, retailer=None, *, display_kst=False):
    if is_costco(row.get('account_name') or retailer):
        raw = row.get('crawl_datetime') or row.get('crawl_strdatetime')
        if raw:
            row['_source_date'] = source_date_value(raw)
            if display_kst:
                stamp = datetime.fromisoformat(str(raw).strip().replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                column = 'crawl_datetime' if row.get('crawl_datetime') else 'crawl_strdatetime'
                row[column] = stamp.astimezone(costco.KST).strftime('%Y-%m-%d %H:%M:%S')
        return row
    return sea_layer2.annotate_source_date(row, retailer)


def display_columns(product, column):
    date_column = 'crawl_datetime' if product in ('tv', 'ldy_dryer') else 'crawl_strdatetime'
    # Always retain all three ratings and all three prices for a NULL review.
    return list(dict.fromkeys(('id', date_column, 'item', 'retailer_sku_name',
                               column, *METRICS, *PRICES, 'product_url')))
