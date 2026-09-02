"""
Layer 3 필드 누락 서비스 레이어
"""

from datetime import timedelta
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.retail_columns import get_missing_exclude_conditions
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer3.dashboard.services import validate_exclude_condition
from apps.dx.dx_layer3.field_missing import sea_services


def is_sea_field_missing_product_line(product_line):
    return sea_services.is_sea_product_line(product_line)


def get_field_missing_validation_columns(product_line):
    return sea_services.get_validation_columns(product_line)


def get_field_missing_retailers(product_line):
    if sea_services.is_sea_product_line(product_line):
        return sea_services.get_retailers(product_line)
    return ['Amazon', 'Bestbuy', 'Walmart']


def get_field_missing_excluded_columns(product_line):
    """Columns that are conditionally present and should not count as field-missing issues."""
    if (product_line or '').lower() == 'tv':
        return {'original_sku_price', 'savings'}
    return set()


def resolve_field_missing_date_contract(inspection_date, product_line):
    """Resolve the inspection date without changing non-SEA placeholders."""
    if (product_line or '').lower() == 'tv':
        return resolve_monitoring_date(inspection_date, 'SEA', 'sea_tv')
    if sea_services.is_sea_product_line(product_line):
        source_key = sea_services.get_source_key(product_line)
        return resolve_monitoring_date(inspection_date, 'SEA', source_key)
    value = inspection_date.isoformat()
    return {
        'inspection_date': value,
        'source_date': value,
        'offset_days': 0,
        'country': '',
        'source_key': '',
    }


