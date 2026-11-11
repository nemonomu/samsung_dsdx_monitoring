"""Rank monitoring uses the registered Layer 1 countries and original source dates."""
from apps.dx.dx_layer1.column_statistics.services import _sources

COUNTRIES = ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE', 'SEIB', 'SEUK')
PRODUCTS = ('TV', 'REF', 'LDY', 'LDY_DRYER')


def catalog(country):
    if country not in COUNTRIES:
        raise ValueError('Invalid country')
    sources = [s for s in _sources() if s['country'] == country]
    return [{'product': p, 'retailers': next(
        [r['name'] for r in s['retailers']] for s in sources if s['product'] == p
    )} for p in PRODUCTS if any(s['product'] == p for s in sources)]


def select_source(country, product, retailer):
    for source in _sources():
        if source['country'] == country and source['product'] == product:
            for account in source['retailers']:
                if account['name'] == retailer:
                    return source, account
    raise ValueError('Invalid rank source')
