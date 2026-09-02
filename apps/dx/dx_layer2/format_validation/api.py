"""
형식 검증 API — HTTP 래퍼 (파라미터 파싱 + DB 연결 관리)
"""

from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.response import safe_error, log_error
from apps.common.params import parse_date
from .services import (
    VALID_TABLES_FORMAT,
    VALID_TABLES_RULES,
    get_format_detail,
    get_format_rules,
)


SEA_TSE_DEFAULT_HISTORY_TABLES = frozenset({
    'tv_retail',
    'sea_ref_retail',
    'sea_ldy_retail',
    'tse_tv_retail',
    'tse_ref_retail',
    'tse_ldy_retail',
})


def format_detail(request):
    """형식 오류 상세 조회 API"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)
    table = request.GET.get('table', 'tv_retail')
    if table not in VALID_TABLES_FORMAT:
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)
    retailer = request.GET.get('retailer')
    default_days = (
        3 if table in SEA_TSE_DEFAULT_HISTORY_TABLES else 1
    )
    try:
        days = max(1, int(request.GET.get('days', default_days)))
    except (ValueError, TypeError):
        days = default_days

    try:
        with dx_connection() as (conn, cursor):
            data = get_format_detail(cursor, target_date, table, retailer, days)
            return JsonResponse(data)
    except Exception as e:
        return safe_error(e)


def format_rules(request):
    """형식검증 규칙 조회 API - DB 기반 (신규 테이블)"""
    table_name = request.GET.get('table', 'tv_retail_com')
    if table_name not in VALID_TABLES_RULES:
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)
    retailer = request.GET.get('retailer', 'Amazon')

    try:
        with dx_connection() as (conn, cursor):
            data = get_format_rules(cursor, table_name, retailer)
            return JsonResponse(data)
    except Exception as e:
        log_error(e, 'db')
        return JsonResponse({'rules': []})
