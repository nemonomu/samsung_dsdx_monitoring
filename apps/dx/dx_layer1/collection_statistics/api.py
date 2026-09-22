"""Bounded reads of persisted statistics; these endpoints never contact source tables."""
from datetime import date, timedelta, timezone as tz

from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily, CollectionWeeklySnapshot as Weekly
from apps.dx.dx_layer1.common.context import build_context
from .calculations import COUNTRIES, week_start


def page(request):
    return render(request, 'dx_layer1_collection_statistics.html', build_context('collection_statistics', request))


def selected_date(value):
    if not value:
        return timezone.localdate(timezone=tz(timedelta(hours=9)))
    if len(value) != 10:
        raise ValueError('Invalid date')
    return date.fromisoformat(value)


@require_GET
def weekly(request):
    try:
        country = request.GET.get('country', 'SEA')
        product = request.GET.get('product', 'ALL')
        retailer = request.GET.get('retailer', '')
        if country not in COUNTRIES or product not in ('ALL', 'TV', 'REF', 'LDY') or len(retailer) > 200:
            raise ValueError('Invalid filter')
        weeks = int(request.GET.get('weeks', '8'))
        if not 1 <= weeks <= 12:
            raise ValueError('Invalid weeks')
        end_week = week_start(selected_date(request.GET.get('date')))
        start_week = end_week - timedelta(weeks=weeks - 1)
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '국가·제품군·날짜·기간을 확인해주세요.'}, status=400)
    try:
        snapshots = list(Weekly.objects.filter(country=country, week_start__range=(start_week, end_week)).order_by('-week_start'))
    except DatabaseError:
        return JsonResponse({'error': '통계를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.'}, status=503)
    by_week = {snapshot.week_start: snapshot for snapshot in snapshots}
    retailers = sorted({row['retailer'] for snapshot in snapshots for row in snapshot.rows
                        if product == 'ALL' or row['product'] == product})
    result = []
    for offset in range(weeks):
        monday = end_week - timedelta(weeks=offset)
        snapshot = by_week.get(monday)
        rows = [row for row in snapshot.rows if (product == 'ALL' or row['product'] == product)
                and (not retailer or row['retailer'] == retailer)] if snapshot else []
        result.append({'start': str(monday), 'end': str(monday + timedelta(days=6)),
                       'rows': rows, 'available': bool(snapshot),
                       'updated_at': snapshot.updated_at.isoformat() if snapshot else None})
    return JsonResponse({'country': country, 'product': product, 'retailers': retailers, 'weeks': result,
                         'updated_at': min((s.updated_at for s in snapshots), default=None),
                         'basis': 'source_date', 'baseline_days': 28, 'minimum_history_days': 7})


@require_GET
def alerts(request):
    try:
        day = selected_date(request.GET.get('date'))
    except (ValueError, TypeError):
        return JsonResponse({'error': '날짜를 확인해주세요.'}, status=400)
    try:
        snapshots = list(Daily.objects.filter(inspection_date=day, country__in=COUNTRIES))
    except DatabaseError:
        return JsonResponse({'error': '수집량 비교 결과를 불러올 수 없습니다.'}, status=503)
    now = timezone.now()
    return JsonResponse({'inspection_date': str(day), 'snapshots': [{
        'country': snapshot.country, 'source_date': str(snapshot.source_date),
        'updated_at': snapshot.updated_at.isoformat(),
        'available': not snapshot.refresh_error and now - snapshot.updated_at < timedelta(minutes=60)
            if day >= timezone.localdate(timezone=tz(timedelta(hours=9))) else not snapshot.refresh_error,
        'rows': [{key: row.get(key) for key in ('product', 'retailer', 'slot', 'main', 'bsr', 'total',
                   'batch_id', 'complete', 'alerts', 'comparison_state')} for row in snapshot.rows],
    } for snapshot in snapshots]})