def field_missing_detection(
        cursor, target_date, product_line, retailer, retail_columns,
        inspection_date=None):
    """
    필드 누락 탐지 비즈니스 로직
    - 데이터일과 그 직전 2일 비교
    - 직전에는 값이 있었는데 데이터일에 NULL/빈값인 필드 탐지
    Returns: dict
    """
    if sea_services.is_sea_product_line(product_line):
        return sea_services.field_missing_detection(
            cursor, target_date, product_line, retailer,
            inspection_date=inspection_date,
        )

    if product_line != 'tv':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'retailer': retailer,
            'prev_dates': [str(target_date - timedelta(days=1)), str(target_date - timedelta(days=2))],
            'summary': {'total_missing_cases': 0, 'fields_with_issues': 0, 'status': 'OK'},
            'missing_fields': []
        }

    prev_date_1 = target_date - timedelta(days=1)
    prev_date_2 = target_date - timedelta(days=2)

    results = {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'retailer': retailer,
        'prev_dates': [str(prev_date_1), str(prev_date_2)],
        'summary': {},
        'missing_fields': []
    }

    # 테이블명과 날짜 컬럼 결정
    if product_line == 'tv':
        table_name = 'tv_retail_com'
        date_column = 'crawl_datetime::timestamp'
    else:
        table_name = 'hhp_retail_com'
        date_column = 'crawl_strdatetime'

    # 리테일러 목록
    retailers_to_check = ['Amazon', 'Bestbuy', 'Walmart'] if retailer == 'all' else [retailer]

    total_missing = 0

    for ret in retailers_to_check:
        if ret not in retail_columns:
            continue

        columns_to_check = retail_columns[ret]
        # 기본 필드 제외 (항상 있어야 하는 필드)
        exclude_cols = ['id', 'item', 'account_name', 'page_type', 'crawl_datetime', 'crawl_strdatetime', 'calendar_week']
        field_missing_excludes = get_field_missing_excluded_columns(product_line)
        columns_to_check = [c for c in columns_to_check if c not in exclude_cols and c not in field_missing_excludes]

        if not columns_to_check:
            continue

        # 모든 필드에 대해 한번의 쿼리로 처리
        # 각 필드별로 직전값 존재 여부, 오늘 NULL 여부를 item별로 집계
        case_prev = []
        case_today = []
        for col in columns_to_check:
            safe_col = f'"{col}"'
            case_prev.append(f"MAX(CASE WHEN DATE({date_column}) IN ('{prev_date_1}', '{prev_date_2}') AND {safe_col} IS NOT NULL AND CAST({safe_col} AS TEXT) != '' THEN 1 ELSE 0 END) as prev_{col.replace(' ', '_')}")

            # exclude 조건 적용
            exclude_conds = get_missing_exclude_conditions(ret, table_name, col)
            exclude_conds = [c for c in exclude_conds if validate_exclude_condition(c)]
            exclude_sql = ""
            if exclude_conds:
                # psycopg2에서 %를 %%로 이스케이프 (LIKE 패턴 등)
                exclude_parts = " OR ".join([f"({c.replace('%', '%%')})" for c in exclude_conds])
                exclude_sql = f" AND NOT ({exclude_parts})"

            case_today.append(f"MAX(CASE WHEN DATE({date_column}) = '{target_date}' AND ({safe_col} IS NULL OR CAST({safe_col} AS TEXT) = ''){exclude_sql} THEN 1 ELSE 0 END) as today_{col.replace(' ', '_')}")

        query = f"""
            SELECT item, {', '.join(case_prev)}, {', '.join(case_today)}
            FROM {table_name}
            WHERE account_name = %s
            AND {get_tv_validation_condition()}
            AND DATE({date_column}) IN (%s, %s, %s)
            GROUP BY item
        """
        cursor.execute(query, (ret, prev_date_1, prev_date_2, target_date))
        rows = cursor.fetchall()

        # 각 필드별 누락 카운트 계산
        field_stats = {col: {'prev_count': 0, 'missing_count': 0, 'missing_items': []} for col in columns_to_check}
        num_cols = len(columns_to_check)

        for row in rows:
            # row: (item, prev_col1, prev_col2, ..., today_col1, today_col2, ...)
            item_name = row[0]
            for i, col in enumerate(columns_to_check):
                prev_val = row[1 + i]  # prev 값들
                today_val = row[1 + num_cols + i]  # today 값들
                if prev_val == 1:
                    field_stats[col]['prev_count'] += 1
                    if today_val == 1:
                        field_stats[col]['missing_count'] += 1
                        field_stats[col]['missing_items'].append(item_name)

        # 각 필드별 오늘 날짜 누락 데이터 수(행 수) 조회
        for col in columns_to_check:
            stats = field_stats[col]
            if stats['missing_count'] > 0 and stats['missing_items']:
                # 누락 item들의 오늘 날짜 NULL 행 수 조회
                safe_col = f'"{col}"'
                placeholders = ', '.join(['%s'] * len(stats['missing_items']))
                # exclude 조건 적용
                exclude_conds = get_missing_exclude_conditions(ret, table_name, col)
                exclude_conds = [c for c in exclude_conds if validate_exclude_condition(c)]
                exclude_sql = ""
                if exclude_conds:
                    exclude_parts = " OR ".join([f"({c.replace('%', '%%')})" for c in exclude_conds])
                    exclude_sql = f" AND NOT ({exclude_parts})"

                null_count_query = f"""
                    SELECT COUNT(*) FROM {table_name}
                    WHERE account_name = %s
                    AND {get_tv_validation_condition()}
                    AND DATE({date_column}) = %s
                    AND item IN ({placeholders})
                    AND ({safe_col} IS NULL OR CAST({safe_col} AS TEXT) = ''){exclude_sql}
                """
                cursor.execute(null_count_query, (ret, target_date, *stats['missing_items']))
                stats['today_null_rows'] = cursor.fetchone()[0] or 0

        # 정상처리 건수 차감 (field_missing)
        try:
            cursor.execute("""
                SELECT column_name, COUNT(DISTINCT item) FROM monitoring_corrections
                WHERE layer = 3 AND correction_type = 'field_missing'
                  AND table_name = %s AND crawl_date = %s AND retailer = %s
                  AND status = 'normal'
                GROUP BY column_name
            """, (
                table_name, str(inspection_date or target_date), ret,
            ))
            for nr_row in cursor.fetchall():
                nr_col, nr_count = nr_row[0], nr_row[1]
                if nr_col in field_stats:
                    field_stats[nr_col]['missing_count'] = max(0, field_stats[nr_col]['missing_count'] - nr_count)
        except Exception:
            pass

        # 결과 집계
        for col in columns_to_check:
            stats = field_stats[col]
            if stats['missing_count'] > 0:
                total_missing += stats['missing_count']
                results['missing_fields'].append({
                    'retailer': ret,
                    'column': col,
                    'prev_had_value_items': stats['prev_count'],
                    'today_missing_items': stats['missing_count'],
                    'today_null_rows': stats.get('today_null_rows', 0),  # 누락 데이터 수 (행 수)
                    'missing_rate': round(stats['missing_count'] / stats['prev_count'] * 100, 2) if stats['prev_count'] > 0 else 0
                })

    results['summary'] = {
        'total_missing_cases': total_missing,
        'fields_with_issues': len(results['missing_fields']),
        'status': 'OK' if total_missing == 0 else ('WARNING' if total_missing < 10 else 'CRITICAL')
    }

    return results


