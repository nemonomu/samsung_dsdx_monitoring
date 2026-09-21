from datetime import date

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.common.db import dx_connection
from apps.common.response import safe_error
from .retail_batches import _source, fetch_batch_details


@require_GET
def batch_details(request):
    try:
        check_type = request.GET.get('check_type', '')
        product = request.GET.get('product_line', '')
        source_date = date.fromisoformat(request.GET.get('source_date', '')).isoformat()
        retailer = request.GET.get('retailer', '').strip()
        _source(check_type, product)
        if not retailer or len(retailer) > 200:
            raise ValueError('Invalid retailer')
    except ValueError:
        return JsonResponse({'error': '조회할 법인·품목·리테일러·수집 대상일을 확인해주세요.'}, status=400)
    try:
        with dx_connection() as (_conn, cursor):
            return JsonResponse(fetch_batch_details(cursor, check_type, product, source_date, retailer))
    except Exception as exc:
        return safe_error(exc, 'db')
