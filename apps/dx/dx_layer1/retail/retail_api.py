from django.http import JsonResponse
from datetime import datetime, timedelta
from apps.common.response import log_error
from . import retail_services as svc


def retail_detail(request):
    """리테일 상세 현황 API"""
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'tv')  # tv or hhp

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        result = svc.get_retail_detail(target_date, product_line)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': log_error(e)})


def retail_summary(request):
    """Retail 상세 현황 API - 리테일러×시간대×페이지타입별 테이블 + NULL 컬럼 현황"""
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'tv')  # tv or hhp

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        result = svc.get_retail_summary(target_date, product_line)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': log_error(e)})


def retailer_raw_data(request):
    """
    리테일러별 원본 데이터 조회 API
    - category: TV 또는 HHP
    - retailer: Amazon, Bestbuy, Walmart
    - period: 일일
    - date: 조회 날짜 (YYYY-MM-DD)
    """
    category = request.GET.get('category', 'TV')
    retailer = request.GET.get('retailer', 'Amazon')
    period = request.GET.get('period', '일일')
    date_str = request.GET.get('date')

    if not date_str:
        target_date = (datetime.now() - timedelta(days=1)).date()
    else:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    try:
        result = svc.get_retailer_raw_data(category, retailer, period, target_date)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': log_error(e)})


def retailer_columns_info(request):
    """
    TV/HHP 리테일러별 수집 컬럼 정보 API
    - DB(monitoring_retail_columns)에서 컬럼 정보 로드
    """
    try:
        result = svc.get_retailer_columns_info()
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': log_error(e)})


def backup_status(request):
    """백업 상태 확인 API — Layer 2/3 진입 시 호출"""
    from apps.common.backup import get_backup_status

    target_date = request.GET.get('date', '').strip()
    if not target_date:
        return JsonResponse({'success': True, 'pending_count': 0, 'has_backup': True})

    return JsonResponse(get_backup_status(target_date))


def backup_retail_data(request):
    """SEA TV와 TSE TV/REF/LDY 통합 백업 API.

    GET: 백업 대상 건수 조회
    POST: 백업 실행
    """
    from apps.common.backup import backup_all_retail, get_backup_count

    target_date = request.GET.get('date') or request.POST.get('date') or ''
    target_date = target_date.strip() or None

    if request.method == 'GET':
        # 건수만 조회
        result = get_backup_count(target_date)
        if result['success']:
            return JsonResponse({
                'success': True,
                'tv_count': result['tv_count'],
                'tse_tv_count': result['tse_tv_count'],
                'tse_ref_count': result['tse_ref_count'],
                'tse_ldy_count': result['tse_ldy_count'],
                'hhp_count': 0,
                'total_count': result['total_count'],
            })
        else:
            return JsonResponse({'success': False, 'error': result.get('error', 'Unknown error')})

    elif request.method == 'POST':
        # 백업 실행
        username = request.user.username if request.user.is_authenticated else ''
        result = backup_all_retail(username, target_date)

        if result['success']:
            counts = {
                'tv_count': result['tv']['count'],
                'tse_tv_count': result['tse_tv']['count'],
                'tse_ref_count': result['tse_ref']['count'],
                'tse_ldy_count': result['tse_ldy']['count'],
            }
            message = (
                f"백업 완료 - SEA TV: {counts['tv_count']}건, "
                f"TSE TV: {counts['tse_tv_count']}건, "
                f"TSE REF: {counts['tse_ref_count']}건, "
                f"TSE LDY: {counts['tse_ldy_count']}건"
            )
            return JsonResponse({
                'success': True,
                'message': message,
                **counts,
                'hhp_count': 0,
                'total_count': sum(counts.values()),
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error', '통합 백업 중 오류가 발생했습니다.'),
            })
