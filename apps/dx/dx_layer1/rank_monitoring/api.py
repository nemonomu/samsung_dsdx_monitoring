import csv
import io
import math
import json
import logging
from datetime import date, timedelta, timezone as tz

from django.core import signing
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.dx.dx_layer1.common.context import build_context
from apps.dx.dx_layer1.models import RetailRankReview
from .sources import COUNTRIES, catalog, select_source
from . import reviews, snapshots, listing

logger = logging.getLogger(__name__)


@require_GET
@ensure_csrf_cookie
def page(request, mode, country):
    if mode not in ('all', 'samsung') or country not in COUNTRIES:
        raise Http404
    section = f'rank_{mode}_{country}'
    context = build_context(section, request)
    today = timezone.localdate(timezone=tz(timedelta(hours=9)))
    context.update(section_title=f'{country} Retail · ' + ('삼성 제품 순위' if mode == 'samsung' else '전체 상품 순위'),
                   rank_config={'country': country, 'mode': mode, 'catalog': catalog(country),
                                'date': str(today), 'results': reviews.RESULTS})
    return render(request, 'dx_layer1_rank_monitoring.html', context)


def private(response):
    response['Cache-Control'] = 'private, no-store'
    return response


def requested_scope(request):
    country, product, retailer = (request.GET.get(k, '') for k in ('country', 'product', 'retailer'))
    mode = request.GET.get('mode', 'all')
    day = date.fromisoformat(request.GET.get('date', ''))
    today = timezone.localdate(timezone=tz(timedelta(hours=9)))
    if mode not in ('all', 'samsung') or day > today or day < date(2000, 1, 2):
        raise ValueError
    select_source(country, product, retailer)
    return {'country': country, 'product': product, 'retailer': retailer, 'date': str(day)}, mode


def requested_snapshot(request):
    scope, mode = requested_scope(request)
    snapshot = snapshots.pinned(request.GET.get('snapshot', ''))
    if snapshot['scope'] != scope:
        raise ValueError
    return snapshot, mode


def review_index(products):
    try:
        return reviews.summary_index(products), {'review_storage_available': True}
    except DatabaseError:
        return {}, {'review_storage_available': False,
                    'review_storage_message': '확인 기록 저장소를 사용할 수 없습니다. 마이그레이션과 저장소 상태를 확인해주세요.'}


@require_GET
def data(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        scope, mode = requested_scope(request)
        # Validate before scheduling any source work.
        listing.filtered([], request.GET)
        page_number = int(request.GET.get('page', '1'))
        if page_number < 1:
            raise ValueError
        if request.GET.get('snapshot'):
            snapshot, mode = requested_snapshot(request)
            state = {'state': 'pinned', 'age_seconds': max(0, int(snapshots.time.time() - snapshot['created']))}
        else:
            snapshot, state = snapshots.latest(scope)
        if snapshot is None:
            failed = state['state'] == 'failed'
            response = private(JsonResponse({'cache_state': state,
                'error': '순위 조회에 실패했습니다. 잠시 후 다시 조회해주세요.' if failed else '',
                'message': '순위 비교 결과를 준비 중입니다. 수집 누락으로 집계하지 않습니다.'}, status=503 if failed else 202))
            response['Retry-After'] = '20' if failed else '1'
            return response
        result = snapshot['results'][mode]
        products = listing.filtered(result['products'], request.GET)
        pages = max(1, math.ceil(len(products) / 20))
        page_number = min(page_number, pages)
        visible = products[(page_number - 1) * 20:page_number * 20]
        index, storage = review_index(visible)
        payload = {k: v for k, v in result.items() if k != 'products'}
        payload.update(storage, products=[listing.lightweight(p, index) for p in visible],
                       snapshot=snapshots.token(snapshot), cache_state=state,
                       pagination={'page': page_number, 'pages': pages, 'page_size': 20, 'count': len(products)})
        return private(JsonResponse(payload))
    except snapshots.SnapshotExpired:
        return private(JsonResponse({'error': '비교 결과가 만료되거나 원본이 변경되었습니다. 다시 조회해주세요.'}, status=409))
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '조회 조건을 확인해주세요.'}, status=400)
    except Exception:
        logger.exception('Rank snapshot lookup failed')
        return private(JsonResponse({'error': '순위 조회를 완료하지 못했습니다. 잠시 후 다시 조회해주세요.'}, status=503))


