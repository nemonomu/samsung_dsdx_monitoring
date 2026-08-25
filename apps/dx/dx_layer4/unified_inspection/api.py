"""Read-only APIs for the unified inspection page."""

from django.http import JsonResponse

from apps.common.inspection_dates import (
    COUNTRY_ORDER,
    SOURCE_PRODUCT_BY_KEY,
    MonitoringDateError,
    resolve_monitoring_dates,
)


def date_mapping(request):
    """Return the five-country mapping for a required inspection date."""

    try:
        resolutions = resolve_monitoring_dates(request.GET.get('date'))
    except MonitoringDateError as exc:
        return JsonResponse({
            'success': False,
            'error': str(exc),
        }, status=400)

    countries = []
    for country in COUNTRY_ORDER:
        country_sources = [
            resolution
            for resolution in resolutions
            if resolution['country'] == country
        ]
        first = country_sources[0]
        countries.append({
            'country': country,
            'inspection_date': first['inspection_date'],
            'source_date': first['source_date'],
            'offset_days': first['offset_days'],
            'rule': 'D-1' if first['offset_days'] == -1 else 'D',
            'sources': [
                {
                    'source_key': source['source_key'],
                    'product': SOURCE_PRODUCT_BY_KEY[source['source_key']],
                }
                for source in country_sources
            ],
        })

    return JsonResponse({
        'success': True,
        'inspection_date': resolutions[0]['inspection_date'],
        'countries': countries,
        'source_count': len(resolutions),
        'read_only': True,
    })
