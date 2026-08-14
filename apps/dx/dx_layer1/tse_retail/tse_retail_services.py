"""Layer 1 statistics for TSE TV, REF and LDY daily collection."""

from datetime import date, datetime

from apps.common.retail_columns import get_tse_retailer_columns
from apps.common.tse_retail import (
    TSE_EXPECTED_COUNT,
    TSE_LOTUSS_CRITICAL_DEVIATION,
    TSE_LOTUSS_HISTORY_DAYS,
    TSE_LOTUSS_MIN_HISTORY_DAYS,
    TSE_LOTUSS_RETAILER,
    TSE_SOURCE_CONFIG,
    display_tse_retailer,
    get_tse_collection_phase,
    get_tse_count_status,
)

from . import tse_retail_repositories as repo


_STATUS_BY_COUNT = {
    'ok': 'OK',
    'warning': 'WARNING',
    'critical': 'CRITICAL',
}
_STATUS_PRIORITY = {
    'OK': 0,
    'PENDING': 1,
    'COLLECTING': 2,
    'WARNING': 3,
    'CRITICAL': 4,
}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _collection_phase(target_date, now):
    selected_date = _as_date(target_date)
    if selected_date < now.date():
        return 'complete'
    if selected_date > now.date():
        return 'pending'
    return get_tse_collection_phase(now.time().replace(tzinfo=None))


def _status_for_count(actual_count, phase):
    if phase == 'pending':
        return 'PENDING'
    if phase == 'collecting':
        return 'COLLECTING'
    return _STATUS_BY_COUNT[get_tse_count_status(actual_count)]


def _status_for_lotuss_main(main_count, phase, history_counts):
    """Classify Lotuss from its prior MAIN history, never from BSR.

    The baseline is the arithmetic mean of up to seven latest valid days
    before the target date.  Three days are required to make a decision.  An
    absolute difference of exactly 20 rows is critical (not only a decrease).
    """
    baseline = (
        sum(history_counts) / len(history_counts)
        if len(history_counts) >= TSE_LOTUSS_MIN_HISTORY_DAYS
        else None
    )
    if phase == 'pending':
        return 'PENDING', baseline
    if phase == 'collecting':
        return 'COLLECTING', baseline
    if baseline is None:
        return 'PENDING', None

    deviation = abs(int(main_count or 0) - baseline)
    status = 'CRITICAL' if deviation >= TSE_LOTUSS_CRITICAL_DEVIATION else 'OK'
    return status, baseline


def _worst_status(statuses, default='PENDING'):
    return max(statuses, key=lambda item: _STATUS_PRIORITY[item]) if statuses else default


def _configured_retailers(product_line):
    """Return active configured retailers keyed case-insensitively."""
    retailers = {}
    for display_name, config in get_tse_retailer_columns(product_line).items():
        raw_name = config.get('retailer') or display_name
        key = str(raw_name).strip().lower()
        if key:
            retailers[key] = display_tse_retailer(display_name or raw_name)
    return retailers


