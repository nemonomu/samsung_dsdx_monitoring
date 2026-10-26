"""Monitoring source dates, independent of batch names and lookup timezones."""
from apps.common.source_dates import source_date_sql
from apps.common.sea_collection import HOMEDEPOT_FIRST_SOURCE_DATE
from apps.common.seib_retail import FIRST_SOURCE_DATE as SEIB_START
from apps.common.seuk_retail import FIRST_SOURCE_DATE as SEUK_START
from apps.common.sem_retail import SEM_DRYER_FIRST_SOURCE_DATE
from apps.dx.dx_layer1.retail import costco, bestbuy_dryer, homedepot_dryer, lowes_dryer
from apps.dx.dx_layer1.seg_retail.sources import retailer_start_date, get_seg_source


def date_column(source):
    return 'crawl_datetime' if source['key'] == 'sea_tv' else source['date_column']


def day_sql(source, alias='source'):
    column = f'{alias}.{date_column(source)}'
    if source['country'] == 'SIEL':
        # This existing native timestamptz source has an explicit business-day rule.
        return f"TO_CHAR({column} AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')"
    return source_date_sql(column)


def active_from(source, retailer):
    country, product = source['country'], source['product']
    if country == 'SEUK':
        return SEUK_START
    if country == 'SEIB':
        return SEIB_START
    if country == 'SEM' and product == 'LDY_DRYER':
        return SEM_DRYER_FIRST_SOURCE_DATE
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
