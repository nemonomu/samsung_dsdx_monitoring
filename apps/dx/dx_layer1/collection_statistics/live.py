"""Read current collection counts against stored, strictly prior-day history.

This path never runs a collector, acquires a refresh lease, or writes snapshots.
One request is scoped to one country and one inspection date.
"""
import importlib
import logging
from datetime import datetime, timedelta, timezone as tz

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.common.db import dx_connection
from apps.dx.dx_layer1.common.retail_batches import add_batch_counts
from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily
from .api import selected_date
from .calculations import (
    COUNTRIES, OFFSETS, MAIN_POLICY_VERSION, MINIMUM_DAYS, normalize_check,
    compare_rows, comparison_rules, observation_key, SOURCE_START_DATES,
)
from .reviews import review_index, attach_review

logger = logging.getLogger(__name__)


def load_current_check(country, inspection_date):
    name = ('retail.retail_services' if country == 'SEA'
            else f'{country.lower()}_retail.{country.lower()}_retail_services')
    service = importlib.import_module('apps.dx.dx_layer1.' + name)
    now = datetime.now(tz(timedelta(hours=9)))
    if country == 'SEA':
        now = now.replace(tzinfo=None)
    with dx_connection() as (_, cursor):
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '8000ms'")
        result = service.get_layer1_stats(cursor, inspection_date, now)
        check = result.get('check') if isinstance(result, dict) else None
        if not check or check.get('error') or check.get('status') == 'ERROR' or not check.get('categories'):
            raise ValueError('Collection counts unavailable')
        add_batch_counts(cursor, check, inspection_date)
    return check


def current_snapshot(country, inspection_date):
    source_day = inspection_date - timedelta(days=OFFSETS[country])
    start = max(source_day - timedelta(days=28), SOURCE_START_DATES.get(country, source_day - timedelta(days=28)))
    check = load_current_check(country, inspection_date)
    current = normalize_check(check, country, inspection_date)
    # Only saved prior dates enter a median. Neither current counts nor a stale
    # current-day zero can change or suppress that reference.
    snapshots = list(Daily.objects.filter(country=country, refresh_error=False,
        source_date__gte=start, source_date__lt=source_day).order_by('source_date'))
    history = [{**row, 'source_date': str(snapshot.source_date)}
               for snapshot in snapshots for row in snapshot.rows]
    # Preserve lifetime observation through a long gap without scanning raw history.
    older_query = Daily.objects.filter(country=country, refresh_error=False, source_date__lt=start)
    if country in SOURCE_START_DATES:
        older_query = older_query.filter(source_date__gte=SOURCE_START_DATES[country])
    older = older_query.order_by('-source_date').first()
    prior_counts = {}
    for snapshot in ([older] if older else []) + snapshots:
        for row in snapshot.rows:
            count = (MINIMUM_DAYS if row.get('observation_state') == 'ready'
                     else row.get('observation_days', 0))
            key = observation_key(row)
            prior_counts[key] = max(prior_counts.get(key, 0), count or 0)
    rows = compare_rows(current, history, country, prior_observation_counts=prior_counts)
    reviews = review_index(source_day, source_day)
    for row in rows:
        # No saved evidence is not proof that an established retailer is new.
        if not snapshots and not older and not row.get('active_from'):
            row.update(observation_state='unknown', comparison_state='unknown',
                       baselines={}, alerts=[a for a in row['alerts'] if a.get('rule') == 'main_lt_bsr'])
        row['date'] = str(source_day)
        row['state'] = ('error' if row.get('base_status') == 'ERROR' or row.get('refresh_error')
                        else 'complete' if row['complete'] else 'pending')
        row['rules'] = comparison_rules(row, country)
    rows = [attach_review(row, country, row['product'], row['retailer'], row['slot'], reviews)
            for row in rows]
    return {'country': country, 'inspection_date': str(inspection_date),
            'source_date': str(source_day), 'updated_at': timezone.now().isoformat(),
            'available': True, 'live': True, 'check': check, 'rows': rows}


@require_GET
def current(request):
    try:
        country = request.GET.get('country')
        day = selected_date(request.GET.get('date'))
        if country not in COUNTRIES or day > selected_date(None) + timedelta(days=1):
            raise ValueError('Invalid country or date')
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({'error': '국가·검수일을 확인해주세요.'}, status=400)
    try:
        snapshot = current_snapshot(country, day)
        response = JsonResponse({'inspection_date': str(day), 'policy_version': MAIN_POLICY_VERSION,
                                 'snapshots': [snapshot]})
    except Exception:
        # A read failure is never a zero collection or a normal verdict.
        logger.warning('Live collection read failed: %s %s', country, day, exc_info=True)
        response = JsonResponse({'error': '현재 수집 건수를 확인하지 못했습니다. 다시 조회합니다.'}, status=503)
    response['Cache-Control'] = 'private, no-store'
    return response
