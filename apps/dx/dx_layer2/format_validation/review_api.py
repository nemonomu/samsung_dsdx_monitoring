import json
from datetime import date
from django.http import JsonResponse
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
            return JsonResponse(data)
        action = body.get('action')
        if action == 'preview':
            return JsonResponse(service.preview(data, body.get('keys'), body.get('decision'), body.get('reason')))
        if action == 'apply':
            token = body.get('token')
            if not isinstance(token, str) or len(token) > 100000:
                raise ValueError('미리보기 정보가 올바르지 않습니다.')
            event_id = service.commit(data, token, request.user.get_username())
            return JsonResponse({'success': True, 'event_id': event_id})
        if action == 'undo':
            revision, event_id = body.get('revision'), body.get('event_id')
            if type(revision) is not int or type(event_id) is not int or revision < 0 or event_id < 1:
                raise ValueError('취소할 처리 정보가 올바르지 않습니다.')
            repository.undo(data['fingerprint'], revision, event_id, request.user.get_username(),
                            service.validate_reason(body.get('reason')))
            return JsonResponse({'success': True})
        raise ValueError('지원하지 않는 처리입니다.')
    except repository.ReviewConflict as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc)
