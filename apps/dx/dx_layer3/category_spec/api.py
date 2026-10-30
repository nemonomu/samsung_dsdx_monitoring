"""
Layer 3 카테고리별 특성 API
"""

from django.http import JsonResponse
from datetime import datetime, timedelta
from apps.common.db import dx_connection
from apps.common.response import safe_error, log_error
from . import services
from .dates import rule_date_mapping


def category_spec_detail(request):
    """카테고리별 특성 상세 API - 규칙별 요약 또는 상세 데이터

    Parameters:
        - display_name: 화면 표시 이름 (TV 카테고리 특성, Forecast 등)
        - type: 하위호환용 (tv, hhp)
        - mode: summary면 규칙별 요약, 없으면 상세 데이터
        - rule_id: 특정 규칙의 상세 데이터
    """
    date_str = request.GET.get('date')
    display_name = request.GET.get('display_name', '')
    product_line = request.GET.get('type', '')  # 하위호환
    mode = request.GET.get('mode', '')  # summary: 규칙별 요약
    rule_id = request.GET.get('rule_id', '')  # 특정 규칙 상세

    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        target_category, rules = services.resolve_target_category(display_name, product_line)

        with dx_connection() as (conn, cursor):
            # mode=summary: 규칙별 요약 반환
            if mode == 'summary':
                rules_summary = services.get_rules_summary(cursor, target_date, target_category, rules)

                total_checked = sum(r['total'] for r in rules_summary)
                total_anomalies = sum(r['anomaly'] for r in rules_summary)

                return JsonResponse({
                    'date': str(target_date),
                    **rule_date_mapping(target_date, 'tv_retail_com' if target_category == 'tv_retail' else ''),
                    'product_line': display_name or target_category.upper(),
                    'total_checked': total_checked,
                    'total_anomalies': total_anomalies,
                    'rule_summary': rules_summary
                })

            # rule_id로 상세 데이터 조회
            target_rule, anomalies, display_columns, table_name, check_type, is_master_table, retailer_data = \
                services.get_rule_detail(cursor, target_date, rule_id, product_line, rules)

            if target_rule is None:
                return JsonResponse({'error': '규칙을 찾을 수 없습니다.', 'anomalies': []})

            if anomalies is None:
                return JsonResponse({'error': '쿼리가 정의되지 않았습니다.', 'anomalies': []})

            if anomalies == 'invalid_query':
                return JsonResponse({'status': 'error', 'message': '허용되지 않은 쿼리 유형'})

            return JsonResponse({
                'date': str(target_date),
                **rule_date_mapping(target_date, table_name),
                'product_line': target_rule.get('product_line', product_line).upper(),
                'check_type': check_type,
                'total_anomalies': len(anomalies),
                'display_columns': display_columns,
                'table_name': table_name,
                'anomalies': anomalies,
                'is_master_table': is_master_table,
                'retailer_data': retailer_data,
                'retailer_counts': {k: len(v) for k, v in retailer_data.items()}
            })

    except Exception as e:
        log_error(e)
        return safe_error(e, anomalies=[])


def category_rules(request):
    """카테고리별 특성 검증 규칙 목록 API (DB 기반)

    Parameters:
        - section: section_code로 필터링 (tv_retail, hhp_retail, market_forecast 등)
        - display_name: 화면 표시 이름으로 필터링 (TV 카테고리 특성, Forecast 등)
    """
    section_param = request.GET.get('section', request.GET.get('category', ''))
    display_name = request.GET.get('display_name', '')

    try:
        filtered_rules, resolved_section = services.get_filtered_rules(section_param, display_name)

        return JsonResponse({
            'status': 'success',
            'section': resolved_section or 'all',
            'total_rules': len(filtered_rules),
            'rules': filtered_rules
        })

    except Exception as e:
        log_error(e)
        return JsonResponse({'status': 'error', 'message': '처리 중 오류가 발생했습니다.'})
