"""Signed, environment-scoped evidence; manual checks never alter source ranks."""
import hashlib
import json

from django.conf import settings
from django.core import signing
from apps.dx.dx_layer1.models import RetailRankReview

SALT = 'retail-rank-review-v1'
RESULTS = ('구매 가능 확인', '품절 확인', '판매 종료 확인', '순위 변동 확인', '수집 오류 확인', '추가 확인 필요', '미확인')


def environment():
    return 'test' if settings.DEBUG else 'production'


def fingerprint(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def serialize(record):
    return {'result': record.result, 'memo': record.memo, 'revision': record.revision,
            'username': record.updated_by, 'updated_at': record.updated_at.isoformat(),
            'history': record.history}


def context_for(product, scope):
    return {'version': 1, 'environment': environment(), **scope,
            'item_key': product['key'], 'item': product['item'], 'sku': product['sku'],
            'name': product['name'], 'url': product['url'], 'status': product['status'],
            'cells': product['cells']}


def prepare(result, scope):
    """Computed once per snapshot; no signatures, review history or ORM reads."""
    for product in result['products']:
        product['fingerprint'] = fingerprint(context_for(product, scope))


def summary_index(products):
    keys = [p['fingerprint'] for p in products]
    if not keys:
        return {}
    # Explicit export can cover more than SQLite's bound-variable limit.
    found = {}
    for start in range(0, len(keys), 500):
        found.update(RetailRankReview.objects.filter(environment=environment(),
            fingerprint__in=keys[start:start+500]).values_list('fingerprint', 'result'))
    return found


def detail(product, scope, snapshot_token):
    context = context_for(product, scope)
    record = RetailRankReview.objects.filter(environment=environment(),
        fingerprint=product['fingerprint']).first()
    return {**{k: v for k, v in product.items() if k != 'fingerprint'},
            'review_token': signing.dumps({'context': context, 'snapshot': snapshot_token}, salt=SALT, compress=True),
            'review': serialize(record) if record else
                      {'result': '미확인', 'memo': '', 'revision': 0, 'history': []}}
