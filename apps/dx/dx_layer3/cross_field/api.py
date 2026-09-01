"""
Layer 3 크로스 필드 검증 API
"""

from django.http import JsonResponse
from datetime import date, datetime, timedelta
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.db import dx_connection
from apps.common.response import safe_error, log_error
from . import services
from . import sea_services
from . import tse_services


def cross_field_detail(request):
    """크로스 필드 논리 검증 상세 API (DB 기반) - 검증 유형별 요약"""
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'tv')
    rule_id = request.GET.get('rule_id')  # 특정 규칙 상세 조회 시
    product_line_key = str(product_line or '').lower()
    default_days = 2 if (
        product_line_key in {'tv', 'sea_tv'}
        or product_line_key.startswith('sea_')
        or product_line_key.startswith('tse_')
    ) else 1
    try:
        days = int(request.GET.get('days', default_days))
    except (TypeError, ValueError):
        days = default_days
    if days < 1:
        days = 1
    if days > 30:
        days = 30

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    is_tse = product_line_key in ('tse_tv', 'tse_ref', 'tse_ldy')
    is_sea = product_line_key in ('sea_ref', 'sea_ldy')

    # product_line을 section으로 변환
    section_map = {'tv': 'tv_retail', 'hhp': 'hhp_retail'}
    section = section_map.get(product_line, f'{product_line}_retail')

    try:
        if is_tse:
            with dx_connection() as (conn, cursor):
                if rule_id:
                    result = tse_services.get_tse_cross_field_rule_detail(
                        cursor, target_date, product_line, rule_id, days,
                    )
                else:
                    result = tse_services.get_tse_cross_field_summary(
                        cursor, target_date, product_line,
                    )

            if rule_id and not result.get('found'):
                return JsonResponse({'error': '해당 규칙을 찾을 수 없습니다.'})
            result.pop('found', None)
            return JsonResponse(result)

        if is_sea:
            with dx_connection() as (conn, cursor):
                if rule_id:
                    result = sea_services.get_sea_cross_field_rule_detail(
                        cursor, target_date, product_line, rule_id, days,
                    )
                else:
                    result = sea_services.get_sea_cross_field_summary(
                        cursor, target_date, product_line,
                    )

            if rule_id and not result.get('found'):
                return JsonResponse({'error': '해당 규칙을 찾을 수 없습니다.'})
            result.pop('found', None)
            return JsonResponse(result)

        source_date = target_date
        inspection_date = None
        if str(product_line).lower() == 'tv':
            date_contract = resolve_monitoring_date(
                target_date, 'SEA', 'sea_tv'
            )
            source_date = date.fromisoformat(date_contract['source_date'])
            inspection_date = target_date

        if rule_id:
            with dx_connection() as (conn, cursor):
                result = services.get_cross_field_rule_detail(
                    cursor, source_date, product_line, section, rule_id, days,
                    inspection_date=inspection_date,
                )

            if not result.get('found'):
                return JsonResponse({'error': '해당 규칙을 찾을 수 없습니다.'})

            result.pop('found')
            if inspection_date is not None:
                result['offset_days'] = -1
            return JsonResponse(result)

        result = services.get_cross_field_summary(
            source_date, product_line, section,
            inspection_date=inspection_date,
        )
        if inspection_date is not None:
            result['offset_days'] = -1
        return JsonResponse(result)

    except Exception as e:
        log_error(e)
        return safe_error(e)


def sentiment_cross_detail(request):
    """Sentiment ↔ 리뷰 일관성 상세 API"""
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'tv')

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        with dx_connection() as (conn, cursor):
            result = services.get_sentiment_cross_detail(cursor, target_date, product_line)
        return JsonResponse(result)

    except Exception as e:
        log_error(e)
        return safe_error(e, anomalies=[])


def comp_product_cross_detail(request):
    """Comp Product 자사/경쟁사 구분 상세 API"""
    date_str = request.GET.get('date')

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        with dx_connection() as (conn, cursor):
            result = services.get_comp_product_cross_detail(cursor, target_date)
        return JsonResponse(result)

    except Exception as e:
        log_error(e)
        return safe_error(e, anomalies=[])


def crossfield_rules(request):
    """크로스필드 검증 규칙 목록 API (DB 기반)"""
    section = request.GET.get('section', request.GET.get('category', request.GET.get('type', 'all')))

    # 이전 호환성: tv → tv_retail, hhp → hhp_retail
    section_map = {'tv': 'tv_retail', 'hhp': 'hhp_retail'}
    section = section_map.get(section, section)

    try:
        result = services.get_crossfield_rules(section)
        return JsonResponse(result)

    except Exception as e:
        log_error(e)
        return JsonResponse({'status': 'error', 'message': '처리 중 오류가 발생했습니다.'})
