"""
시계열 이상치 서비스 — 순수 비즈니스 로직 (DB 커넥션/HTTP 무관)
"""

from datetime import timedelta
from apps.common.db import dx_table
from apps.common.response import log_error
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer3.dashboard.services import (
    apply_tv_retail_am_filter,
    validate_table_name as _validate_table_name,
)

_RULES_TABLE = dx_table('monitoring_timeseries_rules')


def get_time_series_detail(cursor, target_date, detail_code, days=1):
    """시계열 이상치 상세 — 이상치 item의 N일치 원본 데이터"""
    prev_date = target_date - timedelta(days=1)
    since_date = target_date - timedelta(days=days - 1)

    cursor.execute(f"""
        SELECT table_name, date_column, query
        FROM {_RULES_TABLE}
        WHERE detail_code = %s AND is_active = true
    """, [detail_code])
    rule = cursor.fetchone()
    if not rule:
        return {'error': '규칙을 찾을 수 없습니다.', 'status_code': 404}

    source_table, date_column, stored_query = rule
    stored_query = apply_tv_retail_am_filter(stored_query, source_table, date_column)
    if source_table in {'hhp_retail_com', 'hhp_item_mst'}:
        return {'items': [], 'total': 0, 'anomaly_count': 0}
    _validate_table_name(source_table)

    if not stored_query:
        return {'items': [], 'total': 0, 'anomaly_count': 0}

    # 이상치 item 카운트 (오늘 기준)
    count_sql = f"SELECT COUNT(*) FROM ({stored_query}) x"
    cursor.execute(count_sql, (target_date, target_date, prev_date))
    anomaly_count = cursor.fetchone()[0] or 0

    # 이상치 item의 원본 데이터 조회 (일수 범위)
    date_select = f'd.{date_column} AS crawl_datetime' if date_column != 'crawl_datetime' else 'd.crawl_datetime'

    if days == 1:
        date_filter = f"DATE(d.{date_column}::timestamp) = %s"
        date_params = [str(target_date)]
    else:
        date_filter = f"DATE(d.{date_column}::timestamp) >= %s AND DATE(d.{date_column}::timestamp) <= %s"
        date_params = [str(since_date), str(target_date)]

    combined_sql = f"""
        WITH _anomaly_items AS ({stored_query})
        SELECT d.id, d.item, d.account_name, d.final_sku_price, d.product_url, {date_select}, row_to_json(a)
        FROM {source_table} d
        JOIN _anomaly_items a ON d.item = a.item
        WHERE {date_filter}
        {f'AND {get_tv_validation_condition("d")}' if source_table == 'tv_retail_com' else ''}
        ORDER BY d.item, d.account_name, d.{date_column} ASC
    """
    cursor.execute(combined_sql, (target_date, target_date, prev_date) + tuple(date_params))

    rows = []
    for row in cursor.fetchall():
        anomaly_data = row[6] or {}
        median = anomaly_data.get('median_val')
        rows.append({
            'id': row[0],
            'item': row[1],
            'account_name': row[2],
            'final_sku_price': row[3] or '',
            'product_url': row[4] or '',
            'crawl_datetime': row[5].strftime('%Y-%m-%d %H:%M:%S') if hasattr(row[5], 'strftime') else str(row[5]) if row[5] else '',
            'median_price': f'${median:,.2f}' if median is not None else ''
        })

    return {
        'date': str(target_date),
        'detail_code': detail_code,
        'total': len(rows),
        'anomaly_count': anomaly_count,
        'items': rows
    }


def get_duplicate_detail(cursor, target_date, product_line):
    """중복 변형 탐지 상세 — 같은 수집 시점(AM/PM) 내 중복만 표시"""
    if product_line == 'hhp':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'total_duplicates': 0,
            'duplicates': []
        }

    if product_line == 'tv':
        cursor.execute(f"""
            SELECT item, account_name, page_type,
                   'DAILY' as period,
                   COUNT(*) as cnt,
                   MIN(crawl_datetime) as first_crawl,
                   MAX(crawl_datetime) as last_crawl
            FROM tv_retail_com
            WHERE DATE(crawl_datetime::timestamp) = %s
              AND {get_tv_validation_condition()}
            GROUP BY item, account_name, page_type
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
        """, (target_date,))
    elif product_line == 'hhp':
        cursor.execute("""
            SELECT item, account_name, page_type,
                   CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN 'AM' ELSE 'PM' END as period,
                   COUNT(*) as cnt,
                   MIN(crawl_strdatetime) as first_crawl,
                   MAX(crawl_strdatetime) as last_crawl
            FROM hhp_retail_com
            WHERE DATE(crawl_strdatetime) = %s
            GROUP BY item, account_name, page_type,
                     CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN 'AM' ELSE 'PM' END
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
        """, (target_date,))
    else:
        cursor.execute("""
            SELECT video_id, comment_id,
                   CASE WHEN EXTRACT(HOUR FROM created_at::timestamp) < 12 THEN 'AM' ELSE 'PM' END as period,
                   COUNT(*) as cnt,
                   MIN(created_at) as first_crawl,
                   MAX(created_at) as last_crawl
            FROM youtube_comments
            WHERE DATE(created_at) = %s
            GROUP BY video_id, comment_id,
                     CASE WHEN EXTRACT(HOUR FROM created_at::timestamp) < 12 THEN 'AM' ELSE 'PM' END
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
        """, (target_date,))

    rows = cursor.fetchall()
    duplicates = []

    if product_line in ['tv', 'hhp']:
        for row in rows:
            period_text = '일일' if row[3] == 'DAILY' else ('오전' if row[3] == 'AM' else '오후')
            duplicates.append({
                'item': row[0], 'account_name': row[1], 'page_type': row[2],
                'period': period_text, 'count': row[4],
                'first_crawl': str(row[5]), 'last_crawl': str(row[6])
            })
    else:
        for row in rows:
            period_text = '오전' if row[2] == 'AM' else '오후'
            duplicates.append({
                'video_id': row[0], 'comment_id': row[1],
                'period': period_text, 'count': row[3],
                'first_crawl': str(row[4]), 'last_crawl': str(row[5])
            })

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'total_duplicates': len(duplicates),
        'duplicates': duplicates
    }


