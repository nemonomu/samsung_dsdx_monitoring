"""Read-only overview and prepared counts for the country statistics page."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.cache.backends.filebased import FileBasedCache
from django.utils import timezone

from apps.common.dryer_onboarding import is_preview
from apps.common.inspection_dates import PRODUCT_ORDER, resolve_monitoring_date
from apps.common.monitoring_cache import monitoring_cache_generation, monitoring_cached_value
from apps.common.seib_retail import is_eci_appliance_preview
from apps.dx.dx_layer1.collection_issues.queries import raw_counts
from apps.dx.dx_layer1.siel_retail import jiomart

from .comparison import BASELINE_DAYS, attach_comparisons, collection_complete
from .services import catalog, daily_counts, select_source


logger = logging.getLogger(__name__)
_WINDOW = BASELINE_DAYS + 1
_PREPARED_TTL = 20 * 60  # The existing collection-issue job runs every 15 minutes.
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='column-overview')


@lru_cache(maxsize=4)
def _file_cache(path):
    return FileBasedCache(str(path), {'TIMEOUT': _PREPARED_TTL, 'OPTIONS': {'MAX_ENTRIES': 512}})


def _prepared_cache():
    directory = getattr(settings, 'MONITORING_CACHE_DIR', None)
    base = Path(directory) if directory is not None else Path(settings.BASE_DIR) / '.cache' / 'dx-monitoring'
    return _file_cache(base / ('test' if settings.DEBUG else 'production') / 'column-counts')


def prepared_generation():
    if getattr(settings, 'MONITORING_CACHE_ENABLED', True):
        try:
            return monitoring_cache_generation()
        except OSError:
            logger.warning('Column statistics snapshot directory unavailable', exc_info=True)
    return None


def _key(scope, day, generation):
    return 'column-counts:v1:' + ':'.join((generation, *scope, str(day)))


def _preview(scope, target):
    country, product, retailer = scope
    return (country == 'SEIB' and is_eci_appliance_preview(product, retailer, target)
            or jiomart.matches(*scope) and jiomart.preview(target)
            or is_preview(country, product, retailer, target))


def _window(data, target, totals, now):
    end = data['dates'].index(str(target)) + 1
    if end < _WINDOW:
        return None
    daily = data['daily'][end - _WINDOW:end]
    daily = [*daily[:-1], {**daily[-1], 'raw_total': totals.get(str(target), 0)}]
    return {**data, 'dates': data['dates'][end - _WINDOW:end], 'daily': daily,
            'updated_at': now.isoformat()}


def prepare_recent(data, totals, days, previous_day, now, generation):
    """Reuse the incident scan's history, plus one due day's counts if needed."""
    if generation is None:
        return
    scope = tuple(data[key] for key in ('country', 'product', 'retailer'))
    cache = _prepared_cache()
    for day in days:
        if (day < previous_day - timedelta(days=2) or _preview(scope, day)
                or not collection_complete(*scope, day, now)):
            continue
        window = _window(data, day, totals, now)
        if window is not None:
            cache.set(_key(scope, day, generation), window)

    current_day = previous_day + timedelta(days=1)
    if (previous_day not in days or _preview(scope, previous_day) or _preview(scope, current_day)
            or not collection_complete(*scope, current_day, now)):
        return
    yesterday = _window(data, previous_day, totals, now)
    if yesterday is None:
        return
    today = daily_counts(*scope, current_day, 1)
    if today['columns'] != yesterday['columns']:
        return  # The overview reads a fresh full window after a config change.
    today_totals = raw_counts(*scope, current_day, current_day)
    today['dates'] = yesterday['dates'][1:] + today['dates']
    today['daily'] = data['daily'][-BASELINE_DAYS:] + today['daily']
    cache.set(_key(scope, current_day, generation), _window(today, current_day, today_totals, now))


def selected_scopes(country, product, retailer, inspection_date):
    selections = []
    for entry in catalog():
        if entry['country'] != country or product not in ('all', entry['product']):
            continue
        for name in entry['retailers']:
            if retailer not in ('all', name):
                continue
            scope = (country, entry['product'], name)
            source = select_source(*scope)
            mapping = resolve_monitoring_date(inspection_date, country, source['key'])
            selections.append((scope, date.fromisoformat(mapping['source_date'])))
    if not selections:
        raise ValueError('Invalid column statistics scope')
    order = {product: index for index, product in enumerate((*PRODUCT_ORDER, 'LDY_DRYER'))}
    return sorted(selections, key=lambda entry: order[entry[0][1]])


def history_reuse_enabled(scope):
    return ':'.join(scope) in getattr(settings, 'DX_COLUMN_HISTORY_REUSE_SCOPES', ())


def live_counts(scope, target):
    def read():
        country, product, retailer = scope
        prior = target - timedelta(days=1)
        selection = (scope, prior)
        generation = prepared_generation() if not preview and history_reuse_enabled(scope) else None
        history = _prepared_counts([selection], generation=generation).get(selection) if generation else None
        if history:
            expected_dates = [str(target - timedelta(days=offset)) for offset in range(_WINDOW, 0, -1)]
            if history['dates'] != expected_dates or [row['date'] for row in history['daily']] != expected_dates:
                history = None

        def collect(days):
            started = timezone.now()
            data = daily_counts(*scope, target, days)
            if country == 'SEIB' and is_eci_appliance_preview(product, retailer, target):
                totals = {str(target): data['daily'][-1]['total']}
            else:
                totals = raw_counts(*scope, target, target)
            return data, totals, started

        data, totals, started = collect(1 if history else _WINDOW)
        if history:
            if data['columns'] == history['columns'] and generation == prepared_generation():
                data['dates'] = history['dates'][1:] + data['dates']
                prior_rows = [{key: value for key, value in row.items() if key != 'raw_total'}
                              for row in history['daily'][1:]]
                data['daily'] = prior_rows + data['daily']
                data['read_days'] = 1
            else:
                data, totals, started = collect(_WINDOW)
        data.setdefault('read_days', _WINDOW)
        return _window(data, target, totals, started)

    preview = _preview(scope, target)
    if preview:
        return read()
    return monitoring_cached_value('column-overview-live-v3', [*scope, str(target)], read)


def _prepared_counts(selections, *, generation=None):
    if generation is None:
        generation = prepared_generation()
    if generation is None:
        return {}
    keys = {_key(scope, day, generation): (scope, day) for scope, day in selections
            if not _preview(scope, day)}
    try:
        stored = _prepared_cache().get_many(keys)
    except (OSError, ValueError):
        logger.warning('Failed to load prepared column statistics', exc_info=True)
        return {}
    return {keys[key]: entry for key, entry in stored.items()}


def detail_counts(scope, target, days):
    if days != _WINDOW or _preview(scope, target):
        return None
    selection = (scope, target)
    result = _prepared_counts([selection]).get(selection)
    if result and datetime.fromisoformat(result['updated_at']) >= timezone.now() - timedelta(minutes=5):
        return result
    return monitoring_cached_value('column-overview-live-v3', [*scope, str(target)])


def _compare(data, target, now):
    compared = attach_comparisons(data, target, now)
    if any(row['status'] == 'uncollected' for row in compared['comparisons']):
        from .observations import apply_collection_coverage

        apply_collection_coverage(compared, target)
    return compared


def _active_reviews(country, comparisons):
    from .reviews import Review, environment

    dates = {data['comparison_date'] for data in comparisons}
    return set(Review.objects.filter(environment=environment(), active=True,
                                    source_date__in=dates, context__country=country)
               .values_list('fingerprint', flat=True))


def _summary(data, active_reviews):
    from .reviews import context_for, fingerprint

    rows = []
    for row in data['comparisons']:
        item = {'column': row['column'], 'status': row['status']}
        if (row['status'] in ('abnormal', 'review')
                and fingerprint(context_for(data, row)) in active_reviews):
            item['review'] = {'active': True}
        rows.append(item)
    return {'product': data['product'], 'retailer': data['retailer'],
            'comparison_date': data['comparison_date'], 'total': data['daily'][-1]['total'],
            'column_count': len(data['columns']), 'comparisons': rows}


def country_overview(country, selections, *, include_reviews, now=None):
    now = now or timezone.now()
    prepared = _prepared_counts(selections)
    futures = {selection: _POOL.submit(live_counts, *selection)
               for selection in selections if selection not in prepared}
    scoped = {}
    for selection in selections:
        scope, day = selection
        try:
            counts = prepared[selection] if selection in prepared else futures[selection].result()
            scoped[selection] = _compare(counts, day, now)
        except Exception:
            scoped[selection] = None
            logger.warning('Column statistics unavailable for %s on %s', scope, day, exc_info=True)

    comparisons = [data for data in scoped.values() if data is not None]
    active, review_error = set(), False
    if include_reviews and any(row['status'] in ('abnormal', 'review')
                               for data in comparisons for row in data['comparisons']):
        try:
            active = _active_reviews(country, comparisons)
        except Exception:
            review_error = True
            logger.warning('Column statistics overview review status unavailable', exc_info=True)
    return {'rows': [_summary(scoped[selection], active) if scoped[selection] is not None
                     else {'product': scope[1], 'retailer': scope[2], 'comparison_date': str(day), 'error': True}
                     for selection in selections for scope, day in [selection]],
            'updated_at': min((data['updated_at'] for data in comparisons), default=None),
            'review_error': review_error}
