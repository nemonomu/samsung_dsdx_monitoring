import re
from datetime import datetime, timedelta

from apps.common.db import dx_connection
from apps.common.retail_columns import get_retailer_columns, get_all_retailer_columns
from apps.common.response import log_error
from apps.dx.dx_layer1.common.context import SECTION_TITLES
from apps.common.dx_schedules import get_retail_time_slots, get_kst_time_info, get_schedule_kst_info
from . import retail_repositories as repo


OK_THRESHOLD = 200

ALLOWED_TABLES = {'tv_retail_com'}
ALLOWED_DATE_FIELDS = {'crawl_datetime::timestamp'}
ALLOWED_RANK_FIELDS = {'promotion_position', 'trend_rank'}


def _get_daily_retailers(all_slots):
    """1일 1회 수집 리테일러 판별"""
    retailer_slot_count = {}
    for slot in all_slots:
        for r in slot.get('retailers', []):
            name = r['name'].lower()
            retailer_slot_count[name] = retailer_slot_count.get(name, 0) + 1
    return {name for name, count in retailer_slot_count.items() if count == 1}


def check_retailer_data(rows, category='TV', slot_retailers=None):
    if slot_retailers:
        retailer_names = [r['name'].lower() for r in slot_retailers]
    else:
        retailer_names = ['amazon', 'bestbuy', 'walmart']

    retailer_counts = {r: {'count': 0, 'main': 0, 'bsr': 0, 'extra': 0} for r in retailer_names}

    for row in rows:
        retailer_name = row[0].lower() if row[0] else ''
        count = row[1]
        if retailer_name in retailer_counts:
            retailer_counts[retailer_name] = {
                'count': count,
                'main': row[2] if len(row) > 2 else 0,
                'bsr': row[3] if len(row) > 3 else 0,
                'extra': row[4] if len(row) > 4 else 0
            }

    expected_map = {}
    if slot_retailers:
        for r in slot_retailers:
            expected_map[r['name'].lower()] = r.get('expected_count', 0) or 0

    retailer_details = []
    total_count = 0
    statuses = []

    for retailer in retailer_names:
        data = retailer_counts[retailer]
        count = data['count']
        total_count += count
        retailer_expected = expected_map.get(retailer, 300)

        if count >= OK_THRESHOLD:
            status = 'OK'
        else:
            status = 'CRITICAL'

        statuses.append(status)

        if category == 'TV':
            if retailer == 'bestbuy':
                items = [
                    {'name': 'Main Rank', 'count': data['main']},
                    {'name': 'BSR Rank', 'count': data['bsr']},
                    {'name': 'Promotion Position', 'count': data['extra']}
                ]
            else:
                items = [
                    {'name': 'Main Rank', 'count': data['main']},
                    {'name': 'BSR Rank', 'count': data['bsr']}
                ]
        else:
            if retailer == 'bestbuy':
                items = [
                    {'name': 'Main Rank', 'count': data['main']},
                    {'name': 'BSR Rank', 'count': data['bsr']},
                    {'name': 'Trend Rank', 'count': data['extra']}
                ]
            else:
                items = [
                    {'name': 'Main Rank', 'count': data['main']},
                    {'name': 'BSR Rank', 'count': data['bsr']}
                ]

        retailer_details.append({
            'retailer': retailer.capitalize(),
            'count': count,
            'expected': retailer_expected,
            'ok_threshold': OK_THRESHOLD,
            'status': status,
            'items': items
        })

    if 'CRITICAL' in statuses:
        overall_status = 'CRITICAL'
    else:
        overall_status = 'OK'

    return retailer_details, total_count, overall_status


