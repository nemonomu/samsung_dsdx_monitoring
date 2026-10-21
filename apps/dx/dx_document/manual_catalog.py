"""Read collection configuration and add manual scaffolding without changing sources."""
import copy
import json
import logging
import re
from pathlib import Path
from django.db import connections, DatabaseError, transaction

COUNTRIES = {'SEA': '미국', 'SEG': '독일', 'SEIB': '스페인', 'SEM': '멕시코',
             'TSE': '태국', 'SEDA': '브라질', 'SIEL': '인도'}
PRODUCTS = {'tv': 'TV', 'ref': '냉장고', 'ldy': '세탁기', 'ldy_dryer': '건조기', 'dryer': '건조기', 'hhp': 'HHP'}
EXCLUDED = {'id', 'country', 'account_name', 'product_url', 'main_rank', 'bsr_rank'}
COMMON = {'sku', 'retailer_sku_name', 'item', 'final_sku_price', 'original_sku_price',
          'savings', 'count_of_reviews', 'star_rating', 'count_of_star_ratings',
          'calendar_week', 'crawl_datetime', 'crawl_strdatetime', 'page_type', 'batch_id',
          'sku_status', 'sku_popularity', 'discount_type', 'delivery_availability',
          'pick_up_availability', 'available_quantity_for_purchase'}
CATALOG_PATH = Path(__file__).with_name('manual_data') / 'collection_catalog.json'


def retailer_token(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def source_identity(product_line, retailer):
    line = product_line.lower()
    if line in ('tv', 'hhp'):
        country, product = 'SEA', line
    else:
        country, _, product = line.partition('_')
        country = country.upper()
    if country not in COUNTRIES or product not in PRODUCTS or not retailer_token(retailer):
        return None
    return country, product, retailer_token(retailer)


def configured_columns():
    """The shared registry is read-only, like the existing collection settings UI."""
    connection = connections['dx']
    if connection.vendor != 'postgresql':
        return json.loads(CATALOG_PATH.read_text(encoding='utf-8')), ''
    try:
        with transaction.atomic(using='dx'), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5000ms'")
            cursor.execute('''SELECT product_line, retailer, column_name
                FROM public.monitoring_retail_columns
                WHERE is_active = TRUE AND COALESCE(is_del, FALSE) = FALSE
                ORDER BY id''')
            return [dict(zip(('product_line', 'retailer', 'column_name'), row)) for row in cursor.fetchall()], ''
    except DatabaseError:
        logging.getLogger(__name__).warning('Manual collection catalog unavailable; using saved catalog')
        return json.loads(CATALOG_PATH.read_text(encoding='utf-8')), '등록 정보를 갱신하지 못해 마지막 확인한 구성을 표시합니다.'


def blank_field(name, number, label=None, direct=True):
    return {'n': number, 'field': name, 'label': label or name, 'scope': 'main · bsr',
            'page': '', 'position': '', 'original': '', 'example': '', 'note': '',
            'direct': direct, 'images': []}


def blank_profile(country, name):
    return {'country': country, 'name': name, 'region': '', 'currency': '', 'queries': {},
            'mainBase': '', 'bsr': {}, 'mainSort': '', 'bsrSort': '', 'summary': '', 'warning': ''}


def prepare_data(data, catalog=None):
    """Add missing registered fields; retain all originals and their historical variants."""
    result = copy.deepcopy(data)
    if catalog is None:
        catalog, _ = configured_columns()
    rows, profiles = result['datasets'], result['profiles']
    labels = {f['field']: f['label'] for ds in rows for f in ds['fields']}
    identities = {(key.split('/')[0], retailer_token(key.split('/')[1])): key for key in profiles}
    identities.update({(key.split('/')[0], retailer_token(profile['name'])): key for key, profile in profiles.items()})
    by_key = {(ds['retailer'], ds['category']): ds for ds in rows}
    for item in catalog:
        identity = source_identity(item['product_line'], item['retailer'])
        if identity is None:
            continue
        country, category, token = identity
        key = identities.get((country, token), country + '/' + token)
        identities[country, token] = key
        if key not in profiles:
            display = {'amazon': 'Amazon', 'bestbuy': 'Bestbuy', 'walmart': 'Walmart', 'lowes': 'Lowes',
                       'mediamarkt': 'MediaMarkt', 'otto': 'OTTO', 'homedepot': 'Home Depot',
                       'flipkart': 'Flipkart', 'casasbahia': 'Casas Bahia', 'magalu': 'Magalu'}.get(token, item['retailer'])
            profiles[key] = blank_profile(COUNTRIES[country], display)
        profile = profiles[key]
        profile.setdefault('queries', {}).setdefault(category, '')
        profile.setdefault('bsr', {}).setdefault(category, '')
        # The original Spain guide uses `dryer`; don't create a duplicate category.
        if category == 'ldy_dryer' and (key, 'dryer') in by_key:
            category = 'dryer'
        if (key, category) not in by_key:
            dataset = {'key': key + '/' + category, 'retailer': key, 'category': category,
                       'title': PRODUCTS[category], 'fields': []}
            rows.append(dataset)
            by_key[key, category] = dataset
        fields = by_key[key, category]['fields']
        name = item['column_name']
        if not any(f['field'] == name for f in fields):
            fields.append(blank_field(name, max((f['n'] for f in fields), default=0) + 1,
                                      labels.get(name), name not in EXCLUDED | {'batch_id', 'calendar_week', 'crawl_datetime', 'crawl_strdatetime', 'page_type'}))
    for retailer in profiles:
        datasets = [ds for ds in rows if ds['retailer'] == retailer and ds['category'] != 'all']
        if not datasets:
            continue
        shared = by_key.get((retailer, 'all'))
        if shared is None:
            shared = {'key': retailer + '/all', 'retailer': retailer, 'category': 'all', 'title': '공통 컬럼', 'fields': []}
            rows.append(shared)
            by_key[retailer, 'all'] = shared
        existing = {f['field'] for f in shared['fields']}
        # Match reviewed meanings wherever the field is actually registered.
        # Retain per-source text as variants; never overwrite differing descriptions.
        for source in datasets:
            for field in source['fields']:
                key = field['field']
                if key in existing or key not in COMMON or key in EXCLUDED:
                    continue
                variants = [(ds, f) for ds in datasets for f in ds['fields'] if f['field'] == key]
                if len(variants) < 2 or len({f['direct'] for _, f in variants}) != 1:
                    continue
                preferred = next((f for ds, f in variants if ds['category'] == 'ref'), field)
                common = copy.deepcopy(preferred)
                common['n'] = max((f['n'] for f in shared['fields']), default=0) + 1
                common['legacyVariants'] = [dict(category=ds['category'], **{k: f[k] for k in
                    ('label', 'page', 'position', 'original', 'example', 'note')}) for ds, f in variants]
                shared['fields'].append(common)
                existing.add(key)
    result['schemaVersion'] = 2
    return result
