"""
data_edit 서비스 — 셀 수정 / 정상 처리 이유 비즈니스 로직
cursor + params 를 받아 plain dict 를 반환한다.
"""

import re
from datetime import datetime
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.retail_columns import get_editable_columns

try:
    from apps.common.retail_validation import get_tv_validation_condition
except (ImportError, AttributeError):
    def get_tv_validation_condition(_alias=None):
        return 'TRUE'

try:
    from apps.common.inspection_dates import resolve_monitoring_date
    from apps.common.sea_retail import SEA_RETAIL_SOURCES
except (ImportError, AttributeError):
    resolve_monitoring_date = None
    SEA_RETAIL_SOURCES = {}

try:
    from apps.common.tse_retail import (
        TSE_TABLE_TO_PRODUCT_LINE,
        get_tse_editable_columns,
        get_tse_product_line_for_table,
        resolve_tse_table,
    )
except (ImportError, AttributeError):
    TSE_TABLE_TO_PRODUCT_LINE = {}
    get_tse_editable_columns = None
    get_tse_product_line_for_table = None
    resolve_tse_table = None

try:
    from apps.common.siel_retail import (
        SIEL_BUSINESS_TIMEZONE,
        SIEL_TABLE_TO_PRODUCT_LINE,
        get_siel_format_editable_columns,
        get_siel_product_line_for_table,
        get_siel_source,
    )
except (ImportError, AttributeError):
    SIEL_BUSINESS_TIMEZONE = 'Asia/Seoul'
    SIEL_TABLE_TO_PRODUCT_LINE = {}
    get_siel_format_editable_columns = None
    get_siel_product_line_for_table = None
    get_siel_source = None


VALID_TABLES_UPDATE = ({
    'tv_retail_com',
    'ref_retail_com', 'ldy_retail_com',
    'public.ref_retail_com', 'public.ldy_retail_com',
    'youtube_collection_logs', 'youtube_videos', 'youtube_comments',
    'market_trend', 'market_comp_product', 'market_comp_event', 'openai_forecast_results',
} | set(TSE_TABLE_TO_PRODUCT_LINE) | set(
    SIEL_TABLE_TO_PRODUCT_LINE
)) - DISABLED_SOURCE_TABLES


def _get_sea_edit_context(table_name):
    """Return fixed SEA REF/LDY edit metadata for a canonical table."""

    if not resolve_monitoring_date:
        return None
    table_basename = str(table_name or '').strip().lower().split('.')[-1]
    for product_key in ('ref', 'ldy'):
        source = SEA_RETAIL_SOURCES.get(product_key)
        source_basename = str(
            source.get('table_name') if source else ''
        ).strip().lower().split('.')[-1]
        if source and source_basename == table_basename:
            return source
    return None


def _get_tse_edit_context(table_name):
    """Return registry-backed TSE edit metadata for a canonical table."""
    if not all((
        get_tse_editable_columns,
        get_tse_product_line_for_table,
        resolve_tse_table,
    )):
        return None
    try:
        canonical_table = resolve_tse_table(table_name)
        product_line = get_tse_product_line_for_table(canonical_table)
        return {
            'table_name': canonical_table,
            'product_line': product_line,
            'max_editable': set(get_tse_editable_columns(product_line)),
        }
    except (ImportError, AttributeError, ValueError):
        return None


def _get_siel_edit_context(table_name):
    """Return registry-backed SIEL edit metadata for a canonical table."""
    if not all((
        get_siel_format_editable_columns,
        get_siel_product_line_for_table,
        get_siel_source,
    )) or table_name not in SIEL_TABLE_TO_PRODUCT_LINE:
        return None
    try:
        product_line = get_siel_product_line_for_table(table_name)
        source = get_siel_source(product_line)
        return {
            'table_name': source['table_name'],
            'product_line': product_line,
            'source': source,
        }
    except (ImportError, AttributeError, ValueError):
        return None


def _select_siel_edit_record(
        cursor, context, select_columns, row_id, inspection_date):
    """Select only the SIEL inspection-day latest MAIN-anchored row."""
    source = context['source']
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


