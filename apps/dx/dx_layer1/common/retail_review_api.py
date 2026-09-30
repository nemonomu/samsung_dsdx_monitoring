"""Persist a user's review of the exact Layer 1 decision they inspected.

The context is an audit snapshot of the displayed decision, not an override
of collector data or of the automatic validation rules.
"""
import hashlib
import json
from datetime import date

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.dx.dx_layer1.models import RetailNormalReview


def validate_context(value):
    if not isinstance(value, dict) or set(value) != {
        'version', 'date', 'source_date', 'country', 'product', 'slot',
        'retailer', 'batch_id', 'status', 'counts', 'reasons', 'basis',
    }:
        raise ValueError('검토 대상 정보가 올바르지 않습니다.')
    if value['version'] != 1 or value['country'] not in ('SEA', 'SEDA', 'SEM', 'SIEL', 'SEG', 'TSE'):
        raise ValueError('지원하지 않는 검토 대상입니다.')
    if value['product'] not in ('TV', 'REF', 'LDY') or value['status'] not in ('REVIEW', 'VOLUME_REVIEW', 'VOLUME_HIGH'):
        raise ValueError('확인 필요 항목만 정상 확인할 수 있습니다.')
    for key in ('date', 'source_date'):
        if not isinstance(value[key], str) or date.fromisoformat(value[key]).isoformat() != value[key]:
            raise ValueError('날짜가 올바르지 않습니다.')
    for key in ('slot', 'retailer', 'batch_id'):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 200:
            raise ValueError('리테일러와 배치 정보가 필요합니다.')
    counts = value['counts']
    if not isinstance(counts, list) or len(counts) != 4 or any(type(n) is not int or n < 0 for n in counts):
        raise ValueError('수집 건수가 올바르지 않습니다.')
    reasons = value['reasons']
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= 20 or any(
        not isinstance(text, str) or not text.strip() or len(text) > 1000 for text in reasons
    ):
        raise ValueError('확인 필요 사유가 필요합니다.')
    # Preserve precise inputs in addition to the human-readable reasons.
    basis = value['basis']
    if not isinstance(basis, str) or len(basis) > 12000:
        raise ValueError('판정 근거가 올바르지 않습니다.')
    parsed = json.loads(basis)
    if not isinstance(parsed, dict):
        raise ValueError('판정 근거가 올바르지 않습니다.')
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def serialize(record):
    return {'context': record.context, 'active': record.active,
            'revision': record.revision, 'history': record.history}


@require_http_methods(['GET', 'POST'])
def reviews(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        if request.method == 'GET':
            day = date.fromisoformat(request.GET.get('date', ''))
            records = RetailNormalReview.objects.filter(inspection_date=day).order_by('id')
            return JsonResponse({'date': day.isoformat(), 'reviews': [serialize(r) for r in records]})
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('요청이 올바르지 않습니다.')
        context = data.get('context')
        fingerprint = validate_context(context)
        action = data.get('action')
        memo = data.get('memo', '')
        revision = data.get('revision', 0)
        if action not in ('confirm', 'cancel') or type(revision) is not int or revision < 0:
            raise ValueError('검토 동작이 올바르지 않습니다.')
        if not isinstance(memo, str) or not memo.strip() or len(memo) > 1000:
            raise ValueError('확인 근거 또는 취소 사유를 1~1,000자로 입력하세요.')
        with transaction.atomic():
            if action == 'cancel' and not RetailNormalReview.objects.filter(fingerprint=fingerprint).exists():
                raise ValueError('취소할 확인 기록이 없습니다.')
            record, _ = RetailNormalReview.objects.get_or_create(
                fingerprint=fingerprint,
                defaults={'inspection_date': context['date'], 'context': context},
            )
            if record.revision != revision or record.active == (action == 'confirm'):
                return JsonResponse({'error': '다른 검토 결과가 저장되었습니다. 새로고침 후 다시 확인하세요.'}, status=409)
            history = record.history + [{
                'action': action, 'memo': memo.strip(), 'username': request.user.get_username(),
                'at': timezone.now().isoformat(),
            }]
            changed = RetailNormalReview.objects.filter(pk=record.pk, revision=revision).update(
                active=action == 'confirm', revision=revision + 1, history=history,
            )
            if not changed:
                return JsonResponse({'error': '검토 결과가 변경되었습니다. 새로고침 후 다시 확인하세요.'}, status=409)
            record.refresh_from_db()
        return JsonResponse({'review': serialize(record)})
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '검토 정보 또는 메모가 올바르지 않습니다.'}, status=400)
    except IntegrityError:
        return JsonResponse({'error': '동시에 저장된 검토가 있습니다. 새로고침 후 다시 확인하세요.'}, status=409)
