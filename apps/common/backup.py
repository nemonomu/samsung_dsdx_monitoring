"""SEA/TSE Retail 데이터 백업 유틸리티."""

from datetime import datetime
from collections.abc import Mapping
from apps.common.db import get_dx_connection
from apps.common.response import log_error


_BACKUP_SOURCES = (
    {
        'key': 'tv',
        'category': 'TV',
        'product_line': 'tv',
        'source_table': 'tv_retail_com',
        'backup_table': 'tv_retail_com_backup_all',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'timestamp',
    },
    {
        'key': 'tse_tv',
        'category': 'TSE TV',
        'product_line': 'tse_tv',
        'source_table': 'dx_tse.dx_tse_tv_retail_com',
        'backup_table': 'dx_tse.dx_tse_tv_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
    {
        'key': 'tse_ref',
        'category': 'TSE REF',
        'product_line': 'tse_ref',
        'source_table': 'dx_tse.dx_tse_ref_retail_com',
        'backup_table': 'dx_tse.dx_tse_ref_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
    {
        'key': 'tse_ldy',
        'category': 'TSE LDY',
        'product_line': 'tse_ldy',
        'source_table': 'dx_tse.dx_tse_ldy_retail_com',
        'backup_table': 'dx_tse.dx_tse_ldy_retail_com_backup',
        'date_column': 'a.crawl_datetime',
        'date_mode': 'text_prefix',
    },
)
_BACKUP_SOURCE_BY_KEY = {source['key']: source for source in _BACKUP_SOURCES}


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
    """날짜 필터 조건 생성"""
    if target_date:
        date_value = str(target_date)[:10]
        if mode == 'text_prefix':
            return f"AND LEFT(TRIM({date_column}), 10) = %s", (date_value,)
        return f"AND DATE({date_column}::timestamp) = %s", (date_value,)
    return "", ()


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


def _backup_source(cursor, source, username, target_date):
    """Copy one fixed source into its fixed backup and return actual ids."""
    date_sql, date_params = _date_condition(
        source['date_column'], target_date, source['date_mode'],
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
        target_date,
        count,
        min(inserted_ids) if inserted_ids else None,
        max(inserted_ids) if inserted_ids else None,
        username,
    )
    return {
        'success': True,
        'count': count,
        'category': source['category'],
    }


def backup_tv_retail(username='', target_date=None):
    """TV retail 데이터 백업 (신규 데이터만 INSERT)"""
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        result = _backup_source(
            cursor, _BACKUP_SOURCE_BY_KEY['tv'], username, target_date,
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
    """백업 대상 건수만 조회 (실제 백업 없음)"""
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        counts = {
            f"{source['key']}_count": _count_pending_source(
                cursor, source, target_date,
            )
            for source in _BACKUP_SOURCES
        }
        result = {
            'success': True,
            'hhp_count': 0,
            **counts,
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
        return {'success': False, 'error': result.get('error')}

    pending = result.get('total_count', 0)

    # 미백업 0건이면 자동 통과
    if pending == 0:
        return {'success': True, 'pending_count': 0, 'has_backup': True}

    # 미백업 >0건일 때만 이력 조회
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM monitoring_backup_log WHERE target_date = %s
        """, (target_date,))
        has_backup = cursor.fetchone()[0] > 0

        return {
            'success': True,
            'has_backup': has_backup,
            'pending_count': pending,
            'tv_count': result.get('tv_count', 0),
            'hhp_count': result.get('hhp_count', 0),
            'tse_tv_count': result.get('tse_tv_count', 0),
            'tse_ref_count': result.get('tse_ref_count', 0),
            'tse_ldy_count': result.get('tse_ldy_count', 0),
        }
    except Exception as e:
        log_error(e, 'backup')
        return {'success': False, 'error': '백업 상태 조회 중 오류가 발생했습니다.'}
    finally:
        cursor.close()
        conn.close()


def backup_all_retail(username='', target_date=None):
    """Back up SEA TV and all TSE products in one transaction."""
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        results = {
            source['key']: _backup_source(
                cursor, source, username, target_date,
            )
            for source in _BACKUP_SOURCES
        }
        conn.commit()
        return {
            'success': True,
            **results,
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
        }
    finally:
        cursor.close()
        conn.close()