def get_review_change_detail(cursor, target_date, product_line):
    if product_line == 'hhp':
        return {
            'date': str(target_date),
            'compare_date': str(target_date - timedelta(days=1)),
            'product_line': product_line.upper(),
            'check_type': 'review',
            'threshold': '+50%',
            'total_changes': 0,
            'changes': []
        }

    """리뷰 수 급변 상세 — 오전/오후 구분 비교"""
    prev_date = target_date - timedelta(days=1)

    if product_line == 'tv':
        table = 'tv_retail_com'
        date_col = 'crawl_datetime'
    else:
        table = 'hhp_retail_com'
        date_col = 'crawl_strdatetime'

    date_func = f"DATE({date_col}::timestamp)" if product_line == 'tv' else f"DATE({date_col})"
    hour_func = f"EXTRACT(HOUR FROM {date_col}::timestamp)"

    cursor.execute(f"""
        WITH today_daily AS (
            SELECT item, account_name, retailer_sku_name as product_name,
                   CAST(REPLACE(count_of_star_ratings, ',', '') AS INTEGER) as review_count,
                   product_url, '일일' as period
            FROM {table}
            WHERE {date_func} = %s
            {f'AND {get_tv_validation_condition()}' if product_line == 'tv' else ''}
            AND count_of_star_ratings IS NOT NULL AND count_of_star_ratings ~ '^[0-9,]+$'
        ),
        yesterday_daily AS (
            SELECT item, account_name,
                   CAST(REPLACE(count_of_star_ratings, ',', '') AS INTEGER) as review_count
            FROM {table}
            WHERE {date_func} = %s
            {f'AND {get_tv_validation_condition()}' if product_line == 'tv' else ''}
            AND count_of_star_ratings IS NOT NULL AND count_of_star_ratings ~ '^[0-9,]+$'
        ),
        daily_changes AS (
            SELECT t.item, t.account_name, t.product_name,
                   y.review_count as prev_count, t.review_count as curr_count,
                   ROUND(((t.review_count - y.review_count)::float / y.review_count * 100)::numeric, 2) as change_pct,
                   t.product_url, t.period,
                   (t.review_count - y.review_count)::float / y.review_count as abs_change
            FROM today_daily t JOIN yesterday_daily y ON t.item = y.item AND t.account_name = y.account_name
            WHERE y.review_count > 0 AND (t.review_count - y.review_count)::float / y.review_count > 0.5
            AND (t.review_count - y.review_count) >= 30
        )
        SELECT item, account_name, product_name, prev_count, curr_count, change_pct, product_url, period
        FROM daily_changes
        ORDER BY abs_change DESC
    """, (target_date, prev_date))

    changes = []
    for row in cursor.fetchall():
        changes.append({
            'item': row[0], 'account_name': row[1],
            'product_name': str(row[2])[:50] + '...' if row[2] and len(str(row[2])) > 50 else row[2],
            'prev_count': row[3], 'curr_count': row[4],
            'change_pct': float(row[5]) if row[5] else None,
            'product_url': row[6], 'period': row[7]
        })

    return {
        'date': str(target_date),
        'compare_date': str(prev_date),
        'product_line': product_line.upper(),
        'check_type': 'review',
        'threshold': '+50%',
        'total_changes': len(changes),
        'changes': changes
    }


