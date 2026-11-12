"""Rank monitoring uses the registered Layer 1 countries and original source dates."""
from apps.common.sem_retail import SEM_SOURCE_CONFIG
from apps.dx.dx_layer1.column_statistics.services import _sources
from apps.dx.dx_layer4.collection_status.email_registry import _retailer

COUNTRIES = ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE', 'SEIB', 'SEUK')
PRODUCTS = ('TV', 'REF', 'LDY', 'LDY_DRYER')


def _rank_sources():
    for source in _sources():
        if source['country'] == 'SEM':
            # The inherited email catalog omits Coppel REF/LDY. Rank monitoring
            # follows the collection registry without changing email scope.
            accounts = {r['name']: r for r in source['retailers']}
            source = {**source, 'retailers': tuple(
                accounts[name] if name in accounts else _retailer(name)
                for name in SEM_SOURCE_CONFIG[source['key']]['retailers']
            )}
        yield source


def catalog(country):
    if country not in COUNTRIES:
        raise ValueError('Invalid country')
    sources = [s for s in _rank_sources() if s['country'] == country]
    return [{'product': p, 'retailers': next(
        [r['name'] for r in s['retailers']] for s in sources if s['product'] == p
    )} for p in PRODUCTS if any(s['product'] == p for s in sources)]


def select_source(country, product, retailer):
    for source in _rank_sources():
        if source['country'] == country and source['product'] == product:
            for account in source['retailers']:
                if account['name'] == retailer:
                    return source, account
    raise ValueError('Invalid rank source')
