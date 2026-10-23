"""Resolve monitoring selections to exact guide fields, including legacy retailer aliases."""
from urllib.parse import urlencode
from .manual_catalog import retailer_token, EXCLUDED


def key(country, product, retailer, column):
    return '|'.join((country, product, retailer_token(retailer), column))


def guide_targets(data):
    targets = {}
    common = {row['retailer']: row for row in data['datasets'] if row['category'] == 'all'}
    for row in data['datasets']:
        if row['category'] in ('all', 'hhp'):
            continue
        retailer = row['retailer']
        profile = data['profiles'][retailer]
        country, token = retailer.split('/', 1)
        product = 'LDY_DRYER' if row['category'] == 'dryer' else row['category'].upper()
        shared = common.get(retailer, {}).get('fields', [])
        deleted_common = {f['field'] for f in shared if f.get('deleted')}
        fields = {f['field']: row['category'] for f in row['fields'] if not f.get('deleted')}
        fields.update({f['field']: 'common' for f in shared if not f.get('deleted')})
        for column, scope in fields.items():
            if column in EXCLUDED or column in deleted_common:
                continue
            target = dict(retailer=retailer, country=profile['country'], category=row['category'], scope=scope, field=column)
            for alias in (token, profile['name']):
                targets[key(country, product, alias, column)] = target
    return targets


def guide_urls(data):
    return {identity: '/dx/documents/manual/?' + urlencode(dict(
        country=identity.split('|')[0], product=identity.split('|')[1],
        retailer=target['retailer'].split('/', 1)[1], column=target['field']))
        for identity, target in guide_targets(data).items()}


def requested_target(data, params):
    if not any(params.get(k) for k in ('country', 'product', 'retailer', 'column')):
        return None, ''
    identity = key(params.get('country', ''), params.get('product', ''), params.get('retailer', ''), params.get('column', ''))
    target = guide_targets(data).get(identity)
    return target, '' if target else '요청한 국가·쇼핑몰·제품군·컬럼의 가이드가 등록되어 있지 않습니다.'
