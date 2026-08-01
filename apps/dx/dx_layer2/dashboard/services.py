"""
Layer 2 Dashboard: 비즈니스 로직
- get_layer_stats: 각 메뉴 서비스의 stats 함수를 호출하는 오케스트레이터
- get_retailer_detail: 리테일러별 상세 오류 데이터
"""

from datetime import datetime
from apps.common.retail_columns import validate_field
from apps.common.response import log_error
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer2.common.context import get_status
from apps.dx.dx_layer2.null_validation.services import get_null_stats
from apps.dx.dx_layer2.format_validation.services import (
    get_format_stats, get_tv_format_errors,
    validate_tv_field,
)
from apps.dx.dx_layer2.anomaly_validation.services import get_anomaly_stats


# ── 화이트리스트 상수 ──────────────────────────────────────────
VALID_TABLES_RETAILER = {'TV Retail'}


def _run_with_youtube_fallback(
    cursor, target_date, stats_func, savepoint_name
):
    """YouTube SQL 실패 시 트랜잭션을 복구하고 기존 검수만 재조회한다."""
    cursor.execute(f'SAVEPOINT {savepoint_name}')
    try:
        result = stats_func(cursor, target_date)
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint_name}')
        log_error(exc)
        return stats_func(cursor, target_date, include_youtube=False)

    cursor.execute(f'RELEASE SAVEPOINT {savepoint_name}')
    return result


# ══════════════════════════════════════════════════════════════
# 메인 서비스 함수
# ══════════════════════════════════════════════════════════════

def get_layer_stats(cursor, target_date):
    """
    Layer 2 통계 — 각 메뉴 서비스의 stats 함수를 호출하여 집계.
    cursor와 target_date만 받으며, HTTP 의존성 없음.
    """
    results = {
        'timestamp': datetime.now().isoformat(),
        'date': str(target_date),
        'layer': 2,
        'name': '형식/NULL 검수',
        'validation_types': [],
        'summary': {
            'total_issues': 0,
            'null_issues': 0,
            'format_issues': 0,
            'duplicate_issues': 0,
            'overall_status': 'OK'
        }
    }

    # 1. NULL 검증
    null_validation, total_null_issues = _run_with_youtube_fallback(
        cursor,
        target_date,
        get_null_stats,
        'layer2_youtube_null_stats',
    )
    results['validation_types'].append(null_validation)

    # 2. 형식 검증
    format_validation, total_format_issues = get_format_stats(cursor, target_date)
    results['validation_types'].append(format_validation)

    # 3. 중복 검증
    anomaly_validation, total_anomaly_issues = _run_with_youtube_fallback(
        cursor,
        target_date,
        get_anomaly_stats,
        'layer2_youtube_anomaly_stats',
    )
    results['validation_types'].append(anomaly_validation)

    # Summary 계산
    total_issues = total_null_issues + total_format_issues + total_anomaly_issues
    results['summary'] = {
        'total_issues': total_issues,
        'null_issues': total_null_issues,
        'format_issues': total_format_issues,
        'duplicate_issues': total_anomaly_issues,
        'overall_status': 'OK' if total_issues == 0 else 'CRITICAL'
    }

    return results


def get_retailer_detail(cursor, validation_type, table_name, retailer, target_date):
    """
    리테일러별 상세 오류 데이터 조회. dict 반환 (HTTP 의존성 없음).
    """
    results = {
        'type': validation_type,
        'table': table_name,
        'retailer': retailer,
        'date': str(target_date),
        'records': [],
        'total': 0
    }

    # 테이블명 및 날짜 필드 결정
    if table_name == 'TV Retail':
        db_table = 'tv_retail_com'
        date_field = 'crawl_datetime'
        null_fields = ['item', 'screen_size', 'final_sku_price', 'retailer_sku_name',
                      'count_of_reviews', 'star_rating', 'count_of_star_ratings']
    elif False:
        db_table = 'hhp_retail_com'
        date_field = 'crawl_strdatetime'
        null_fields = ['item', 'final_sku_price', 'retailer_sku_name',
                      'count_of_reviews', 'star_rating', 'count_of_star_ratings']
    else:
        results['error'] = '잘못된 테이블 파라미터'
        return results

    if validation_type == 'null':
        # NULL 검증 상세 - 필수값 NULL인 레코드 조회
        null_conditions = ' OR '.join([f"({f} IS NULL OR {f} = '')" for f in null_fields])

        cursor.execute(f"""
            SELECT id, item, {date_field}, product_url,
                   {', '.join([f"CASE WHEN {f} IS NULL OR {f} = '' THEN 1 ELSE 0 END as null_{f}" for f in null_fields])}
            FROM {db_table}
            WHERE DATE({date_field}::timestamp) = %s
              AND account_name = %s
              AND {get_tv_validation_condition()}
              AND ({null_conditions})
            ORDER BY id
        """, (target_date, retailer))

        rows = cursor.fetchall()

        for row in rows:
            record_id = row[0]
            item = row[1]
            crawl_dt = row[2]
            product_url = row[3]

            # NULL인 필드들 찾기
            null_field_list = []
            for i, field in enumerate(null_fields):
                if row[4 + i] == 1:
                    null_field_list.append(field)

            results['records'].append({
                'id': record_id,
                'item': item,
                'product_url': product_url,
                'null_fields': null_field_list,
                'collected_at': str(crawl_dt) if crawl_dt else None
            })

        # 총 개수 조회
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM {db_table}
            WHERE DATE({date_field}::timestamp) = %s
              AND account_name = %s
              AND {get_tv_validation_condition()}
              AND ({null_conditions})
        """, (target_date, retailer))
        results['total'] = cursor.fetchone()[0]

    elif validation_type == 'format':
        # 형식 검증 상세 - TV와 HHP에 맞는 형식 오류 조회
        if table_name == 'TV Retail':
            format_errors = get_tv_format_errors(cursor, db_table, date_field, target_date, retailer)
        else:
            format_errors = get_hhp_format_errors(cursor, db_table, date_field, target_date, retailer)

        results['records'] = format_errors
        results['total'] = len(format_errors)

    elif validation_type == 'anomaly':
        # 이상치 검증 상세 - 중복 레코드 조회
        cursor.execute(f"""
            SELECT item, COUNT(*) as cnt
            FROM {db_table}
            WHERE DATE({date_field}::timestamp) = %s
              AND account_name = %s
              AND {get_tv_validation_condition()}
            GROUP BY item
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
        """, (target_date, retailer))

        rows = cursor.fetchall()
        for row in rows:
            results['records'].append({
                'id': '-',
                'item': row[0],
                'duplicate_type': f'중복 {row[1]}건',
                'collected_at': str(target_date)
            })

        results['total'] = len(rows)

    return results
