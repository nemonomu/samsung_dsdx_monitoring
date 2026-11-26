"""
Layer 4 보고서 API — 보고서 데이터 조회
"""

from django.http import JsonResponse
from apps.common.monitoring_cache import monitoring_cached_value
from apps.common.response import safe_error
from apps.common.params import parse_date
from .services import get_report_data


def report_data(request):
    """보고서 데이터 조회 (GET)"""
    target_date = parse_date(request.GET.get('date'))
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)

    try:
        authenticated = getattr(getattr(request, 'user', None), 'is_authenticated', False)
        if request.method == 'GET' and authenticated and request.GET.get('refresh') != '1':
            data = monitoring_cached_value(
                'layer4-daily-report-observation', target_date.isoformat(),
                lambda: get_report_data(target_date),
                cacheable=lambda result: (result.get('success') is True
                                          and not (result.get('sem_tv_observation') or {}).get('error')),
            )
        else:
            data = get_report_data(target_date)
        response = JsonResponse(data)
        response['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        return safe_error(e)
