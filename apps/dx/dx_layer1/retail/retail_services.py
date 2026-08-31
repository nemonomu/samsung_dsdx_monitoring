import re
from datetime import date, datetime, timedelta

from apps.common.db import dx_connection
from apps.common.dx_schedules import get_retail_time_slots, get_kst_time_info
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.retail_columns import (
    get_retailer_columns,
    get_all_retailer_columns,
)
from apps.common.response import log_error
from apps.common.sea_retail import SEA_RETAIL_SOURCES, get_sea_retail_source
from apps.dx.dx_layer1.common.context import SECTION_TITLES

from . import retail_repositories as repo


OK_THRESHOLD = 200
DEFAULT_EXPECTED_COUNT = 300
LDY_LOWES_MAIN_MIN = 150
LDY_LOWES_BSR_MIN = 90

ALLOWED_TABLES = {
    source['table_name'] for source in SEA_RETAIL_SOURCES.values()
}
ALLOWED_DATE_FIELDS = {'crawl_datetime::timestamp', 'crawl_strdatetime'}
ALLOWED_RANK_FIELDS = {'promotion_position'}


def _inspection_value(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def _resolve_source(inspection_date, source):
    contract = resolve_monitoring_date(
        _inspection_value(inspection_date), 'SEA', source['source_key'],
    )
    return contract, date.fromisoformat(contract['source_date'])


def _contract_fields(contract):
    return {
        'inspection_date': contract['inspection_date'],
        'source_date': contract['source_date'],
        'offset_days': contract['offset_days'],
        'source_key': contract['source_key'],
    }


def _get_daily_retailers(all_slots):
    """Return retailers configured once per day (legacy compatibility)."""

    retailer_slot_count = {}
    for slot in all_slots:
        for retailer in slot.get('retailers', []):
            name = retailer['name'].lower()
            retailer_slot_count[name] = retailer_slot_count.get(name, 0) + 1
    return {
        name for name, count in retailer_slot_count.items() if count == 1
    }


def _matching_schedule_slots(source, source_date, now=None):
    configured = {
        retailer.lower() for retailer in source['retailers']
    }
    slots = get_retail_time_slots(source['category'], source_date, now=now)
    matching = []
    for slot in slots:
        retailers = [
            retailer for retailer in slot.get('retailers', [])
            if str(retailer.get('name') or '').strip().lower() in configured
        ]
        if not retailers:
            continue
        matching.append({**slot, 'retailers': retailers})
    return matching


def _slot_retailers(source, schedule_slots):
    retailer_map = {}
    for slot in schedule_slots:
        for retailer in slot.get('retailers', []):
            name = retailer.get('name')
            if not name:
                continue
            retailer_map[name.lower()] = {
                'name': name,
                'expected_count': (
                    retailer.get('expected_count', 0)
                    or DEFAULT_EXPECTED_COUNT
                ),
            }

    return [
        {
            'name': name,
            'expected_count': retailer_map.get(
                name.lower(),
                {'expected_count': DEFAULT_EXPECTED_COUNT},
            )['expected_count'],
        }
        for name in source['retailers']
    ]


def _daily_schedule_status(schedule_slots):
    statuses = [
        slot.get('time_status')
        for slot in schedule_slots
        if slot.get('time_status')
    ]
    if statuses:
        # 공통 정책: 수집 완료 전에는 시작 전/진행 중을 나누지 않고
        # 모두 화면의 "수집 중" 상태로 표시한다.
        return 'COLLECTING'
    return None


def _retailer_criteria(category, retailer):
    """Return the completed-collection rule for one SEA retailer."""

    if (
        str(category or '').strip().upper() == 'LDY'
        and str(retailer or '').strip().lower() == 'lowes'
    ):
        return {
            'main_min': LDY_LOWES_MAIN_MIN,
            'bsr_min': LDY_LOWES_BSR_MIN,
        }
    return {'total_min': OK_THRESHOLD}


def _meets_retailer_criteria(data, criteria):
    if data['count'] == 0:
        return False
    if 'main_min' in criteria or 'bsr_min' in criteria:
        return (
            data['main'] >= criteria.get('main_min', 0)
            and data['bsr'] >= criteria.get('bsr_min', 0)
        )
    return data['count'] >= criteria.get('total_min', OK_THRESHOLD)


def _criteria_expected(criteria):
    if 'main_min' in criteria or 'bsr_min' in criteria:
        return (
            f"MAIN >= {criteria.get('main_min', 0)} / "
            f"BSR >= {criteria.get('bsr_min', 0)}"
        )
    return f">= {criteria.get('total_min', OK_THRESHOLD)}"


def _criteria_actual(data, criteria):
    if 'main_min' in criteria or 'bsr_min' in criteria:
        return {'main': data['main'], 'bsr': data['bsr']}
    return {'total': data['count']}


def _criteria_actual_detail(actual):
    if 'main' in actual or 'bsr' in actual:
        return (
            f"MAIN {actual.get('main', 0)} / "
            f"BSR {actual.get('bsr', 0)}"
        )
    return str(actual.get('total', 0))


def check_retailer_data(rows, category='TV', slot_retailers=None):
    if slot_retailers:
        retailer_names = [
            retailer['name'].lower() for retailer in slot_retailers
        ]
        display_names = {
            retailer['name'].lower(): retailer['name']
            for retailer in slot_retailers
        }
    else:
        source = get_sea_retail_source(category)
        retailer_names = [name.lower() for name in source['retailers']]
        display_names = {
            name.lower(): name for name in source['retailers']
        }

    retailer_counts = {
        retailer: {
            'count': 0, 'main': 0, 'bsr': 0, 'extra': 0,
            'batch_id': None,
        }
        for retailer in retailer_names
    }

    for row in rows:
        retailer_name = row[0].lower() if row[0] else ''
        if retailer_name not in retailer_counts:
            continue
        retailer_counts[retailer_name] = {
            'count': int(row[1] or 0),
            'main': int(row[2] or 0) if len(row) > 2 else 0,
            'bsr': int(row[3] or 0) if len(row) > 3 else 0,
            'extra': int(row[4] or 0) if len(row) > 4 else 0,
            'batch_id': row[5] if len(row) > 5 else None,
        }

    expected_map = {}
    if slot_retailers:
        for retailer in slot_retailers:
            expected_map[retailer['name'].lower()] = (
                retailer.get('expected_count', 0)
                or DEFAULT_EXPECTED_COUNT
            )

    retailer_details = []
    total_count = 0
    statuses = []
    for retailer in retailer_names:
        data = retailer_counts[retailer]
        count = data['count']
        total_count += count
        expected = expected_map.get(retailer, DEFAULT_EXPECTED_COUNT)
        criteria = _retailer_criteria(category, retailer)
        status = (
            'OK' if _meets_retailer_criteria(data, criteria)
            else 'CRITICAL'
        )
        statuses.append(status)

        items = [
            {'name': 'Main Rank', 'count': data['main']},
            {'name': 'BSR Rank', 'count': data['bsr']},
        ]
        if category.upper() == 'TV' and retailer == 'bestbuy':
            items.append({
                'name': 'Promotion Position', 'count': data['extra'],
            })

        retailer_details.append({
            'retailer': display_names.get(retailer, retailer.capitalize()),
            'count': count,
            'expected': expected,
            'ok_threshold': criteria.get('total_min'),
            'criteria': criteria,
            'criteria_actual': _criteria_actual(data, criteria),
            'status': status,
            'items': items,
            'batch_id': (
                '' if data['batch_id'] is None else str(data['batch_id'])
            ),
        })

    overall_status = 'CRITICAL' if 'CRITICAL' in statuses else 'OK'
    return retailer_details, total_count, overall_status


def _source_rows(cursor, source, source_date, slot_start, slot_end,
                 slot_retailers):
    if source['product_key'] == 'tv':
        return repo.query_retail_counts(
            cursor,
            source['table_name'],
            'crawl_datetime::timestamp',
            source['extra_rank_field'],
            slot_start,
            slot_end,
            set(),
        )
    return repo.query_appliance_counts(
        cursor,
        source['table_name'],
        source['date_column'],
        source_date,
        [retailer['name'] for retailer in slot_retailers],
    )


def _build_category(cursor, source, inspection_date, now):
    contract, source_date = _resolve_source(inspection_date, source)
    next_day = source_date + timedelta(days=1)
    slot_start = f'{source_date} 00:00:00'
    slot_end = f'{next_day} 00:00:00'

    schedule_slots = _matching_schedule_slots(source, source_date, now)
    slot_retailers = _slot_retailers(source, schedule_slots)
    rows = _source_rows(
        cursor, source, source_date, slot_start, slot_end, slot_retailers,
    )
    retailer_details, total, count_status = check_retailer_data(
        rows, source['category'], slot_retailers,
    )

    schedule_status = _daily_schedule_status(schedule_slots)
    status = schedule_status or count_status
    if schedule_status:
        for retailer in retailer_details:
            retailer['status'] = schedule_status
    expected = sum(
        retailer.get('expected_count', 0) for retailer in slot_retailers
    )
    active_expected = 0 if status in ('PENDING', 'COLLECTING') else expected
    time_slot = {
        'name': '일일',
        'us_time': str(source_date),
        'kr_time': '',
        'is_dst': False,
        'total': total,
        'expected': expected,
        'status': status,
        'retailers': retailer_details,
        **_contract_fields(contract),
    }
    category = {
        'name': source['category'],
        'product_line': source['product_key'],
        'total': total,
        'expected': active_expected,
        'status': status,
        'time_slots': [time_slot],
        'has_extra_rank': source['extra_rank_field'] is not None,
        'extra_rank_name': source['extra_rank_name'],
        **_contract_fields(contract),
    }

    failed_items = []
    if schedule_status is None:
        for retailer in retailer_details:
            if retailer['status'] == 'OK':
                continue
            failed_items.append({
                'source': (
                    f"SEA {source['category']} Retail - "
                    f"{retailer['retailer']}"
                ),
                'error_type': (
                    '수집 없음' if retailer['count'] == 0
                    else '수집량 부족'
                ),
                'expected': _criteria_expected(retailer['criteria']),
                'actual': retailer['count'],
                'actual_detail': _criteria_actual_detail(
                    retailer['criteria_actual']
                ),
                'timestamp': f"{source['category']} 일일",
            })

    return category, failed_items, contract


def get_layer1_stats(cursor, target_date, now=None):
    categories = []
    failed_items = []
    contracts = []
    for product_key in ('tv', 'ref', 'ldy'):
        category, category_failures, contract = _build_category(
            cursor,
            SEA_RETAIL_SOURCES[product_key],
            target_date,
            now,
        )
        categories.append(category)
        failed_items.extend(category_failures)
        contracts.append(contract)

    statuses = [category['status'] for category in categories]
    if 'CRITICAL' in statuses:
        overall_status = 'CRITICAL'
    elif 'WARNING' in statuses:
        overall_status = 'WARNING'
    elif 'COLLECTING' in statuses:
        overall_status = 'COLLECTING'
    elif statuses and all(status == 'PENDING' for status in statuses):
        overall_status = 'PENDING'
    elif 'PENDING' in statuses:
        overall_status = 'PENDING'
    else:
        overall_status = 'OK'

    total_count = sum(category['total'] for category in categories)
    total_expected = sum(category['expected'] for category in categories)

    source_date = date.fromisoformat(contracts[0]['source_date'])
    next_day = source_date + timedelta(days=1)
    am_kst = get_kst_time_info(0, source_date)
    pm_kst = get_kst_time_info(12, source_date)
    am_kst_date = next_day if am_kst['next_day'] else source_date
    pm_kst_date = next_day if pm_kst['next_day'] else source_date
    retail_time_info = {
        'daily': {
            'us': str(source_date),
            'kst': str(source_date),
            'is_dst': am_kst['is_dst'],
        },
        'am': {
            'us': f'{source_date} 00:00',
            'kst': f'{am_kst_date} {am_kst["hour"]:02d}:00',
            'is_dst': am_kst['is_dst'],
        },
        'pm': {
            'us': f'{source_date} 12:00',
            'kst': f'{pm_kst_date} {pm_kst["hour"]:02d}:00',
            'is_dst': pm_kst['is_dst'],
        },
        'is_dst': am_kst['is_dst'],
    }

    check = {
        'name': SECTION_TITLES['retail'],
        'description': 'SEA TV/REF/LDY 일일 수집 현황',
        'actual': total_count,
        'expected': total_expected,
        'expected_min': total_expected,
        'status': overall_status,
        'check_type': 'retail',
        'time_info': retail_time_info,
        'categories': categories,
        'inspection_date': contracts[0]['inspection_date'],
        'source_date': contracts[0]['source_date'],
        'offset_days': contracts[0]['offset_days'],
        'source_keys': [contract['source_key'] for contract in contracts],
    }
    return {'check': check, 'failed_items': failed_items}


def _empty_product_result(target_date, product_line):
    return {
        'date': str(target_date),
        'inspection_date': str(target_date),
        'source_date': '',
        'offset_days': None,
        'source_key': '',
        'product_line': str(product_line).upper(),
        'results': [],
        'total_retailers': 0,
        'total_products': 0,
    }


def get_retail_detail(target_date, product_line):
    if str(product_line or '').strip().lower() == 'hhp':
        return _empty_product_result(target_date, product_line)

    source = get_sea_retail_source(product_line)
    contract, source_date = _resolve_source(target_date, source)
    with dx_connection() as (_conn, cursor):
        if source['product_key'] == 'tv':
            rows = repo.get_tv_retail_detail_list(cursor, source_date)
        else:
            rows = repo.get_appliance_retail_detail_list(
                cursor,
                source['table_name'],
                source['date_column'],
                source_date,
                source['retailers'],
            )

    results = []
    for row in rows:
        results.append({
            'retailer': row[0],
            'total': int(row[1] or 0),
            'main_count': int(row[2] or 0),
            'bsr_count': int(row[3] or 0),
            'price_count': int(row[4] or 0),
            'completeness': (
                round((row[4] / row[1] * 100), 1) if row[1] > 0 else 0
            ),
            'batch_id': (
                str(row[5]) if len(row) > 5 and row[5] is not None else ''
            ),
        })

    return {
        'date': contract['inspection_date'],
        'product_line': source['category'],
        'results': results,
        'total_retailers': len(results),
        'total_products': sum(result['total'] for result in results),
        **_contract_fields(contract),
    }


def _empty_summary(target_date, product_line):
    result = _empty_product_result(target_date, product_line)
    result.update({
        'extra_rank_name': '',
        'has_extra_rank': False,
        'summary': [],
        'null_columns': [],
        'totals': {'grand_total': 0, 'am_total': 0, 'pm_total': 0},
        'check_stats': {'total_checks': 0, 'null_count': 0},
        'column_checks': [],
    })
    result.pop('results', None)
    result.pop('total_retailers', None)
    result.pop('total_products', None)
    return result


def get_retail_summary(target_date, product_line):
    if str(product_line or '').strip().lower() == 'hhp':
        return _empty_summary(target_date, product_line)

    source = get_sea_retail_source(product_line)
    contract, source_date = _resolve_source(target_date, source)
    next_day = source_date + timedelta(days=1)
    slot_start = f'{source_date} 00:00:00'
    slot_end = f'{next_day} 00:00:00'

    if source['table_name'] not in ALLOWED_TABLES:
        raise ValueError(f"허용되지 않은 테이블: {source['table_name']}")
    if source['extra_rank_field'] and (
        source['extra_rank_field'] not in ALLOWED_RANK_FIELDS
    ):
        raise ValueError(
            f"허용되지 않은 랭크 필드: {source['extra_rank_field']}"
        )

    summary_data = []
    null_columns_data = []
    column_checks_data = []
    total_check_count = 0
    total_null_count = 0

    with dx_connection() as (_conn, cursor):
        for retailer in source['retailers']:
            check_columns = (
                get_retailer_columns('tv', retailer)
                if source['product_key'] == 'tv'
                else []
            )
            for column in check_columns:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column):
                    raise ValueError(f'허용되지 않은 컬럼명: {column}')

            if source['product_key'] == 'tv':
                row = repo.query_retail_counts_by_retailer(
                    cursor,
                    source['table_name'],
                    'crawl_datetime::timestamp',
                    source['extra_rank_field'],
                    slot_start,
                    slot_end,
                    retailer,
                ) or (0, 0, 0, 0)
                main_count, bsr_count, extra_count, total = [
                    int(value or 0) for value in row[:4]
                ]
                batch_id = row[4] if len(row) > 4 else None
            else:
                (
                    main_count, bsr_count, extra_count, total, batch_id,
                ) = repo.query_appliance_counts_by_retailer(
                    cursor,
                    source['table_name'],
                    source['date_column'],
                    source_date,
                    retailer,
                )

            row_data = {
                'time_slot': '일일',
                'main': main_count,
                'bsr': bsr_count,
                'extra': extra_count,
                'extra_name': source['extra_rank_name'],
                'total': total,
                'batch_id': '' if batch_id is None else str(batch_id),
            }
            summary_data.append({
                'retailer': retailer,
                'rows': [row_data],
                'total': total,
                'batch_id': row_data['batch_id'],
            })

            if total <= 0 or not check_columns:
                continue
            total_check_count += len(check_columns)
            count_row = repo.get_retail_summary_null_counts(
                cursor,
                source['table_name'],
                'crawl_datetime::timestamp',
                check_columns,
                slot_start,
                slot_end,
                retailer,
                False,
            )
            if not count_row:
                continue
            counts = {
                column: int(count or 0)
                for column, count in zip(check_columns, count_row)
            }
            null_columns = [
                column for column, count in counts.items() if count == 0
            ]
            total_null_count += len(null_columns)
            column_checks_data.append({
                'retailer': retailer,
                'check_columns': check_columns,
                'time_slots': [{
                    'time_slot': '일일',
                    'total': total,
                    'counts': counts,
                }],
            })
            if null_columns:
                null_columns_data.append({
                    'retailer': retailer,
                    'time_slots': [{
                        'time_slot': '일일',
                        'null_columns': null_columns,
                    }],
                })

    grand_total = sum(item['total'] for item in summary_data)
    return {
        'date': contract['inspection_date'],
        'product_line': source['category'],
        'extra_rank_name': source['extra_rank_name'],
        'has_extra_rank': source['extra_rank_field'] is not None,
        'summary': summary_data,
        'null_columns': null_columns_data,
        'totals': {
            'grand_total': grand_total,
            'am_total': grand_total,
            'pm_total': 0,
        },
        'check_stats': {
            'total_checks': total_check_count,
            'null_count': total_null_count,
        },
        'column_checks': column_checks_data,
        **_contract_fields(contract),
    }


