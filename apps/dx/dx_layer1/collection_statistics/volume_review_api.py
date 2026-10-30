"""Metric-scoped normal decisions shared by statistics and past incidents."""
import hashlib
import json
import logging
from datetime import date, timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction, IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.dx.dx_layer1.models import RetailNormalReview, CollectionIssue
from .calculations import COUNTRIES, OFFSETS
from .reviews import alert_basis

logger = logging.getLogger(__name__)


def environment():
    return 'test' if settings.DEBUG else 'production'


def fingerprint(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def inspect(target):
    from .live import current_snapshot
    country, product = target.get('country'), target.get('product')
    metric, retailer, slot = target.get('metric'), target.get('retailer'), target.get('slot')
    if country not in COUNTRIES or product not in ('TV', 'REF', 'LDY', 'LDY_DRYER') or metric not in ('main', 'bsr'):
        raise ValueError('검토 대상을 확인해주세요.')
    day = date.fromisoformat(target['source_date'])
    inspection = day + timedelta(days=OFFSETS[country])
    snapshot = current_snapshot(country, inspection)
    rows = [r for r in snapshot['rows'] if r['product'] == product and r['retailer'] == retailer and r['slot'] == slot]
    if len(rows) != 1:
        raise ValueError('현재 수집 대상을 찾지 못했습니다.')
    row = rows[0]
    alerts = [a for a in row.get('alerts', []) if a.get('metric') == metric]
    if (row.get('state') != 'complete' or row.get('base_status') == 'ERROR' or row.get('refresh_error')
            or not row.get('batch_id') or not row.get('main') or not row.get('total') or not alerts):
        raise ValueError('수집이 완료된 MAIN·BSR 이상 항목만 정상 확인할 수 있습니다.')
    context = dict(version=2, environment=environment(), country=country, product=product,
                   retailer=retailer, slot=slot, source_date=str(day), date=str(inspection), metric=metric,
                   batch_id=row['batch_id'], counts=[row[k] for k in ('main', 'bsr', 'total')]+[row.get('batch_count', 0)],
                   basis=json.dumps({'alerts': alert_basis(alerts)}, sort_keys=True))
    return context, row


def record_state(context):
    record = RetailNormalReview.objects.filter(fingerprint=fingerprint(context)).first()
    return record, record.revision if record else 0


@require_http_methods(['GET', 'POST'])
def review(request):
    if not getattr(getattr(request, 'user', None), 'is_authenticated', False):
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        payload = request.GET if request.method == 'GET' else json.loads(request.body)
        target = {k: payload.get(k) for k in ('country', 'product', 'retailer', 'source_date', 'slot', 'metric')}
        context, row = inspect(target)
        digest = fingerprint(context)
        decision = row.get('metric_reviews', {}).get(context['metric'])
        stamp = {'fingerprint': digest, 'decision': decision}
        record, revision = record_state(context)
        if request.method == 'POST':
            expected = signing.loads(payload.get('token', ''), salt='collection-metric-review', max_age=3600)
            if expected != stamp or type(payload.get('revision')) is not int or payload['revision'] != revision:
                return JsonResponse({'error': '수집 결과 또는 확인 이력이 변경됐습니다. 창을 다시 열어주세요.'}, status=409)
            action, memo = payload.get('action'), payload.get('memo')
            if action not in ('confirm', 'cancel') or not isinstance(memo, str) or not 1 <= len(memo.strip()) <= 1000:
                raise ValueError('처리 사유를 1~1,000자로 입력해주세요.')
            if action == 'cancel' and not decision:
                raise ValueError('취소할 확인 기록이 없습니다.')
            with transaction.atomic():
                record, _ = RetailNormalReview.objects.get_or_create(fingerprint=digest,
                    defaults={'inspection_date': context['date'], 'context': context})
                if record.revision != revision:
                    return JsonResponse({'error': '다른 확인 결과가 저장됐습니다. 다시 조회해주세요.'}, status=409)
                now = timezone.now()
                event = {'action': action, 'memo': memo.strip(), 'username': request.user.get_username(), 'at': now.isoformat()}
                if not RetailNormalReview.objects.filter(pk=record.pk, revision=revision).update(
                        active=action == 'confirm', revision=revision+1, history=record.history+[event]):
                    raise IntegrityError('Concurrent review')
                from apps.dx.dx_layer1.collection_issues.volume import metric_column
                from apps.dx.dx_layer1.collection_issues.services import event as issue_event
                for issue in CollectionIssue.objects.filter(environment=environment(), country=context['country'],
                        product=context['product'], retailer=context['retailer'], source_date=context['source_date'],
                        column=metric_column(context['metric'], context['slot'])):
                    issue.evidence = {**issue.evidence, 'current_row': row}
                    issue.current_count = row[context['metric']]
                    issue.last_checked_at = now
                    issue.revision += 1
                    issue.save(update_fields=['evidence', 'current_count', 'last_checked_at', 'revision'])
                    issue_event(issue, 'normal_confirm' if action == 'confirm' else 'normal_cancel', now,
                                username=event['username'], reason=event['memo'], evidence=context)
            return JsonResponse({'saved': True})
        decision = row.get('metric_reviews', {}).get(context['metric'])
        result = dict(target=target, counts=context['counts'], inspection_date=context['date'], batch_id=context['batch_id'],
                      reasons=[a.get('reason', '') for a in row['alerts'] if a.get('metric') == context['metric']],
                      decision=decision, history=record.history if record else [], revision=revision,
                      token=signing.dumps(stamp, salt='collection-metric-review'))
        response = JsonResponse(result)
        response['Cache-Control'] = 'private, no-store'
        return response
    except (ValueError, KeyError, TypeError, signing.BadSignature):
        return JsonResponse({'error': '수집 완료된 이상 항목인지 확인하고 처리 사유를 입력해주세요. 변경된 항목은 다시 조회해주세요.'}, status=400)
    except IntegrityError:
        return JsonResponse({'error': '동시에 처리된 기록이 있습니다. 다시 조회해주세요.'}, status=409)
    except Exception:
        logger.exception('Collection metric review failed')
        return JsonResponse({'error': '현재 수집 결과를 확인하지 못했습니다. 기존 상태를 유지합니다.'}, status=503)
