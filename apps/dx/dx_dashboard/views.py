"""
DX 대시보드 — 페이지 뷰
"""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.common.db import dx_connection
from apps.common.monitoring_cache import cached_monitoring_stats
from apps.common.params import parse_date
from apps.common.response import safe_error
from apps.common.sem_retail import SEM_TV_OBSERVATION_START
from apps.dx.dx_layer1.sem_retail.sem_retail_services import get_new_tv_receipts
from .dashboard.dashboard_services import get_dashboard_context

def dashboard(request):
    """DX 대시보드 페이지"""
    context = get_dashboard_context()
    return render(request, 'dx_dashboard.html', context)


_RECEIPT_STATUS = {
    'OK': 'received', 'CRITICAL': 'uncollected',
    'COLLECTING': 'collecting', 'PENDING': 'scheduled',
}


@require_GET
@cached_monitoring_stats
def sem_tv_status(request):
    target_date = parse_date(request.GET.get('date'), default=None)
    if target_date is None:
        return JsonResponse({'error': '날짜 형식이 올바르지 않습니다.'}, status=400)
    if target_date < SEM_TV_OBSERVATION_START:
        return JsonResponse({'countries': []})
    try:
        with dx_connection() as (_, cursor):
            source_date, receipts = get_new_tv_receipts(cursor, target_date)
    except Exception as exc:
        return safe_error(exc)
    retailers = []
    for receipt in receipts:
        row = {'retailer': receipt['retailer'], 'product': 'TV',
               'status': _RECEIPT_STATUS[receipt['status']]}
        main, bsr = receipt['main_count'], receipt['bsr_count']
        if main < bsr:
            row.update(status='rank_mismatch',
                       status_reason=f'MAIN {main}건 / BSR {bsr}건 / MAIN이 BSR보다 적음')
        retailers.append(row)
    return JsonResponse({'countries': [{
        'country': 'SEM', 'source_date': source_date, 'retailers': retailers,
    }]})
