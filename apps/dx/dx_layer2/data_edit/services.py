"""
data_edit 서비스 — 셀 수정 / 정상 처리 이유 비즈니스 로직
cursor + params 를 받아 plain dict 를 반환한다.
"""

from datetime import datetime
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.retail_columns import get_editable_columns


VALID_TABLES_UPDATE = {
    'tv_retail_com',
    'youtube_collection_logs', 'youtube_videos', 'youtube_comments',
    'market_trend', 'market_comp_product', 'market_comp_event', 'openai_forecast_results',
} - DISABLED_SOURCE_TABLES


def update_cell_value(cursor, conn, table_name, row_id, column_name, new_value,
                      crawl_date, correction_type, username, memo):
    """
    셀 값 수정 — 기존 값 조회 + UPDATE + corrections 이력 저장.
    conn.commit() 는 이 함수 내에서 호출하지 않는다 (api 에서 처리).
    """
    # correction_type 화이트리스트 검증
    valid_correction_types = {'null': 'null_check', 'format': 'format_check', 'duplicate': 'duplicate_check'}
    correction_type_value = valid_correction_types.get(correction_type, 'null_check')

    # product_line 결정
    product_line = 'tv' if table_name == 'tv_retail_com' else 'hhp'

    # 기존 값 + retailer + item 조회
    cursor.execute(
        f"SELECT {column_name}, account_name, item FROM {table_name} WHERE id = %s",
        (row_id,)
    )
    row = cursor.fetchone()
    if not row:
        return {'error': '해당 레코드가 없습니다', 'status': 404}

    old_value = row[0]
    retailer = row[1]
    item_value = str(row[2]) if row[2] else ''

    # editable 컬럼 확인
    editable_cols = get_editable_columns(product_line, retailer)
    if column_name not in editable_cols:
        return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}

    # 값이 같으면 스킵
    old_str = str(old_value) if old_value is not None else ''
    new_str = str(new_value) if new_value is not None else ''
    if old_str == new_str:
        return {'success': True, 'message': '변경 없음'}

    # UPDATE 실행
    update_value = new_value if new_value != '' else None
    cursor.execute(
        f"UPDATE {table_name} SET {column_name} = %s WHERE id = %s",
        (update_value, row_id)
    )

    # monitoring_corrections에 이력 저장
    now = datetime.now()
    cursor.execute("""
        INSERT INTO monitoring_corrections
            (layer, correction_type, table_name, record_id, column_name,
             old_value, new_value, crawl_date, created_id, created_at, status, memo, retailer, item)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        2, correction_type_value, table_name, row_id, column_name,
        str(old_value) if old_value is not None else None,
        str(new_value) if new_value is not None else None,
        crawl_date, username, now, 'corrected', memo, retailer, item_value or None
    ))

    return {'success': True, 'old_value': old_str, 'new_value': new_str}


def get_review_reasons(check_type):
    """정상 처리 이유 목록 조회 — 코드 상수에서 반환"""
    from apps.common.constants import get_reasons
    reasons = [{'text': r} for r in get_reasons(check_type)]
    return {'success': True, 'reasons': reasons}