def get_layer1_stats(cursor, target_date, now):
    next_day = target_date + timedelta(days=1)
    failed_items = []

    schedule_slots = get_retail_time_slots('TV', target_date)
    slot_retailer_map = {}
    for slot in schedule_slots:
        for r in slot.get('retailers', []):
            name = r.get('name')
            if not name:
                continue
            slot_retailer_map[name.lower()] = {
                'name': name,
                'expected_count': r.get('expected_count', 0) or 0,
            }

    slot_retailers = list(slot_retailer_map.values())
    if not slot_retailers:
        slot_retailers = [
            {'name': 'Amazon', 'expected_count': 300},
            {'name': 'Bestbuy', 'expected_count': 300},
            {'name': 'Walmart', 'expected_count': 300},
        ]

    slot_expected = sum(r.get('expected_count', 0) for r in slot_retailers)
    slot_start = f'{target_date} 00:00:00'
    slot_end = f'{next_day} 00:00:00'
    rows = repo.query_retail_counts(cursor, 'tv_retail_com', 'crawl_datetime::timestamp', 'promotion_position', slot_start, slot_end, set())

    tv_time_slots = []
    tv_total_count = 0
    tv_slot_statuses = []

    schedule_statuses = [s.get('time_status') for s in schedule_slots if s.get('time_status')]
    if 'COLLECTING' in schedule_statuses:
        daily_time_status = 'COLLECTING'
    elif schedule_statuses and all(s == 'PENDING' for s in schedule_statuses):
        daily_time_status = 'PENDING'
    else:
        daily_time_status = None

    if daily_time_status:
        retailer_details, total, _ = check_retailer_data(rows, 'TV', slot_retailers)
        tv_total_count += total
        tv_time_slots.append({
            'name': '일일',
            'us_time': f'{target_date}',
            'kr_time': '',
            'is_dst': False,
            'total': total,
            'expected': slot_expected,
            'status': daily_time_status,
            'retailers': retailer_details
        })
    else:
        retailer_details, total, slot_status = check_retailer_data(rows, 'TV', slot_retailers)
        tv_total_count += total
        tv_slot_statuses.append(slot_status)
        tv_time_slots.append({
            'name': '일일',
            'us_time': f'{target_date}',
            'kr_time': '',
            'is_dst': False,
            'total': total,
            'expected': slot_expected,
            'status': slot_status,
            'retailers': retailer_details
        })

        for r in retailer_details:
            if r['status'] != 'OK':
                error_type = '수집 없음' if r['count'] == 0 else ('주의' if r['status'] == 'WARNING' else '수집량 부족')
                failed_items.append({
                    'source': f"SEA Retail - {r['retailer']}",
                    'error_type': error_type,
                    'expected': f">= {OK_THRESHOLD}",
                    'actual': r['count'],
                    'timestamp': "TV 일일"
                })

    tv_has_collecting = any(s['status'] == 'COLLECTING' for s in tv_time_slots)
    tv_all_pending = all(s['status'] == 'PENDING' for s in tv_time_slots)

    if 'CRITICAL' in tv_slot_statuses:
        tv_overall_status = 'CRITICAL'
    elif 'WARNING' in tv_slot_statuses:
        tv_overall_status = 'WARNING'
    elif not tv_slot_statuses and tv_has_collecting:
        tv_overall_status = 'COLLECTING'
    elif not tv_slot_statuses and tv_all_pending:
        tv_overall_status = 'PENDING'
    elif not tv_slot_statuses:
        tv_overall_status = 'PENDING'
    else:
        tv_overall_status = 'OK'

    tv_active_slots = len([s for s in tv_time_slots if s['status'] not in ['PENDING', 'COLLECTING']])
    tv_ok_slots = len([s for s in tv_time_slots if s['status'] == 'OK'])

    tv_retail_data = {
        'name': 'TV',
        'total': tv_total_count,
        'expected': sum(s['expected'] for s in tv_time_slots if s['status'] not in ['PENDING', 'COLLECTING']),
        'status': tv_overall_status,
        'time_slots': tv_time_slots
    }

    total_retail_count = tv_total_count
    total_retail_expected = tv_retail_data['expected']
    total_retail_status = tv_overall_status
    retail_ok_count = 1 if tv_overall_status == 'OK' else 0

    am_kst = get_kst_time_info(0, target_date)
    pm_kst = get_kst_time_info(12, target_date)
    am_kst_date = next_day if am_kst['next_day'] else target_date
    pm_kst_date = next_day if pm_kst['next_day'] else target_date

    retail_time_info = {
        'daily': {
            'us': str(target_date),
            'kst': str(target_date),
            'is_dst': am_kst['is_dst']
        },
        # Backward-compatible display metadata only. Old cached JS may still read am/pm.
        'am': {
            'us': f'{target_date} 00:00',
            'kst': f'{am_kst_date} {am_kst["hour"]:02d}:00',
            'is_dst': am_kst['is_dst']
        },
        'pm': {
            'us': f'{target_date} 12:00',
            'kst': f'{pm_kst_date} {pm_kst["hour"]:02d}:00',
            'is_dst': pm_kst['is_dst']
        },
        'is_dst': am_kst['is_dst']
    }

    check = {
        'name': SECTION_TITLES['retail'],
        'description': f'{retail_ok_count}/1 카테고리 정상',
        'actual': total_retail_count,
        'expected': total_retail_expected,
        'expected_min': total_retail_expected,
        'status': total_retail_status,
        'check_type': 'retail',
        'time_info': retail_time_info,
        'categories': [tv_retail_data]
    }

    return {'check': check, 'failed_items': failed_items}


