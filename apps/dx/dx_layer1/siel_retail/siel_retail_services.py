"""Layer 1 statistics for SIEL TV, REF and LDY daily collection."""

from datetime import date, datetime, timedelta, timezone

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.siel_retail import (
    SIEL_CHECK_TYPE,
    SIEL_COUNTRY,
    SIEL_EXPECTED_COUNT,
    SIEL_OK_THRESHOLD,
    SIEL_SOURCE_CONFIG,
    display_siel_retailer,
    get_siel_collection_phase,
    get_siel_count_status,
)

from . import siel_retail_repositories as repo


_STATUS_BY_COUNT = {
    'ok': 'OK',
    'critical': 'CRITICAL',
}
_STATUS_PRIORITY = {
    'OK': 0,
    'PENDING': 1,
    'COLLECTING': 2,
    'CRITICAL': 3,
}
_SIEL_KST = timezone(timedelta(hours=9))


def _get_kst_now():
    return datetime.now(_SIEL_KST)


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
    return get_siel_collection_phase(now.time().replace(tzinfo=None))


def _status_for_count(actual_count, phase):
    if phase == 'pending':
        return 'PENDING'
    if phase == 'collecting':
        return 'COLLECTING'
    return _STATUS_BY_COUNT[get_siel_count_status(actual_count)]


def _worst_status(statuses, default='PENDING'):
    return (
        max(statuses, key=lambda item: _STATUS_PRIORITY[item])
        if statuses else default
    )


def _date_contract(target_date, source):
    return resolve_monitoring_date(
        _as_date(target_date), SIEL_COUNTRY, source['source_key'],
    )


def _build_category(cursor, product_line, source, target_date, phase):
    contract = _date_contract(target_date, source)
    rows = repo.get_latest_main_batch_counts(
        cursor, product_line, contract['source_date'],
    )
    actual_by_retailer = {
        str(row.get('retailer') or '').strip().lower(): row
        for row in rows
        if str(row.get('retailer') or '').strip()
    }

    retailers = []
    for retailer_name in source['retailers']:
        data = actual_by_retailer.get(retailer_name.lower(), {})
        actual = int(data.get('actual_count') or 0)
        status = _status_for_count(actual, phase)
        retailers.append({
            'retailer': display_siel_retailer(retailer_name),
            'batch_id': (
                '' if data.get('batch_id') is None
                else str(data.get('batch_id'))
            ),
            'expected': SIEL_EXPECTED_COUNT,
            'ok_threshold': SIEL_OK_THRESHOLD,
            'actual': actual,
            'count': actual,
            'total': actual,
            'main_count': int(data.get('main_count') or 0),
            'bsr_count': int(data.get('bsr_count') or 0),
            'rate': round(actual / SIEL_EXPECTED_COUNT * 100, 1),
            'status': status,
        })

    expected_total = SIEL_EXPECTED_COUNT * len(retailers)
    actual_total = sum(item['actual'] for item in retailers)
    return {
        'name': source['category'],
        'category': source['category'],
        'product_line': product_line,
        'table_name': source['table_name'],
        'expected': expected_total,
        'actual': actual_total,
        'total': actual_total,
        'rate': round(actual_total / expected_total * 100, 1),
        'status': _worst_status([item['status'] for item in retailers]),
        'retailers': retailers,
        'inspection_date': contract['inspection_date'],
        'source_date': contract['source_date'],
        'offset_days': contract['offset_days'],
        'source_key': contract['source_key'],
    }


def get_layer1_stats(cursor, target_date, now=None):
    """Return the independent SIEL collection card for Layer 1."""
    current = now or _get_kst_now()
    phase = _collection_phase(target_date, current)
    categories = [
        _build_category(cursor, product_line, source, target_date, phase)
        for product_line, source in SIEL_SOURCE_CONFIG.items()
    ]

    failed_items = []
    if phase == 'complete':
        for category in categories:
            for retailer in category['retailers']:
                if retailer['status'] != 'CRITICAL':
                    continue
                failed_items.append({
                    'source': (
                        f"SIEL {category['category']} "
                        f"({retailer['retailer']})"
                    ),
                    'error_type': (
                        '수집 건수 없음'
                        if retailer['actual'] == 0 else '수집 건수 부족'
                    ),
                    'expected': f'>= {SIEL_OK_THRESHOLD}',
                    'actual': retailer['actual'],
                    'timestamp': category['source_date'],
                })

    expected_total = sum(category['expected'] for category in categories)
    actual_total = sum(category['actual'] for category in categories)
    statuses = [category['status'] for category in categories]
    check = {
        'name': 'SIEL Retail',
        'description': 'SIEL TV/REF/LDY 당일(D) 수집 현황',
        'check_type': SIEL_CHECK_TYPE,
        'status': _worst_status(statuses),
        'phase': phase,
        'collection_window': 'KST 09:00 완료 기준',
        'expected': expected_total,
        'actual': actual_total,
        'total': actual_total,
        'rate': round(actual_total / expected_total * 100, 1),
        'categories': categories,
        'inspection_date': categories[0]['inspection_date'],
        'source_date': categories[0]['source_date'],
        'offset_days': categories[0]['offset_days'],
        'source_keys': [category['source_key'] for category in categories],
    }
    return {'check': check, 'failed_items': failed_items}
