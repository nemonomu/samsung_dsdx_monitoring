"""
DX 컬럼 설정 로드
DB에서 TV/HHP 리테일러별 컬럼 정보 및 NULL 체크 컬럼 정보를 읽어옴
"""

import csv
import time
from pathlib import Path
from apps.common.db import execute_dx_query, dx_table
from apps.common.response import log_error
from apps.common.tse_retail import (
    TSE_SOURCE_CONFIG,
    display_tse_retailer,
    normalize_tse_product_line,
)

# CSV 파일 경로 (config/csv 폴더) - 형식검증, 시계열 규칙용
CSV_DIR = Path(__file__).parent.parent.parent / 'config' / 'csv'

# TTL 캐시 — DB 변경 시 최대 60초 후 자동 반영
_CACHE_TTL = 60  # 초

_retail_columns_cache = None
_retail_columns_cache_time = None

_tse_retail_columns_cache = None
_tse_retail_columns_cache_time = None

_format_rules_cache = None
_format_rules_cache_time = None


def load_retail_columns():
    """
    DB에서 리테일러별 컬럼 정보 로드
    테이블: monitoring_retail_columns
    Y 표시된 컬럼은 해당 리테일러에 포함되며 자동으로 NULL 체크 대상

    Returns: {
        'tv': {
            'Amazon': [column1, column2, ...],
            'Bestbuy': [...],
            'Walmart': [...]
        },
        'hhp': {...}
    }
    """
    global _retail_columns_cache, _retail_columns_cache_time
    now = time.time()
    if _retail_columns_cache is not None and _retail_columns_cache_time and (now - _retail_columns_cache_time) < _CACHE_TTL:
        return _retail_columns_cache

    result = {
        'tv': {'Amazon': [], 'Bestbuy': [], 'Walmart': []},
        'hhp': {'Amazon': [], 'Bestbuy': [], 'Walmart': []}
    }

    try:
        query = """
            SELECT product_line, column_name, retailer
            FROM monitoring_retail_columns
            WHERE is_active = TRUE
            ORDER BY id
        """
        rows = execute_dx_query(query)

        # retailer 값을 표시명으로 매핑
        retailer_map = {'amazon': 'Amazon', 'bestbuy': 'Bestbuy', 'walmart': 'Walmart'}

        for row in rows:
            product_line = row['product_line'].lower()
            column_name = row['column_name']
            retailer_key = row['retailer'].lower()
            retailer_name = retailer_map.get(retailer_key)

            if retailer_name and product_line in result:
                result[product_line][retailer_name].append(column_name)

        _retail_columns_cache = result
        _retail_columns_cache_time = now
    except Exception as e:
        log_error(e, 'db')

    return result


def get_retailer_columns(product_line, retailer):
    """
    특정 리테일러의 컬럼 목록 반환 (Y 표시된 컬럼 = NULL 체크 대상)

    Args:
        product_line: 'tv' 또는 'hhp'
        retailer: 'Amazon', 'Bestbuy', 'Walmart'

    Returns:
        list: 컬럼명 리스트
    """
    columns_data = load_retail_columns()
    product_key = product_line.lower()

    if product_key not in columns_data:
        return []

    return columns_data[product_key].get(retailer, [])


def get_all_retailer_columns(product_line):
    """
    해당 제품라인의 모든 리테일러 컬럼 정보 반환

    Args:
        product_line: 'tv' 또는 'hhp'

    Returns:
        dict: {retailer: [columns...], ...}
    """
    columns_data = load_retail_columns()
    product_key = product_line.lower()

    if product_key not in columns_data:
        return {}

    return columns_data[product_key]


def reload_retail_columns():
    """캐시 초기화 후 다시 로드"""
    global _retail_columns_cache, _tse_retail_columns_cache
    _retail_columns_cache = None
    _tse_retail_columns_cache = None
    return load_retail_columns()


def load_tse_retail_columns():
    """Load active TSE NULL/edit column settings without changing TV/HHP data.

    Returns::

        {
            'tse_tv': {
                'Homepro': {
                    'retailer': 'homepro',
                    'required_columns': [...],
                    'editable_columns': [...],
                },
            },
            ...
        }
    """
    global _tse_retail_columns_cache, _tse_retail_columns_cache_time

    now = time.time()
    if (
        _tse_retail_columns_cache is not None
        and _tse_retail_columns_cache_time
        and (now - _tse_retail_columns_cache_time) < _CACHE_TTL
    ):
        return _tse_retail_columns_cache

    result = {product_line: {} for product_line in TSE_SOURCE_CONFIG}
    try:
        query = """
            SELECT product_line, column_name, retailer,
                   skip_missing_check, is_editable
            FROM monitoring_retail_columns
            WHERE product_line IN (%s, %s, %s)
              AND is_active = TRUE
              AND COALESCE(is_del, FALSE) = FALSE
            ORDER BY product_line, retailer, id
        """
        rows = execute_dx_query(query, tuple(TSE_SOURCE_CONFIG.keys()))
        for row in rows:
            try:
                product_line = normalize_tse_product_line(row['product_line'])
            except ValueError:
                continue

            retailer_key = str(row.get('retailer') or '').strip().lower()
            if not retailer_key:
                continue
            retailer_name = display_tse_retailer(row['retailer'])
            retailer_config = result[product_line].setdefault(retailer_name, {
                'retailer': retailer_key,
                'required_columns': [],
                'editable_columns': [],
            })
            column_name = row['column_name']
            if not row.get('skip_missing_check'):
                retailer_config['required_columns'].append(column_name)
            if row.get('is_editable'):
                retailer_config['editable_columns'].append(column_name)
    except Exception as e:
        log_error(e, 'db')

    _tse_retail_columns_cache = result
    _tse_retail_columns_cache_time = now
    return result


