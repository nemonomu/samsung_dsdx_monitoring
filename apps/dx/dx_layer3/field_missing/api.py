"""
Layer 3 필드 누락 API
"""

from django.http import JsonResponse
from datetime import datetime
from apps.common.db import dx_connection
from apps.common.retail_columns import get_editable_columns
from apps.common.response import safe_error, log_error
from . import services
from .services import get_field_missing_excluded_columns


def _validation_columns(product_line, retailer):
    fixed = services.get_field_missing_validation_columns(product_line)
    if fixed:
        return fixed
    from apps.common.retail_columns import get_retail_columns_for_retailer
    return get_retail_columns_for_retailer(product_line, retailer)


def _columns_with_related(product_line, retailer):
    from apps.common.retail_columns import get_retail_columns_with_related
    configured = get_retail_columns_with_related(product_line, retailer)
    fixed = services.get_field_missing_validation_columns(product_line)
    if not fixed:
        return configured
    result = []
    configured_names = set()
    for column in configured:
        column_name = column.get('column_name')
        if not column_name or column_name in configured_names:
            continue
        configured_names.add(column_name)
        result.append(column)
    for column in fixed:
        if column in configured_names:
            continue
        result.append({
            'column_name': column,
            'related_columns': '',
        })
    return result


def _resolve_request_dates(date_str, product_line):
    inspection_date = (
        datetime.strptime(date_str, '%Y-%m-%d').date()
        if date_str
        else datetime.now().date()
    )
    contract = services.resolve_field_missing_date_contract(
        inspection_date, product_line
    )
    source_date = datetime.strptime(
        contract['source_date'], '%Y-%m-%d'
    ).date()
    return inspection_date, source_date, contract


def _attach_date_contract(result, contract):
    result['inspection_date'] = contract['inspection_date']
    result['source_date'] = contract['source_date']
    result['offset_days'] = contract['offset_days']
    return result


def field_missing_detection(request):
    """
    필드 누락 탐지 API
    - 데이터일과 그 직전 2일 비교
    - 직전에는 값이 있었는데 데이터일에 NULL/빈값인 필드 탐지
    """
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'tv')  # tv, hhp
    retailer = request.GET.get('retailer', 'all')  # Amazon, Bestbuy, Walmart, all

    _inspection_date, target_date, date_contract = _resolve_request_dates(
        date_str, product_line
    )

    # DB에서 리테일러별 수집 필드 로드 (skip_missing_check=TRUE인 필드 제외)
    retail_columns = {}
    for ret in services.get_field_missing_retailers(product_line):
        cols = _validation_columns(product_line, ret)
        if cols:
            retail_columns[ret] = cols

    try:
        with dx_connection() as (conn, cursor):
            result = services.field_missing_detection(
                cursor, target_date, product_line, retailer, retail_columns,
                inspection_date=_inspection_date,
            )
        _attach_date_contract(result, date_contract)
        return JsonResponse(result)
    except Exception as e:
        log_error(e)
        return safe_error(e)


def field_missing_detail_all(request):
    """
    필드 누락 탐지 상세 - 3일치 raw 데이터 (무한스크롤용)
    item + crawl_datetime 순으로 정렬, 필드들을 컬럼으로 표시
    offset/limit 파라미터로 데이터 분할 조회
    """
    date_str = request.GET.get('date')
    product_line = request.GET.get('product_line', request.GET.get('type', 'tv'))
    retailer = request.GET.get('retailer', 'Amazon')
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
        limit = min(int(request.GET.get('limit', 100)), 500)
    except (ValueError, TypeError):
        offset = 0
        limit = 100

    _inspection_date, target_date, date_contract = _resolve_request_dates(
        date_str, product_line
    )

    # DB에서 리테일러별 수집 필드 로드
    if services.is_sea_field_missing_product_line(product_line):
        retail_columns = [
            column['column_name']
            for column in _columns_with_related(product_line, retailer)
        ]
    else:
        from apps.common.retail_columns import get_retailer_columns
        retail_columns = get_retailer_columns(product_line, retailer)

    # 표시할 필드 선택 (긴 텍스트 필드 제외)
    exclude_cols = ['calendar_week', 'detailed_review_content', 'summarized_review_content']
    display_fields = [c for c in retail_columns if c not in exclude_cols and c not in ['id', 'item', 'account_name', 'page_type', 'crawl_datetime', 'crawl_strdatetime', 'product_url']]

    try:
        with dx_connection() as (conn, cursor):
            result = services.field_missing_detail_all(
                cursor, target_date, product_line, retailer,
                display_fields, offset, limit
            )
        _attach_date_contract(result, date_contract)
        return JsonResponse(result)
    except Exception as e:
        log_error(e)
        return JsonResponse({'status': 'error', 'message': '처리 중 오류가 발생했습니다.'})


