"""
Layer 3 대시보드 서비스 — 공통 규칙 로드, 검증, 상태 판정
"""

import re
from apps.common.db import get_dx_connection, dx_table
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.response import log_error
from apps.common.retail_validation import (
    apply_tv_validation_scope,
    get_tv_validation_condition,
)


_DANGEROUS_SQL = {'DROP', 'DELETE', 'TRUNCATE', 'UPDATE', 'INSERT', 'ALTER', 'GRANT', 'REVOKE'}

_ALLOWED_TABLES = {
    'tv_retail_com',
    'tv_item_mst',
    'tv_sentiment_com', 'hhp_sentiment_com',
    'comp_product',
    'openai_forecast_results',
} - DISABLED_SOURCE_TABLES

EXCLUDED_RETAIL_TABLES = {'hhp_retail_com', 'hhp_item_mst'}
EXCLUDED_RETAIL_SECTIONS = {'hhp_retail'}


def is_excluded_retail_rule(rule):
    table_name = (rule.get('table_name') or '').lower()
    section_code = (rule.get('section_code') or '').lower()
    return (
        table_name in EXCLUDED_RETAIL_TABLES
        or section_code in EXCLUDED_RETAIL_SECTIONS
        or table_name in DISABLED_SOURCE_TABLES
    )

_EXCLUDE_PATTERN = re.compile(
    r"""^\s*\w+\s+(?:
        LIKE\s+'[^']*'          |
        NOT\s+LIKE\s+'[^']*'    |
        =\s*'[^']*'             |
        !=\s*'[^']*'            |
        <>\s*'[^']*'            |
        IS\s+NULL               |
        IS\s+NOT\s+NULL         |
        IN\s*\([^)]+\)
    )\s*$""",
    re.IGNORECASE | re.VERBOSE
)


def validate_table_name(table_name):
    """테이블명 화이트리스트 검증"""
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"허용되지 않은 테이블: {table_name}")
    return table_name


def validate_select_query(query):
    """SELECT 전용 쿼리인지 검증. 위험 키워드 포함 시 False 반환."""
    upper = query.strip().upper()
    if not upper.startswith('SELECT') and not upper.startswith('WITH'):
        return False
    for keyword in _DANGEROUS_SQL:
        if re.search(r'\b' + keyword + r'\b', upper):
            return False
    if ';' in query:
        return False
    return True

def apply_tv_retail_am_filter(query, table_name, date_col='crawl_datetime'):
    """Compatibility wrapper for the full-date TV validation scope."""
    return apply_tv_validation_scope(query, table_name)

def validate_exclude_condition(condition):
    """exclude_condition SQL 조각 검증 — 화이트리스트 패턴만 허용"""
    if not condition or not condition.strip():
        return False
    if ';' in condition or '--' in condition or '/*' in condition:
        return False
    parts = re.split(r'\bOR\b', condition, flags=re.IGNORECASE)
    for part in parts:
        if not _EXCLUDE_PATTERN.match(part.strip()):
            return False
    return True