def get_tse_retailer_columns(product_line):
    """Return TSE retailer column settings for one product line."""
    key = normalize_tse_product_line(product_line)
    return load_tse_retail_columns().get(key, {})


def get_tse_required_columns_for_retailer(product_line, retailer):
    """Return active required columns for a TSE retailer."""
    retailer_key = str(retailer or '').strip().lower()
    for config in get_tse_retailer_columns(product_line).values():
        if config['retailer'] == retailer_key:
            return list(config['required_columns'])
    return []


def get_editable_columns(product_line, retailer):
    """
    리테일러별 수정 가능 컬럼 목록 반환

    Args:
        product_line: 'tv' 또는 'hhp'
        retailer: 'Amazon', 'Bestbuy', 'Walmart'

    Returns:
        list: ['screen_size', 'item', ...] 수정 가능 컬럼명 목록
    """
    try:
        query = """
            SELECT column_name
            FROM monitoring_retail_columns
            WHERE product_line = %s AND LOWER(retailer) = LOWER(%s)
                  AND is_editable = TRUE AND is_active = TRUE
            ORDER BY id
        """
        rows = execute_dx_query(query, (product_line.lower(), retailer.lower()))
        return [row['column_name'] for row in rows]
    except Exception as e:
        log_error(e, 'db')
        return []


def get_retailer_list():
    """
    리테일러 목록 반환

    Returns:
        list: ['Amazon', 'Bestbuy', 'Walmart']
    """
    # 현재 지원하는 리테일러 목록 (DB 컬럼명과 매핑)
    return ['Amazon', 'Bestbuy', 'Walmart']


def get_retail_duplicate_keys(product_line):
    """
    특정 제품라인(tv/hhp)의 중복검증 키 컬럼 목록 반환 (duplicate_key=TRUE인 컬럼)

    Args:
        product_line: 'tv' 또는 'hhp'

    Returns:
        list: ['item', 'account_name'] 등 중복키 컬럼 목록
    """
    try:
        query = """
            SELECT DISTINCT column_name
            FROM monitoring_retail_columns
            WHERE product_line = %s AND duplicate_key = TRUE AND is_active = TRUE
            ORDER BY column_name
        """
        rows = execute_dx_query(query, (product_line.lower(),))
        return [row['column_name'] for row in rows]
    except Exception as e:
        log_error(e, 'db')
        return ['item', 'account_name']  # 기본값


def get_retail_columns_for_retailer(product_line, retailer):
    """
    특정 제품라인/리테일러의 컬럼 목록 반환 (skip_missing_check 제외)

    Args:
        product_line: 'tv' 또는 'hhp'
        retailer: 'Amazon', 'Bestbuy', 'Walmart'

    Returns:
        list: 컬럼명 목록 (skip_missing_check=FALSE인 것만)
    """
    try:
        query = """
            SELECT column_name
            FROM monitoring_retail_columns
            WHERE product_line = %s AND retailer = %s
                  AND skip_missing_check = FALSE AND is_active = TRUE
            ORDER BY id
        """
        rows = execute_dx_query(query, (product_line.lower(), retailer.lower()))
        return [row['column_name'] for row in rows]
    except Exception as e:
        log_error(e, 'db')
        return []


def get_retail_columns_with_related(product_line, retailer):
    """
    특정 제품라인/리테일러의 컬럼 목록과 related_columns 반환

    Args:
        product_line: 'tv' 또는 'hhp'
        retailer: 'Amazon', 'Bestbuy', 'Walmart'

    Returns:
        list of dict: [{'column_name': 'screen_size', 'related_columns': 'retailer_sku_name'}, ...]
    """
    try:
        query = """
            SELECT column_name, related_columns
            FROM monitoring_retail_columns
            WHERE product_line = %s AND retailer = %s AND is_active = TRUE
            ORDER BY id
        """
        rows = execute_dx_query(query, (product_line.lower(), retailer.lower()))
        return [{'column_name': row['column_name'], 'related_columns': row['related_columns'] or ''} for row in rows]
    except Exception as e:
        log_error(e, 'db')
        return []


