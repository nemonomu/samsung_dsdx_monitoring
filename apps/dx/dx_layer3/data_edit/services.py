"""
Layer3 셀 수정 / 정상 처리 서비스 — 순수 비즈니스 로직
"""

from datetime import datetime
import re
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.retail_columns import get_editable_columns
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.retail_validation import get_tv_validation_condition
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.common.siel_retail import (
    SIEL_BUSINESS_TIMEZONE,
    SIEL_TABLE_TO_PRODUCT_LINE,
    get_siel_crossfield_editable_columns,
    get_siel_product_line_for_table,
    get_siel_source,
)
from apps.common.tse_retail import (
    TSE_TABLE_TO_PRODUCT_LINE,
    get_tse_product_line_for_table,
    validate_tse_editable_column,
)


VALID_TABLES_UPDATE = {
    'tv_retail_com',
    'ref_retail_com', 'ldy_retail_com',
    'public.ref_retail_com', 'public.ldy_retail_com',
    'youtube_collection_logs', 'youtube_videos', 'youtube_comments',
    'market_trend', 'market_comp_product', 'market_comp_event', 'openai_forecast_results',
} - DISABLED_SOURCE_TABLES
VALID_TABLES_UPDATE.update(TSE_TABLE_TO_PRODUCT_LINE)
VALID_TABLES_UPDATE.update(SIEL_TABLE_TO_PRODUCT_LINE)

SIEL_CROSSFIELD_REVIEW_COLUMNS = frozenset({
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
    'detailed_review_content', 'final_sku_price', 'original_sku_price',
    'savings', 'page_type', 'main_rank', 'bsr_rank',
})


def _is_tse_table(table_name):
    return table_name in TSE_TABLE_TO_PRODUCT_LINE


def _is_siel_table(table_name):
    return table_name in SIEL_TABLE_TO_PRODUCT_LINE


def _get_sea_edit_context(table_name):
    table_basename = str(table_name or '').strip().lower().split('.')[-1]
    for product_key in ('ref', 'ldy'):
        source = SEA_RETAIL_SOURCES[product_key]
        source_basename = source['table_name'].lower().split('.')[-1]
        if table_basename == source_basename:
            return source
    return None


def _get_siel_edit_context(table_name):
    if not _is_siel_table(table_name):
        return None
    product_line = get_siel_product_line_for_table(table_name)
    return get_siel_source(product_line)


def _get_product_line(table_name):
    if _is_tse_table(table_name):
        return get_tse_product_line_for_table(table_name)
    if _is_siel_table(table_name):
        return get_siel_product_line_for_table(table_name)
    sea_context = _get_sea_edit_context(table_name)
    if sea_context:
        return sea_context['product_line']
    return 'tv' if table_name == 'tv_retail_com' else 'hhp'


def _select_sea_record(
        cursor, source, select_columns, row_id, inspection_date):
    date_contract = resolve_monitoring_date(
        inspection_date, 'SEA', source['source_key']
    )
    table_name = source['table_name']
    date_column = source['date_column']
    cursor.execute(f"""
        SELECT {select_columns}
        FROM {table_name} source
        WHERE source.id = %s
          AND LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10) = %s
          AND UPPER(TRIM(COALESCE(source.page_type, '')))
              IN ('MAIN', 'BSR')
          AND source.batch_id = (
              SELECT anchor.batch_id
              FROM {table_name} anchor
              WHERE LEFT(TRIM(CAST(anchor.{date_column} AS TEXT)), 10) = %s
                AND LOWER(TRIM(anchor.account_name)) =
                    LOWER(TRIM(source.account_name))
                AND UPPER(TRIM(COALESCE(anchor.page_type, ''))) = 'MAIN'
              ORDER BY anchor.id DESC
              LIMIT 1
          )
    """, (
        row_id, date_contract['source_date'], date_contract['source_date'],
    ))


