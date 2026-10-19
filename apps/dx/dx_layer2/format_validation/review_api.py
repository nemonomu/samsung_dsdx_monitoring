import json
from datetime import date
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.common.db import dx_connection
from apps.common.response import safe_error
from . import review_service as service, review_repository as repository


@require_http_methods(['GET', 'POST'])
def reviews(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    try:
        body = request.GET if request.method == 'GET' else json.loads(request.body)
        if not hasattr(body, 'get'):
            raise ValueError('요청이 올바르지 않습니다.')
        day = date.fromisoformat(body.get('date', ''))
        if day > timezone.localdate():
            raise ValueError('오늘 이후 날짜는 검토할 수 없습니다.')
        table, retailer = body.get('table', ''), body.get('retailer', '')
        if not isinstance(table, str) or not isinstance(retailer, str):
            raise ValueError('검토 범위가 올바르지 않습니다.')
        with dx_connection() as (_conn, cursor):
            data = service.inventory(cursor, day, table, retailer)
        if request.method == 'GET':
            if body.get('event_id'):
                event_id = int(body['event_id'])
                response = JsonResponse(repository.evidence_detail(service.event_origin(data, event_id), event_id))
                response['Cache-Control'] = 'private, no-store'
                return response
            return JsonResponse(data)
        action = body.get('action')
        if action == 'review':
            event_id = service.apply_direct(
                data, body.get('keys'), body.get('decision'), body.get('reason'),
                request.user.get_username(), body.get('evidence'), body.get('snapshots'),
            )
            return JsonResponse({'success': True, 'event_id': event_id})
        if action == 'preview':
            return JsonResponse(service.preview(data, body.get('keys'), body.get('decision'), body.get('reason'), body.get('evidence')))
        if action == 'apply':
            token = body.get('token')
            if not isinstance(token, str) or len(token) > 100000:
                raise ValueError('미리보기 정보가 올바르지 않습니다.')
            event_id = service.commit(data, token, request.user.get_username(), body.get('evidence'))
            return JsonResponse({'success': True, 'event_id': event_id})
        if action == 'undo':
            revision, event_id = body.get('revision'), body.get('event_id')
            if type(revision) is not int or type(event_id) is not int or revision < 0 or event_id < 1:
                raise ValueError('취소할 처리 정보가 올바르지 않습니다.')
            if body.get('shared_revision') != data['shared_revision'] or revision != data['revision']:
                raise repository.ReviewConflict('공유 기준이 변경됐습니다. 새로 조회하세요.')
            origin = service.event_origin(data, event_id)
            event = next((e for e in data['history'] if e['id'] == event_id), None)
            if not event:
                raise ValueError('취소할 처리 이력을 찾을 수 없습니다.')
            origin_revision = event['origin_revision']
            repository.undo(origin, origin_revision, event_id, request.user.get_username(),
                            service.validate_reason(body.get('reason')),
                            expected_shared_revision=data['shared_revision'])
            return JsonResponse({'success': True})
        raise ValueError('지원하지 않는 처리입니다.')
    except repository.ReviewConflict as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc)


@require_http_methods(['GET'])
def capture(request, capture_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)
    environment = 'test' if settings.DEBUG else 'production'
    if not repository.ready(evidence=True):
        return JsonResponse({'error': '캡처 저장소가 준비되지 않았습니다.'}, status=503)
    image = repository.capture(capture_id, environment)
    if not image:
        return JsonResponse({'error': '캡처를 찾을 수 없습니다.'}, status=404)
    response = HttpResponse(bytes(image.content), content_type=image.content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['Content-Disposition'] = 'inline; filename="review-capture"'
    return response