def _build_category(cursor, product_line, source, target_date, phase):
    rows = repo.get_latest_batch_counts(cursor, product_line, target_date)
    configured = _configured_retailers(product_line)
    actual_by_retailer = {}

    for row in rows:
        raw_retailer = str(row.get('retailer') or '').strip()
        if not raw_retailer:
            continue
        key = raw_retailer.lower()
        actual_by_retailer[key] = {
            'retailer': display_tse_retailer(raw_retailer),
            'batch_id': row.get('batch_id'),
            'actual_count': int(row.get('actual_count') or 0),
            'main_count': int(row.get('main_count') or 0),
            'bsr_count': int(row.get('bsr_count') or 0),
        }

    retailer_keys = sorted(
        set(configured) | set(actual_by_retailer),
        key=lambda value: (configured.get(value) or actual_by_retailer[value]['retailer']).lower(),
    )
    retailers = []
    for retailer_key in retailer_keys:
        data = actual_by_retailer.get(retailer_key, {})
        raw_count = int(data.get('actual_count') or 0)
        main_count = int(data.get('main_count') or 0)
        is_lotuss = retailer_key == TSE_LOTUSS_RETAILER

        if is_lotuss:
            history_rows = repo.get_previous_main_counts(
                cursor,
                product_line,
                configured.get(retailer_key) or data.get('retailer') or 'Lotuss',
                target_date,
                limit=TSE_LOTUSS_HISTORY_DAYS,
            )
            history_counts = [
                int(item.get('main_count') or 0)
                for item in history_rows
                if int(item.get('main_count') or 0) > 0
            ][:TSE_LOTUSS_HISTORY_DAYS]
            status, baseline = _status_for_lotuss_main(
                main_count,
                phase,
                history_counts,
            )
            expected = round(baseline, 1) if baseline is not None else None
            actual = main_count
            rate = (
                round(actual / baseline * 100, 1)
                if baseline is not None and baseline > 0
                else None
            )
            deviation = (
                round(abs(actual - baseline), 1)
                if baseline is not None
                else None
            )
            baseline_ready = baseline is not None
            status_basis = 'previous_main_average'
        else:
            history_counts = []
            expected = TSE_EXPECTED_COUNT
            actual = raw_count
            rate = round(actual / TSE_EXPECTED_COUNT * 100, 1)
            status = _status_for_count(actual, phase)
            deviation = None
            baseline_ready = True
            status_basis = 'fixed_count'

        retailers.append({
            'retailer': configured.get(retailer_key) or data['retailer'],
            'batch_id': data.get('batch_id'),
            'expected': expected,
            'actual': actual,
            'count': actual,
            'total': actual,
            'raw_count': raw_count,
            'main_count': main_count,
            'bsr_count': int(data.get('bsr_count') or 0),
            'rate': rate,
            'status': status,
            'status_basis': status_basis,
            'baseline_ready': baseline_ready,
            'history_day_count': len(history_counts),
            'history_days_required': (
                TSE_LOTUSS_MIN_HISTORY_DAYS if is_lotuss else None
            ),
            'allowed_deviation': (
                TSE_LOTUSS_CRITICAL_DEVIATION if is_lotuss else None
            ),
            'deviation': deviation,
        })

    actual_total = sum(item['actual'] for item in retailers)
    if retailers:
        expected_total = sum(
            item['expected'] for item in retailers
            if item['expected'] is not None
        )
    else:
        expected_total = TSE_EXPECTED_COUNT
    baseline_pending = any(
        item['status_basis'] == 'previous_main_average'
        and not item['baseline_ready']
        for item in retailers
    )
    if retailers:
        category_status = _worst_status([item['status'] for item in retailers])
    else:
        category_status = _status_for_count(0, phase)

    return {
        'name': source['category'],
        'category': source['category'],
        'product_line': product_line,
        'table_name': source['table_name'],
        'expected': expected_total,
        'actual': actual_total,
        'total': actual_total,
        'rate': (
            round(actual_total / expected_total * 100, 1)
            if expected_total else 0
        ),
        'status': category_status,
        'baseline_pending': baseline_pending,
        'retailers': retailers,
    }


def get_layer1_stats(cursor, target_date, now=None):
    """Return the independent TSE collection card for the Layer 1 dashboard."""
    current = now or datetime.now()
    phase = _collection_phase(target_date, current)
    categories = [
        _build_category(cursor, product_line, source, target_date, phase)
        for product_line, source in TSE_SOURCE_CONFIG.items()
    ]

    failed_items = []
    if phase == 'complete':
        for category in categories:
            if category['retailers']:
                candidates = category['retailers']
            else:
                candidates = [{
                    'retailer': '',
                    'expected': category['expected'],
                    'actual': 0,
                    'status': category['status'],
                }]
            for retailer in candidates:
                if retailer['status'] not in ('WARNING', 'CRITICAL'):
                    continue
                source_name = f"TSE {category['category']}"
                if retailer.get('retailer'):
                    source_name += f" ({retailer['retailer']})"
                failed_items.append({
                    'source': source_name,
                    'error_type': (
                        '최근 MAIN 평균 대비 수집 건수 차이'
                        if retailer.get('status_basis') == 'previous_main_average'
                        else '수집 건수 부족'
                    ),
                    'expected': retailer['expected'],
                    'actual': retailer['actual'],
                    'timestamp': str(target_date),
                })

    expected_total = sum(category['expected'] for category in categories)
    actual_total = sum(category['actual'] for category in categories)
    check = {
        'name': 'TSE Retail',
        'description': 'TSE TV/REF/LDY 일일 수집 현황',
        'check_type': 'tse_retail',
        'status': _worst_status([category['status'] for category in categories]),
        'phase': phase,
        'collection_window': 'RDP 09:00~09:30',
        'expected': expected_total,
        'actual': actual_total,
        'total': actual_total,
        'rate': round(actual_total / expected_total * 100, 1) if expected_total else 0,
        'baseline_pending': any(
            category.get('baseline_pending') for category in categories
        ),
        'categories': categories,
    }
    return {'check': check, 'failed_items': failed_items}