def _select_siel_record(
        cursor, source, select_columns, row_id, inspection_date):
    date_contract = resolve_monitoring_date(
        inspection_date, 'SIEL', source['source_key']
    )
    table_name = source['table_name']
    date_column = source['date_column']
    source_date = date_contract['source_date']
    cursor.execute(f"""
        SELECT {select_columns}
        FROM {table_name} source
        WHERE source.id = %s
          AND source.{date_column} >= (
                %s::date::timestamp AT TIME ZONE '{SIEL_BUSINESS_TIMEZONE}'
              )
          AND source.{date_column} < (
                (%s::date + 1)::timestamp AT TIME ZONE
                '{SIEL_BUSINESS_TIMEZONE}'
              )
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT)))
              IN ('main', 'bsr')
          AND {get_tv_validation_condition('source')}
          AND source.batch_id IS NOT DISTINCT FROM (
              SELECT anchor.batch_id
              FROM {table_name} anchor
              WHERE anchor.{date_column} >= (
                        %s::date::timestamp AT TIME ZONE
                        '{SIEL_BUSINESS_TIMEZONE}'
                    )
                AND anchor.{date_column} < (
                        (%s::date + 1)::timestamp AT TIME ZONE
                        '{SIEL_BUSINESS_TIMEZONE}'
                    )
                AND LOWER(BTRIM(CAST(anchor.account_name AS TEXT))) =
                    LOWER(BTRIM(CAST(source.account_name AS TEXT)))
                AND LOWER(BTRIM(CAST(anchor.page_type AS TEXT))) = 'main'
                AND {get_tv_validation_condition('anchor')}
              ORDER BY anchor.id DESC
              LIMIT 1
          )
    """, (
        row_id, source_date, source_date, source_date, source_date,
    ))


def _validate_edit_target(table_name, column_name):
    """Validate dynamic SQL identifiers at the service boundary as well."""
    if table_name not in VALID_TABLES_UPDATE:
        return {'error': '허용되지 않는 테이블', 'status': 400}
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(column_name or '')):
        return {'error': '잘못된 컬럼명', 'status': 400}
    return None


def _validate_tse_column(table_name, column_name):
    if _is_tse_table(table_name):
        product_line = get_tse_product_line_for_table(table_name)
        validate_tse_editable_column(product_line, column_name)


def _check_tse_unique_key(
        cursor, table_name, row_id, column_name, new_value,
        batch_id, retailer, item_value):
    """Protect the source ``(account_name, batch_id, item)`` unique key."""
    if not _is_tse_table(table_name) or column_name not in ('account_name', 'item'):
        return None

    target_retailer = new_value if column_name == 'account_name' else retailer
    target_item = new_value if column_name == 'item' else item_value
    cursor.execute(f"""
        SELECT id
        FROM {table_name}
        WHERE account_name IS NOT DISTINCT FROM %s
          AND batch_id IS NOT DISTINCT FROM %s
          AND item IS NOT DISTINCT FROM %s
          AND id <> %s
        LIMIT 1
    """, (target_retailer, batch_id, target_item, row_id))
    if cursor.fetchone():
        return {
            'error': '동일 리테일러·배치·item 레코드가 이미 존재합니다',
            'status': 409,
        }
    return None


def update_cell_value(cursor, conn, table_name, row_id, column_name, new_value,
                      crawl_date, correction_type, username, memo, rule_id=None):
    """셀 값 수정"""
    invalid_target = _validate_edit_target(table_name, column_name)
    if invalid_target:
        return invalid_target
    product_line = _get_product_line(table_name)
    sea_context = _get_sea_edit_context(table_name)
    siel_context = _get_siel_edit_context(table_name)
    if sea_context:
        table_name = sea_context['table_name']
    elif siel_context:
        table_name = siel_context['table_name']

    try:
        _validate_tse_column(table_name, column_name)
    except ValueError as exc:
        return {'error': str(exc), 'status': 403}

    select_columns = (
        f"{column_name}, batch_id, account_name, item"
        if _is_tse_table(table_name)
        else f"{column_name}, NULL AS batch_id, account_name, item"
    )
    if _is_tse_table(table_name):
        cursor.execute(f"""
            SELECT {select_columns}
            FROM {table_name}
            WHERE id = %s
              AND country = 'TSE'
              AND LEFT(TRIM(crawl_datetime), 10) = %s
        """, (row_id, str(crawl_date)))
    elif sea_context:
        _select_sea_record(
            cursor, sea_context, select_columns, row_id, crawl_date
        )
    elif siel_context:
        _select_siel_record(
            cursor, siel_context, select_columns, row_id, crawl_date
        )
    else:
        cursor.execute(
            f"SELECT {select_columns} FROM {table_name} WHERE id = %s",
            (row_id,),
        )
    row = cursor.fetchone()
    if not row:
        return {'error': '해당 레코드가 없습니다', 'status': 404}

    old_value = row[0]
    batch_id = row[1]
    retailer = row[2]
    item_value = str(row[3]) if row[3] else ''

    editable_cols = (
        get_siel_crossfield_editable_columns(product_line, retailer)
        if siel_context else
        get_editable_columns(product_line, retailer)
    )
    if column_name not in editable_cols:
        return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}

    old_str = str(old_value) if old_value is not None else ''
    new_str = str(new_value) if new_value is not None else ''
    if old_str == new_str:
        return {'success': True, 'message': '변경 없음'}

    conflict = _check_tse_unique_key(
        cursor, table_name, row_id, column_name, new_value,
        batch_id, retailer, item_value,
    )
    if conflict:
        return conflict

    update_value = new_value if new_value != '' else None
    try:
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
    except Exception:
        conn.rollback()
        raise
    return {'success': True, 'old_value': old_str, 'new_value': new_str}


