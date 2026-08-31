from django.http import JsonResponse
from datetime import datetime
from apps.common.response import log_error
from . import youtube_services as svc


def youtube_raw_data(request):
    """
    YouTube 원본 데이터 조회 API
    - category: HHP
    - date: 조회 날짜 (YYYY-MM-DD)
    - data_type: logs, videos, comments (기본: logs)
    """
    category = request.GET.get('category', 'HHP')
    date_str = request.GET.get('date')
    data_type = request.GET.get('data_type', 'logs')

    if not date_str:
        target_date = datetime.now().date()
    else:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    try:
        result = svc.get_youtube_raw_data(category, data_type, target_date)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': log_error(e)})
