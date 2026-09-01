"""
NULL 검증 API — HTTP 래퍼 (파라미터 파싱, DB 연결 관리, JsonResponse 반환)
"""

import json
import re

from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.response import safe_error
from apps.common.params import parse_date
from .services import get_all_categories
from . import services


SEA_TSE_DEFAULT_HISTORY_CATEGORIES = frozenset({
    'tv_retail',
    'sea_ref_retail',
    'sea_ldy_retail',
    'tse_tv_retail',
    'tse_ref_retail',
    'tse_ldy_retail',
})


def null_detail(request):
    """NULL 필드 상세 조회 API - category 기반 동적 처리"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)
    category = request.GET.get('table', 'tv_retail')
    if category not in get_all_categories():
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)
    retailer = request.GET.get('retailer')
    column = request.GET.get('column')
    default_days = (
        2 if category in SEA_TSE_DEFAULT_HISTORY_CATEGORIES else 1
    )
    try:
        days = min(30, max(1, int(request.GET.get('days', default_days))))
    except (ValueError, TypeError):
        days = default_days

    # column 필수 + regex 검증 (SQL injection 방지)
    if not column:
        return JsonResponse({'error': 'column 파라미터 필수'}, status=400)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column):
        return JsonResponse({'error': '잘못된 컬럼명'}, status=400)

    try:
        with dx_connection() as (conn, cursor):
            result = services.get_null_detail(cursor, target_date, category, retailer, days, column)
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)


def null_review(request):
    """NULL 검증 정상 처리 / 취소 API (POST)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '잘못된 요청 형식'}, status=400)

    table_name = body.get('table_name', '')
    try:
        record_id = int(body.get('record_id'))
    except (ValueError, TypeError):
        return JsonResponse({'error': '잘못된 ID 형식'}, status=400)
    column_name = body.get('column_name', '')
    status = body.get('status', '')  # 'normal' or 'reverted'
    memo = body.get('memo', '')
    reason = body.get('reason', '')  # 사유 텍스트
    crawl_date = body.get('crawl_date')
    correction_type = body.get('correction_type', 'null')

    # 컬럼명 regex 검증 (입력 검증은 HTTP 레이어에서 처리)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column_name):
        return JsonResponse({'error': '잘못된 컬럼명'}, status=400)

    username = request.user.username if request.user.is_authenticated else 'anonymous'

    try:
        with dx_connection() as (conn, cursor):
            result = services.save_null_review(
                cursor, conn, table_name, record_id, column_name,
                status, memo, reason, crawl_date, correction_type, username
            )
            status_code = result.pop('status_code', 200)
            if 'error' in result:
                return JsonResponse(result, status=status_code)
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)


def null_review_logs(request):
    """해당값 정상으로 처리한 TSE NULL 검수 로그 API (GET)."""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        with dx_connection() as (conn, cursor):
            return JsonResponse(
                services.get_tse_null_review_logs(cursor, target_date)
            )
    except Exception as e:
        return safe_error(e)