def get_price_anomalies(cursor, target_date, product_line):
    if product_line == 'hhp':
        return {
            'date': str(target_date),
            'product_line': product_line.upper(),
            'total_anomalies': 0,
            'anomalies': []
        }

    """가격 이상치 상세 조회"""
    if product_line == 'tv':
        cursor.execute(f"""
            SELECT product_name, account_name, final_sku_price, main_rank, crawl_datetime
            FROM tv_retail_com
            WHERE DATE(crawl_datetime::timestamp) = %s
            AND {get_tv_validation_condition()}
            AND (final_sku_price < 0 OR final_sku_price > 50000)
            ORDER BY final_sku_price DESC
        """, (target_date,))
    else:
        cursor.execute("""
            SELECT product_name, account_name, final_sku_price, main_rank, crawl_strdatetime
            FROM hhp_retail_com
            WHERE DATE(crawl_strdatetime) = %s
            AND (final_sku_price < 0 OR final_sku_price > 5000)
            ORDER BY final_sku_price DESC
        """, (target_date,))

    anomalies = []
    for row in cursor.fetchall():
        anomalies.append({
            'product_name': row[0], 'retailer': row[1],
            'price': float(row[2]) if row[2] else None,
            'rank': row[3],
            'timestamp': str(row[4]) if row[4] else None
        })

    return {
        'date': str(target_date),
        'product_line': product_line.upper(),
        'total_anomalies': len(anomalies),
        'anomalies': anomalies
    }


def get_price_changes(cursor, target_date, product_line, threshold=0.3):
    if product_line == 'hhp':
        return {
            'date': str(target_date),
            'prev_date': str(target_date - timedelta(days=1)),
            'product_line': product_line.upper(),
            'threshold': f'{threshold * 100}%',
            'total_changes': 0,
            'changes': []
        }

    """급격한 가격 변동 조회"""
    prev_date = target_date - timedelta(days=1)

    if product_line == 'tv':
        cursor.execute(f"""
            WITH today AS (
                SELECT item, product_name, account_name, final_sku_price as price, product_url
                FROM tv_retail_com WHERE DATE(crawl_datetime::timestamp) = %s
                AND {get_tv_validation_condition()}
                AND final_sku_price IS NOT NULL
            ),
            yesterday AS (
                SELECT item, product_name, account_name, final_sku_price as price
                FROM tv_retail_com WHERE DATE(crawl_datetime::timestamp) = %s
                AND {get_tv_validation_condition()}
                AND final_sku_price IS NOT NULL
            )
            SELECT t.item, t.account_name, t.product_name,
                   y.price as prev_price, t.price as curr_price,
                   ROUND(((t.price - y.price) / NULLIF(y.price, 0) * 100)::numeric, 2) as change_pct,
                   t.product_url
            FROM today t JOIN yesterday y ON t.item = y.item AND t.account_name = y.account_name
            WHERE ABS(t.price - y.price) / NULLIF(y.price, 0) > %s
            ORDER BY ABS(t.price - y.price) / NULLIF(y.price, 0) DESC
        """, (target_date, prev_date, threshold))
    else:
        cursor.execute("""
            WITH today AS (
                SELECT item, product_name, account_name,
                       CAST(REPLACE(REPLACE(SPLIT_PART(REPLACE(final_sku_price, '$', ''), '/', 1), ',', ''), ' ', '') AS NUMERIC) as price,
                       product_url
                FROM hhp_retail_com WHERE DATE(crawl_strdatetime) = %s
                AND final_sku_price IS NOT NULL AND final_sku_price LIKE '$%%' AND final_sku_price !~ '[a-zA-Z]'
            ),
            yesterday AS (
                SELECT item, product_name, account_name,
                       CAST(REPLACE(REPLACE(SPLIT_PART(REPLACE(final_sku_price, '$', ''), '/', 1), ',', ''), ' ', '') AS NUMERIC) as price
                FROM hhp_retail_com WHERE DATE(crawl_strdatetime) = %s
                AND final_sku_price IS NOT NULL AND final_sku_price LIKE '$%%' AND final_sku_price !~ '[a-zA-Z]'
            )
            SELECT t.item, t.account_name, t.product_name,
                   y.price as prev_price, t.price as curr_price,
                   ROUND(((t.price - y.price) / NULLIF(y.price, 0) * 100)::numeric, 2) as change_pct,
                   t.product_url
            FROM today t JOIN yesterday y ON t.item = y.item AND t.account_name = y.account_name
            WHERE t.price > 0 AND y.price > 0 AND ABS(t.price - y.price) / NULLIF(y.price, 0) > %s
            ORDER BY ABS(t.price - y.price) / NULLIF(y.price, 0) DESC
        """, (target_date, prev_date, threshold))

    changes = []
    for row in cursor.fetchall():
        changes.append({
            'item': row[0], 'retailer': row[1], 'product_name': row[2],
            'prev_price': float(row[3]) if row[3] else None,
            'curr_price': float(row[4]) if row[4] else None,
            'change_pct': float(row[5]) if row[5] else None,
            'product_url': row[6]
        })

    return {
        'date': str(target_date),
        'prev_date': str(prev_date),
        'product_line': product_line.upper(),
        'threshold': f'{threshold * 100}%',
        'total_changes': len(changes),
        'changes': changes
    }