# ============================================================
# 필드 누락 예외 규칙 (monitoring_missing_exclude_rules)
# 특정 리테일러/필드에서 NULL이 허용되는 조건 관리
# ============================================================

_missing_exclude_cache = None
_missing_exclude_cache_time = None
_MISSING_EXCLUDE_TTL = 60  # 캐시 유효시간 (초)


def load_missing_exclude_rules():
    """
    DB에서 필드 누락 예외 규칙 로드 (60초 TTL 캐시)
    테이블: monitoring_missing_exclude_rules

    Returns: {
        ('Amazon', 'tv_retail_com', 'original_sku_price'): [
            "final_sku_price LIKE 'To see our price%' OR final_sku_price = 'See price in cart'"
        ],
        ...
    }
    """
    global _missing_exclude_cache, _missing_exclude_cache_time

    now = time.time()
    if _missing_exclude_cache is not None and _missing_exclude_cache_time and (now - _missing_exclude_cache_time) < _MISSING_EXCLUDE_TTL:
        return _missing_exclude_cache

    result = {}

    try:
        query = """
            SELECT retailer, table_name, field_name, exclude_condition
            FROM monitoring_missing_exclude_rules
            WHERE is_active = TRUE
            ORDER BY id
        """
        rows = execute_dx_query(query)

        for row in rows:
            key = (row['retailer'], row['table_name'], row['field_name'])
            if key not in result:
                result[key] = []
            result[key].append(row['exclude_condition'])

        _missing_exclude_cache = result
        _missing_exclude_cache_time = now
    except Exception as e:
        log_error(e, 'db')
        result = {}

    return result


def get_missing_exclude_conditions(retailer, table_name, field_name):
    """
    특정 리테일러/테이블/필드의 예외 조건 목록 반환

    Args:
        retailer: 'Amazon', 'Bestbuy', 'Walmart'
        table_name: 'tv_retail_com', 'hhp_retail_com'
        field_name: 'original_sku_price' 등

    Returns:
        list: exclude_condition 문자열 리스트
    """
    rules = load_missing_exclude_rules()
    return rules.get((retailer, table_name, field_name), [])


def reload_missing_exclude_rules():
    """캐시 초기화 후 다시 로드"""
    global _missing_exclude_cache
    _missing_exclude_cache = None
    return load_missing_exclude_rules()


# ============================================================
# 중복검증 관련 함수
# monitoring_retail_columns 테이블의 duplicate_key 사용
# ============================================================

def get_duplicate_key_columns(product_line):
    """
    특정 제품라인(tv/hhp)의 중복검증 키 컬럼 목록 반환

    Args:
        product_line: 'tv' 또는 'hhp'

    Returns:
        list: ['item', 'account_name'] 등 중복키 컬럼 목록
    """
    return get_retail_duplicate_keys(product_line)


def get_duplicate_check_query(product_line, use_period=False):
    """
    특정 제품라인의 중복검증 쿼리 생성

    Args:
        product_line: 'tv' 또는 'hhp'
        use_period: True면 오전/오후 구분 추가

    Returns:
        dict: {
            'table_name': 'tv_retail_com',
            'date_column': 'crawl_datetime',
            'duplicate_keys': ['item', 'account_name'],
            'group_by_sql': 'item, account_name'
        }
    """
    dup_keys = get_retail_duplicate_keys(product_line)
    if not dup_keys:
        return None

    # 테이블명과 날짜 컬럼 결정
    if product_line.lower() == 'tv':
        table_name = 'tv_retail_com'
        date_col = 'crawl_datetime'
    else:
        table_name = 'hhp_retail_com'
        date_col = 'crawl_strdatetime'

    # 오전/오후 구분
    if use_period and date_col:
        period_expr = f"CASE WHEN EXTRACT(HOUR FROM {date_col}::timestamp) < 12 THEN '오전' ELSE '오후' END"
        group_cols = dup_keys + ['period']
        group_by_sql = ', '.join(dup_keys) + f", {period_expr} as period"
    else:
        group_cols = dup_keys
        group_by_sql = ', '.join(dup_keys)

    return {
        'table_name': table_name,
        'date_column': date_col,
        'duplicate_keys': dup_keys,
        'group_by_columns': group_cols,
        'group_by_sql': group_by_sql,
        'use_period': use_period
    }


# ============================================================
# 형식검증 규칙 관련 함수
# ============================================================

import re

