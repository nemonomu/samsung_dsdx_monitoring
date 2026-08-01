"""
Layer 3 크로스 필드 검증 서비스 레이어
"""

from datetime import timedelta
from apps.common.retail_columns import get_editable_columns, get_retailer_columns
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer3.dashboard.services import (
    validate_crossfield,
    validate_review_detail_match,
    get_crossfield_normal_counts,
    get_all_no_review_texts,
    load_crossfield_rules,
)


def get_cross_field_rule_detail(cursor, target_date, product_line, section, rule_id, days):
    """특정 규칙 상세 조회 - 에러 아이템 원본 데이터 + 정상 처리 이력 반환"""
    crossfield_result = validate_crossfield(target_date, section)

    for rule_result in crossfield_result['rule_results']:
        if str(rule_result['rule_id']) == str(rule_id):
            table_name = crossfield_result.get('table_name', '')
            date_col = crossfield_result.get('date_col', '')
            validation_type = rule_result.get('validation_type', '')

            # 에러 아이템 추출 (account_name + item 쌍)
            error_pairs = set()
            direct_error_details = []
            error_detail_map = {}  # (acct, item) → error_detail (검증 태그용)
            for detail in rule_result['error_details']:
                acct = detail.get('account_name', '')
                item = detail.get('item', '')
                if acct and item:
                    error_pairs.add((acct, item))
                    error_detail_map[(acct, item)] = detail
                elif detail.get('id') is not None:
                    direct_error_details.append(detail)

            if (not error_pairs and not direct_error_details) or not table_name or not date_col:
                anomalies = []
            else:
                # 리테일러별 아이템 그룹핑
                retailer_items = {}
                for acct, item in error_pairs:
                    retailer_items.setdefault(acct, []).append(item)

                anomalies = []
                from_date = target_date - timedelta(days=days - 1)

                # select_fields에서 기본 표시 컬럼 결정
                select_fields_raw = rule_result.get('select_fields', '')
                if select_fields_raw:
                    dynamic_cols = [f.strip() for f in select_fields_raw.split('|') if f.strip()]
                else:
                    exclude = {'id', 'item', 'account_name', 'page_type', date_col, 'product_url'}
                    dynamic_cols = []
                    if rule_result['error_details']:
                        for k in rule_result['error_details'][0].keys():
                            if k not in exclude:
                                dynamic_cols.append(k)

                for acct, items in retailer_items.items():
                    # 리테일러 전체 수집 컬럼으로 SELECT
                    retail_cols = get_retailer_columns(product_line, acct)
                    fixed_cols = ['id', 'account_name', 'item', 'page_type', date_col]
                    added = set(fixed_cols + ['product_url'])
                    ordered_cols = list(fixed_cols)
                    for c in dynamic_cols:
                        if c not in added:
                            ordered_cols.append(c)
                            added.add(c)
                    for c in retail_cols:
                        if c not in added:
                            ordered_cols.append(c)
                            added.add(c)
                    ordered_cols.append('product_url')
                    select_sql = ', '.join(ordered_cols)

                    placeholders = ', '.join(['%s'] * len(items))
                    cursor.execute(f"""
                        SELECT {select_sql}
                        FROM {table_name}
                        WHERE account_name = %s
                          AND item IN ({placeholders})
                          AND DATE({date_col}::timestamp) >= %s
                          AND DATE({date_col}::timestamp) <= %s
                          {f'AND {get_tv_validation_condition()}' if table_name == 'tv_retail_com' else ''}
                        ORDER BY item, {date_col}
                    """, [acct] + items + [str(from_date), str(target_date)])
                    cols_desc = [desc[0] for desc in cursor.description]
                    for row in cursor.fetchall():
                        anomaly = {}
                        for i, col_name in enumerate(cols_desc):
                            val = row[i]
                            anomaly[col_name] = str(val) if val is not None else None
                        # 검증 태그 추가 (1일치 에러 항목에만)
                        pair_key = (anomaly.get('account_name', ''), anomaly.get('item', ''))
                        if validation_type == 'cross_detail_mismatch' and pair_key in error_detail_map:
                            detail = error_detail_map[pair_key]
                            validation_info = validate_review_detail_match(detail, product_line, return_detail=True)
                            anomaly['validation_tag'] = validation_info.get('reason', '')
                            anomaly['expected_pattern'] = validation_info.get('expected_pattern', '')
                        anomalies.append(anomaly)

                seen_ids = {str(a.get('id')) for a in anomalies if a.get('id') is not None}
                for detail in direct_error_details:
                    detail_id = detail.get('id')
                    if detail_id is not None and str(detail_id) in seen_ids:
                        continue
                    anomaly = {}
                    for key, val in detail.items():
                        anomaly[key] = str(val) if val is not None else None
                    if validation_type == 'cross_detail_mismatch':
                        validation_info = validate_review_detail_match(detail, product_line, return_detail=True)
                        anomaly['validation_tag'] = validation_info.get('reason', '')
                        anomaly['expected_pattern'] = validation_info.get('expected_pattern', '')
                    anomalies.append(anomaly)

            # account_name, item, crawl_datetime 순으로 정렬
            anomalies.sort(key=lambda x: (
                x.get('account_name', '') or '',
                x.get('item', '') or '',
                str(x.get('crawl_datetime', '') or x.get('crawl_strdatetime', '') or '')
            ))

            # editable 컬럼 수집 (리테일러별 합집합)
            editable_columns = []
            if table_name in ('tv_retail_com', 'hhp_retail_com'):
                seen_retailers = set()
                all_editable = set()
                for a in anomalies:
                    r = a.get('account_name', '')
                    if r and r not in seen_retailers:
                        seen_retailers.add(r)
                        cols = get_editable_columns(product_line, r)
                        all_editable.update(cols)
                editable_columns = sorted(all_editable)

            # 기존 정상 처리 이력 조회
            normal_reviews = {}
            cursor.execute("""
                SELECT record_id, column_name, memo, reason, created_id, created_at
                FROM monitoring_corrections
                WHERE layer = 3 AND correction_type = 'cross_field'
                  AND crawl_date = %s AND status = 'normal'
                  AND table_name = %s AND rule_id = %s
            """, (str(target_date), table_name, rule_id))
            for nr_row in cursor.fetchall():
                nr_key = f"{nr_row[0]}_{nr_row[1]}"
                normal_reviews[nr_key] = {
                    'memo': nr_row[2] or '',
                    'reason': nr_row[3] or '',
                    'created_id': nr_row[4] or '',
                    'created_at': str(nr_row[5]) if nr_row[5] else ''
                }

            # 정상 처리된 record_id 집합
            normal_record_ids = set()
            for nr_key in normal_reviews:
                rid = nr_key.split('_')[0]
                normal_record_ids.add(rid)

            # 리테일러별 집계 (건수 계산의 단일 기준)
            retailer_summary = {}
            for a in anomalies:
                retailer = a.get('account_name', 'Unknown')
                if retailer not in retailer_summary:
                    retailer_summary[retailer] = {'count': 0, 'items': []}
                if str(a.get('id', '')) not in normal_record_ids:
                    retailer_summary[retailer]['count'] += 1
                item = a.get('item', '')
                if item and item not in retailer_summary[retailer]['items']:
                    retailer_summary[retailer]['items'].append(item)

            adjusted_total = sum(r['count'] for r in retailer_summary.values())

            # 리테일러별 전체 수집 컬럼 (컬럼 선택용)
            retailer_columns = {}
            for r in retailer_summary:
                cols = get_retailer_columns(product_line, r)
                retailer_columns[r] = cols

            return {
                'found': True,
                'date': str(target_date),
                'days': days,
                'product_line': product_line.upper(),
                'rule_id': rule_result['rule_id'],
                'detail_code': rule_result['detail_code'],
                'field1': rule_result['field1'],
                'field2': rule_result.get('field2'),
                'validation_type': validation_type,
                'error_message': rule_result['error_message'],
                'total_anomalies': adjusted_total,
                'retailer_summary': retailer_summary,
                'anomalies': anomalies,
                'select_fields': rule_result.get('select_fields', ''),
                'table_name': table_name,
                'editable_columns': editable_columns,
                'normal_reviews': normal_reviews,
                'retailer_columns': retailer_columns,
            }

    return {'found': False}


