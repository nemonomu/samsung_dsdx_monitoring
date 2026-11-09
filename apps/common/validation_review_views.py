"""Administrator review: read-only audit data and separate completion checks."""
import json
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache

from apps.common.params import parse_date
from apps.common.response import safe_error
from . import validation_review as service
from . import validation_review_checks as checks


def administrator(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and (user.is_staff or user.is_superuser)):
            return JsonResponse({'error': '관리자만 검수 이력을 조회할 수 있습니다.'}, status=403)
        return view(request, *args, **kwargs)
    return never_cache(guarded)


def arguments(request):
    day = parse_date(request.GET.get('date'))
    kind = request.GET.get('type', '')
    if day is None or kind not in service.KINDS:
        raise ValueError('검증 종류와 조회 날짜를 확인하세요.')
    return day, kind


@administrator
@require_GET
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
@require_GET
def data(request):
    try:
        day, kind = arguments(request)
        table = request.GET.get('table', '')
        retailer = request.GET.get('retailer')
        if request.GET.get('view') != 'records':
            result = service.summary(day, kind, table, retailer)
            if not table:
                checks.attach(result.get('items', []), day, kind)
            return JsonResponse(result)
        field = request.GET.get('field', '')
        rule = int(request.GET['rule']) if request.GET.get('rule') else None
        page_number, days = int(request.GET.get('page', 1)), int(request.GET.get('days', 3))
        status = request.GET.get('status', 'all')
        if not table or retailer is None or not field or page_number < 1 or not 1 <= days <= 30:
            raise ValueError('상세 조회 조건을 확인하세요.')
        if status not in {'all', *service.STATUSES}:
            raise ValueError('처리 상태를 확인하세요.')
        options = {}
        if kind in service.DETAIL_TOOLS and 'columns' in request.GET:
            selected = [c for c in request.GET['columns'].split(',') if c]
            if len(selected) > 100 or any(not service.audit.IDENTIFIER.fullmatch(c) for c in selected):
                raise ValueError('추가 컬럼 선택을 확인하세요.')
            options['extra_columns'] = selected
        for name, allowed, default in (
                ('q_field', service.SEARCH_FIELDS, 'all'),
                ('sort_by', ('', 'id', 'item'), ''),
                ('sort_order', ('asc', 'desc'), 'asc')):
            if name in request.GET:
                value = request.GET.get(name, default)
                if value not in allowed:
                    raise ValueError('검색 항목과 정렬 조건을 확인하세요.')
                options[name] = value
        return JsonResponse(service.records(day, kind, table, retailer, field, rule,
                            page_number, days, request.GET.get('q', '').strip(), status, **options))
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc, 'admin_validation_review')


@administrator
@require_http_methods(['GET', 'POST'])
@csrf_protect
def check(request):
    try:
        body = request.GET if request.method == 'GET' else json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError('요청을 확인하세요.')
        day = parse_date(body.get('date'), default=None)
        if day is None:
            raise ValueError('검수 날짜를 확인하세요.')
        if request.method == 'GET':
            result = checks.get_checked(day, body.get('type'), body.get('table'), body.get('retailer'))
        else:
            result = checks.set_checked(day, body.get('type'), body.get('table'),
                                        body.get('retailer'), body.get('checked'),
                                        request.user.get_username())
        return JsonResponse({'success': True, 'check': result})
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc, 'save')
