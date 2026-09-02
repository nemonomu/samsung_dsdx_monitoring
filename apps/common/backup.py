"""SEA/SIEL/TSE Retail 데이터 백업 유틸리티."""

from datetime import datetime
from collections.abc import Mapping
from apps.common.db import get_dx_connection
from apps.common.inspection_dates import (
    MonitoringDateError,
    resolve_monitoring_date,
)
from apps.common.response import log_error
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.common.siel_retail import (
    SIEL_BUSINESS_TIMEZONE,
    SIEL_SOURCE_CONFIG,
)


def _sea_backup_source(product_key):
    source = SEA_RETAIL_SOURCES[product_key]
    return {
        'key': source['key'],
        'source_key': source['source_key'],
        'country': 'SEA',
        'category': source['category'],
        'product_line': source['product_line'],
        'source_table': source['table_name'],
        'backup_table': source['backup_table'],
        'date_column': f"a.{source['date_column']}",
        'date_mode': source['date_mode'],
    }


def _siel_backup_source(source_key):
    source = SIEL_SOURCE_CONFIG[source_key]
    return {
        'key': source['source_key'],
        'source_key': source['source_key'],
        'country': 'SIEL',
        'category': f"SIEL {source['category']}",
        'product_line': source['source_key'],
        'source_table': source['table_name'],
        'backup_table': source['backup_table_name'],
        'date_column': f"a.{source['date_column']}",
        'date_mode': 'siel_kst_timestamp',
    }


