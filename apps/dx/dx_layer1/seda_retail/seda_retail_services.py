"""SEDA Layer 1 collection counts for the inspection day's D-1 data."""

from datetime import date, datetime, timedelta, timezone

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seda_retail import (
    SEDA_CHECK_TYPE,
    SEDA_COUNTRY,
    SEDA_HISTORY_DAYS,
    SEDA_SOURCE_CONFIG,
    display_seda_retailer,
    get_seda_average,
)
from . import seda_retail_repositories as repo


_KST = timezone(timedelta(hours=9))
_PRIORITY = {'OK': 0, 'PENDING': 1, 'CRITICAL': 2}


def _totals(rows):
    expected = [row['expected'] for row in rows]
    return {
        'expected': sum(expected) if all(v is not None for v in expected) else None,
        'actual': sum(row['actual'] for row in rows),
        'raw_count': sum(row['raw_count'] for row in rows),
        'main_count': sum(row['main_count'] for row in rows),
        'bsr_count': sum(row['bsr_count'] for row in rows),
        'status': max((row['status'] for row in rows), key=_PRIORITY.get),
    }


def get_layer1_stats(cursor, target_date, now=None):
    selected = date.fromisoformat(str(target_date))
    current_time = now or datetime.now(_KST)
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(_KST)
    phase = 'pending' if selected > current_time.date() else 'complete'

    categories, failed_items = [], []
    for product_line, source in SEDA_SOURCE_CONFIG.items():
        mapping = resolve_monitoring_date(
            selected, SEDA_COUNTRY, source['source_key']
        )
        counts = {
            display_seda_retailer(row['retailer']).casefold(): row
            for row in repo.get_latest_main_batch_counts(
                cursor, product_line, mapping['source_date']
            )
        }
        history = repo.get_previous_main_counts(
            cursor, product_line, mapping['source_date'], SEDA_HISTORY_DAYS
        )
        retailers = []
        for name in source['retailers']:
            row = counts.get(name.casefold(), {})
            previous = [
                history_row for history_row in history
                if display_seda_retailer(
                    history_row['retailer']
                ).casefold() == name.casefold()
            ]
            expected = get_seda_average(
                [history_row['main_count'] for history_row in previous]
            )
            actual = int(row.get('main_count') or 0)
            raw_count = int(row.get('actual_count') or 0)
            status = (
                'PENDING' if phase == 'pending'
                else 'OK' if raw_count > 0
                else 'CRITICAL'
            )
            retailers.append({
                'retailer': name,
                'batch_id': row.get('batch_id') or '',
                'actual': actual,
                'count': actual,
                'main_count': actual,
                'raw_count': raw_count,
                'bsr_count': int(row.get('bsr_count') or 0),
                'expected': expected,
                'difference': actual - expected if expected is not None else None,
                'history_day_count': len(previous),
                'history': previous,
                'rate': actual * 100 // expected if expected else None,
                'status': status,
                'status_basis': 'collection_presence',
            })
            if status == 'CRITICAL':
                failed_items.append({
                    'source': f"SEDA {source['category']} ({name})",
                    'error_type': '수집 건수 없음',
                    'expected': expected,
                    'actual': 0,
                    'timestamp': mapping['source_date'],
                })
        categories.append({
            'name': source['category'],
            'category': source['category'],
            'product_line': product_line,
            'table_name': source['table_name'],
            'retailers': retailers,
            **_totals(retailers),
            **mapping,
        })

    return {
        'check': {
            'name': 'SEDA Retail',
            'check_type': SEDA_CHECK_TYPE,
            'description': 'SEDA 브라질 TV/REF/LDY D-1 일일 수집 현황',
            'phase': phase,
            'collection_window': '검수일 D-1 데이터',
            'categories': categories,
            **_totals(categories),
            'inspection_date': str(selected),
            'source_date': categories[0]['source_date'],
            'offset_days': categories[0]['offset_days'],
            'source_keys': list(SEDA_SOURCE_CONFIG),
            'status_basis': 'collection_presence',
        },
        'failed_items': failed_items,
    }