def get_cross_field_summary(target_date, product_line, section):
    """규칙별 요약 반환 (검증 유형별 건수) - DB 연결 불필요"""
    crossfield_result = validate_crossfield(target_date, section)

    table_name_for_normal = 'tv_retail_com' if product_line == 'tv' else 'hhp_retail_com'
    normal_counts = get_crossfield_normal_counts(target_date, table_name_for_normal)

    rule_summary = []
    total_anomalies = 0
    for r in crossfield_result['rule_results']:
        adjusted_count = max(0, r['error_count'] - normal_counts.get(r['rule_id'], 0))
        rule_summary.append({
            'rule_id': r['rule_id'],
            'detail_code': r['detail_code'],
            'field1': r['field1'],
            'field2': r.get('field2'),
            'validation_type': r.get('validation_type', ''),
            'error_message': r['error_message'],
            'error_count': adjusted_count,
            'query': r.get('query', ''),
            'select_fields': r.get('select_fields', '')
        })
        total_anomalies += adjusted_count

    table_name = crossfield_result.get('table_name', '')
    date_col = crossfield_result.get('date_col', '')

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'total_anomalies': total_anomalies,
        'rule_summary': rule_summary,
        'table_name': table_name,
        'date_col': date_col,
        'no_review_texts': get_all_no_review_texts(),
    }


