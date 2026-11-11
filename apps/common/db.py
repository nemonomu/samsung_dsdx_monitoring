"""
데이터베이스 연결 헬퍼
"""

import psycopg2
from contextlib import contextmanager
from django.conf import settings
from config.config import DB_CONFIG, DB_CONFIG_V2

# 개발서버: test_ 접두사 → 운영 테이블과 분리
def dx_table(name):
    """DX(PostgreSQL) 모니터링 테이블명. 개발서버(DEBUG)면 test_ 접두사 추가."""
    return f'test_{name}' if settings.DEBUG else name


def ds_table(name):
    """DS(MySQL) 모니터링 테이블명. 개발서버(DEBUG)면 test_ 접두사 추가."""
    if settings.DEBUG:
        return name.replace('ds_monitoring_', 'test_ds_monitoring_')
    return name


# 공유 토큰 테이블명 (기존 호환)
DX_SHARE_TOKEN_TABLE = dx_table('monitoring_share_tokens')
DS_SHARE_TOKEN_TABLE = ds_table('ssd_crawl_db.ds_monitoring_share_tokens')


def get_dx_connection(*, connect_timeout=None):
    """DX PostgreSQL 연결"""
    return psycopg2.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database='postgres',
        **({'connect_timeout': connect_timeout} if connect_timeout is not None else {}),
    )


def get_ds_connection():
    """DS MySQL 연결"""
    import pymysql
    return pymysql.connect(
        host=DB_CONFIG_V2['host'],
        port=DB_CONFIG_V2['port'],
        user=DB_CONFIG_V2['user'],
        password=DB_CONFIG_V2['password'],
        database=DB_CONFIG_V2['database'],
        charset='utf8mb4'
    )


@contextmanager
def dx_connection(*, connect_timeout=None):
    """DX PostgreSQL 커넥션 컨텍스트 매니저 (에러 시 rollback, 자동 close)"""
    conn = get_dx_connection(connect_timeout=connect_timeout) if connect_timeout is not None else get_dx_connection()
    cursor = conn.cursor()
    try:
        yield conn, cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@contextmanager
def ds_connection(existing=None):
    """DS MySQL 커넥션 컨텍스트 매니저 (에러 시 rollback, 자동 close)
    existing=(conn, cursor) 전달 시 기존 커넥션 재사용 (close 안 함)"""
    if existing:
        yield existing
    else:
        conn = get_ds_connection()
        cursor = conn.cursor()
        try:
            yield conn, cursor
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


def execute_dx_query(query, params=None, *, cursor=None):
    """DX DB 쿼리 실행 후 결과 반환"""
    if cursor is not None:
        cursor.execute(query, params or ())
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn = get_dx_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params or ())
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        cursor.close()
        conn.close()


def execute_ds_query(query, params=None):
    """DS DB 쿼리 실행 후 결과 반환"""
    conn = get_ds_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params or ())
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        cursor.close()
        conn.close()