def update_cell_value(cursor, conn, table_name, row_id, column_name, new_value,
                      crawl_date, correction_type, username, memo):
    """
    셀 값 수정 — 기존 값 조회 + UPDATE + corrections 이력 저장.
    conn.commit() 는 이 함수 내에서 호출하지 않는다 (api 에서 처리).
    """
    if table_name not in VALID_TABLES_UPDATE:
        return {'error': '허용되지 않는 테이블', 'status': 400}
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', str(column_name or '')):
        return {'error': '잘못된 컬럼명', 'status': 400}

    # correction_type 화이트리스트 검증
    valid_correction_types = {'null': 'null_check', 'format': 'format_check', 'duplicate': 'duplicate_check'}
    correction_type_value = valid_correction_types.get(correction_type, 'null_check')

    # product_line 결정
    tse_context = _get_tse_edit_context(table_name)
    siel_context = _get_siel_edit_context(table_name)
    sea_context = _get_sea_edit_context(table_name)
    if tse_context:
        table_name = tse_context['table_name']
        product_line = tse_context['product_line']
        if column_name not in tse_context['max_editable']:
            return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}
    elif sea_context:
        table_name = sea_context['table_name']
        product_line = sea_context['product_line']
    elif siel_context:
        table_name = siel_context['table_name']
        product_line = siel_context['product_line']
    else:
        product_line = 'tv' if table_name == 'tv_retail_com' else 'hhp'

    # 기존 값 + retailer + item 조회
    select_columns = f"{column_name}, account_name, item"
    if tse_context:
        select_columns += ", batch_id"
    if tse_context:
        cursor.execute(f"""
            SELECT {select_columns}
            FROM {table_name}
            WHERE id = %s
              AND (
                  country = 'TSE'
                  OR country IS NULL
                  OR TRIM(CAST(country AS TEXT)) = ''
              )
              AND LEFT(TRIM(crawl_datetime), 10) = %s
        """, (row_id, str(crawl_date)))
    elif sea_context:
        date_contract = resolve_monitoring_date(
            crawl_date, 'SEA', sea_context['source_key']
        )
        date_column = sea_context['date_column']
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
                  WHERE LEFT(
                            TRIM(CAST(anchor.{date_column} AS TEXT)), 10
                        ) = %s
                    AND LOWER(TRIM(anchor.account_name)) =
                        LOWER(TRIM(source.account_name))
                    AND UPPER(TRIM(COALESCE(anchor.page_type, ''))) = 'MAIN'
                  ORDER BY anchor.id DESC
                  LIMIT 1
              )
        """, (
            row_id, date_contract['source_date'],
            date_contract['source_date'],
        ))
    elif siel_context:
        _select_siel_edit_record(
            cursor, siel_context, select_columns, row_id, crawl_date
        )
    else:
        cursor.execute(
            f"SELECT {select_columns} FROM {table_name} WHERE id = %s",
            (row_id,)
        )
    row = cursor.fetchone()
    if not row:
        return {'error': '해당 레코드가 없습니다', 'status': 404}

    old_value = row[0]
    retailer = row[1]
    item_value = str(row[2]) if row[2] else ''
    batch_id = row[3] if tse_context else None

    # editable 컬럼 확인
    editable_retailer = retailer
    if tse_context and not editable_retailer and column_name == 'account_name':
        editable_retailer = new_value
    if siel_context and column_name == 'account_name':
        editable_retailer = new_value
    editable_cols = (
        get_siel_format_editable_columns(product_line, editable_retailer)
        if siel_context else
        get_editable_columns(product_line, editable_retailer)
    )
    if column_name not in editable_cols:
        return {'error': f'{column_name} 컬럼은 수정할 수 없습니다', 'status': 403}

    # 값이 같으면 스킵
    old_str = str(old_value) if old_value is not None else ''
    new_str = str(new_value) if new_value is not None else ''
    if old_str == new_str:
        return {'success': True, 'message': '변경 없음'}

    update_value = new_value if new_value != '' else None

    # TSE source tables enforce UNIQUE(account_name, batch_id, item). Check
    # the candidate identity before UPDATE so the API returns a clear error
    # and no correction history is written on collision.
    if tse_context and column_name in {'account_name', 'item'}:
        candidate_retailer = (
            update_value if column_name == 'account_name' else retailer
        )
        candidate_item = (
            update_value if column_name == 'item' else row[2]
        )
        cursor.execute(f"""
            SELECT id
            FROM {table_name}
            WHERE account_name IS NOT DISTINCT FROM %s
              AND batch_id IS NOT DISTINCT FROM %s
              AND item IS NOT DISTINCT FROM %s
              AND id <> %s
            LIMIT 1
        """, (candidate_retailer, batch_id, candidate_item, row_id))
        if cursor.fetchone():
            return {
                'error': '동일 배치에 같은 리테일러와 item이 이미 존재합니다',
                'status': 409,
            }

    # UPDATE 실행
    try:
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
            crawl_date, username, now, 'corrected', memo,
            editable_retailer, item_value or None
        ))
    except Exception:
        conn.rollback()
        raise

    return {'success': True, 'old_value': old_str, 'new_value': new_str}


def get_review_reasons(check_type):
    """정상 처리 이유 목록 조회 — 코드 상수에서 반환"""
    from apps.common.constants import get_reasons
    reasons = [{'text': r} for r in get_reasons(check_type)]
    return {'success': True, 'reasons': reasons}