def save_review(cursor, conn, table_name, record_id, column_name,
                status, memo, reason, crawl_date, correction_type, username, rule_id=None):
    """크로스필드/누락필드 정상 처리"""
    invalid_target = _validate_edit_target(table_name, column_name)
    if invalid_target:
        return invalid_target
    product_line = _get_product_line(table_name)
    sea_context = _get_sea_edit_context(table_name)
    siel_context = _get_siel_edit_context(table_name)
    if sea_context:
        table_name = sea_context['table_name']
    elif siel_context:
        table_name = siel_context['table_name']
    try:
        _validate_tse_column(table_name, column_name)
    except ValueError as exc:
        return {'error': str(exc), 'status': 403}

    if _is_tse_table(table_name):
        cursor.execute(f"""
            SELECT {column_name}, account_name, item
            FROM {table_name}
            WHERE id = %s
              AND country = 'TSE'
              AND LEFT(TRIM(crawl_datetime), 10) = %s
        """, (record_id, str(crawl_date)))
    elif sea_context:
        _select_sea_record(
            cursor, sea_context,
            f'{column_name}, account_name, item', record_id, crawl_date,
        )
    elif siel_context:
        _select_siel_record(
            cursor, siel_context,
            f'{column_name}, account_name, item', record_id, crawl_date,
        )
    else:
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

    if _is_tse_table(table_name):
        editable_cols = get_editable_columns(product_line, retailer)
        if column_name not in editable_cols:
            return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}

    if siel_context:
        is_crossfield_confirmation = (
            status == 'normal' and correction_type == 'cross_field'
        )
        if is_crossfield_confirmation:
            if column_name not in SIEL_CROSSFIELD_REVIEW_COLUMNS:
                return {
                    'error': f'{column_name} 컬럼은 정상 확인할 수 없습니다',
                    'status': 403,
                }
        else:
            editable_cols = get_editable_columns(product_line, retailer)
            if column_name not in editable_cols:
                return {
                    'error': f'{column_name} 컬럼은 수정할 수 없습니다',
                    'status': 403,
                }

    if siel_context and status == 'normal' and not str(memo or '').strip():
        return {
            'error': 'SIEL 크로스필드 확인 메모는 필수입니다',
            'status': 400,
        }

    # 중복 정상처리 체크
    cursor.execute("""
        SELECT id FROM monitoring_corrections
        WHERE table_name = %s AND record_id = %s AND column_name = %s
          AND correction_type = %s AND status = 'normal' AND crawl_date = %s
    """, (table_name, record_id, column_name, correction_type, str(crawl_date)))
    if cursor.fetchone():
        return {'error': '이미 정상처리된 항목입니다', 'status': 400}

    try:
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
    except Exception:
        conn.rollback()
        raise
    return {'success': True, 'status': status}


def get_review_reasons(check_type):
    """정상 처리 이유 목록"""
    from apps.common.constants import get_reasons
    reasons = [{'text': r} for r in get_reasons(check_type)]
    return {'success': True, 'reasons': reasons}