def load_format_rules():
    """
    DB에서 형식검증 규칙 로드 (신규 테이블: monitoring_format_rules + monitoring_format_templates)
    DB에 데이터 추가 시 reload_format_rules() 호출하면 즉시 반영

    Returns: {
        'tv_retail_com': {
            'ALL': {
                'item': [
                    {'retailer': 'Amazon', 'type': 'allowed_values', 'rule': '', 'allowed': ['N/A'], 'error': ''},
                    {'retailer': 'Amazon', 'type': 'regex', 'rule': '^[A-Za-z0-9]+$', 'allowed': [], 'error': 'item 형식 오류'},
                    ...
                ],
                ...
            },
        },
        'youtube_videos': {...},
        ...
    }
    """
    global _format_rules_cache, _format_rules_cache_time
    now = time.time()
    if _format_rules_cache is not None and _format_rules_cache_time and (now - _format_rules_cache_time) < _CACHE_TTL:
        return _format_rules_cache

    result = {}

    try:
        tbl_rules = dx_table('monitoring_format_rules')
        tbl_templates = dx_table('monitoring_format_templates')
        query = f"""
            SELECT r.table_name, r.column_name, r.account_name,
                   t.check_type, t.pattern,
                   r.rule_value, r.extra_allowed, r.forbidden_chars,
                   r.error_message
            FROM {tbl_rules} r
            LEFT JOIN {tbl_templates} t ON r.template_id = t.id
            WHERE r.is_active = TRUE AND r.is_del = FALSE
              AND (t.id IS NULL OR t.is_active = TRUE)
            ORDER BY r.id
        """
        rows = execute_dx_query(query)

        for row in rows:
            table_name = row['table_name']
            column_name = row['column_name']
            account_name = row['account_name'] or 'common'
            check_type = row.get('check_type') or ''
            pattern = row.get('pattern') or ''
            rule_value = row.get('rule_value') or ''
            extra_allowed = row.get('extra_allowed') or ''
            forbidden_chars = row.get('forbidden_chars') or ''
            error_message = row.get('error_message') or ''

            # 신규 구조에는 product_line이 없으므로 ALL 사용
            if table_name not in result:
                result[table_name] = {}
            if 'ALL' not in result[table_name]:
                result[table_name]['ALL'] = {}
            if column_name not in result[table_name]['ALL']:
                result[table_name]['ALL'][column_name] = []

            rules_list = result[table_name]['ALL'][column_name]

            # forbidden_chars 파싱
            forbidden_list = [v.strip() for v in forbidden_chars.split('|') if v.strip()] if forbidden_chars else []

            # extra_allowed → allowed_values 규칙 추가
            if extra_allowed:
                allowed_list = [v.strip() for v in extra_allowed.split('|') if v.strip()]
                if allowed_list:
                    rules_list.append({
                        'retailer': account_name,
                        'type': 'allowed_values',
                        'rule': '',
                        'allowed': allowed_list,
                        'forbidden': [],
                        'error': ''
                    })

            # 3. 메인 검증 규칙 (template 기반)
            if check_type:
                if check_type in ('regex', 'regex_clean'):
                    # regex 계열: pattern이 있으면 template 패턴 사용, 없으면 rule_value를 패턴으로 사용 (커스텀 정규식)
                    if pattern:
                        validation_rule = pattern
                        allowed_list = [v.strip() for v in rule_value.split('|') if v.strip()] if rule_value else []
                    else:
                        validation_rule = rule_value
                        allowed_list = []
                elif check_type == 'enum':
                    # enum: rule_value를 파이프 구분 허용값 목록으로 파싱
                    validation_rule = ''
                    allowed_list = [v.strip() for v in rule_value.split('|') if v.strip()] if rule_value else []
                else:
                    # range, range_float, starts_with, min, separator_count, fk_check
                    validation_rule = rule_value
                    allowed_list = []

                rules_list.append({
                    'retailer': account_name,
                    'type': check_type,
                    'rule': validation_rule,
                    'allowed': allowed_list,
                    'forbidden': forbidden_list,
                    'error': error_message
                })

        _format_rules_cache = result
        _format_rules_cache_time = now
    except Exception as e:
        log_error(e, 'db')

    return result


def get_format_rules(table_name, column_name, product_line='ALL'):
    """
    특정 테이블/필드의 형식검증 규칙 목록 반환

    Args:
        table_name: 테이블명 (예: 'tv_retail_com', 'youtube_videos')
        column_name: 필드명
        product_line: 'TV', 'HHP', 'ALL' (기본값 ALL)

    Returns:
        list: 검증 규칙 리스트 또는 빈 리스트
    """
    rules_data = load_format_rules()

    if table_name not in rules_data:
        return []

    table_rules = rules_data[table_name]
    result = []

    # product_line에 해당하는 규칙 추가
    product_key = product_line.upper()
    if product_key in table_rules and column_name in table_rules[product_key]:
        result.extend(table_rules[product_key][column_name])

    # ALL 규칙도 추가 (product_line이 ALL이 아닌 경우)
    if product_key != 'ALL' and 'ALL' in table_rules and column_name in table_rules['ALL']:
        result.extend(table_rules['ALL'][column_name])

    return result