def field_missing_detail_problem(request):
    """
    필드 누락 탐지 상세 - 문제 있는 item만 (직전에 있었는데 데이터일에 없는)
    column 파라미터 없으면 해당 리테일러의 모든 컬럼 검사
    무한 스크롤: offset, limit 파라미터 지원
    """
    date_str = request.GET.get('date')
    product_line = request.GET.get('product_line', request.GET.get('type', 'tv'))
    retailer = request.GET.get('retailer', 'Amazon')
    column = request.GET.get('column', '')  # 선택: 검사할 컬럼 (없으면 모든 컬럼)
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
        limit = min(int(request.GET.get('limit', 100)), 500)
    except (ValueError, TypeError):
        offset = 0
        limit = 100

    _inspection_date, target_date, date_contract = _resolve_request_dates(
        date_str, product_line
    )

    # DB에서 리테일러별 수집 필드 로드
    if services.is_sea_field_missing_product_line(product_line):
        retail_columns = services.get_field_missing_validation_columns(
            product_line
        )
    else:
        from apps.common.retail_columns import get_retailer_columns
        retail_columns = get_retailer_columns(product_line, retailer)

    # 기본 필드 제외
    exclude_cols = ['id', 'item', 'account_name', 'page_type', 'crawl_datetime', 'crawl_strdatetime', 'calendar_week', 'product_url']
    field_missing_excludes = get_field_missing_excluded_columns(product_line)
    columns_to_check = [c for c in retail_columns if c not in exclude_cols and c not in field_missing_excludes]

    # column 파라미터가 있으면 해당 컬럼만
    if column:
        columns_to_check = [column] if column in columns_to_check else []

    try:
        with dx_connection() as (conn, cursor):
            result = services.field_missing_detail_problem(
                cursor, target_date, product_line, retailer,
                columns_to_check, offset, limit
            )
        _attach_date_contract(result, date_contract)
        return JsonResponse(result)
    except Exception as e:
        log_error(e)
        return JsonResponse({'status': 'error', 'message': '처리 중 오류가 발생했습니다.'})


def field_missing_detail_by_field(request):
    """
    특정 필드의 누락 item들에 대한 3일치 raw 데이터 조회
    - 직전 2일에 값이 있었는데 데이터일에 없는 item들의 3일치 전체 데이터
    """
    date_str = request.GET.get('date')
    product_line = request.GET.get('product_line', 'tv')
    retailer = request.GET.get('retailer', 'Amazon')
    field = request.GET.get('field', '')  # 필수: 조회할 필드
    _inspection_date, target_date, date_contract = _resolve_request_dates(
        date_str, product_line
    )
    if field in get_field_missing_excluded_columns(product_line):
        result = {
            'status': 'success',
            'message': 'field excluded from missing validation',
            'date': date_contract['source_date'],
            'product_line': product_line.upper(),
            'retailer': retailer,
            'field': field,
            'total_rows': 0,
            'data': [],
            'normal_reviews': {},
        }
        return JsonResponse(_attach_date_contract(result, date_contract))
    days = int(request.GET.get('days', 3))
    if days < 1:
        days = 1
    if days > 30:
        days = 30

    if not field:
        return JsonResponse({'status': 'error', 'message': 'field 파라미터가 필요합니다.'})

    # DB에서 리테일러별 수집 필드 및 related_columns 로드
    columns_info = _columns_with_related(product_line, retailer)
    display_fields = [c['column_name'] for c in columns_info]
    related_columns = []
    for c in columns_info:
        if c['column_name'] == field and c['related_columns']:
            related_columns = [col.strip() for col in c['related_columns'].split('|') if col.strip()]
            break
    default_related = services.get_field_missing_default_related_columns(
        product_line, field
    )
    if default_related:
        related_columns = default_related

    if field not in display_fields:
        return JsonResponse({'status': 'error', 'message': '허용되지 않은 필드'})

    editable_cols = get_editable_columns(product_line, retailer)

    try:
        with dx_connection() as (conn, cursor):
            result = services.field_missing_detail_by_field(
                cursor, target_date, product_line, retailer, field, days,
                columns_info, display_fields, related_columns, editable_cols,
                inspection_date=_inspection_date,
            )
        _attach_date_contract(result, date_contract)
        return JsonResponse(result)
    except Exception as e:
        log_error(e)
        return JsonResponse({'status': 'error', 'message': '처리 중 오류가 발생했습니다.'})
