"""Administrator-only, GET-only validation review pages and data."""
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from apps.common.params import parse_date
from apps.common.response import safe_error
from . import validation_review as service


def administrator(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and (user.is_staff or user.is_superuser)):
            return JsonResponse({'error': '관리자만 검수 이력을 조회할 수 있습니다.'}, status=403)
        return view(request, *args, **kwargs)
    return never_cache(require_GET(guarded))


def arguments(request):
    day = parse_date(request.GET.get('date'))
    kind = request.GET.get('type', '')
    if day is None or kind not in service.KINDS:
        raise ValueError('검증 종류와 조회 날짜를 확인하세요.')
    return day, kind


@administrator
def page(request):
    try:
        day, kind = arguments(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    label, layer, section = service.KINDS[kind]
    if layer == 2:
        from apps.dx.dx_layer2.common.context import build_context
    else:
        from apps.dx.dx_layer3.common.context import build_context
    context = build_context(section, request)
    context.update(admin_review=True, review_kind=kind, review_label=label,
                   target_date=str(day), base_template=f'base_layer{layer}.html')
    return render(request, 'validation_review.html', context)


@administrator
def data(request):
    try:
        day, kind = arguments(request)
        table = request.GET.get('table', '')
        retailer = request.GET.get('retailer')
        if request.GET.get('view') != 'records':
            return JsonResponse(service.summary(day, kind, table, retailer))
        field = request.GET.get('field', '')
        rule = int(request.GET['rule']) if request.GET.get('rule') else None
        page_number, days = int(request.GET.get('page', 1)), int(request.GET.get('days', 3))
        status = request.GET.get('status', 'all')
        if not table or retailer is None or not field or page_number < 1 or not 1 <= days <= 30:
            raise ValueError('상세 조회 조건을 확인하세요.')
        if status not in {'all', *service.STATUSES}:
            raise ValueError('처리 상태를 확인하세요.')
        return JsonResponse(service.records(day, kind, table, retailer, field, rule,
                            page_number, days, request.GET.get('q', '').strip(), status))
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc, 'admin_validation_review')
