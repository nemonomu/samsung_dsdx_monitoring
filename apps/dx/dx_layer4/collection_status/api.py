"""
수집 현황 API — 리테일러별 수집 건수 및 컬럼별 NULL 현황, 이메일 발송
"""

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.common.response import safe_error
from apps.common.params import parse_date
from apps.common.email_config import get_recipients_with_name
from .services import (
    VALID_COLLECTION_CATEGORIES,
    check_email_sent,
    get_collection_status,
    get_null_detail,
    send_email_report as _send_email_report,
)
from .email_services import get_email_report_data


def collection_status_data(request):
    """리테일러별 수집 건수 + 컬럼별 NULL 수 조회"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    category = request.GET.get('category', 'tv')
    if category not in VALID_COLLECTION_CATEGORIES:
        return JsonResponse({'error': '잘못된 카테고리입니다.'}, status=400)

    try:
        return JsonResponse(get_collection_status(target_date, category))
    except Exception as e:
        return safe_error(e)


def email_report_data(request):
    """Email-only multi-country latest-batch collection data."""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        return JsonResponse(get_email_report_data(target_date))
    except Exception as error:
        return safe_error(error)


def collection_null_detail(request):
    """특정 리테일러/컬럼의 NULL 행 상세 조회"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    category = request.GET.get('category', 'tv')
    retailer = request.GET.get('retailer', '')
    column = request.GET.get('column', '')

    if category not in VALID_COLLECTION_CATEGORIES:
        return JsonResponse({'error': '잘못된 카테고리입니다.'}, status=400)
    if not retailer or not column:
        return JsonResponse({'error': '리테일러와 컬럼을 지정해주세요.'}, status=400)

    try:
        return JsonResponse(get_null_detail(target_date, category, retailer, column))
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return safe_error(e)


@require_POST
def send_email_report(request):
    """이메일 보고 발송 API"""
    try:
        body = json.loads(request.body)
        subject = body.get('subject', '')
        html_content = body.get('html', '')
        crawl_date = body.get('date', '')

        if not subject or not html_content:
            return JsonResponse({'error': '제목과 내용을 입력해주세요.'}, status=400)

        target_date = parse_date(crawl_date, default=None)
        if target_date is None:
            return JsonResponse(
                {'error': '날짜 형식이 올바르지 않습니다.'}, status=400,
            )

        report_data = get_email_report_data(target_date)
        if not report_data.get('complete'):
            return JsonResponse({
                'error': '이메일 보고 데이터가 불완전하여 발송할 수 없습니다.',
                'complete': False,
                'errors': report_data.get('errors', []),
            }, status=409)

        recipients = get_recipients_with_name('collection_status_receiver')
        if not recipients:
            return JsonResponse({'error': '수신자가 등록되어 있지 않습니다. 관리자 페이지에서 수신자를 추가해주세요.'}, status=400)

        sent_id = request.user.username if request.user.is_authenticated else 'anonymous'
        return JsonResponse(_send_email_report(
            subject, html_content, str(target_date), recipients, sent_id,
        ))
    except Exception as e:
        return JsonResponse({'error': f'발송 실패: {str(e)}'}, status=500)


def email_recipients(request):
    """이메일 수신자 목록 조회 API"""
    try:
        rows = get_recipients_with_name('collection_status_receiver')
        return JsonResponse({'success': True, 'recipients': rows})
    except Exception as e:
        return safe_error(e)


def email_sent_check(request):
    """해당 날짜 이메일 발송 여부 및 횟수 확인"""
    crawl_date = request.GET.get('date', '')
    if not crawl_date:
        return JsonResponse({'count': 0})

    try:
        return JsonResponse(check_email_sent(crawl_date))
    except Exception:
        return JsonResponse({'sent': False})
