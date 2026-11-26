"""Rank monitoring uses the registered Layer 1 countries and original source dates."""
from apps.common.sem_retail import SEM_LAYER1_RETAILERS, sem_tv_observation_retailer
from apps.common.seib_retail import is_eci_appliance
from apps.dx.dx_layer1.column_statistics.services import _sources
from apps.dx.dx_layer4.collection_status.email_registry import _retailer
from apps.dx.dx_layer1.siel_retail import jiomart
from apps.dx.dx_layer1.seuk_retail.sources import new_tv_retailer

COUNTRIES = ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE', 'SEIB', 'SEUK')
PRODUCTS = ('TV', 'REF', 'LDY', 'LDY_DRYER')


def supports_bsr(country, product, retailer):
    return ((country == 'SEIB' and is_eci_appliance(product, retailer))
            or jiomart.matches(country, product, retailer)
            or new_tv_retailer(country, product, retailer)
            or (country == 'SEM' and product == 'TV' and bool(sem_tv_observation_retailer('sem_tv', retailer))))


def _rank_sources():
    for source in _sources():
        if source['country'] == 'SEM':
            # The inherited email catalog omits Coppel REF/LDY. Rank monitoring
            # follows the collection registry without changing email scope.
            accounts = {r['name']: r for r in source['retailers']}
            source = {**source, 'retailers': tuple(
                accounts[name] if name in accounts else _retailer(name)
                for name in SEM_LAYER1_RETAILERS[source['key']]
            )}
        yield source


def catalog(country):
    if country not in COUNTRIES:
        raise ValueError('Invalid country')
    sources = [s for s in _rank_sources() if s['country'] == country]
    by_product = {s['product']: s for s in sources}
    result = []
    for product in PRODUCTS:
        if product not in by_product:
            continue
        retailers = [r['name'] for r in by_product[product]['retailers']]
        entry = {'product': product, 'retailers': retailers}
        bsr_retailers = [name for name in retailers if supports_bsr(country, product, name)]
        if bsr_retailers:
            entry['bsr_retailers'] = bsr_retailers
        result.append(entry)
    return result


def select_source(country, product, retailer):
    for source in _rank_sources():
        if source['country'] == country and source['product'] == product:
            for account in source['retailers']:
                if account['name'] == retailer:
                    return source, account
    raise ValueError('Invalid rank source')