def validate_field(table_name, field_name, value, account_name='Amazon', product_line='ALL', row_context=None):
    """
    CSV 기반 필드 형식 검증

    Args:
        table_name: 테이블명 (예: 'tv_retail_com', 'hhp_retail_com', 'youtube_videos')
        field_name: 필드명
        value: 검증할 값
        account_name: 'Amazon', 'Bestbuy', 'Walmart', 'common' 등
        product_line: 'TV', 'HHP', 'ALL' (기본값 ALL)
        row_context: dict - 행 전체 데이터 (date_compare, conditional_empty 등에서 다른 컬럼 참조용)

    Returns:
        str: 오류 메시지 (오류 시) 또는 None (정상)
    """
    if value is None:
        return None
    val = str(value).strip()
    if val == '':
        return None

    rules = get_format_rules(table_name, field_name, product_line)
    if not rules:
        return None

    # 리테일러별 + ALL 규칙 (순서: retailer → ALL)
    retailer_rules = [r for r in rules if r['retailer'] == account_name]
    all_rules = [r for r in rules if r['retailer'] == 'ALL']

    for rule in retailer_rules + all_rules:
        result = _apply_validation_rule(val, rule, field_name, row_context)
        if result is True:
            return None
        elif result is not None:
            return result

    return None


def _apply_validation_rule(val, rule, field_name, row_context=None):
    """
    개별 검증 규칙 적용

    Returns:
        True: 검증 통과 (더 이상 검사 불필요)
        None: 이 규칙은 해당 안됨 (다음 규칙 검사 필요)
        str: 오류 메시지
    """
    rule_type = rule['type']
    rule_value = rule['rule']
    allowed = rule['allowed']
    forbidden = rule.get('forbidden', [])
    error_msg = rule['error']

    # forbidden_chars 선검사: 금지 문자열 포함 시 즉시 오류
    if forbidden:
        for f in forbidden:
            if f in val:
                return error_msg or f'{field_name} 금지 문자열 포함: {f}'

    # allowed_values: 허용값 목록에 있으면 통과
    if rule_type == 'allowed_values':
        if val in allowed:
            return True
        return None  # 다음 규칙 검사

    # regex: 정규식 패턴 매칭
    if rule_type == 'regex':
        if re.match(rule_value, val):
            return True
        return f'{error_msg}: {val[:20]}' if error_msg else f'{field_name} 형식 오류: {val[:20]}'

    # regex_clean: 전처리 후 정규식 매칭
    if rule_type == 'regex_clean':
        clean_val = val
        clean_type = allowed[0] if allowed else ''

        if 'comma' in clean_type:
            clean_val = clean_val.replace(',', '')
        if 'plus' in clean_type:
            clean_val = clean_val.replace('+', '')
        if 'null' in clean_type:
            if val.lower() in ['null', 'none']:
                return True

        if re.match(rule_value, clean_val):
            return True
        return f'{error_msg}: {val[:20]}' if error_msg else f'{field_name} 형식 오류: {val[:20]}'

    # range: 정수 범위 검증
    if rule_type == 'range':
        try:
            parts = rule_value.split('~')
            min_val, max_val = int(parts[0]), int(parts[1])
            num = int(val)
            if min_val <= num <= max_val:
                return True
            return f'{error_msg}: {val}' if error_msg else f'{field_name} 범위 오류'
        except ValueError:
            return f'{field_name} 숫자 아님: {val}'

    # range_float: 실수 범위 검증
    if rule_type == 'range_float':
        try:
            parts = rule_value.split('~')
            min_val, max_val = float(parts[0]), float(parts[1])
            num = float(val)
            if min_val <= num <= max_val:
                return True
            return f'{error_msg}: {val}' if error_msg else f'{field_name} 범위 오류'
        except ValueError:
            return f'{field_name} 형식 오류: {val[:20]}'

    # enum: 허용값 목록 검증
    if rule_type == 'enum':
        if val in allowed:
            return True
        return f'{error_msg}: {val}' if error_msg else f'{field_name} 허용값 오류: {val[:20]}'

    # starts_with: 시작 문자열 검증
    if rule_type == 'starts_with':
        if val.startswith(rule_value):
            return True
        return error_msg if error_msg else f'{field_name} 시작값 오류: {val[:20]}'

    # separator_count: 구분자 개수 검증 (예: |||~3)
    if rule_type == 'separator_count':
        try:
            parts = rule_value.split('~')
            separator, expected_count = parts[0], int(parts[1])
            actual_count = val.count(separator)
            if actual_count == expected_count:
                return True
            return f'{error_msg}' if error_msg else f'{field_name} 구분자 오류'
        except (ValueError, IndexError):
            return None

    # min: 최솟값 검증
    if rule_type == 'min':
        try:
            min_val = float(rule_value)
            num = float(val)
            if num >= min_val:
                return True
            return f'{error_msg}: {val}' if error_msg else f'{field_name} 최솟값 오류 (>= {rule_value})'
        except ValueError:
            return f'{field_name} 숫자 아님: {val[:20]}'

    # fk_check: FK 참조 검증 (Python에서는 스킵, SQL에서 처리)
    if rule_type == 'fk_check':
        return None

    # date_compare: 날짜 비교 (row_context 있으면 Python 검증)
    if rule_type == 'date_compare':
        if row_context is None:
            return None
        parts = rule_value.split('|')
        other_col = parts[0].strip()
        op = parts[1].strip() if len(parts) > 1 else '<='
        other_val = row_context.get(other_col)
        if not other_val:
            return None
        try:
            from datetime import datetime as _dt
            dt_val = _dt.strptime(str(val)[:19], '%Y-%m-%d %H:%M:%S')
            dt_other = _dt.strptime(str(other_val)[:19], '%Y-%m-%d %H:%M:%S')
            passed = (
                (op == '<=' and dt_val <= dt_other) or
                (op == '>=' and dt_val >= dt_other) or
                (op == '<' and dt_val < dt_other) or
                (op == '>' and dt_val > dt_other)
            )
            if passed:
                return True
            return error_msg or f'{field_name} 날짜 비교 오류 ({op} {other_col})'
        except (ValueError, TypeError):
            return None

    # conditional_empty: 조건부 빈값 (row_context 있으면 Python 검증)
    if rule_type == 'conditional_empty':
        if row_context is None:
            return None
        parts = rule_value.split('|')
        cond = parts[0].strip()
        action = parts[1].strip() if len(parts) > 1 else 'must_empty'
        cond_col, cond_val = cond.split('=', 1)
        actual = str(row_context.get(cond_col.strip(), '') or '').strip()
        if actual != cond_val.strip():
            return True  # 조건 불일치 → 이 규칙 해당 없음 (통과)
        if action == 'must_empty':
            if val:
                return error_msg or f'{field_name}: {cond_col.strip()}={cond_val.strip()}일 때 빈값이어야 함'
            return True
        elif action == 'must_not_empty':
            if not val:
                return error_msg or f'{field_name}: {cond_col.strip()}={cond_val.strip()}일 때 값이 있어야 함'
            return True
        return None

    return None