def get_sentiment_cross_detail(cursor, target_date, product_line):
    if product_line != 'tv':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'total_anomalies': 0,
            'anomalies': [],
        }

    """Sentiment ↔ 리뷰 일관성 상세 조회"""
    anomalies = []

    if product_line == 'tv':
        cursor.execute(f"""
            SELECT
                r.id,
                r.item,
                r.account_name,
                r.page_type,
                r.count_of_star_ratings,
                s.sentiment_score,
                r.main_rank,
                r.crawl_datetime
            FROM tv_retail_sentiment s
            JOIN tv_retail_com r ON s.retail_com_id = r.id
            WHERE DATE(r.crawl_datetime::timestamp) = %s
            AND {get_tv_validation_condition('r')}
            AND s.sentiment_score IS NOT NULL
            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
            AND (
                r.count_of_star_ratings IS NULL
                OR r.count_of_star_ratings = ''
                OR r.count_of_star_ratings = '0'
                OR r.count_of_star_ratings = 'No reviews'
                OR r.count_of_star_ratings = 'No ratings'
            )
            ORDER BY r.crawl_datetime DESC
            LIMIT 100
        """, (target_date,))

        rows = cursor.fetchall()
        for row in rows:
            anomalies.append({
                'retail_com_id': row[0],
                'item': row[1],
                'account_name': row[2],
                'page_type': row[3],
                'errors': [{
                    'field': 'sentiment ↔ count_of_star_ratings',
                    'error': f'리뷰 수가 "{row[4]}"인데 sentiment 점수({row[5]})가 존재'
                }]
            })
    else:
        cursor.execute("""
            SELECT
                r.id,
                r.item,
                r.account_name,
                r.page_type,
                r.count_of_star_ratings,
                s.sentiment_score,
                r.main_rank,
                r.crawl_strdatetime
            FROM hhp_retail_sentiment s
            JOIN hhp_retail_com r ON s.retail_com_id = r.id
            WHERE DATE(r.crawl_strdatetime::timestamp) = %s
            AND s.sentiment_score IS NOT NULL
            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
            AND (
                r.count_of_star_ratings IS NULL
                OR r.count_of_star_ratings = ''
                OR r.count_of_star_ratings = '0'
                OR r.count_of_star_ratings = 'No reviews'
                OR r.count_of_star_ratings = 'No ratings'
            )
            ORDER BY r.crawl_strdatetime DESC
            LIMIT 100
        """, (target_date,))

        rows = cursor.fetchall()
        for row in rows:
            anomalies.append({
                'retail_com_id': row[0],
                'item': row[1],
                'account_name': row[2],
                'page_type': row[3],
                'errors': [{
                    'field': 'sentiment ↔ count_of_star_ratings',
                    'error': f'리뷰 수가 "{row[4]}"인데 sentiment 점수({row[5]})가 존재'
                }]
            })

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'total_anomalies': len(anomalies),
        'anomalies': anomalies,
    }