def field_missing_detail_all(cursor, target_date, product_line, retailer, display_fields, offset, limit):
    """
    필드 누락 탐지 상세 - 3일치 raw 데이터 (무한스크롤용)
    item + crawl_datetime 순으로 정렬, 필드들을 컬럼으로 표시
    offset/limit 파라미터로 데이터 분할 조회
    Returns: dict
    """
    if sea_services.is_sea_product_line(product_line):
        return sea_services.field_missing_detail_all(
            cursor, target_date, product_line, retailer, display_fields,
            offset, limit,
        )

    if product_line != 'tv':
        return {
            'status': 'success',
            'date': str(target_date),
            'prev_dates': [str(target_date - timedelta(days=2)), str(target_date - timedelta(days=1))],
            'product_line': product_line.upper(),
            'retailer': retailer,
            'columns': [],
            'display_fields': [],
            'offset': offset,
            'limit': limit,
            'fetched_rows': 0,
            'has_more': False,
            'data': [],
            'total_count': 0
        }

    prev_date_1 = target_date - timedelta(days=1)
    prev_date_2 = target_date - timedelta(days=2)

    if product_line == 'tv':
        table_name = 'tv_retail_com'
        date_column = 'crawl_datetime'
        date_cast = 'crawl_datetime::timestamp'
    else:
        table_name = 'hhp_retail_com'
        date_column = 'crawl_strdatetime'
        date_cast = 'crawl_strdatetime'

    # SELECT 절 구성: id, crawl_datetime, item + 표시 필드들 + product_url(마지막)
    select_cols = ['id', date_column, 'item']
    for col in display_fields:
        select_cols.append(f'"{col}"')
    select_cols.append('product_url')  # URL은 마지막에

    select_clause = ', '.join(select_cols)

    # 먼저 총 건수 조회 (첫 요청시에만)
    total_count = 0
    if offset == 0:
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE account_name = %s
            AND {get_tv_validation_condition()}
            AND DATE({date_cast}) IN (%s, %s, %s)
        """, (retailer, prev_date_2, prev_date_1, target_date))
        total_count = cursor.fetchone()[0]

    # 3일치 데이터 조회 (item, crawl_datetime 순 정렬, 무한스크롤용)
    cursor.execute(f"""
        SELECT {select_clause}
        FROM {table_name}
        WHERE account_name = %s
        AND {get_tv_validation_condition()}
        AND DATE({date_cast}) IN (%s, %s, %s)
        ORDER BY item, {date_column} ASC
        LIMIT %s OFFSET %s
    """, (retailer, prev_date_2, prev_date_1, target_date, limit, offset))

    rows = cursor.fetchall()

    # 컬럼명 목록 (product_url은 마지막)
    column_names = ['id', date_column, 'item'] + display_fields + ['product_url']

    # 데이터 변환
    all_data = []
    for row in rows:
        row_dict = {}
        for i, col_name in enumerate(column_names):
            val = row[i]
            # datetime 변환
            if col_name == date_column and val:
                val = str(val)
            row_dict[col_name] = val
        all_data.append(row_dict)

    response_data = {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [str(prev_date_2), str(prev_date_1)],
        'product_line': product_line.upper(),
        'retailer': retailer,
        'columns': column_names,
        'display_fields': display_fields,
        'offset': offset,
        'limit': limit,
        'fetched_rows': len(all_data),
        'has_more': len(all_data) == limit,
        'data': all_data
    }

    # 첫 요청시에만 total_count 포함
    if offset == 0:
        response_data['total_count'] = total_count

    return response_data


def field_missing_detail_problem(cursor, target_date, product_line, retailer, columns_to_check, offset, limit):
    """
    필드 누락 탐지 상세 - 문제 있는 item만 (직전에 있었는데 데이터일에 없는)
    column 파라미터 없으면 해당 리테일러의 모든 컬럼 검사
    무한 스크롤: offset, limit 파라미터 지원
    Returns: dict (empty result dict if no columns to check)
    """
    if sea_services.is_sea_product_line(product_line):
        return sea_services.field_missing_detail_problem(
            cursor, target_date, product_line, retailer, columns_to_check,
            offset, limit,
        )

    if product_line != 'tv':
        return {
            'status': 'success',
            'date': str(target_date),
            'prev_dates': [str(target_date - timedelta(days=1)), str(target_date - timedelta(days=2))],
            'product_line': product_line.upper(),
            'retailer': retailer,
            'fields': [],
            'total_count': 0,
            'offset': offset,
            'limit': limit,
            'has_more': False,
            'data': []
        }

    prev_date_1 = target_date - timedelta(days=1)
    prev_date_2 = target_date - timedelta(days=2)

    if product_line == 'tv':
        table_name = 'tv_retail_com'
        date_column = 'crawl_datetime'
        date_cast = 'crawl_datetime::timestamp'
    else:
        table_name = 'hhp_retail_com'
        date_column = 'crawl_strdatetime'
        date_cast = 'crawl_strdatetime'

    # 모든 컬럼에 대한 누락 데이터를 UNION ALL로 한번에 조회
    union_queries = []
    params = []

    for col in columns_to_check:
        safe_col = f'"{col}"'
        union_queries.append(f"""
            SELECT
                p.item,
                p.account_name,
                '{col}' as field_name,
                p.prev_value
            FROM (
                SELECT DISTINCT item, account_name, MAX(CAST({safe_col} AS TEXT)) as prev_value
                FROM {table_name}
                WHERE account_name = %s
                AND {get_tv_validation_condition()}
                AND DATE({date_cast}) IN (%s, %s)
                AND {safe_col} IS NOT NULL
                AND CAST({safe_col} AS TEXT) != ''
                GROUP BY item, account_name
            ) p
            LEFT JOIN (
                SELECT DISTINCT item, account_name, {safe_col}
                FROM {table_name}
                WHERE account_name = %s
                AND {get_tv_validation_condition()}
                AND DATE({date_cast}) = %s
            ) t ON p.item = t.item AND p.account_name = t.account_name
            WHERE t.{safe_col} IS NULL OR CAST(t.{safe_col} AS TEXT) = ''
        """)
        params.extend([retailer, prev_date_1, prev_date_2, retailer, target_date])

    if not union_queries:
        return {
            'status': 'success',
            'date': str(target_date),
            'prev_dates': [str(prev_date_1), str(prev_date_2)],
            'product_line': product_line.upper(),
            'retailer': retailer,
            'fields': columns_to_check,
            'total_count': 0,
            'offset': offset,
            'limit': limit,
            'has_more': False,
            'data': []
        }

    full_query = " UNION ALL ".join(union_queries)

    # 먼저 전체 카운트 조회
    count_query = f"SELECT COUNT(*) FROM ({full_query}) as all_data"
    cursor.execute(count_query, params)
    total_count = cursor.fetchone()[0]

    # 페이지네이션 적용한 데이터 조회
    data_query = f"""
        SELECT * FROM ({full_query}) as all_data
        ORDER BY field_name, item
        OFFSET %s LIMIT %s
    """
    cursor.execute(data_query, params + [offset, limit])

    rows = cursor.fetchall()
    all_missing = []
    for row in rows:
        prev_val = row[3]
        all_missing.append({
            'item': row[0],
            'account_name': row[1],
            'field_name': row[2],
            'd2_value': prev_val,
            'd1_value': prev_val,
            'today_value': None,
            'today_has_value': False
        })

    return {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [str(prev_date_1), str(prev_date_2)],
        'product_line': product_line.upper(),
        'retailer': retailer,
        'fields': columns_to_check,
        'total_count': total_count,
        'offset': offset,
        'limit': limit,
        'has_more': (offset + limit) < total_count,
        'data': all_missing
    }


def field_missing_detail_by_field(cursor, target_date, product_line, retailer, field, days,
                                   columns_info, display_fields, related_columns,
                                   editable_cols, inspection_date=None):
    """
    특정 필드의 누락 item들에 대한 N일치 raw 데이터 조회
    - 직전 2일에 값이 있었는데 데이터일에 없는 item들의 N일치 전체 데이터
    Returns: dict (empty result dict if no missing items)
    """
    if sea_services.is_sea_product_line(product_line):
        return sea_services.field_missing_detail_by_field(
            cursor, target_date, product_line, retailer, field, days,
            columns_info, display_fields, related_columns, editable_cols,
            inspection_date=inspection_date,
        )

    if product_line != 'tv':
        return {
            'status': 'success',
            'date': str(target_date),
            'product_line': product_line.upper(),
            'retailer': retailer,
            'field': field,
            'total_count': 0,
            'data': [],
            'normal_reviews': {}
        }

    from apps.common.retail_columns import get_missing_exclude_conditions as get_exclude_conds

    # 조회 범위: target_date 포함 days일치
    prev_dates = [target_date - timedelta(days=i) for i in range(1, days)]
    all_dates = [target_date] + prev_dates  # [오늘, 어제, 그저께, ...]

    # 누락 판정용 (직전 2일)
    prev_date_1 = target_date - timedelta(days=1)
    prev_date_2 = target_date - timedelta(days=2)

    if product_line == 'tv':
        table_name = 'tv_retail_com'
        date_column = 'crawl_datetime'
        date_cast = 'crawl_datetime::timestamp'
    else:
        table_name = 'hhp_retail_com'
        date_column = 'crawl_strdatetime'
        date_cast = 'crawl_strdatetime'

    safe_field = f'"{field}"'

    # SELECT 컬럼 구성: 필수(id, 수집시간, item) + 전체 수집 컬럼 + URL(마지막)
    select_cols = ['id', date_column, 'item']
    # 기본 표시 컬럼: related_columns가 있으면 related, 없으면 해당 필드만
    default_display = []
    if related_columns:
        for rel_col in related_columns:
            if rel_col in display_fields:
                default_display.append(rel_col)
    else:
        default_display.append(field)

    # 전체 수집 컬럼 SELECT (컬럼 선택 기능용)
    added = {'id', date_column, 'item', 'product_url'}
    # 기본 표시 컬럼 먼저
    for col in default_display:
        select_cols.append(f'"{col}"')
        added.add(col)
    # 나머지 수집 컬럼
    for col in display_fields:
        if col not in added:
            select_cols.append(f'"{col}"')
            added.add(col)
    select_cols.append('product_url')  # URL은 마지막에
    select_clause = ', '.join(select_cols)

    # 먼저 요약 API와 동일한 방식으로 누락 item 목록 추출
    # (직전 2일에 값이 있었고, 오늘 NULL인 item)
    # exclude 조건 적용 (요약과 동일)
    exclude_conds = get_exclude_conds(retailer, table_name, field)
    exclude_conds = [c for c in exclude_conds if validate_exclude_condition(c)]
    exclude_sql = ""
    if exclude_conds:
        exclude_parts = " OR ".join([f"({c.replace('%', '%%')})" for c in exclude_conds])
        exclude_sql = f" AND NOT ({exclude_parts})"

    missing_items_query = f"""
        SELECT item
        FROM {table_name}
        WHERE account_name = %s
        AND {get_tv_validation_condition()}
        AND DATE({date_cast}) IN (%s, %s, %s)
        GROUP BY item
        HAVING
            MAX(CASE WHEN DATE({date_cast}) IN (%s, %s) AND {safe_field} IS NOT NULL AND CAST({safe_field} AS TEXT) != '' THEN 1 ELSE 0 END) = 1
            AND MAX(CASE WHEN DATE({date_cast}) = %s AND ({safe_field} IS NULL OR CAST({safe_field} AS TEXT) = ''){exclude_sql} THEN 1 ELSE 0 END) = 1
    """

    cursor.execute(missing_items_query, (
        retailer, prev_date_2, prev_date_1, target_date,
        prev_date_1, prev_date_2,
        target_date
    ))
    missing_items = [row[0] for row in cursor.fetchall()]

    # 컬럼명 목록: select_cols와 동일한 순서
    base_set = {'id', date_column, 'item', 'product_url'}
    column_names = ['id', date_column, 'item'] + [c for c in default_display if c not in base_set] + [c for c in display_fields if c not in base_set and c not in set(default_display)] + ['product_url']

    if not missing_items:
        # 누락 item이 없으면 빈 결과 반환
        return {
            'status': 'success',
            'date': str(target_date),
            'prev_dates': [str(d) for d in prev_dates],
            'product_line': product_line.upper(),
            'retailer': retailer,
            'field': field,
            'columns': column_names,
            'total_rows': 0,
            'data': []
        }

    # 누락 item들의 N일치 데이터 조회
    placeholders = ', '.join(['%s'] * len(missing_items))
    date_placeholders = ', '.join(['%s'] * len(all_dates))
    query = f"""
        SELECT {select_clause}
        FROM {table_name}
        WHERE account_name = %s
        AND {get_tv_validation_condition()}
        AND DATE({date_cast}) IN ({date_placeholders})
        AND item IN ({placeholders})
        ORDER BY item, {date_column}
    """

    cursor.execute(query, (
        retailer, *[str(d) for d in all_dates],
        *missing_items
    ))

    rows = cursor.fetchall()

    # 데이터 변환
    all_data = []
    today_null_count = 0  # 오늘 날짜의 NULL 행 수
    for row in rows:
        row_dict = {}
        for i, col_name in enumerate(column_names):
            val = row[i]
            if col_name == date_column and val:
                val = str(val)
            row_dict[col_name] = val
        all_data.append(row_dict)

        # 오늘 날짜이고 해당 필드가 NULL인 경우 카운트
        crawl_date = row_dict.get(date_column, '')[:10] if row_dict.get(date_column) else ''
        field_val = row_dict.get(field)
        if crawl_date == str(target_date) and (field_val is None or field_val == ''):
            today_null_count += 1

    # normal_reviews 조회 (field_missing 정상처리 이력)
    normal_reviews = {}
    try:
        cursor.execute("""
            SELECT record_id, column_name, reason, memo, created_id
            FROM monitoring_corrections
            WHERE layer = 3 AND correction_type = 'field_missing'
              AND table_name = %s AND crawl_date = %s
              AND status = 'normal'
        """, (table_name, str(inspection_date or target_date)))
        for nr_row in cursor.fetchall():
            nk = str(nr_row[0]) + '_' + nr_row[1]
            normal_reviews[nk] = {
                'reason': nr_row[2] or '',
                'memo': nr_row[3] or '',
                'created_id': nr_row[4] or ''
            }
    except Exception:
        pass

    # 리테일러 전체 수집 컬럼 (컬럼 선택용)
    all_display_fields = [c['column_name'] for c in columns_info
                          if c['column_name'] not in ('id', 'item', 'account_name', 'page_type', date_column, 'product_url')]

    return {
        'status': 'success',
        'date': str(target_date),
        'prev_dates': [str(d) for d in prev_dates],
        'product_line': product_line.upper(),
        'retailer': retailer,
        'field': field,
        'columns': column_names,
        'display_fields': all_display_fields,
        'total_rows': len(all_data),
        'missing_item_count': len(missing_items),
        'today_null_count': today_null_count,
        'data': all_data,
        'table_name': table_name,
        'editable_columns': editable_cols,
        'normal_reviews': normal_reviews,
        'default_columns': ['id', date_column, 'item'] + list(default_display) + ['product_url'],
    }
