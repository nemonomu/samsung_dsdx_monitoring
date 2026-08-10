"""
Layer3 셀 수정 / 정상 처리 API — HTTP 래퍼
"""

import re
import json
from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.response import safe_error
from .services import VALID_TABLES_UPDATE
from . import services


def update_cell(request):
    """셀 값 수정 API (POST)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '잘못된 요청 형식'}, status=400)

    table_name = body.get('table_name', '')
    try:
        row_id = int(body.get('row_id'))
        if row_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({'error': '잘못된 ID 형식'}, status=400)
    column_name = body.get('column_name', '')
    new_value = body.get('new_value')
    crawl_date = body.get('crawl_date')
    memo = body.get('memo', '') or None
    rule_id = body.get('rule_id')
    if rule_id not in (None, ''):
        try:
            rule_id = int(rule_id)
            if rule_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return JsonResponse({'error': '잘못된 규칙 ID 형식'}, status=400)
    correction_type = body.get('correction_type', 'cross_field')
    if correction_type not in ('cross_field', 'field_missing'):
        correction_type = 'cross_field'

    if not all([table_name, row_id, column_name]):
        return JsonResponse({'error': '필수 파라미터 누락'}, status=400)
    if table_name not in VALID_TABLES_UPDATE:
        return JsonResponse({'error': '수정 불가능한 테이블'}, status=400)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column_name):
        return JsonResponse({'error': '잘못된 컬럼명'}, status=400)

    username = request.user.username if request.user.is_authenticated else 'anonymous'

    try:
        with dx_connection() as (conn, cursor):
            result = services.update_cell_value(
                cursor, conn, table_name, row_id, column_name, new_value,
                crawl_date, correction_type, username, memo, rule_id
            )
            if 'error' in result:
                return JsonResponse({'error': result['error']}, status=result.get('status', 400))
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)


def review_reasons(request):
    """정상 처리 이유 목록 조회 API (GET)"""
    check_type = request.GET.get('check_type', 'cross_field')
    return JsonResponse(services.get_review_reasons(check_type))


def review(request):
    """크로스필드/누락필드 정상 처리 API (POST)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '잘못된 요청 형식'}, status=400)

    table_name = body.get('table_name', '')
    try:
        record_id = int(body.get('record_id'))
        if record_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({'error': '잘못된 ID 형식'}, status=400)
    column_name = body.get('column_name', '')
    status = body.get('status', '')
    memo = body.get('memo', '')
    reason = body.get('reason', '')
    crawl_date = body.get('crawl_date')
    rule_id = body.get('rule_id')
    if rule_id not in (None, ''):
        try:
            rule_id = int(rule_id)
            if rule_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return JsonResponse({'error': '잘못된 규칙 ID 형식'}, status=400)
    correction_type = body.get('correction_type', 'cross_field')
    if correction_type not in ('cross_field', 'field_missing'):
        correction_type = 'cross_field'

    if not all([table_name, record_id, column_name, status]):
        return JsonResponse({'error': '필수 파라미터 누락'}, status=400)
    if status != 'normal':
        return JsonResponse({'error': '잘못된 status 값'}, status=400)
    if not reason:
        return JsonResponse({'error': '이유 선택은 필수입니다'}, status=400)
    if table_name not in VALID_TABLES_UPDATE:
        return JsonResponse({'error': '허용되지 않는 테이블'}, status=400)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column_name):
        return JsonResponse({'error': '잘못된 컬럼명'}, status=400)

    username = request.user.username if request.user.is_authenticated else 'anonymous'

    try:
        with dx_connection() as (conn, cursor):
            result = services.save_review(
                cursor, conn, table_name, record_id, column_name,
                status, memo, reason, crawl_date, correction_type, username, rule_id
            )
            if 'error' in result:
                return JsonResponse({'error': result['error']}, status=result.get('status', 400))
            return JsonResponse(result)
    except Exception as e:
        return safe_error(e)