def get_retail_detail(target_date, product_line):
    if product_line != 'tv':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'results': [],
            'total_retailers': 0,
            'total_products': 0
        }

    with dx_connection() as (conn, cursor):
        rows = repo.get_tv_retail_detail_list(cursor, target_date.strftime('%Y-%m-%d'))

    results = []
    for row in rows:
        results.append({
            'retailer': row[0],
            'total': row[1],
            'main_count': row[2],
            'bsr_count': row[3],
            'price_count': row[4],
            'completeness': round((row[4] / row[1] * 100), 1) if row[1] > 0 else 0
        })

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'results': results,
        'total_retailers': len(results),
        'total_products': sum(r['total'] for r in results)
    }


def get_retail_summary(target_date, product_line):
    if product_line != 'tv':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'extra_rank_name': '',
            'summary': [],
            'null_columns': [],
            'totals': {
                'grand_total': 0,
                'am_total': 0,
                'pm_total': 0
            },
            'check_stats': {
                'total_checks': 0,
                'null_count': 0
            },
            'column_checks': []
        }


    next_day = target_date + timedelta(days=1)
    time_slots = [
        {'name': '일일', 'start': f'{target_date} 00:00:00', 'end': f'{next_day} 00:00:00'}
    ]

    table_name = 'tv_retail_com'
    date_field = 'crawl_datetime::timestamp'
    extra_rank_field = 'promotion_position'
    extra_rank_name = 'Promotion'

    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"허용되지 않은 테이블: {table_name}")
    if date_field not in ALLOWED_DATE_FIELDS:
        raise ValueError(f"허용되지 않은 날짜 필드: {date_field}")
    if extra_rank_field not in ALLOWED_RANK_FIELDS:
        raise ValueError(f"허용되지 않은 랭크 필드: {extra_rank_field}")

    all_slots = get_retail_time_slots(product_line, target_date)
    retailer_set = set()
    for s in all_slots:
        for r in s.get('retailers', []):
            retailer_set.add(r['name'])
    retailers = sorted(retailer_set) if retailer_set else ['Amazon', 'Bestbuy', 'Walmart']
    daily_retailers = set()

    summary_data = []
    null_columns_data = []
    total_check_count = 0
    total_null_count = 0
    column_checks_data = []

    with dx_connection() as (conn, cursor):
        for retailer in retailers:
            retailer_rows = []
            retailer_null_cols = []
            retailer_total = 0
            check_columns = get_retailer_columns(product_line, retailer)

            for col in check_columns:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                    raise ValueError(f"허용되지 않은 컬럼명: {col}")

            retailer_check_slots = []
            is_daily = retailer.lower() in daily_retailers

            for slot in time_slots:
                if is_daily and slot['name'] == '오후':
                    retailer_rows.append({
                        'time_slot': slot['name'],
                        'main': 0, 'bsr': 0, 'extra': 0,
                        'extra_name': extra_rank_name, 'total': 0
                    })
                    continue

                row = repo.query_retail_counts_by_retailer(cursor, table_name, date_field, extra_rank_field, slot['start'], slot['end'], retailer)

                main_count = row[0] or 0
                bsr_count = row[1] or 0
                extra_count = row[2] or 0
                total = row[3] or 0

                retailer_rows.append({
                    'time_slot': slot['name'],
                    'main': main_count,
                    'bsr': bsr_count,
                    'extra': extra_count,
                    'extra_name': extra_rank_name,
                    'total': total
                })
                retailer_total += total

                if total > 0 and check_columns:
                    total_check_count += len(check_columns)
                    count_row = repo.get_retail_summary_null_counts(cursor, table_name, date_field, check_columns, slot['start'], slot['end'], retailer, is_daily)
                    
                    if count_row:
                        col_counts = {}
                        null_cols = []
                        for col, cnt in zip(check_columns, count_row):
                            col_counts[col] = cnt
                            if cnt == 0:
                                null_cols.append(col)

                        total_null_count += len(null_cols)
                        retailer_check_slots.append({
                            'time_slot': slot['name'],
                            'total': total,
                            'counts': col_counts
                        })

                        if null_cols:
                            retailer_null_cols.append({
                                'time_slot': slot['name'],
                                'null_columns': null_cols
                            })

            summary_data.append({
                'retailer': retailer,
                'rows': retailer_rows,
                'total': retailer_total
            })

            if retailer_null_cols:
                null_columns_data.append({
                    'retailer': retailer,
                    'time_slots': retailer_null_cols
                })

            if retailer_check_slots:
                column_checks_data.append({
                    'retailer': retailer,
                    'check_columns': check_columns,
                    'time_slots': retailer_check_slots
                })

    grand_total = sum(r['total'] for r in summary_data)
    am_total = sum(r['rows'][0]['total'] for r in summary_data if r['rows'])
    pm_total = 0

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'extra_rank_name': extra_rank_name,
        'summary': summary_data,
        'null_columns': null_columns_data,
        'totals': {
            'grand_total': grand_total,
            'am_total': am_total,
            'pm_total': pm_total
        },
        'check_stats': {
            'total_checks': total_check_count,
            'null_count': total_null_count
        },
        'column_checks': column_checks_data
    }


