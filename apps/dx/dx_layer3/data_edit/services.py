"""
Layer3 셀 수정 / 정상 처리 서비스 — 순수 비즈니스 로직
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
                      crawl_date, correction_type, username, memo, rule_id=None):
    """셀 값 수정"""
    product_line = 'tv' if table_name == 'tv_retail_com' else 'hhp'

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

    editable_cols = get_editable_columns(product_line, retailer)
    if column_name not in editable_cols:
        return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}

    old_str = str(old_value) if old_value is not None else ''
    new_str = str(new_value) if new_value is not None else ''
    if old_str == new_str:
        return {'success': True, 'message': '변경 없음'}

    update_value = new_value if new_value != '' else None
    cursor.execute(
        f"UPDATE {table_name} SET {column_name} = %s WHERE id = %s",
        (update_value, row_id)
    )

    now = datetime.now()
    cursor.execute("""
        INSERT INTO monitoring_corrections
            (layer, correction_type, table_name, record_id, column_name,
             old_value, new_value, crawl_date, created_id, created_at, status, memo, retailer, item, rule_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        3, correction_type, table_name, row_id, column_name,
        str(old_value) if old_value is not None else None,
        str(new_value) if new_value is not None else None,
        crawl_date, username, now, 'corrected', memo, retailer, item_value or None, rule_id
    ))

    conn.commit()
    return {'success': True, 'old_value': old_str, 'new_value': new_str}


def save_review(cursor, conn, table_name, record_id, column_name,
                status, memo, reason, crawl_date, correction_type, username, rule_id=None):
    """크로스필드/누락필드 정상 처리"""
    cursor.execute(
        f"SELECT {column_name}, account_name, item FROM {table_name} WHERE id = %s",
        (record_id,)
    )
    row = cursor.fetchone()
    if not row:
        return {'error': '해당 레코드가 없습니다', 'status': 404}

    old_value = row[0]
    retailer = row[1]
    item_value = str(row[2]) if row[2] else None

    # 중복 정상처리 체크
    cursor.execute("""
        SELECT id FROM monitoring_corrections
        WHERE table_name = %s AND record_id = %s AND column_name = %s
          AND correction_type = %s AND status = 'normal' AND crawl_date = %s
    """, (table_name, record_id, column_name, correction_type, str(crawl_date)))
    if cursor.fetchone():
        return {'error': '이미 정상처리된 항목입니다', 'status': 400}

    now = datetime.now()
    cursor.execute("""
        INSERT INTO monitoring_corrections
            (layer, correction_type, table_name, record_id, column_name,
             old_value, new_value, crawl_date, created_id, created_at, status, memo, reason, retailer, item, rule_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        3, correction_type, table_name, record_id, column_name,
        str(old_value) if old_value is not None else None,
        None,
        crawl_date, username, now, status, memo or None,
        reason or None, retailer or None, item_value, rule_id
    ))

    conn.commit()
    return {'success': True, 'status': status}


def get_review_reasons(check_type):
    """정상 처리 이유 목록"""
    from apps.common.constants import get_reasons
    reasons = [{'text': r} for r in get_reasons(check_type)]
    return {'success': True, 'reasons': reasons}
