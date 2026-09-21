"""
anomaly_validation API — HTTP 래퍼
connection/cursor 관리, 파라미터 파싱, JsonResponse 반환
"""

import json as json_mod
from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.response import safe_error
from apps.common.params import parse_date
from apps.common.seda_retail import get_seda_product_line, seda_retailer_key
from . import services
from .services import VALID_TABLES_ANOMALY, _DUP_TABLE_CONFIG


def anomaly_detail(request):
    """중복 검증 상세 조회 API"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)
    table = request.GET.get('table', 'tv_retail')
    if table not in VALID_TABLES_ANOMALY:
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)
    retailer = request.GET.get('retailer', '')
    if get_seda_product_line(table) and seda_retailer_key(retailer) not in ('magalu', 'casasbahia'):
        return JsonResponse({'error': '잘못된 SEDA 리테일러 파라미터'}, status=400)
    try:
        days = max(1, int(request.GET.get('days', 1)))
    except (ValueError, TypeError):
        days = 1
    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(int(request.GET.get('page_size', 50)), 200)
    except (ValueError, TypeError):
        return JsonResponse({'error': '잘못된 페이지 파라미터'}, status=400)

    try:
        with dx_connection() as (conn, cursor):
            result = services.get_anomaly_detail(cursor, target_date, table, retailer, days, page, page_size)
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)


def duplicate_cleanup(request):
    """중복 데이터 정리 API — 체크박스로 선택한 id 목록을 백업 후 삭제"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json_mod.loads(request.body)
    except (json_mod.JSONDecodeError, ValueError):
        return JsonResponse({'error': '잘못된 요청 형식'}, status=400)

    table = data.get('table', '')
    if table not in _DUP_TABLE_CONFIG:
        return JsonResponse({'error': '잘못된 테이블 파라미터'}, status=400)

    ids = data.get('ids', [])
    if not ids:
        return JsonResponse({'error': '삭제할 항목을 선택해주세요.'}, status=400)

    # id를 정수로 변환
    try:
        delete_ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return JsonResponse({'error': '잘못된 ID 형식'}, status=400)

    target_date = parse_date(data.get('date')) or None
    username = request.user.username if request.user.is_authenticated else 'anonymous'

    try:
        with dx_connection() as (conn, cursor):
            result = services.cleanup_duplicates(cursor, conn, table, delete_ids, target_date, username)
            conn.commit()
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)
