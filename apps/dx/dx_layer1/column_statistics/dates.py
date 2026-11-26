"""Monitoring source dates, independent of batch names and lookup timezones."""
from apps.common.dryer_onboarding import config as dryer_config, OPERATIONAL_FROM
from apps.common.source_dates import source_date_sql
from apps.common.sea_collection import HOMEDEPOT_FIRST_SOURCE_DATE
from apps.common.seib_retail import get_seib_source, retailer_start_date as seib_retailer_start_date
from apps.common.seuk_retail import FIRST_SOURCE_DATE as SEUK_START
from apps.common.sem_retail import sem_start_date
from apps.dx.dx_layer1.retail import costco, bestbuy_dryer, homedepot_dryer, lowes_dryer
from apps.dx.dx_layer1.seg_retail.sources import retailer_start_date, get_seg_source
from apps.dx.dx_layer1.siel_retail import jiomart
from apps.dx.dx_layer1.seuk_retail.sources import TV_START, new_tv_retailer


def date_column(source):
    return 'crawl_datetime' if source['key'] == 'sea_tv' else source['date_column']


def day_sql(source, alias='source'):
    column = f'{alias}.{date_column(source)}'
    if source['country'] == 'SIEL':
        # This existing native timestamptz source has an explicit business-day rule.
        return f"TO_CHAR({column} AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')"
    return source_date_sql(column)


def day_range_sql(source, alias='source'):
    if source['country'] == 'SIEL':
        column = f'{alias}.{date_column(source)}'
        return (f"({column} >= (%s::date::timestamp AT TIME ZONE 'Asia/Seoul') "
                f"AND {column} < ((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'))")
    return f'({day_sql(source, alias)}) BETWEEN %s AND %s'


def active_from(source, retailer):
    country, product = source['country'], source['product']
    if jiomart.matches(country, product, retailer):
        return jiomart.START
    if dryer_config(country, product, retailer):
        return OPERATIONAL_FROM
    if country == 'SEUK':
        return TV_START if new_tv_retailer(country, product, retailer) else SEUK_START
    if country == 'SEIB':
        return seib_retailer_start_date(get_seib_source(source['key']), retailer)
    if country == 'SEM':
        return sem_start_date(source['key'], retailer)
    if country == 'SEG':
        return retailer_start_date(get_seg_source(source['key']), retailer)
    if country == 'SEA':
        if retailer == 'Costco':
            return costco.first_source_date(product)
        for module in (bestbuy_dryer, homedepot_dryer, lowes_dryer):
            if module.matches(product, retailer):
                return module.FIRST_SOURCE_DATE
        if retailer == 'HomeDepot':
            return HOMEDEPOT_FIRST_SOURCE_DATE
    return None
