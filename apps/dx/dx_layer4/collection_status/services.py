"""
Layer 4 수집 현황 Services — 수집 건수/NULL 현황 조회, 이메일 발송
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime
from apps.common.db import dx_connection, dx_table
from apps.common.retail_columns import load_retail_columns, get_tse_retailer_columns
from apps.common.retail_validation import get_tv_validation_condition
from apps.common.tse_retail import (
    TSE_SOURCE_CONFIG,
    get_tse_required_columns,
    get_tse_source,
    normalize_tse_product_line,
    resolve_tse_table,
    tse_retailer_include_unassigned,
)
from config.config import EMAIL_CONFIG

_EMAIL_LOG_TABLE = dx_table('monitoring_email_logs')

_TABLE_MAP = {
    'tv': 'tv_retail_com',
    **{
        product_line: config['table_name']
        for product_line, config in TSE_SOURCE_CONFIG.items()
    },
}

_DATE_COL_MAP = {
    'tv': 'crawl_datetime',
    **{product_line: 'crawl_datetime' for product_line in TSE_SOURCE_CONFIG},
}

VALID_COLLECTION_CATEGORIES = frozenset(_TABLE_MAP)

_BATCH_DATE_EXPR = "substring(COALESCE(batch_id, '') from '([0-9]{8})')"


def _batch_date_key(date_value):
    return str(date_value)[:10].replace('-', '')


def _get_tse_columns(product_line):
    """Return active TSE configuration intersected with server allowlists."""
    key = normalize_tse_product_line(product_line)
    allowed = set(get_tse_required_columns(key))
    result = []
    for retailer_name, config in get_tse_retailer_columns(key).items():
        required = [
            column
            for column in config.get('required_columns', [])
            if column in allowed
        ]
        if required:
            result.append({
                'retailer': retailer_name,
                'retailer_key': config['retailer'],
                'columns': required,
            })
    return result


def _get_tse_collection_status(target_date, product_line):
    """Return latest-batch NULL counts for one TSE product line."""
    key = normalize_tse_product_line(product_line)
    table_name = resolve_tse_table(key)
    retailer_configs = _get_tse_columns(key)
    if not retailer_configs:
        return {
            'success': True,
            'category': key,
            'label': get_tse_source(key)['display_name'],
            'retailers': [],
        }

    retailers = []
    with dx_connection() as (conn, cursor):
        for retailer_config in retailer_configs:
            include_unassigned = tse_retailer_include_unassigned(
                retailer_config['retailer_key']
            )
            columns = retailer_config['columns']
            null_parts = [
                f"SUM(CASE WHEN t.{column} IS NULL OR "
                f"BTRIM(CAST(t.{column} AS TEXT)) = '' THEN 1 ELSE 0 END)"
                for column in columns
            ]
            account_scope = "LOWER(t.account_name) = LOWER(%s)"
            if include_unassigned:
                account_scope = f"""(
                    {account_scope}
                    OR t.account_name IS NULL
                    OR BTRIM(CAST(t.account_name AS TEXT)) = ''
                )"""
            sql = (
                f"SELECT COUNT(*) AS total_count, {', '.join(null_parts)} "
                f"FROM {table_name} t "
                f"JOIN ("
                f"  SELECT batch_id FROM {table_name} "
                f"  WHERE LOWER(account_name) = LOWER(%s) "
                f"    AND LEFT(TRIM(crawl_datetime), 10) = %s "
                f"  ORDER BY id DESC LIMIT 1"
                f") latest ON t.batch_id IS NOT DISTINCT FROM latest.batch_id "
                f"WHERE {account_scope} "
                f"  AND LEFT(TRIM(t.crawl_datetime), 10) = %s"
            )
            cursor.execute(sql, [
                retailer_config['retailer_key'],
                str(target_date),
                retailer_config['retailer_key'],
                str(target_date),
            ])
            row = cursor.fetchone()
            total_count = (row[0] or 0) if row else 0
            column_nulls = []
            for index, column in enumerate(columns):
                null_count = (row[index + 1] or 0) if row else 0
                column_nulls.append({
                    'column': column,
                    'total_count': total_count,
                    'null_count': null_count,
                })
            retailers.append({
                'retailer': retailer_config['retailer'],
                'total_count': total_count,
                'columns': column_nulls,
            })

    return {
        'success': True,
        'category': key,
        'label': get_tse_source(key)['display_name'],
        'retailers': retailers,
    }


def get_collection_status(target_date, category):
    """리테일러별 수집 건수 + 컬럼별 NULL 수 조회"""
    if category in TSE_SOURCE_CONFIG:
        return _get_tse_collection_status(target_date, category)

    table_name = _TABLE_MAP[category]
    date_col = _DATE_COL_MAP[category]

    all_col_data = load_retail_columns()
    retailer_columns = all_col_data.get(category, {})

    if not retailer_columns:
        return {'success': True, 'retailers': []}

    with dx_connection() as (conn, cursor):
        retailers = []
        for retailer, columns in sorted(retailer_columns.items()):
            if not columns:
                continue

            null_parts = []
            for col in columns:
                null_parts.append(
                    f"SUM(CASE WHEN {col} IS NULL OR CAST({col} AS TEXT) = '' THEN 1 ELSE 0 END) AS null_{col}"
                )
            null_parts.append(
                "SUM(CASE WHEN savings IS NOT NULL AND CAST(savings AS TEXT) != '' THEN 1 ELSE 0 END) AS savings_count"
            )
            null_parts.append(
                "SUM(CASE WHEN (savings IS NOT NULL AND CAST(savings AS TEXT) != '') "
                "AND (original_sku_price IS NULL OR CAST(original_sku_price AS TEXT) = '') THEN 1 ELSE 0 END) AS original_price_missing"
            )

            sql = (
                f"SELECT COUNT(*) AS total_count, {', '.join(null_parts)} "
                f"FROM {table_name} "
                f"WHERE account_name = %s AND {_BATCH_DATE_EXPR} = %s "
                f"AND {get_tv_validation_condition()} "
            )
            cursor.execute(sql, [retailer, _batch_date_key(target_date)])
            row = cursor.fetchone()

            redirect_true_count = 0
            if category == 'tv' and retailer == 'Amazon':
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} "
                    f"WHERE account_name = %s AND {_BATCH_DATE_EXPR} = %s "
                    f"AND redirect IS TRUE",
                    [retailer, _batch_date_key(target_date)],
                )
                redirect_row = cursor.fetchone()
                redirect_true_count = (redirect_row[0] or 0) if redirect_row else 0

            total_count = (row[0] or 0) if row else 0
            savings_count = (row[len(columns) + 1] or 0) if row else 0
            original_price_missing = (row[len(columns) + 2] or 0) if row else 0

            CUSTOM_TOTALS = {
                'bsr_rank': 100,
            }

            REMARKS = {
                'bsr_rank': 'BSR 페이지 수집 항목 (일 100건)',
                'trend_rank': '트렌드 수집 항목 (최대 10개)',
                'original_sku_price': '할인가 존재 시에만 원본가 존재 (Amazon 제외)',
            }
            if category == 'tv':
                REMARKS['promotion_type'] = '프로모션 페이지 수집 항목'
                REMARKS['promotion_position'] = '프로모션 페이지 수집 항목'

            not_null_counts = {
                col: total_count - ((row[i + 1] or 0) if row else 0)
                for i, col in enumerate(columns)
            }
            promotion_total = not_null_counts.get('promotion_position', 0)

            column_nulls = []
            for i, col in enumerate(columns):
                raw_null = (row[i + 1] or 0) if row else 0
                not_null = total_count - raw_null
                if col == 'original_sku_price' and retailer in ('Bestbuy', 'Walmart'):
                    col_total = savings_count
                    null_count = original_price_missing
                elif col == 'trend_rank':
                    col_total = not_null
                    null_count = 0
                elif category == 'tv' and col in ('promotion_type', 'promotion_position'):
                    col_total = promotion_total
                    null_count = max(col_total - not_null, 0)
                elif col in CUSTOM_TOTALS:
                    col_total = CUSTOM_TOTALS[col]
                    null_count = col_total - not_null if col_total > not_null else 0
                else:
                    col_total = total_count
                    null_count = raw_null
                item = {
                    'column': col,
                    'total_count': col_total,
                    'null_count': null_count,
                }
                if col in REMARKS:
                    item['remark'] = REMARKS[col]
                column_nulls.append(item)

            retailers.append({
                'retailer': retailer,
                'total_count': total_count,
                'redirect_true_count': redirect_true_count,
                'columns': column_nulls,
            })

    return {'success': True, 'retailers': retailers}


def get_null_detail(target_date, category, retailer, column):
    """특정 리테일러/컬럼의 NULL 행 상세 조회"""
    if category in TSE_SOURCE_CONFIG:
        return _get_tse_null_detail(target_date, category, retailer, column)

    table_name = _TABLE_MAP[category]
    date_col = _DATE_COL_MAP[category]
    date_expr = 'crawl_datetime' if category == 'tv' else 'crawl_strdatetime AS crawl_datetime'

    # 허용된 컬럼인지 검증 (SQL 인젝션 방지)
    all_col_data = load_retail_columns()
    retailer_columns = all_col_data.get(category, {}).get(retailer, [])
    if column not in retailer_columns:
        raise ValueError('허용되지 않은 컬럼입니다.')

    with dx_connection() as (conn, cursor):
        sql = (
            f"SELECT id, {date_expr}, account_name, item, {column}, product_url "
            f"FROM {table_name} "
            f"WHERE account_name = %s AND {_BATCH_DATE_EXPR} = %s "
            f"AND {get_tv_validation_condition()} "
            f"AND ({column} IS NULL OR CAST({column} AS TEXT) = '') "
            f"ORDER BY item, {date_col} ASC"
        )
        cursor.execute(sql, [retailer, _batch_date_key(target_date)])

        col_names = ['id', 'crawl_datetime', 'account_name', 'item', column, 'product_url']
        rows = []
        for row in cursor.fetchall():
            d = {}
            for idx, val in enumerate(row):
                if hasattr(val, 'strftime'):
                    d[col_names[idx]] = val.strftime('%Y-%m-%d %H:%M:%S')
                elif val is None:
                    d[col_names[idx]] = ''
                else:
                    d[col_names[idx]] = str(val)
            rows.append(d)

    return {'success': True, 'columns': col_names, 'rows': rows}


def _get_tse_null_detail(target_date, product_line, retailer, column):
    """Return a read-only Layer 4 detail for a TSE latest-batch NULL."""
    key = normalize_tse_product_line(product_line)
    table_name = resolve_tse_table(key)
    retailer_key = str(retailer or '').strip().lower()
    retailer_configs = _get_tse_columns(key)
    matched = next(
        (
            config for config in retailer_configs
            if config['retailer_key'] == retailer_key
        ),
        None,
    )
    if not matched or column not in matched['columns']:
        raise ValueError('허용되지 않은 컬럼입니다.')
    include_unassigned = tse_retailer_include_unassigned(
        matched['retailer_key']
    )
    account_scope = "LOWER(t.account_name) = LOWER(%s)"
    if include_unassigned:
        account_scope = f"""(
            {account_scope}
            OR t.account_name IS NULL
            OR BTRIM(CAST(t.account_name AS TEXT)) = ''
        )"""

    with dx_connection() as (conn, cursor):
        sql = (
            f"SELECT t.id, t.crawl_datetime, t.account_name, t.item, "
            f"t.{column}, t.product_url "
            f"FROM {table_name} t "
            f"JOIN ("
            f"  SELECT batch_id FROM {table_name} "
            f"  WHERE LOWER(account_name) = LOWER(%s) "
            f"    AND LEFT(TRIM(crawl_datetime), 10) = %s "
            f"  ORDER BY id DESC LIMIT 1"
            f") latest ON t.batch_id IS NOT DISTINCT FROM latest.batch_id "
            f"WHERE {account_scope} "
            f"  AND LEFT(TRIM(t.crawl_datetime), 10) = %s "
            f"  AND (t.{column} IS NULL OR BTRIM(CAST(t.{column} AS TEXT)) = '') "
            f"ORDER BY t.item, t.id"
        )
        cursor.execute(
            sql,
            [retailer_key, str(target_date), retailer_key, str(target_date)],
        )
        col_names = [
            'id', 'crawl_datetime', 'account_name', 'item', column, 'product_url'
        ]
        rows = []
        for row in cursor.fetchall():
            rows.append({
                name: '' if value is None else str(value)
                for name, value in zip(col_names, row)
            })

    return {
        'success': True,
        'category': key,
        'actual_table': table_name,
        'read_only': True,
        'columns': col_names,
        'rows': rows,
    }


def save_email_log(crawl_date, subject, receiver, sender, sent_id, status, error_message=None):
    """이메일 발송 이력 저장"""
    try:
        with dx_connection() as (conn, cursor):
            cursor.execute(f"""
                INSERT INTO {_EMAIL_LOG_TABLE}
                    (crawl_date, subject, receiver_email, sender_email, sent_at, sent_id, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, [crawl_date, subject, receiver, sender, datetime.now(), sent_id, status, error_message])
            conn.commit()
    except Exception:
        pass


