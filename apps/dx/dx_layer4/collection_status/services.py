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
from apps.common.retail_columns import load_retail_columns
from apps.common.retail_validation import get_tv_validation_condition
from config.config import EMAIL_CONFIG

_EMAIL_LOG_TABLE = dx_table('monitoring_email_logs')

_TABLE_MAP = {
    'tv': 'tv_retail_com',
}

_DATE_COL_MAP = {
    'tv': 'crawl_datetime',
}

_BATCH_DATE_EXPR = "substring(COALESCE(batch_id, '') from '([0-9]{8})')"


def _batch_date_key(date_value):
    return str(date_value)[:10].replace('-', '')


def get_collection_status(target_date, category):
    """리테일러별 수집 건수 + 컬럼별 NULL 수 조회"""
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
            if category == 'tv':
                CUSTOM_TOTALS['promotion_type'] = 18
                CUSTOM_TOTALS['promotion_position'] = 18

            REMARKS = {
                'bsr_rank': 'BSR 페이지 수집 항목 (일 100건)',
                'trend_rank': '트렌드 수집 항목 (최대 10개)',
                'original_sku_price': '할인가 존재 시에만 원본가 존재 (Amazon 제외)',
            }
            if category == 'tv':
                REMARKS['promotion_type'] = '프로모션 페이지 수집 항목 (TV 최대 18개)'
                REMARKS['promotion_position'] = '프로모션 페이지 수집 항목 (TV 최대 18개)'

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
