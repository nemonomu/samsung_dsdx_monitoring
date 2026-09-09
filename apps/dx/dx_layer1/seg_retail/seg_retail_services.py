"""SEG Layer 1 collection counts and integer historical MAIN averages."""

from datetime import date, datetime, timedelta, timezone

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seg_retail import (
    SEG_CHECK_TYPE, SEG_HISTORY_DAYS, SEG_SOURCE_CONFIG,
    get_seg_average, get_seg_collection_phase,
)
from . import seg_retail_repositories as repo


_KST = timezone(timedelta(hours=9))
_PRIORITY = {'OK': 0, 'PENDING': 1, 'COLLECTING': 2, 'CRITICAL': 3}


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
    phase = (
        'complete' if selected < current_time.date()
        else 'pending' if selected > current_time.date()
        else get_seg_collection_phase(current_time.time().replace(tzinfo=None))
    )
    categories, failed_items = [], []
    for product_line, source in SEG_SOURCE_CONFIG.items():
        mapping = resolve_monitoring_date(selected, 'SEG', product_line)
        counts = {
            row['retailer'].strip().lower(): row
            for row in repo.get_latest_main_batch_counts(
                cursor, product_line, mapping['source_date'],
            )
        }
        history = repo.get_previous_main_counts(
            cursor, product_line, mapping['source_date'], SEG_HISTORY_DAYS,
        )
        retailers = []
        for name in source['retailers']:
            row = counts.get(name.lower(), {})
            previous = [r for r in history if r['retailer'] == name.lower()]
            expected = get_seg_average([r['main_count'] for r in previous])
            actual = int(row.get('main_count') or 0)
            # Until a deviation threshold is agreed, only completed zero
            # collection is critical; historical differences remain visible.
            status = (
                'PENDING' if phase == 'pending'
                else 'COLLECTING' if phase == 'collecting'
                else 'OK' if actual > 0 else 'CRITICAL'
            )
            retailers.append({
                'retailer': name, 'batch_id': row.get('batch_id') or '',
                'actual': actual, 'count': actual, 'main_count': actual,
                'raw_count': int(row.get('actual_count') or 0),
                'bsr_count': int(row.get('bsr_count') or 0),
                'redirect_count': int(row.get('redirect_count') or 0),
                'expected': expected,
                'difference': actual - expected if expected is not None else None,
                'history_day_count': len(previous),
                'history': previous,
                'rate': actual * 100 // expected if expected else None,
                'status': status,
            })
            if status == 'CRITICAL':
                failed_items.append({
                    'source': f"SEG {source['category']} ({name})",
                    'error_type': '수집 건수 없음', 'expected': expected,
                    'actual': actual, 'timestamp': mapping['source_date'],
                })
        categories.append({
            'name': source['category'], 'category': source['category'],
            'product_line': product_line, 'table_name': source['table_name'],
            'retailers': retailers, **_totals(retailers), **mapping,
        })
    return {
        'check': {
            'name': 'SEG Retail', 'check_type': SEG_CHECK_TYPE,
            'description': 'SEG 독일 TV/REF/LDY 일일 수집 현황',
            'phase': phase, 'collection_window': 'KST 07:00~12:00',
            'categories': categories, **_totals(categories),
            'inspection_date': str(selected), 'source_date': str(selected),
            'offset_days': 0, 'source_keys': list(SEG_SOURCE_CONFIG),
            'status_basis': 'collection_presence',
        },
        'failed_items': failed_items,
    }