def reload_format_rules():
    """캐시 초기화 후 다시 로드"""
    global _format_rules_cache
    _format_rules_cache = None
    return load_format_rules()


# ============================================================
# 형식 규칙 → SQL WHERE 조건 변환
# ============================================================

def build_format_error_sql(table_name, product_line='ALL', account_name=None):
    """
    monitoring_format_rules 규칙을 SQL WHERE 조건으로 변환.
    DB에서 오류 행을 직접 필터링할 수 있는 SQL 조건을 생성한다.

    Args:
        table_name: 테이블명 (예: 'tv_retail_com')
        product_line: 'TV', 'HHP', 'ALL'
        account_name: 리테일러명 (예: 'Amazon'). None이면 common 규칙만 사용.

    Returns:
        str: SQL WHERE 조건 (하나라도 오류 필드가 있는 행이면 TRUE)
    """
    rules_cache = load_format_rules()
    table_rules = rules_cache.get(table_name, {})

    # ALL + product_line 규칙 병합
    all_field_rules = table_rules.get('ALL', {})
    pl_field_rules = table_rules.get(product_line, {}) if product_line != 'ALL' else {}

    # 모든 필드 수집
    all_fields = set(list(all_field_rules.keys()) + list(pl_field_rules.keys()))

    field_conditions = []

    for field in sorted(all_fields):
        # 필드별 규칙 수집 (product_line 우선, ALL 보충)
        field_rules = []
        if field in pl_field_rules:
            field_rules.extend(pl_field_rules[field])
        if field in all_field_rules:
            field_rules.extend(all_field_rules[field])

        if not field_rules:
            continue

        # 리테일러별 + ALL 분리 (순서: retailer → ALL)
        if account_name:
            retailer_rules = [r for r in field_rules if r['retailer'] == account_name]
            all_rules = [r for r in field_rules if r['retailer'] == 'ALL']
            ordered = retailer_rules + all_rules
        else:
            ordered = [r for r in field_rules if r['retailer'] == 'ALL']

        # bypass(allowed_values), terminal 규칙, forbidden_chars 분리
        bypass_values = set()
        terminal_rule = None
        forbidden_all = set()

        for rule in ordered:
            rtype = rule['type']
            if rtype == 'allowed_values':
                bypass_values.update(rule['allowed'])
            else:
                if terminal_rule is None:
                    terminal_rule = rule
                # forbidden_chars는 모든 규칙에서 수집
            forbidden_all.update(rule.get('forbidden', []))

        if terminal_rule is None and not forbidden_all:
            continue

        trimmed = f"TRIM({field}::text)"

        # 오류 조건 조합: terminal 실패 OR 금지문자 포함
        error_or_parts = []

        # terminal rule SQL
        if terminal_rule:
            pass_cond = _rule_to_pass_sql(trimmed, terminal_rule)
            if pass_cond:
                error_or_parts.append(f"NOT ({pass_cond})")

        # forbidden_chars SQL: LIKE '%forbidden%'
        for f in sorted(forbidden_all):
            escaped_f = _sql_esc(f).replace('%', '\\%').replace('_', '\\_')
            error_or_parts.append(f"{trimmed} LIKE '%{escaped_f}%'")

        if not error_or_parts:
            continue

        # "오류" 조건 = NOT NULL AND NOT empty AND NOT bypassed AND (terminal 실패 OR 금지문자 포함)
        parts = [f"{field} IS NOT NULL", f"{trimmed} != ''"]

        if bypass_values:
            escaped = ", ".join(f"'{_sql_esc(v)}'" for v in sorted(bypass_values))
            parts.append(f"{trimmed} NOT IN ({escaped})")

        if len(error_or_parts) == 1:
            parts.append(error_or_parts[0])
        else:
            parts.append("(" + " OR ".join(error_or_parts) + ")")

        cond = "(" + " AND ".join(parts) + ")"
        field_conditions.append(cond)

    if not field_conditions:
        return "FALSE"

    # psycopg2가 %를 파라미터 플레이스홀더로 해석하지 않도록 %% 이스케이프
    return (" OR ".join(field_conditions)).replace('%', '%%')