def get_comp_product_cross_detail(cursor, target_date):
    """Comp Product 자사/경쟁사 구분 상세 조회"""
    month_start = target_date.replace(day=1).strftime('%Y-%m-%d')
    if target_date.month == 12:
        month_end_date = target_date.replace(year=target_date.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end_date = target_date.replace(month=target_date.month + 1, day=1) - timedelta(days=1)
    month_end = month_end_date.strftime('%Y-%m-%d')

    anomalies = []

    # 해당 월에 실행된 comp_product 배치 조회
    cursor.execute("""
        SELECT batch_id, MAX(created_at) as last_run
        FROM market_comp_product
        WHERE batch_id IS NOT NULL
          AND created_at >= %s AND created_at < %s::date + INTERVAL '1 day'
        GROUP BY batch_id
        ORDER BY last_run DESC
        LIMIT 1
    """, (month_start, month_end))
    batch_row = cursor.fetchone()
    batch_id = batch_row[0] if batch_row else None

    if batch_id:
        # samsung_series_name에 comp_brand가 포함된 경우
        cursor.execute("""
            SELECT
                samsung_series_name,
                comp_brand,
                comp_product_name,
                created_at
            FROM market_comp_product
            WHERE batch_id = %s
            AND LOWER(samsung_series_name) LIKE '%%' || LOWER(comp_brand) || '%%'
            ORDER BY created_at DESC
            LIMIT 100
        """, (batch_id,))

        rows = cursor.fetchall()
        for idx, row in enumerate(rows):
            anomalies.append({
                'item': str(idx + 1),
                'account_name': row[1],  # comp_brand
                'page_type': row[0],  # samsung_series_name
                'errors': [{
                    'field': 'samsung_series_name ↔ comp_brand',
                    'error': f'삼성 시리즈({row[0]})에 경쟁사 브랜드({row[1]})가 포함됨'
                }]
            })

    return {
        'date': str(target_date),
        'batch_id': batch_id,
        'total_anomalies': len(anomalies),
        'anomalies': anomalies,
    }


def get_crossfield_rules(section):
    """크로스필드 검증 규칙 목록 반환 (캐시 기반, DB 불필요)"""
    rules = load_crossfield_rules()

    filtered_rules = []
    for rule in rules:
        rule_section = rule.get('section_code', '').lower()

        if section == 'all' or rule_section == section:
            filtered_rules.append({
                'rule_id': rule.get('rule_id'),
                'detail_code': rule.get('detail_code'),
                'detail_name': rule.get('detail_name'),
                'section_code': rule.get('section_code'),
                'field1': rule.get('field1'),
                'field2': rule.get('field2'),
                'error_message': rule.get('error_message'),
                'retailer': rule.get('retailer'),
                'validation_type': rule.get('validation_type'),
            })

    return {
        'status': 'success',
        'section': section,
        'total_rules': len(filtered_rules),
        'rules': filtered_rules,
    }
