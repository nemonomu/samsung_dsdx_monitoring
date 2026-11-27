"""
Layer 1 Dashboard API: HTTP 요청/응답 처리
"""

import logging

from django.http import JsonResponse
from psycopg2 import Error
from apps.common.monitoring_cache import cached_monitoring_stats
from apps.common.params import parse_date
from .services import get_dashboard_stats
from .collection_services import get_dday_collection_status

logger = logging.getLogger(__name__)


@cached_monitoring_stats
def layer_stats(request):
    """Layer 1 통계 API"""
    target_date = parse_date(request.GET.get('date'))
    check_type_filter = request.GET.get('check_type')
    results = get_dashboard_stats(target_date, check_type_filter)
    return JsonResponse(results)


@cached_monitoring_stats
def collection_status(request):
    target_date = parse_date(request.GET.get('date'))
    try:
        return JsonResponse(get_dday_collection_status(target_date))
    except Error:
        logger.warning('D-DAY collection read failed', exc_info=True)
        return JsonResponse({'error': '당일 수집 현황을 조회하지 못했습니다.'}, status=503)