def load_timeseries_rules():
    """DB에서 시계열 이상치 검증 규칙 로드 (monitoring_timeseries_rules 테이블)"""
    rules = []
    table = dx_table('monitoring_timeseries_rules')
    try:
        conn = get_dx_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, detail_code, detail_name, section_code, section_name,
                   table_name, date_column, product_line,
                   check_type, threshold_pct,
                   error_message, query, sort_order
            FROM {table}
            WHERE is_active = true
            ORDER BY sort_order, id
        """)
        columns = [
            'rule_id', 'detail_code', 'detail_name', 'section_code', 'section_name',
            'table_name', 'date_column', 'product_line',
            'check_type', 'threshold_pct',
            'error_message', 'query', 'sort_order'
        ]
        for row in cursor.fetchall():
            rule = dict(zip(columns, row))
            if is_excluded_retail_rule(rule):
                continue
            rules.append(rule)
        cursor.close()
        conn.close()
    except Exception as e:
        log_error(e)

    return rules


def load_crossfield_rules():
    """DB에서 크로스필드 검증 규칙 로드 (monitoring_validation_rules 테이블)"""
    rules = []
    try:
        conn = get_dx_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, detail_code, detail_name, section_code, section_name,
                   table_name, date_column, product_line, retailer,
                   field1, field2, validation_type,
                   error_message, select_fields, query, sort_order
            FROM monitoring_validation_rules
            WHERE rule_type = 'crossfield' AND is_active = true
            ORDER BY sort_order, id
        """)
        columns = [
            'rule_id', 'detail_code', 'detail_name', 'section_code', 'section_name',
            'table_name', 'date_column', 'product_line', 'retailer',
            'field1', 'field2', 'validation_type',
            'error_message', 'select_fields', 'query', 'sort_order'
        ]
        for row in cursor.fetchall():
            rule = dict(zip(columns, row))
            if is_excluded_retail_rule(rule):
                continue
            rules.append(rule)
        cursor.close()
        conn.close()
    except Exception as e:
        log_error(e)

    return rules


