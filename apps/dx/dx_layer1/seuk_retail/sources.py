from datetime import date, time

from apps.common import seuk_retail
from apps.common.source_dates import source_date_value

TV_START = date(2026, 11, 22)
TV_RETAILERS = ('Amazon', 'Argos')
TV_RETAILER_KEYS = frozenset(name.casefold() for name in TV_RETAILERS)
COLLECTION_START = time(1)
COLLECTION_END = time(6)
COLLECTION_WINDOW = f'KST {COLLECTION_START:%H:%M}~{COLLECTION_END:%H:%M}'
COLUMN_ALERT_EXCLUSIONS = {'amazon': 'count_of_reviews', 'argos': 'is_redirect'}

SEUK_SOURCE_CONFIG = {
    **seuk_retail.SEUK_SOURCE_CONFIG,
    'seuk_tv': {
        **seuk_retail.SEUK_SOURCE_CONFIG['seuk_tv'],
        'retailers': (*seuk_retail.SEUK_SOURCE_CONFIG['seuk_tv']['retailers'], *TV_RETAILERS),
    },
}


def new_tv_retailer(country, product, retailer):
    return (country == 'SEUK' and str(product).upper() == 'TV'
            and seuk_retail.seuk_retailer_key(retailer) in TV_RETAILER_KEYS)


def retailer_start_date(source, retailer):
    if new_tv_retailer('SEUK', source['category'], retailer):
        return TV_START
    return seuk_retail.retailer_start_date(source, retailer)


def collection_phase(day, now=None):
    return seuk_retail.collection_phase(day, now, start=COLLECTION_START, end=COLLECTION_END)


def latest_scope(source, start, end, retailer):
    start = max(source_date_value(start), str(retailer_start_date(source, retailer)))
    return seuk_retail.latest_scope(source, start, end, retailer)