@require_GET
def detail(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        snapshot, mode = requested_snapshot(request)
        product = next((p for p in snapshot['results'][mode]['products'] if p['key'] == request.GET.get('key')), None)
        if product is None:
            return JsonResponse({'error': '상품을 찾을 수 없습니다.'}, status=404)
        try:
            value = reviews.detail(product, snapshot['scope'], request.GET['snapshot'])
            value['review_storage_available'] = True
        except DatabaseError:
            value = {k: v for k, v in product.items() if k != 'fingerprint'}
            value.update(review_storage_available=False, review_storage_message='확인 기록 저장소를 사용할 수 없습니다.',
                         review={'result': '미확인', 'memo': '', 'revision': 0, 'history': []})
        return private(JsonResponse(value))
    except snapshots.SnapshotExpired:
        return private(JsonResponse({'error': '비교 결과가 만료되었습니다. 다시 조회해주세요.'}, status=409))
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '조회 조건을 확인해주세요.'}, status=400)
    except Exception:
        logger.exception('Rank detail lookup failed')
        return private(JsonResponse({'error': '상품 상세를 조회하지 못했습니다.'}, status=503))


def csv_cell(value):
    value = str(value if value is not None else '')
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


@require_GET
def export(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        snapshot, mode = requested_snapshot(request)
        result = snapshot['results'][mode]
        products = listing.filtered(result['products'], request.GET)
        index, storage = review_index(products)
        # A failed review read must not be exported as a real unreviewed result.
        if not storage['review_storage_available']:
            return JsonResponse({'error': storage['review_storage_message']}, status=503)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['국가','제품군','리테일러','기준 수집일','상품명','ITEM','SKU', *result['dates'], '점검 신호','확인 결과'])
        labels = {'absent':'미발견','unavailable':'비교 보류','invalid':'순위값 확인','ambiguous':'복수 순위','identity':'ITEM 확인','batch':'배치 ID 확인'}
        for p in products:
            values = [result['country'],result['product'],result['retailer'],result['date'],p['name'],p['item'],p['sku'],
                      *[str(c['rank'])+'위' if c['state'] in ('ranked','outside') else labels.get(c['state'],'확인 필요') for c in p['cells']],
                      p['label'],index.get(p['fingerprint'],'미확인')]
            writer.writerow([csv_cell(v) for v in values])
        response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="rank-export.csv"'
        return private(response)
    except snapshots.SnapshotExpired:
        return private(JsonResponse({'error': '비교 결과가 만료되었습니다. 다시 조회해주세요.'}, status=409))
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '조회 조건을 확인해주세요.'}, status=400)
    except Exception:
        logger.exception('Rank export failed')
        return private(JsonResponse({'error': '내보내기를 완료하지 못했습니다.'}, status=503))


@require_POST
def save_review(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        body = json.loads(request.body)
        payload = signing.loads(body['token'], salt=reviews.SALT, max_age=snapshots.SNAPSHOT_SECONDS)
        context = payload['context']
        snapshot = snapshots.pinned(payload['snapshot'])
        product = next((p for p in snapshot['results']['all']['products'] if p['key'] == context['item_key']), None)
        if (not product or reviews.context_for(product, snapshot['scope']) != context):
            raise ValueError
        if context['environment'] != reviews.environment():
            raise ValueError
        result, memo, revision = body['result'], body['memo'], body['revision']
        if result not in reviews.RESULTS or not isinstance(memo, str) or not 1 <= len(memo.strip()) <= 2000:
            raise ValueError
        if type(revision) is not int or revision < 0:
            raise ValueError
    except (ValueError, TypeError, KeyError, signing.BadSignature):
        return JsonResponse({'error': '확인 결과와 근거(1~2,000자)를 입력하세요. 조회 후 20분이 지났거나 원본이 변경됐다면 다시 조회하세요.'}, status=400)
    except OSError:
        return JsonResponse({'error': '비교 근거 저장소를 사용할 수 없습니다. 잠시 후 다시 조회해주세요.'}, status=503)
    try:
        with transaction.atomic():
            record, _ = RetailRankReview.objects.get_or_create(
                fingerprint=reviews.fingerprint(context), defaults={
                    'environment': context['environment'], 'source_date': context['date'],
                    'context': context, 'updated_at': timezone.now(), 'updated_by': '',
                })
            if revision != record.revision:
                return JsonResponse({'error': '다른 확인 기록이 저장되었습니다. 다시 조회해주세요.'}, status=409)
            now = timezone.now()
            event = {'result': result, 'memo': memo.strip(), 'at': now.isoformat(),
                     'username': request.user.get_username()}
            changed = RetailRankReview.objects.filter(pk=record.pk, revision=revision).update(
                result=result, memo=memo.strip(), revision=revision + 1, updated_at=now,
                updated_by=request.user.get_username(), history=record.history + [event])
            if not changed:
                return JsonResponse({'error': '확인 기록이 변경되었습니다. 다시 조회해주세요.'}, status=409)
            record.refresh_from_db()
        return JsonResponse({'review': reviews.serialize(record)})
    except DatabaseError:
        return JsonResponse({'error': '확인 기록을 저장하지 못했습니다. 저장소 상태를 확인해주세요.'}, status=503)