_BACKUP_SOURCES = tuple(
    _sea_backup_source(product_key)
    for product_key in ('tv', 'ref', 'ldy')
) + (
    {
        'key': 'tse_tv',
        'source_key': 'tse_tv',
        'country': 'TSE',
        'category': 'TSE TV',
        'product_line': 'tse_tv',
        'source_table': 'dx_tse.dx_tse_tv_retail_com',
        'backup_table': 'dx_tse.dx_tse_tv_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
    {
        'key': 'tse_ref',
        'source_key': 'tse_ref',
        'country': 'TSE',
        'category': 'TSE REF',
        'product_line': 'tse_ref',
        'source_table': 'dx_tse.dx_tse_ref_retail_com',
        'backup_table': 'dx_tse.dx_tse_ref_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
    {
        'key': 'tse_ldy',
        'source_key': 'tse_ldy',
        'country': 'TSE',
        'category': 'TSE LDY',
        'product_line': 'tse_ldy',
        'source_table': 'dx_tse.dx_tse_ldy_retail_com',
        'backup_table': 'dx_tse.dx_tse_ldy_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
) + tuple(
    _siel_backup_source(source_key)
    for source_key in ('siel_tv', 'siel_ref', 'siel_ldy')
)
_BACKUP_SOURCE_BY_KEY = {source['key']: source for source in _BACKUP_SOURCES}
_INVALID_DATE_ERROR_CODE = 'invalid_inspection_date'


def _resolve_date_mappings(inspection_date):
    """Resolve the user-selected inspection date for every backup source."""
    return {
        source['key']: resolve_monitoring_date(
            inspection_date,
            source['country'],
            source['source_key'],
        )
        for source in _BACKUP_SOURCES
    }


def _date_payload(date_mappings):
    first_mapping = date_mappings[_BACKUP_SOURCES[0]['key']]
    mappings_by_source_key = {
        source['source_key']: dict(date_mappings[source['key']])
        for source in _BACKUP_SOURCES
    }
    return {
        'inspection_date': first_mapping['inspection_date'],
        'source_dates': {
            source_key: mapping['source_date']
            for source_key, mapping in mappings_by_source_key.items()
        },
        'date_mappings': mappings_by_source_key,
    }


def _invalid_date_result(error):
    return {
        'success': False,
        'error_code': _INVALID_DATE_ERROR_CODE,
        'error': f'검수일이 유효하지 않습니다. {error}',
    }


def _insert_backup_log(cursor, product_line, table_name, target_date, count, min_id, max_id, username):
    """백업 로그 기록 (0건이면 기록 안 함)"""
    if count <= 0:
        return
    cursor.execute("""
        INSERT INTO monitoring_backup_log
            (product_line, table_name, target_date, backup_count, min_id, max_id, executed_id, executed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (product_line, table_name, target_date, count, min_id, max_id, username, datetime.now()))


def _date_condition(date_column, target_date, mode='timestamp'):
    """Build a mandatory exact-date predicate for one resolved source date."""
    try:
        date_value = datetime.strptime(str(target_date), '%Y-%m-%d').date().isoformat()
    except (TypeError, ValueError) as exc:
        raise MonitoringDateError('source_date가 유효하지 않습니다.') from exc

    if mode == 'text_prefix':
        return f"AND LEFT(TRIM({date_column}), 10) = %s", (date_value,)
    if mode == 'timestamp':
        return f"AND DATE({date_column}::timestamp) = %s", (date_value,)
    if mode == 'siel_kst_timestamp':
        return f"""
            AND {date_column} >= (
                    %s::date::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                )
            AND {date_column} < (
                    (%s::date + 1)::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                )
        """, (date_value, date_value)
    raise ValueError(f'허용되지 않은 백업 날짜 모드입니다: {mode}')


def _row_id(row):
    if isinstance(row, Mapping):
        return row.get('id')
    return row[0]


def _count_pending_source(cursor, source, target_date):
    date_sql, date_params = _date_condition(
        source['date_column'], target_date, source['date_mode'],
    )
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM {source['source_table']} a
        LEFT JOIN {source['backup_table']} b ON a.id = b.id
        WHERE b.id IS NULL
        {date_sql}
    """, date_params)
    return int(cursor.fetchone()[0] or 0)


def _backup_source(cursor, source, username, date_mapping):
    """Copy one fixed source into its fixed backup and return actual ids."""
    source_date = date_mapping['source_date']
    date_sql, date_params = _date_condition(
        source['date_column'], source_date, source['date_mode'],
    )
    cursor.execute(f"""
        INSERT INTO {source['backup_table']}
        SELECT a.*
        FROM {source['source_table']} a
        LEFT JOIN {source['backup_table']} b ON a.id = b.id
        WHERE b.id IS NULL
        {date_sql}
        ON CONFLICT DO NOTHING
        RETURNING id
    """, date_params)
    inserted_ids = [
        record_id for record_id in (_row_id(row) for row in cursor.fetchall())
        if record_id is not None
    ]
    count = len(inserted_ids)
    _insert_backup_log(
        cursor,
        source['product_line'],
        source['source_table'],
        source_date,
        count,
        min(inserted_ids) if inserted_ids else None,
        max(inserted_ids) if inserted_ids else None,
        username,
    )
    return {
        'success': True,
        'count': count,
        'category': source['category'],
        'inspection_date': date_mapping['inspection_date'],
        'source_date': source_date,
        'offset_days': date_mapping['offset_days'],
        'source_key': source['source_key'],
    }


def backup_tv_retail(username='', target_date=None):
    """Back up SEA TV for a required inspection date."""
    try:
        date_mapping = _resolve_date_mappings(target_date)['tv']
    except MonitoringDateError as error:
        return _invalid_date_result(error)

    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        result = _backup_source(
            cursor, _BACKUP_SOURCE_BY_KEY['tv'], username, date_mapping,
        )
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        log_error(e, 'backup')
        return {'success': False, 'error': '백업 중 오류가 발생했습니다.', 'category': 'TV'}
    finally:
        cursor.close()
        conn.close()


def backup_hhp_retail(username='', target_date=None):
    return {'success': True, 'count': 0, 'category': 'HHP', 'excluded': True}

    """HHP retail 데이터 백업 (신규 데이터만 INSERT)"""
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        date_sql, date_params = _date_condition('a.crawl_strdatetime', target_date)

        cursor.execute(f"""
            SELECT COUNT(*), MIN(a.id), MAX(a.id)
            FROM hhp_retail_com a
            LEFT JOIN hhp_retail_com_backup b ON a.id = b.id
            WHERE b.id IS NULL
            {date_sql}
        """, date_params)
        count, min_id, max_id = cursor.fetchone()

        if count > 0:
            cursor.execute(f"""
                INSERT INTO hhp_retail_com_backup
                SELECT a.*
                FROM hhp_retail_com a
                LEFT JOIN hhp_retail_com_backup b ON a.id = b.id
                WHERE b.id IS NULL
                {date_sql}
            """, date_params)
            _insert_backup_log(cursor, 'hhp', 'hhp_retail_com', target_date, count, min_id, max_id, username)
            conn.commit()

        return {'success': True, 'count': count, 'category': 'HHP'}
    except Exception as e:
        conn.rollback()
        log_error(e, 'backup')
        return {'success': False, 'error': '백업 중 오류가 발생했습니다.', 'category': 'HHP'}
    finally:
        cursor.close()
        conn.close()


def get_backup_count(target_date=None):
    """Return pending counts for one required inspection date."""
    try:
        date_mappings = _resolve_date_mappings(target_date)
    except MonitoringDateError as error:
        return _invalid_date_result(error)

    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        counts = {
            f"{source['key']}_count": _count_pending_source(
                cursor,
                source,
                date_mappings[source['key']]['source_date'],
            )
            for source in _BACKUP_SOURCES
        }
        result = {
            'success': True,
            'hhp_count': 0,
            **counts,
            **_date_payload(date_mappings),
        }
        result['total_count'] = sum(counts.values())
        return result
    except Exception as e:
        log_error(e, 'backup')
        return {'success': False, 'error': '백업 조회 중 오류가 발생했습니다.'}
    finally:
        cursor.close()
        conn.close()


def get_backup_status(target_date):
    """백업 상태 확인 — 미백업 건수 먼저, >0일 때만 이력 조회"""
    result = get_backup_count(target_date)
    if not result.get('success'):
        return result

    pending = result.get('total_count', 0)
    status_payload = {
        'success': True,
        'pending_count': pending,
        'inspection_date': result['inspection_date'],
        'source_dates': result['source_dates'],
        'date_mappings': result['date_mappings'],
        'hhp_count': result.get('hhp_count', 0),
        **{
            f"{source['key']}_count": result.get(
                f"{source['key']}_count", 0,
            )
            for source in _BACKUP_SOURCES
        },
    }

    # 미백업 0건이면 자동 통과
    if pending == 0:
        return {**status_payload, 'has_backup': True}

    # 미백업 >0건일 때만 이력 조회
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        source_dates = tuple(dict.fromkeys(result['source_dates'].values()))
        placeholders = ', '.join('%s' for _ in source_dates)
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM monitoring_backup_log
            WHERE target_date IN ({placeholders})
        """, source_dates)
        has_backup = cursor.fetchone()[0] > 0

        return {**status_payload, 'has_backup': has_backup}
    except Exception as e:
        log_error(e, 'backup')
        return {'success': False, 'error': '백업 상태 조회 중 오류가 발생했습니다.'}
    finally:
        cursor.close()
        conn.close()


def backup_all_retail(username='', target_date=None):
    """Back up all SEA/SIEL/TSE retail sources for one inspection date."""
    try:
        date_mappings = _resolve_date_mappings(target_date)
    except MonitoringDateError as error:
        return _invalid_date_result(error)

    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        results = {
            source['key']: _backup_source(
                cursor,
                source,
                username,
                date_mappings[source['key']],
            )
            for source in _BACKUP_SOURCES
        }
        conn.commit()
        return {
            'success': True,
            **results,
            **_date_payload(date_mappings),
            'hhp': {
                'success': True,
                'count': 0,
                'category': 'HHP',
                'excluded': True,
            },
        }
    except Exception as e:
        conn.rollback()
        log_error(e, 'backup')
        return {
            'success': False,
            'error': '통합 백업 중 오류가 발생했습니다. 전체 백업을 취소했습니다.',
            **_date_payload(date_mappings),
        }
    finally:
        cursor.close()
        conn.close()