def get_retailer_raw_data(category, retailer, period, target_date):
    if str(category or '').strip().lower() == 'hhp':
        return {
            'category': category,
            'retailer': retailer,
            'period': period,
            'date': str(target_date),
            'columns': [],
            'data': [],
            'error': 'HHP Retail is excluded from monitoring.',
        }

    source = get_sea_retail_source(category)
    contract, source_date = _resolve_source(target_date, source)
    canonical_retailers = {
        name.lower(): name for name in source['retailers']
    }
    retailer_name = canonical_retailers.get(
        str(retailer or '').strip().lower()
    )
    if retailer_name is None:
        raise ValueError(f'허용되지 않은 리테일러: {retailer}')

    results = {
        'category': source['category'],
        'retailer': retailer_name,
        'period': '일일',
        'date': contract['inspection_date'],
        'columns': [],
        'data': [],
        'batch_id': '',
        **_contract_fields(contract),
    }
    try:
        if source['product_key'] == 'tv':
            db_columns = get_retailer_columns('tv', retailer_name)
            columns = ['id'] + [
                column for column in db_columns if column != 'id'
            ]
            configured = get_all_retailer_columns('tv')
            all_valid_columns = {'id'}
            for retailer_columns in configured.values():
                all_valid_columns.update(retailer_columns)
            invalid_columns = [
                column for column in columns
                if column not in all_valid_columns
            ]
            if invalid_columns:
                raise ValueError(f'허용되지 않은 컬럼: {invalid_columns}')
            next_day = source_date + timedelta(days=1)
            with dx_connection() as (_conn, cursor):
                rows = repo.get_retailer_raw_data_list(
                    cursor,
                    source['table_name'],
                    columns,
                    retailer_name,
                    source['date_column'],
                    f'{source_date} 00:00:00',
                    f'{next_day} 00:00:00',
                )
        else:
            columns = list(source['raw_columns'])
            with dx_connection() as (_conn, cursor):
                batch_id = repo.get_latest_appliance_main_batch(
                    cursor,
                    source['table_name'],
                    source['date_column'],
                    source_date,
                    retailer_name,
                )
                rows = repo.get_appliance_raw_data_list(
                    cursor,
                    source['table_name'],
                    columns,
                    retailer_name,
                    source['date_column'],
                    source_date,
                ) if batch_id is not None else []
            results['batch_id'] = (
                '' if batch_id is None else str(batch_id)
            )

        results['columns'] = columns
        results['total_count'] = len(rows)
        results['data'] = rows
    except Exception as exc:
        results['error'] = log_error(exc)
    return results


def get_retailer_columns_info():
    tv_columns = get_all_retailer_columns('tv')
    all_tv_columns = sorted({
        column for columns in tv_columns.values() for column in columns
    })
    return {
        'tv': {
            'columns': tv_columns,
            'all_columns': all_tv_columns,
        },
    }
