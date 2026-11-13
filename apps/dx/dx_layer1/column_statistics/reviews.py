"""Image-backed human decisions; source counts and automatic verdicts stay intact."""
import hashlib
import io
import json
import logging
from datetime import date

from PIL import Image, UnidentifiedImageError
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_document.manual import dx_access
from apps.dx.dx_layer1.models import ColumnNormalReview as Review, ColumnReviewImage as Evidence
from apps.dx.dx_layer1.collection_issues.services import environment
from apps.dx.dx_layer1.collection_issues.queries import raw_counts
from .services import select_source, daily_counts
from .comparison import attach_comparisons, KST

logger = logging.getLogger(__name__)
SALT = 'column-normal-review-v1'
MAX_IMAGE = 5 * 1024 * 1024
MAX_TOTAL = 15 * 1024 * 1024
TARGET_KEYS = ('country', 'product', 'retailer', 'column', 'inspection_date', 'source_date')


def fingerprint(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def context_for(data, row):
    day = next(d for d in data['daily'] if d['date'] == data['comparison_date'])
    return dict(environment=environment(), country=data['country'], product=data['product'],
                retailer=data['retailer'], source_date=data['comparison_date'], column=row['column'],
                current=row['current'], baseline=row['baseline'], status=row['status'],
                total=day['total'], raw_total=day.get('raw_total', day['total']))


def target_for(data, row):
    return dict(country=data['country'], product=data['product'], retailer=data['retailer'],
                column=row['column'], inspection_date=data['inspection_date'], source_date=data['comparison_date'])


def summary(record):
    return dict(active=record.active, revision=record.revision) if record else None


def attach_reviews(data):
    contexts = [(row, context_for(data, row)) for row in data['comparisons']]
    records = {r.fingerprint:r for r in Review.objects.filter(
        environment=environment(), source_date=data['comparison_date'],
        context__country=data['country'], context__product=data['product'], context__retailer=data['retailer'])}
    history_columns = {r.context['column'] for r in records.values()}
    for row, context in contexts:
        row['review'] = summary(records.get(fingerprint(context)))
        row['review_target'] = target_for(data, row)
        row['review_history'] = row['column'] in history_columns
    return data


def inspect(target):
    if not isinstance(target, dict) or any(not isinstance(target.get(k), str) for k in TARGET_KEYS):
        raise ValueError('검수 대상을 확인하세요.')
    source = select_source(target['country'], target['product'], target['retailer'])
    inspection = date.fromisoformat(target['inspection_date'])
    if inspection > timezone.now().astimezone(KST).date():
        raise ValueError('미래 날짜는 검수할 수 없습니다.')
    mapping = resolve_monitoring_date(inspection, target['country'], source['key'])
    if mapping['source_date'] != target['source_date']:
        raise ValueError('검수일과 원본 수집일을 확인하세요.')
    day = date.fromisoformat(target['source_date'])
    data = daily_counts(target['country'], target['product'], target['retailer'], day, 29)
    totals = raw_counts(target['country'], target['product'], target['retailer'], day, day)
    for item in data['daily']:
        if item['date'] == str(day):
            item['raw_total'] = totals.get(str(day), 0)
    data = attach_comparisons(data, day)
    data.update(mapping)
    row = next((r for r in data['comparisons'] if r['column'] == target['column']), None)
    if row is None:
        raise ValueError('현재 수집 대상 컬럼을 찾지 못했습니다.')
    return context_for(data, row), row


def read_images(files):
    if not 1 <= len(files) <= 5 or sum(f.size for f in files) > MAX_TOTAL:
        raise ValueError('근거 이미지는 1~5장, 합계 15MB 이하로 첨부하세요.')
    result = []
    for upload in files:
        if upload.size > MAX_IMAGE:
            raise ValueError('이미지 한 장은 5MB 이하여야 합니다.')
        raw = upload.read(MAX_IMAGE + 1)
        if len(raw) > MAX_IMAGE:
            raise ValueError('이미지 한 장은 5MB 이하여야 합니다.')
        try:
            with Image.open(io.BytesIO(raw)) as img:
                fmt = img.format
                if fmt not in ('PNG', 'JPEG', 'WEBP') or img.width * img.height > 20000000 or getattr(img, 'n_frames', 1) != 1:
                    raise ValueError('PNG·JPG·WEBP 정지 이미지(2천만 화소 이하)를 첨부하세요.')
                img.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('이미지 파일을 읽을 수 없습니다.') from exc
        result.append((raw, {'PNG':'image/png', 'JPEG':'image/jpeg', 'WEBP':'image/webp'}[fmt]))
    return result


def serialize(record):
    return dict(active=record.active, revision=record.revision, context=record.context,
                history=record.history) if record else dict(active=False, revision=0, history=[])


@dx_access
@require_http_methods(['GET', 'POST'])
@never_cache
def review(request):
    try:
        payload = request.GET if request.method == 'GET' else request.POST
        target = {k:payload.get(k) for k in TARGET_KEYS}
        context, row = inspect(target)
        digest = fingerprint(context)
        record = Review.objects.filter(environment=environment(), fingerprint=digest).first()
        revision = record.revision if record else 0
        stamp = dict(fingerprint=digest, revision=revision)
        if request.method == 'GET':
            # Older evidence remains inspectable even after the collected count changes.
            previous = Review.objects.filter(environment=environment(), source_date=context['source_date'],
                context__country=context['country'], context__product=context['product'],
                context__retailer=context['retailer'], context__column=context['column']).exclude(
                    fingerprint=digest).order_by('-id')[:20]
            return JsonResponse(dict(target=target, comparison=row, review=serialize(record),
                previous=[serialize(r) for r in previous], token=signing.dumps(stamp, salt=SALT)))
        expected = signing.loads(payload.get('token', ''), salt=SALT, max_age=3600)
        if expected != stamp:
            return JsonResponse({'error':'수집 결과 또는 검수 이력이 변경됐습니다. 창을 다시 열어 확인하세요.'}, status=409)
        action, memo = payload.get('action'), payload.get('memo', '').strip()
        if action not in ('confirm', 'cancel') or len(memo) > 1000:
            raise ValueError('처리 동작과 설명(최대 1,000자)을 확인하세요.')
        if action == 'confirm' and (row['status'] not in ('abnormal', 'review') or (record and record.active)):
            raise ValueError('아직 정상 확인하지 않은 이상·확인 필요 항목만 처리할 수 있습니다.')
        if action == 'cancel' and (not record or not record.active or not memo):
            raise ValueError('정상 확인된 항목인지 확인하고 취소 사유를 입력하세요.')
        images = read_images(request.FILES.getlist('images')) if action == 'confirm' else []
        with transaction.atomic():
            record, _ = Review.objects.get_or_create(fingerprint=digest, defaults={
                'environment':environment(), 'source_date':context['source_date'], 'context':context})
            if record.revision != revision:
                raise IntegrityError('Concurrent column review')
            now = timezone.now()
            entry = dict(action=action, memo=memo, username=request.user.get_username(),
                         at=now.isoformat(), images=[])
            if not Review.objects.filter(pk=record.pk, revision=revision).update(
                    active=action == 'confirm', revision=revision+1):
                raise IntegrityError('Concurrent column review')
            for raw, content_type in images:
                evidence = Evidence.objects.create(review=record, revision=revision+1,
                    content=raw, content_type=content_type, digest=hashlib.sha256(raw).hexdigest(), created_at=now)
                entry['images'].append(dict(url=f'/dx/layer1/api/column-review/images/{evidence.pk}/'))
            record.history = [*record.history, entry]
            record.save(update_fields=['history'])
            record.refresh_from_db()
        row.update(review=summary(record), review_target=target, review_history=True)
        return JsonResponse(dict(saved=True, review=serialize(record), comparison=row,
            token=signing.dumps(dict(fingerprint=digest, revision=record.revision), salt=SALT)))
    except signing.BadSignature:
        return JsonResponse({'error':'검수 창이 만료됐습니다. 창을 다시 열어주세요.'}, status=409)
    except (ValueError, TypeError, KeyError) as exc:
        return JsonResponse({'error':str(exc) if isinstance(exc, ValueError) else '검수 요청을 확인하세요.'}, status=400)
    except IntegrityError:
        return JsonResponse({'error':'다른 검수 결과가 저장됐습니다. 창을 다시 열어주세요.'}, status=409)
    except Exception:
        logger.exception('Column evidence review failed')
        return JsonResponse({'error':'검수 기록을 처리하지 못했습니다. 첨부 내용은 유지되니 다시 시도하세요.'}, status=503)


@dx_access
@require_GET
@never_cache
def image(request, image_id):
    item = Evidence.objects.filter(pk=image_id, review__environment=environment()).first()
    if item is None:
        raise Http404()
    response = HttpResponse(bytes(item.content), content_type=item.content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = 'inline'
    return response
