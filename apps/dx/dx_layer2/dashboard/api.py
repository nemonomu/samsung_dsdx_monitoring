"""
Layer 2 Dashboard API: HTTP 래퍼 (request 파싱 + services 호출 + JsonResponse)
"""

from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.response import log_error
from apps.common.params import parse_date
from apps.dx.dx_layer2.dashboard import services


def layer_stats(request):
    """Layer 2 통계 API - 검증유형별, 테이블별 구조화"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        with dx_connection() as (conn, cursor):
            results = services.get_layer_stats(
                cursor, target_date, request.GET.get('section', '')
            )
    except Exception as e:
        results = {
            'timestamp': None,
            'date': str(target_date),
            'layer': 2,
            'name': '형식/NULL 검수',
            'validation_types': [],
            'summary': {
                'total_issues': 0,
                'null_issues': 0,
                'format_issues': 0,
                'duplicate_issues': 0,
                'overall_status': 'ERROR'
            },
            'error': log_error(e)
        }

    return JsonResponse(results)


def retailer_detail(request):
    """리테일러별 상세 오류 데이터 조회 API"""
    validation_type = request.GET.get('type', 'null')
    table_name = request.GET.get('table', '')
    if table_name not in services.VALID_TABLES_RETAILER:
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)
    retailer = request.GET.get('retailer', '')
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        with dx_connection() as (conn, cursor):
            results = services.get_retailer_detail(cursor, validation_type, table_name, retailer, target_date)
    except Exception as e:
        results = {
            'type': validation_type,
            'table': table_name,
            'retailer': retailer,
            'date': str(target_date),
            'records': [],
            'total': 0,
            'error': log_error(e)
        }

    return JsonResponse(results)
