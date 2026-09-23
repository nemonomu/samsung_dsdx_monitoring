from datetime import date, timedelta, timezone as tz

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.dx.dx_layer1.common.context import build_context
from .services import catalog, daily_counts, select_source


@require_GET
def page(request):
    return render(request, 'dx_layer1_column_statistics.html', {
        **build_context('column_statistics', request), 'column_catalog': catalog(),
    })


@require_GET
def daily(request):
    try:
        country = request.GET.get('country', 'SEA')
        product = request.GET.get('product', 'TV')
        retailer = request.GET.get('retailer', 'Amazon')
        select_source(country, product, retailer)
        days = int(request.GET.get('days', '7'))
        if days not in (5, 7, 14, 28, 49):
            raise ValueError('Invalid period')
        today = timezone.localdate(timezone=tz(timedelta(hours=9)))
        raw_date = request.GET.get('date', str(today))
        if len(raw_date) != 10:
            raise ValueError('Invalid date')
        end = date.fromisoformat(raw_date)
        if end > today:
            raise ValueError('Future date')
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '국가·제품군·리테일러·기간·날짜를 확인해주세요.'}, status=400)
    key = f'column-statistics:v1:{country}:{product}:{retailer}:{end}:{days}'
    try:
        result = cache.get(key)
        if result is None:
            result = daily_counts(country, product, retailer, end, days)
            result['updated_at'] = timezone.now().isoformat()
            cache.set(key, result, 300)
    except Exception:
        # Never convert a failed query into zero collected values or expose DB details.
        return JsonResponse({'error': '수집 통계를 조회하지 못했습니다. 잠시 후 다시 조회해주세요.'}, status=503)
    return JsonResponse(result)