def send_email_report(subject, html_content, crawl_date, recipients, sent_id):
    """이메일 보고 발송. recipients: [{name, email}] 형태"""
    sender = EMAIL_CONFIG['sender_email']
    email_list = [r['email'] for r in recipients]
    to_header = ', '.join(
        formataddr((str(Header(r['name'], 'utf-8')), r['email'])) if r.get('name') else r['email']
        for r in recipients
    )
    receiver_log = ', '.join(email_list)

    full_html = (
        '<!DOCTYPE html>'
        '<html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:20px;font-family:Malgun Gothic,sans-serif;font-size:13px;color:#222;">'
        '<div style="max-width:1100px;">'
        + html_content
        + '</div></body></html>'
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    sender_name = EMAIL_CONFIG.get('sender_name', '')
    msg['From'] = formataddr((str(Header(sender_name, 'utf-8')), sender)) if sender_name else sender
    msg['To'] = to_header
    msg.attach(MIMEText(full_html, 'html', 'utf-8'))

    try:
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(sender, EMAIL_CONFIG['sender_password'])
            server.sendmail(sender, email_list, msg.as_string())
    except Exception as e:
        save_email_log(crawl_date, subject, receiver_log, sender, sent_id, 'failed', str(e))
        raise

    save_email_log(crawl_date, subject, receiver_log, sender, sent_id, 'success')
    return {'success': True, 'message': '이메일이 발송되었습니다.'}


def check_email_sent(crawl_date):
    """해당 날짜 이메일 발송 여부 및 횟수 확인"""
    with dx_connection() as (conn, cursor):
        cursor.execute(
            f"SELECT COUNT(*) FROM {_EMAIL_LOG_TABLE} WHERE crawl_date = %s AND status = 'success'",
            [crawl_date]
        )
        count = cursor.fetchone()[0]

        last_info = {}
        if count > 0:
            cursor.execute(
                f"SELECT sent_at, sent_id FROM {_EMAIL_LOG_TABLE} WHERE crawl_date = %s AND status = 'success' ORDER BY sent_at DESC",
                [crawl_date]
            )
            row = cursor.fetchone()
            last_info = {
                'sent_at': row[0].strftime('%Y-%m-%d %H:%M:%S') if row[0] else '',
                'sent_id': row[1] or '',
            }

    return {'count': count, **last_info}
