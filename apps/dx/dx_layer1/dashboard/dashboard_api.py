"""
Layer 1 Dashboard API: HTTP 요청/응답 처리
"""

import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from psycopg2 import Error
from apps.common.monitoring_cache import cached_monitoring_stats
from apps.common.params import parse_date
from .services import get_dashboard_stats
from .collection_services import get_dday_collection_status

logger = logging.getLogger(__name__)


@cached_monitoring_stats
def _legacy_layer_stats(request):
    target_date = parse_date(request.GET.get('date'))
    return JsonResponse(get_dashboard_stats(target_date, request.GET.get('check_type')))


@never_cache
def _dashboard_stats(request):
    scope = request.GET.get('dashboard_scope')
    if scope not in (None, 'daily', 'periodic'):
        return JsonResponse({'error': '잘못된 대시보드 조회 범위입니다.'}, status=400)
    return JsonResponse(get_dashboard_stats(
        parse_date(request.GET.get('date')), request.GET.get('check_type'),
        parallel=True, reuse_normal=True, refresh=request.GET.get('refresh') == '1',
        dashboard_scope=scope,
    ))


def layer_stats(request):
    """Layer 1 통계 API"""
    return _dashboard_stats(request) if request.GET.get('dashboard') == '1' else _legacy_layer_stats(request)


@cached_monitoring_stats
def collection_status(request):
    target_date = parse_date(request.GET.get('date'))
    reuse = request.GET.get('reuse_normal') == '1' and request.GET.get('refresh') != '1'
    try:
        options = {"reuse_normal": True} if reuse else {}
        return JsonResponse(get_dday_collection_status(target_date, **options))
    except Error:
        logger.warning('D-DAY collection read failed', exc_info=True)
        return JsonResponse({'error': '당일 수집 현황을 조회하지 못했습니다.'}, status=503)