def get_retailer_raw_data(category, retailer, period, target_date):
    if category != 'TV':
        return {
            'category': category,
            'retailer': retailer,
            'period': period,
            'date': str(target_date),
            'columns': [],
            'data': [],
            'error': 'HHP Retail is excluded from monitoring.'
        }

    next_day = target_date + timedelta(days=1)
    period = '일일'
    start_time = f'{target_date} 00:00:00'
    end_time = f'{next_day} 00:00:00'

    results = {
        'category': category,
        'retailer': retailer,
        'period': period,
        'date': str(target_date),
        'columns': [],
        'data': []
    }

    try:
        product_line = 'tv'
        db_columns = get_retailer_columns(product_line, retailer)

        columns = ['id'] + [col for col in db_columns if col != 'id']

        date_column = 'crawl_datetime'
        table_name = 'tv_retail_com'

        if table_name not in ALLOWED_TABLES:
            raise ValueError(f"허용되지 않은 테이블: {table_name}")

        retailer_columns = get_all_retailer_columns(product_line)
        all_valid_columns = set()
        for cols in retailer_columns.values():
            all_valid_columns.update(cols)
        all_valid_columns.add('id')
        invalid_cols = [c for c in columns if c not in all_valid_columns]
        if invalid_cols:
            raise ValueError(f"허용되지 않은 컬럼: {invalid_cols}")

        with dx_connection() as (conn, cursor):
            rows = repo.get_retailer_raw_data_list(cursor, table_name, columns, retailer, date_column, start_time, end_time)

        results['columns'] = columns
        results['total_count'] = len(rows)
        results['data'] = rows

    except Exception as e:
        results['error'] = log_error(e)

    return results

def get_retailer_columns_info():
    tv_columns = get_all_retailer_columns('tv')

    all_tv_columns = sorted(set(col for cols in tv_columns.values() for col in cols))

    return {
        'tv': {
            'columns': tv_columns,
            'all_columns': all_tv_columns
        }
    }