def load_category_rules():
    """DB에서 카테고리별 특성 검증 규칙 로드 (monitoring_validation_rules 테이블)"""
    rules = []
    try:
        conn = get_dx_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, detail_code, detail_name, section_code, section_name,
                   table_name, date_column, product_line, retailer,
                   field1, validation_type, threshold,
                   error_message, display_columns, query, sort_order
            FROM monitoring_validation_rules
            WHERE rule_type = 'category_spec' AND is_active = true
            ORDER BY sort_order, id
        """)
        columns = [
            'rule_id', 'detail_code', 'detail_name', 'section_code', 'section_name',
            'table_name', 'date_column', 'product_line', 'retailer',
            'field1', 'validation_type', 'threshold',
            'error_message', 'display_columns', 'query', 'sort_order'
        ]
        for row in cursor.fetchall():
            rule = dict(zip(columns, row))
            if is_excluded_retail_rule(rule):
                continue
            rules.append(rule)
        cursor.close()
        conn.close()
    except Exception as e:
        log_error(e)

    return rules


def get_non_product_set(cursor, table_name, product_line, pairs):
    """item_mst에서 is_product=false 또는 is_checked=true인 (item, account_name) 집합 반환"""
    if not pairs or 'retail_com' not in table_name:
        return set()
    pl = (product_line or '').lower()
    mst = validate_table_name('hhp_item_mst' if 'hhp' in pl or 'hhp' in table_name else 'tv_item_mst')
    ph = ' OR '.join(['(item = %s AND account_name = %s)'] * len(pairs))
    params = [v for p in pairs for v in p]
    cursor.execute(f"SELECT item, account_name FROM {mst} WHERE (is_product = false OR is_checked = true) AND ({ph})", params)
    return {(r[0], r[1]) for r in cursor.fetchall()}


def get_no_review_texts(account_name):
    """리테일러별 리뷰없음 텍스트 반환"""
    if account_name == 'Amazon':
        return "'No customer reviews'"
    elif account_name == 'Bestbuy':
        return "'Not yet reviewed'"
    else:
        return "'No ratings yet'"


def get_all_no_review_texts():
    """모든 리테일러의 리뷰없음 텍스트 반환"""
    return "'No customer reviews', 'Not yet reviewed', 'No ratings yet'"


def validate_review_detail_match(row, product_line, return_detail=False):
    """count_of_reviews와 detailed_review_content 매칭 검증 (후처리)"""
    count_of_reviews = row.get('count_of_reviews', '')
    detailed_review_content = row.get('detailed_review_content', '')
    account_name = row.get('account_name', '')

    def make_result(is_error, reason='', pattern='', found=False, max_num=0):
        if return_detail:
            return {
                'is_error': is_error,
                'reason': reason,
                'expected_pattern': pattern,
                'pattern_found': found,
                'max_review_num': max_num
            }
        return is_error

    try:
        review_count = int(str(count_of_reviews).replace(',', ''))
    except (ValueError, TypeError):
        return make_result(False, '리뷰 수 파싱 불가')

    if review_count <= 0:
        return make_result(False, '리뷰 수 0 이하')

    if not detailed_review_content or detailed_review_content.strip() == '':
        return make_result(True, '본문 없음', '', False, min(review_count, 20))

    no_review_texts = ['No customer reviews', 'Not yet reviewed', 'No ratings yet']
    if detailed_review_content in no_review_texts:
        return make_result(True, '리뷰없음 텍스트', '', False, min(review_count, 20))

    max_review_num = min(review_count, 20)
    pattern = f"review{max_review_num} -"
    pattern_found = pattern.lower() in detailed_review_content.lower()

    if pattern_found:
        return make_result(False, '정상', pattern, True, max_review_num)
    else:
        return make_result(True, f'패턴 "{pattern}" 없음', pattern, False, max_review_num)


def get_category_display_name(section_code, rules=None):
    """section_code를 화면에 표시할 이름으로 변환"""
    if rules:
        for rule in rules:
            category_name = rule.get('section_name', '').strip()
            if category_name:
                return category_name
    return section_code


def get_category_description(category, rules):
    """category의 규칙들을 요약한 description 생성"""
    if not rules:
        return ''
    field_names = list(set(r.get('field1', '') for r in rules if r.get('field1')))
    return ', '.join(field_names) + ' 범위 검증' if field_names else '범위 검증'


def validate_all_category_specs(target_date):
    """카테고리별 특성 검증 - 모든 섹션을 동적으로 처리"""
    rules = load_category_rules()
    if not rules:
        return []

    section_rules_map = {}
    for rule in rules:
        sec = rule.get('section_code', '').lower()
        if sec not in section_rules_map:
            section_rules_map[sec] = []
        section_rules_map[sec].append(rule)

    results = []
    conn = get_dx_connection()
    cursor = conn.cursor()

    for section, sec_rules in section_rules_map.items():
        cat_total = 0
        cat_anomaly = 0
        rule_results = []

        for rule in sec_rules:
            rule_id = rule.get('rule_id')
            detail_code = rule.get('detail_code')
            detail_name = rule.get('detail_name')
            table_name = rule.get('table_name', '')
            field1 = rule.get('field1')
            error_message = rule.get('error_message')
            query_template = rule.get('query', '')

            if not query_template:
                continue

            date_col = (rule.get('date_column') or '').strip()
            has_date_filter = bool(date_col)

            try:
                validate_table_name(table_name)
                if has_date_filter:
                    if table_name == 'tv_retail_com':
                        total_query = (
                            f"SELECT COUNT(*) FROM {table_name} "
                            f"WHERE DATE({date_col}) = %s "
                            f"AND EXTRACT(HOUR FROM {date_col}) < 12 "
                            f"AND {get_tv_validation_condition()}"
                        )
                    else:
                        total_query = f"SELECT COUNT(*) FROM {table_name} WHERE DATE({date_col}) = %s"
                    cursor.execute(total_query, (target_date,))
                else:
                    total_query = f"SELECT COUNT(*) FROM {table_name}"
                    cursor.execute(total_query)

                total_count = cursor.fetchone()[0] or 0

                query = query_template.replace('{table}', table_name).replace('{date_col}', date_col)
                query = apply_tv_retail_am_filter(query, table_name, date_col)
                if not validate_select_query(query):
                    raise ValueError(f'허용되지 않은 쿼리 유형: {detail_code}')
                query = query.replace('%%', '%')
                query = query.replace('%', '%%').replace('%%s', '%s')

                if has_date_filter:
                    cursor.execute(query, (target_date,))
                else:
                    cursor.execute(query)

                anomaly_rows = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description] if cursor.description else []
                anomaly_count = len(anomaly_rows)

                item_idx = col_names.index('item') if 'item' in col_names else -1
                acct_idx = col_names.index('account_name') if 'account_name' in col_names else -1
                if anomaly_rows and item_idx >= 0 and acct_idx >= 0:
                    pairs = list({(r[item_idx], r[acct_idx]) for r in anomaly_rows})
                    non_products = get_non_product_set(cursor, table_name, rule.get('product_line'), pairs)
                    if non_products:
                        anomaly_count = sum(1 for r in anomaly_rows if (r[item_idx], r[acct_idx]) not in non_products)

                cat_total += total_count
                cat_anomaly += anomaly_count

                rule_results.append({
                    'rule_id': rule_id,
                    'detail_code': detail_code,
                    'detail_name': detail_name,
                    'field1': field1,
                    'error_message': error_message,
                    'total': total_count,
                    'anomaly': anomaly_count
                })

            except Exception as e:
                conn.rollback()
                log_error(e)

        results.append({
            'section_code': section,
            'section_name': get_category_display_name(section, sec_rules),
            'description': get_category_description(section, sec_rules),
            'total': cat_total,
            'anomaly': cat_anomaly,
            'rules': rule_results
        })

    cursor.close()
    conn.close()

    return results


def execute_crossfield_query(rule, table_name, date_col, target_date, product_line='tv'):
    """규칙의 쿼리를 실행하고 결과 건수 반환"""
    query_template = rule.get('query', '')
    rule_id = str(rule.get('rule_id', ''))

    if not query_template:
        return 0, []

    if not query_template.strip().upper().startswith('SELECT'):
        return 0, []

    validate_table_name(table_name)

    query = query_template.replace('{table}', table_name)
    query = query.replace('{date_col}', date_col)
    query = query.replace('{no_review_texts}', get_all_no_review_texts())
    query = query.replace('{product_line}', product_line)
    query = apply_tv_retail_am_filter(query, table_name, date_col)
    if not validate_select_query(query):
        return 0, []

    query = query.replace('%', '%%').replace('%%s', '%s')

    try:
        conn = get_dx_connection()
        cursor = conn.cursor()
        cursor.execute(query, (target_date,))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        results = [dict(zip(columns, row)) for row in rows]

        validation_type = rule.get('validation_type', '')
        if validation_type == 'cross_detail_mismatch':
            pl = 'tv' if 'tv' in product_line.lower() else 'hhp'
            results = [r for r in results if validate_review_detail_match(r, pl)]

        return len(results), results
    except Exception as e:
        log_error(e)
        return 0, []


def validate_crossfield(target_date, section='tv_retail'):
    """DB 기반 크로스필드 검증 실행"""
    rules = load_crossfield_rules()
    results = {
        'total_errors': 0,
        'rule_results': []
    }

    table_name = ''
    date_col = ''

    for rule in rules:
        if rule.get('section_code', '').lower() != section:
            continue

        table_name = rule.get('table_name', '')
        date_col = rule.get('date_column', '')
        validate_table_name(table_name)

        error_count, error_details = execute_crossfield_query(
            rule, table_name, date_col, target_date, section
        )

        results['total_errors'] += error_count
        results['rule_results'].append({
            'rule_id': rule.get('rule_id'),
            'detail_code': rule.get('detail_code'),
            'detail_name': rule.get('detail_name'),
            'field1': rule.get('field1'),
            'field2': rule.get('field2'),
            'validation_type': rule.get('validation_type'),
            'error_message': rule.get('error_message'),
            'error_count': error_count,
            'error_details': error_details,
            'query': rule.get('query', ''),
            'select_fields': rule.get('select_fields', '')
        })

    results['table_name'] = table_name
    results['date_col'] = date_col

    return results


def get_crossfield_normal_counts(target_date, table_name=None):
    """크로스필드 정상 처리 건수를 rule_id별로 반환."""
    conn = None
    try:
        conn = get_dx_connection()
        cursor = conn.cursor()
        sql = """
            SELECT rule_id, COUNT(DISTINCT record_id)
            FROM monitoring_corrections
            WHERE layer = 3 AND correction_type = 'cross_field'
              AND status = 'normal' AND crawl_date = %s
              AND rule_id IS NOT NULL
        """
        params = [str(target_date)]
        if table_name:
            sql += " AND table_name = %s"
            params.append(table_name)
        sql += " GROUP BY rule_id"
        cursor.execute(sql, params)
        result = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        return result
    except Exception:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return {}


def get_status(issue_count, total_count=0, needs_review=False):
    """상태 판정"""
    if needs_review:
        return 'REVIEW_NEEDED'
    if issue_count == 0:
        return 'OK'
    elif total_count > 0 and issue_count / total_count < 0.01:
        return 'WARNING'
    elif issue_count <= 10:
        return 'WARNING'
    else:
        return 'CRITICAL'


def validate_cross_field(row_data, account_name='Amazon', product_line='tv'):
    """크로스 필드 논리 검증. 여러 필드 간 관계 검증. 오류 목록 반환"""
    errors = []

    star_rating = row_data.get('star_rating')
    count_of_star_ratings = row_data.get('count_of_star_ratings')
    page_type = row_data.get('page_type')
    main_rank = row_data.get('main_rank')
    bsr_rank = row_data.get('bsr_rank')
    final_sku_price = row_data.get('final_sku_price')
    original_sku_price = row_data.get('original_sku_price')

    if account_name == 'Amazon':
        no_review_texts = ['No customer reviews']
    elif account_name == 'Bestbuy':
        no_review_texts = ['Not yet reviewed']
    else:
        no_review_texts = ['No ratings yet']

    if star_rating is not None and str(star_rating).strip() != '' and str(star_rating).strip() not in no_review_texts:
        try:
            rating_val = float(star_rating)
            if rating_val > 0:
                if count_of_star_ratings is None or str(count_of_star_ratings).strip() == '':
                    errors.append({
                        'field': 'star_rating ↔ count_of_star_ratings',
                        'value': f'star_rating={star_rating}, count_of_star_ratings=NULL',
                        'error': 'star_rating 값이 있는데 count_of_star_ratings가 NULL'
                    })
                elif str(count_of_star_ratings).strip() not in no_review_texts:
                    clean_count = str(count_of_star_ratings).replace(',', '')
                    if clean_count.isdigit() and int(clean_count) == 0:
                        errors.append({
                            'field': 'star_rating ↔ count_of_star_ratings',
                            'value': f'star_rating={star_rating}, count_of_star_ratings=0',
                            'error': 'star_rating 값이 있는데 count_of_star_ratings가 0'
                        })
        except (ValueError, TypeError):
            pass

    if page_type is not None and str(page_type).strip() == 'main':
        if main_rank is None or str(main_rank).strip() == '':
            errors.append({
                'field': 'page_type ↔ main_rank',
                'value': f'page_type=main, main_rank=NULL',
                'error': 'page_type이 main인데 main_rank가 NULL'
            })

    if page_type is not None and str(page_type).strip() == 'bsr':
        if bsr_rank is None or str(bsr_rank).strip() == '':
            errors.append({
                'field': 'page_type ↔ bsr_rank',
                'value': f'page_type=bsr, bsr_rank=NULL',
                'error': 'page_type이 bsr인데 bsr_rank가 NULL'
            })

    promotion_position = row_data.get('promotion_position')
    if page_type is not None and str(page_type).strip() == 'promotion':
        if promotion_position is None or str(promotion_position).strip() == '':
            errors.append({
                'field': 'page_type ↔ promotion_position',
                'value': f'page_type=promotion, promotion_position=NULL',
                'error': 'page_type이 promotion인데 promotion_position이 NULL'
            })

    promotion_type = row_data.get('promotion_type')
    if account_name == 'Bestbuy':
        if promotion_position is not None and str(promotion_position).strip() != '':
            if promotion_type is None or str(promotion_type).strip() == '':
                errors.append({
                    'field': 'promotion_position ↔ promotion_type',
                    'value': f'promotion_position={promotion_position}, promotion_type=NULL',
                    'error': 'promotion_position이 있는데 promotion_type이 NULL'
                })

    trend_rank = row_data.get('trend_rank')
    if page_type is not None and str(page_type).strip() == 'trend':
        if trend_rank is None or str(trend_rank).strip() == '':
            errors.append({
                'field': 'page_type ↔ trend_rank',
                'value': f'page_type=trend, trend_rank=NULL',
                'error': 'page_type이 trend인데 trend_rank가 NULL'
            })

    if final_sku_price is not None and original_sku_price is not None:
        final_str = str(final_sku_price).strip()
        original_str = str(original_sku_price).strip()

        if final_str.startswith('$') and original_str.startswith('$'):
            is_periodic_price = any(p in final_str.lower() for p in ['/month', '/mo', '/day', '/week', '/yr', '/year'])

            try:
                final_val = float(final_str.replace('$', '').replace(',', '').split('/')[0])
                original_val = float(original_str.replace('$', '').replace(',', '').split('/')[0])

                if not is_periodic_price:
                    if final_val > original_val:
                        errors.append({
                            'field': 'final_sku_price ↔ original_sku_price',
                            'value': f'final={final_str}, original={original_str}',
                            'error': f'final_sku_price({final_str})가 original_sku_price({original_str})보다 높음'
                        })

                    if original_val > 0 and final_val > 0:
                        discount_rate = (original_val - final_val) / original_val * 100
                        if discount_rate >= 90:
                            errors.append({
                                'field': 'discount_rate',
                                'value': f'final={final_str}, original={original_str}, 할인율={discount_rate:.1f}%',
                                'error': f'할인율이 90% 이상으로 비정상적 ({discount_rate:.1f}%)'
                            })
            except (ValueError, TypeError):
                pass

    count_of_reviews = row_data.get('count_of_reviews')
    detail_review_content = row_data.get('detail_review_content')

    review_count = 0
    if count_of_reviews is not None:
        try:
            count_str = str(count_of_reviews).strip().replace(',', '')
            if count_str.isdigit():
                review_count = int(count_str)
        except (ValueError, TypeError):
            pass

    if review_count > 0:
        content_str = str(detail_review_content).strip() if detail_review_content is not None else ''
        if not content_str or content_str.lower() == 'null' or content_str.lower() == 'none':
            errors.append({
                'field': 'count_of_reviews ↔ detail_review_content',
                'value': f'count_of_reviews={review_count}, detail_review_content=NULL',
                'error': f'리뷰 수가 {review_count}개인데 detail_review_content가 NULL임'
            })
        else:
            expected_count = min(review_count, 20)
            has_expected_review = False
            error_detail = ''

            if product_line == 'tv' and account_name == 'Amazon':
                expected_key = f'{expected_count}-'
                if expected_key in content_str:
                    has_expected_review = True
                error_detail = f'{expected_count}-'

            elif product_line == 'tv' and account_name == 'Bestbuy':
                delimiter_count = content_str.count('|')
                actual_review_count = delimiter_count + 1 if delimiter_count >= 0 else 1
                if actual_review_count >= expected_count:
                    has_expected_review = True
                error_detail = f'구분자 {delimiter_count}개 (리뷰 {actual_review_count}개), 기대: {expected_count}개'

            else:
                expected_key = f'review{expected_count}'
                if expected_key in content_str:
                    has_expected_review = True
                error_detail = expected_key

            if not has_expected_review:
                errors.append({
                    'field': 'count_of_reviews ↔ detail_review_content',
                    'value': f'count_of_reviews={review_count}, {error_detail}=없음',
                    'error': f'리뷰 수가 {review_count}개인데 detail_review_content에 {error_detail}이 없음'
                })

    return errors