def build_per_field_error_sql(table_name, product_line='ALL', account_name=None):
    """
    필드별 오류 조건 SQL과 에러 메시지를 반환한다.
    format_detail 상세보기에서 SQL로 오류 필드를 식별하기 위해 사용.

    Returns:
        list of dict: [{'field': 'published_at', 'cond': 'NOT NULL AND ... AND NOT(...)', 'error': '에러메시지'}, ...]
    """
    rules_cache = load_format_rules()
    table_rules = rules_cache.get(table_name, {})

    all_field_rules = table_rules.get('ALL', {})
    pl_field_rules = table_rules.get(product_line, {}) if product_line != 'ALL' else {}
    all_fields = set(list(all_field_rules.keys()) + list(pl_field_rules.keys()))

    result = []

    for field in sorted(all_fields):
        field_rules = []
        if field in pl_field_rules:
            field_rules.extend(pl_field_rules[field])
        if field in all_field_rules:
            field_rules.extend(all_field_rules[field])
        if not field_rules:
            continue

        if account_name:
            retailer_rules = [r for r in field_rules if r['retailer'] == account_name]
            all_rules = [r for r in field_rules if r['retailer'] == 'ALL']
            ordered = retailer_rules + all_rules
        else:
            ordered = [r for r in field_rules if r['retailer'] == 'ALL']

        bypass_values = set()
        terminal_rule = None
        forbidden_all = set()
        error_msg = ''

        for rule in ordered:
            rtype = rule['type']
            if rtype == 'allowed_values':
                bypass_values.update(rule['allowed'])
            else:
                if terminal_rule is None:
                    terminal_rule = rule
                    error_msg = rule.get('error', '')
            forbidden_all.update(rule.get('forbidden', []))

        if terminal_rule is None and not forbidden_all:
            continue

        trimmed = f"TRIM({field}::text)"
        error_or_parts = []

        if terminal_rule:
            pass_cond = _rule_to_pass_sql(trimmed, terminal_rule)
            if pass_cond:
                error_or_parts.append(f"NOT ({pass_cond})")

        for f in sorted(forbidden_all):
            escaped_f = _sql_esc(f).replace('%', '\\%').replace('_', '\\_')
            error_or_parts.append(f"{trimmed} LIKE '%{escaped_f}%'")

        if not error_or_parts:
            continue

        parts = [f"{field} IS NOT NULL", f"{trimmed} != ''"]
        if bypass_values:
            escaped = ", ".join(f"'{_sql_esc(v)}'" for v in sorted(bypass_values))
            parts.append(f"{trimmed} NOT IN ({escaped})")

        if len(error_or_parts) == 1:
            parts.append(error_or_parts[0])
        else:
            parts.append("(" + " OR ".join(error_or_parts) + ")")

        cond = "(" + " AND ".join(parts) + ")"
        result.append({
            'field': field,
            'cond': cond.replace('%', '%%'),
            'error': error_msg
        })

    return result


