"""
Layer 4 검수기록 API — 목록 조회, 취소, 이유 조회, 이력 조회
"""

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from apps.common.response import safe_error
from apps.common.params import parse_date
from .services import get_corrections, cancel_corrections, get_bulk_history, get_history


def _detail_arguments(request):
    correction_id = int(request.GET.get('id', ''))
    days = int(request.GET.get('days', 3))
    if correction_id < 1 or not 1 <= days <= 30:
        raise ValueError('검수기록 ID 또는 조회 일수가 올바르지 않습니다.')
    return correction_id, days


@require_GET
def correction_detail(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=403)
    try:
        if request.GET.get('review_event_id'):
            from . import format_reviews
            data = format_reviews.detail(
                int(request.GET['review_event_id']), int(request.GET.get('target', -1)),
                int(request.GET.get('record', -1)),
            )
            data['correction_history'] = format_reviews.correction_history(data['correction'])
            response = JsonResponse(data)
            response['Cache-Control'] = 'private, no-store'
            return response
        from . import detail
        return JsonResponse(detail.detail(*_detail_arguments(request)))
    except LookupError as e:
        return JsonResponse({'error': str(e)}, status=404)
    except (ValueError, TypeError) as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return safe_error(e)


@require_GET
def correction_query(request):
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({'error': '관리자만 조회 쿼리를 확인할 수 있습니다.'}, status=403)
    try:
        from . import detail
        return JsonResponse(detail.queries(*_detail_arguments(request)))
    except LookupError as e:
        return JsonResponse({'error': str(e)}, status=404)
    except (ValueError, TypeError) as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return safe_error(e)


def corrections_list(request):
    """검수기록 목록 조회 (GET)"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        days = int(request.GET.get('days', 3))
        if page < 1 or not 1 <= page_size <= 200 or not 1 <= days <= 30:
            return JsonResponse({'error': '페이지 또는 조회 일수가 올바르지 않습니다.'}, status=400)
        result = get_corrections(
            target_date=target_date,
            correction_type=request.GET.get('type', 'all'),
            status=request.GET.get('status', 'all'),
            search_field=request.GET.get('search_field', ''),
            search_value=request.GET.get('search_value', '').strip(),
            page=page, page_size=page_size, days=days,
            country=request.GET.get('country', 'all'),
            product=request.GET.get('product', 'all'),
            retailer=request.GET.get('retailer', 'all'),
            reviewer=request.GET.get('reviewer', 'all'),
        )
        return JsonResponse(result)
    except (ValueError, TypeError):
        return JsonResponse({'error': '조회 조건이 올바르지 않습니다.'}, status=400)
    except Exception as e:
        return safe_error(e)


@require_POST
def corrections_cancel(request):
    """정상처리 일괄 취소 API"""
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])
        cancel_memo = data.get('cancel_memo', '')
        username = request.user.username if request.user.is_authenticated else ''

        if not ids or not isinstance(ids, list):
            return JsonResponse({'success': False, 'error': '취소할 항목을 선택하세요.'}, status=400)

        return JsonResponse(cancel_corrections(ids, cancel_memo, username))
    except Exception as e:
        return safe_error(e, 'corrections_cancel')


def review_reasons(request):
    """정상 처리 이유 목록 조회 API (GET) — 코드 상수에서 반환"""
    from apps.common.constants import get_reasons
    check_type = request.GET.get('check_type', 'null_check')
    reasons = [{'text': r} for r in get_reasons(check_type)]
    return JsonResponse({'success': True, 'reasons': reasons})


def corrections_bulk_history(request):
    """일괄 이력 조회 API (GET) — 관리자 전용, Retail 테이블 한정"""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)

    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        days = min(int(request.GET.get('days', 3)), 30)
    except (ValueError, TypeError):
        days = 3

    try:
        result = get_bulk_history(
            target_date=target_date,
            correction_type=request.GET.get('type', 'all'),
            category=request.GET.get('category', 'all'),
            days=days,
        )
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e)


def corrections_history(request):
    """원본 테이블 이력 조회 API (GET) — retailer+item 기준 최근 N일"""
    table_name = request.GET.get('table_name', '')
    retailer = request.GET.get('retailer', '')
    item = request.GET.get('item', '')
    column = request.GET.get('column', '')
    record_id = request.GET.get('record_id', '')

    try:
        days = int(request.GET.get('days', 3))
    except (ValueError, TypeError):
        days = 3

    try:
        return JsonResponse(get_history(table_name, retailer, item, column, days, record_id))
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return safe_error(e)
