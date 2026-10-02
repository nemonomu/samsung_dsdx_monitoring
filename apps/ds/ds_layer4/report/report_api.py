"""
DS Layer 4 Report API: 보고서 관리 HTTP 요청/응답 처리 컨트롤러
"""
import json
from urllib.parse import urlencode
from datetime import datetime, timedelta, date
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from apps.common.response import safe_error
from . import report_services

@require_http_methods(["POST"])
def report_update(request):
    """이상치 데이터 수정 API"""
    try:
        body = json.loads(request.body)
        result = report_services.update_report(body)
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

@require_http_methods(["POST"])
def report_daily_update(request):
    """일별 보고서 메모 수정 API"""
    try:
        body = json.loads(request.body)
        result = report_services.update_daily_memo(body)
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

@require_http_methods(["POST"])
def report_save_file_info(request):
    """파일서버 파일 정보 전체 업데이트 API"""
    try:
        body = json.loads(request.body)
        result = report_services.save_file_info(
            crawl_date=body.get('crawl_date'),
            user_id=body.get('user_id', 'system')
        )
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

@require_http_methods(["POST"])
def report_close(request):
    """보고서 마감 API"""
    try:
        body = json.loads(request.body)
        result = report_services.close_report(
            crawl_date=body.get('crawl_date'),
            user_id=request.user.username,
            content=body.get('content')
        )
        if result.get('success'):
            result['document_url'] = reverse('ds_document:index') + '?' + urlencode({
                'category': result['category_id'], 'document_id': result['document_id'],
            })
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

@require_http_methods(["POST"])
def report_cancel_close(request):
    """보고서 마감 취소 API"""
    try:
        body = json.loads(request.body)
        result = report_services.cancel_close_report(
            crawl_date=body.get('crawl_date'),
            user_id=body.get('user_id', 'system'),
            memo=body.get('memo', '')
        )
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

def report_list(request):
    """저장된 이상치 목록 조회 API"""
    date_str = request.GET.get('date')
    retailer_filter = request.GET.get('retailer')
    view_mode = request.GET.get('view', 'status')

    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        result = report_services.get_report_list(date_str, retailer_filter, view_mode)
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)

@require_http_methods(["GET"])
def report_file_size_history(request):
    """최근 N일간 리테일러별 파일 용량 조회"""
    end_date_str = request.GET.get('end_date')
    try:
        days = max(1, min(int(request.GET.get('days', 7)), 90))
    except (ValueError, TypeError):
        days = 7

    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        end_date = date.today() - timedelta(days=1)

    try:
        result = report_services.get_file_size_history(end_date, days)
        return JsonResponse(result)
    except Exception as e:
        return safe_error(e, success=False)
