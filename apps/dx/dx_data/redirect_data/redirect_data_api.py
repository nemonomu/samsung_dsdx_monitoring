"""API for the read-only Amazon redirect data page."""

from datetime import date

from django.http import JsonResponse

from apps.common.response import safe_error

from .redirect_data_services import get_amazon_redirect_list


def redirect_data_list(request):
    date_text = request.GET.get('date', '')
    country = request.GET.get('country', 'SEA')
    product = request.GET.get('product', 'TV')
    try:
        target_date = date.fromisoformat(date_text)
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(200, max(10, int(request.GET.get('page_size', 20))))
    except (TypeError, ValueError):
        return JsonResponse({'error': '잘못된 조회 파라미터'}, status=400)

    try:
        return JsonResponse(
            get_amazon_redirect_list(
                target_date, page, page_size,
                country=country, product=product,
            )
        )
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        return safe_error(exc, 'db')
