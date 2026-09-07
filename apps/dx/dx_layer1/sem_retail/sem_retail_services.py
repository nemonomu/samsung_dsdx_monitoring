"""Layer 1 statistics for SEM Mexico Liverpool TV/REF/LDY."""

from datetime import date, datetime, timedelta, timezone

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.sem_retail import (
    SEM_CHECK_TYPE,
    SEM_COUNTRY,
    SEM_CRITICAL_DEVIATION,
    SEM_HISTORY_DAYS,
    SEM_RETAILER,
    SEM_SOURCE_CONFIG,
    get_sem_collection_phase,
    get_sem_count_status,
)

from . import sem_retail_repositories as repo


_STATUS_PRIORITY = {'OK': 0, 'PENDING': 1, 'COLLECTING': 2, 'CRITICAL': 3}
_KST = timezone(timedelta(hours=9))


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _phase(target_date, now):
    selected = _as_date(target_date)
    if selected < now.date():
        return 'complete'
    if selected > now.date():
        return 'pending'
    return get_sem_collection_phase(now.time().replace(tzinfo=None))


def _worst(statuses):
    return max(statuses, key=lambda value: _STATUS_PRIORITY[value])


def _category(cursor, product_line, source, target_date, phase):
    mapping = resolve_monitoring_date(
        _as_date(target_date), SEM_COUNTRY, source['source_key']
    )
    current = repo.get_latest_batch_counts(
        cursor, product_line, mapping['source_date']
    ) or {
        'retailer': SEM_RETAILER,
        'batch_id': None,
        'actual_count': 0,
        'main_count': 0,
        'bsr_count': 0,
    }
    history_rows = repo.get_previous_main_counts(
        cursor, product_line, mapping['source_date'], SEM_HISTORY_DAYS
    )
    history = [row['main_count'] for row in history_rows]
    if phase == 'pending':
        status, baseline = 'PENDING', None
    elif phase == 'collecting':
        status, baseline = 'COLLECTING', None
    else:
        state, baseline = get_sem_count_status(current['main_count'], history)
        status = 'OK' if state == 'ok' else 'CRITICAL'
    expected = round(baseline, 1) if baseline is not None else None
    main_count = current['main_count']
    retailer = {
        **current,
        'expected': expected,
        'actual': main_count,
        'count': main_count,
        'raw_count': current['actual_count'],
        'rate': (
            round(main_count / baseline * 100, 1)
            if baseline and baseline > 0 else None
        ),
        'status': status,
        'status_basis': 'previous_main_average',
        'history_day_count': len(history),
        'allowed_deviation': SEM_CRITICAL_DEVIATION,
    }
    return {
        'name': source['category'],
        'category': source['category'],
        'product_line': product_line,
        'table_name': source['table_name'],
        'expected': expected,
        'actual': main_count,
        'total': main_count,
        'rate': retailer['rate'],
        'status': status,
        'retailers': [retailer],
        **mapping,
    }


def get_layer1_stats(cursor, target_date, now=None):
    current_time = now or datetime.now(_KST)
    phase = _phase(target_date, current_time)
    categories = [
        _category(cursor, key, source, target_date, phase)
        for key, source in SEM_SOURCE_CONFIG.items()
    ]
    failed = []
    if phase == 'complete':
        for category in categories:
            retailer = category['retailers'][0]
            if retailer['status'] != 'CRITICAL':
                continue
            failed.append({
                'source': f"SEM {category['category']} ({SEM_RETAILER})",
                'error_type': '최근 MAIN 평균 대비 수집 건수 차이',
                'expected': retailer['expected'],
                'actual': retailer['actual'],
                'timestamp': category['source_date'],
            })
    expected_values = [
        category['expected'] for category in categories
        if category['expected'] is not None
    ]
    expected_total = sum(expected_values) if expected_values else None
    actual_total = sum(category['actual'] for category in categories)
    return {
        'check': {
            'name': 'SEM Retail',
            'description': 'SEM Mexico Liverpool TV/REF/LDY 일일 수집 현황',
            'check_type': SEM_CHECK_TYPE,
            'status': _worst([category['status'] for category in categories]),
            'phase': phase,
            'collection_window': 'KST 10:00 완료 기준',
            'expected': expected_total,
            'actual': actual_total,
            'total': actual_total,
            'rate': (
                round(actual_total / expected_total * 100, 1)
                if expected_total else None
            ),
            'categories': categories,
            'inspection_date': categories[0]['inspection_date'],
            'source_date': categories[0]['source_date'],
            'offset_days': categories[0]['offset_days'],
            'source_keys': [category['source_key'] for category in categories],
        },
        'failed_items': failed,
    }