def _rule_to_pass_sql(col, rule):
    """
    단일 규칙의 "통과" 조건을 SQL로 변환.
    col은 TRIM(field::text) 형태.
    """
    rtype = rule['type']
    rval = rule['rule']
    allowed = rule['allowed']

    if rtype == 'regex':
        pattern = rval
        # Python re.match는 시작 앵커 → ^가 없으면 추가
        if not pattern.startswith('^'):
            pattern = '^' + pattern
        return f"{col} ~ '{_sql_esc(pattern)}'"

    if rtype == 'regex_clean':
        clean_type = allowed[0] if allowed else ''
        expr = col
        or_parts = []

        if 'comma' in clean_type:
            expr = f"REPLACE({expr}, ',', '')"
        if 'plus' in clean_type:
            expr = f"REPLACE({expr}, '+', '')"
        if 'null' in clean_type:
            or_parts.append(f"LOWER({col}) IN ('null', 'none')")

        pattern = rval
        if not pattern.startswith('^'):
            pattern = '^' + pattern
        or_parts.append(f"{expr} ~ '{_sql_esc(pattern)}'")
        return " OR ".join(or_parts)

    if rtype == 'range':
        parts = rval.split('~')
        if len(parts) != 2:
            return None
        min_v, max_v = parts[0].strip(), parts[1].strip()
        return f"({col} ~ '^-?[0-9]+$' AND {col}::bigint BETWEEN {min_v} AND {max_v})"

    if rtype == 'range_float':
        parts = rval.split('~')
        if len(parts) != 2:
            return None
        min_v, max_v = parts[0].strip(), parts[1].strip()
        return f"({col} ~ '^-?[0-9]+(\\.[0-9]+)?$' AND {col}::numeric BETWEEN {min_v} AND {max_v})"

    if rtype == 'enum':
        if not allowed:
            return None
        escaped = ", ".join(f"'{_sql_esc(v)}'" for v in allowed)
        return f"{col} IN ({escaped})"

    if rtype == 'starts_with':
        escaped = _sql_esc(rval).replace('%', '\\%').replace('_', '\\_')
        return f"{col} LIKE '{escaped}%'"

    if rtype == 'separator_count':
        parts = rval.split('~')
        if len(parts) != 2:
            return None
        sep = parts[0]
        try:
            expected = int(parts[1])
        except ValueError:
            return None
        sep_len = len(sep)
        if sep_len == 0:
            return None
        escaped_sep = _sql_esc(sep)
        return f"(LENGTH({col}) - LENGTH(REPLACE({col}, '{escaped_sep}', ''))) / {sep_len} = {expected}"

    if rtype == 'min':
        try:
            min_v = float(rval)
        except ValueError:
            return None
        return f"({col} ~ '^-?[0-9]+(\\.[0-9]+)?$' AND {col}::numeric >= {min_v})"

    # fk_check: FK 참조 검증
    # rule_value 형식:
    #   "ref_table.ref_column"
    #   "ref_table.ref_column|key=value"
    #   "ref_table.ref_column|key1=val1&key2=val2"  (다중 조건)
    #   "ref_table.ref_column|latest_batch"          (최신 batch_id)
    #   "ref_table.ref_column~lower_underscore"      (LOWER + 공백→_ 변환)
    if rtype == 'fk_check':
        # ~transform 분리
        transform = ''
        rval_main = rval
        if '~' in rval:
            rval_main, transform = rval.rsplit('~', 1)
            transform = transform.strip()

        parts = rval_main.split('|')
        ref_parts = parts[0].split('.')
        if len(ref_parts) != 2:
            return None
        ref_table, ref_col = ref_parts[0].strip(), ref_parts[1].strip()
        condition = parts[1].strip() if len(parts) > 1 else ''
        where_extra = ''
        if condition == 'latest_batch':
            where_extra = f" AND batch_id = (SELECT MAX(batch_id) FROM {ref_table})"
        elif condition and '&' in condition:
            cond_parts = condition.split('&')
            for cp in cond_parts:
                if '=' in cp:
                    cond_col, cond_val = cp.split('=', 1)
                    where_extra += f" AND {cond_col.strip()} = '{_sql_esc(cond_val.strip())}'"
        elif condition and '=' in condition:
            cond_col, cond_val = condition.split('=', 1)
            where_extra = f" AND {cond_col.strip()} = '{_sql_esc(cond_val.strip())}'"
        elif condition:
            where_extra = f" AND {condition}"

        # 참조 컬럼에 변환 적용
        select_expr = f"{ref_col}::text"
        if transform == 'lower_underscore':
            select_expr = f"LOWER(REPLACE({ref_col}, ' ', '_'))::text"

        return f"{col} IN (SELECT {select_expr} FROM {ref_table} WHERE {ref_col} IS NOT NULL{where_extra})"

    # date_compare: 날짜 비교 (예: "<=created_at")
    if rtype == 'date_compare':
        # rval 예: "<=created_at"
        import re as _re
        m = _re.match(r'^([<>=!]+)(\w+)$', rval)
        if not m:
            return None
        op, target_col = m.group(1), m.group(2)
        return f"{col}::timestamp {op} {target_col}::timestamp"

    # conditional_empty: 조건이 참일 때 빈값이어야 함 (예: "comment_type=top_level")
    if rtype == 'conditional_empty':
        # rval 예: "comment_type=top_level" → comment_type이 top_level이면 이 필드는 빈값이어야 함
        eq_parts = rval.split('=')
        if len(eq_parts) != 2:
            return None
        cond_col, cond_val = eq_parts[0].strip(), eq_parts[1].strip()
        # "통과" = 조건 해당 시 빈값이거나, 조건 비해당
        return f"(TRIM({cond_col}::text) != '{_sql_esc(cond_val)}' OR {col} IS NULL OR {col}::text = '')"

    return None


def _sql_esc(s):
    """SQL 문자열 리터럴 내 작은따옴표 이스케이프"""
    return s.replace("'", "''")
