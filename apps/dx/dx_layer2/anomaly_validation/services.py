"""
anomaly_validation 서비스 — 중복 검증 비즈니스 로직
cursor + params 를 받아 plain dict 를 반환한다.
"""

from apps.common.retail_columns import (
    get_editable_columns, get_duplicate_key_columns,
    get_retailer_list, get_retail_duplicate_keys,
)
from apps.dx.dx_layer2.common.context import get_status


# table 파라미터 화이트리스트
VALID_TABLES_ANOMALY = {
    'tv_retail', 'youtube_videos',
    'market_trend', 'market_product', 'market_event',
}
_YOUTUBE_VIDEO_DUP_KEYS = (
    'video_id', 'keyword', 'collection_country', 'collection_batch_id'
)

# 테이블별 중복 키 / 날짜 컬럼 / 오전오후 구분 매핑
_DUP_TABLE_CONFIG = {
    'tv_retail': {
        'actual': 'tv_retail_com',
        'dup_keys': 'item, account_name',
        'date_col': 'crawl_datetime',
        'use_period': True,
        'retailer_col': 'account_name',
    },
    'youtube_videos': {
        'actual': 'youtube_videos',
        'dup_keys': ', '.join(_YOUTUBE_VIDEO_DUP_KEYS),
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
    'market_trend': {
        'actual': 'market_trend',
        'dup_keys': 'keyword',
        'date_col': 'crawl_at_local_time',
        'use_period': False,
        'retailer_col': None,
    },
    'market_product': {
        'actual': 'market_comp_product',
        'dup_keys': 'batch_id, samsung_series_name, comp_brand, comp_series_name',
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
    'market_event': {
        'actual': 'market_comp_event',
        'dup_keys': 'batch_id, comp_brand, comp_sku_name',
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
}


def _build_dup_delete_query(table, retailer=''):
    """
    중복 그룹에서 최신 1건만 남기고 삭제할 대상의 id + row_to_json 을 조회하는 쿼리를 생성.
    반환: (sql, params)  — sql에는 %s 플레이스홀더, params는 (target_date,) 기준으로 외부에서 결합
    """
    cfg = _DUP_TABLE_CONFIG.get(table)
    if not cfg:
        return None, None

    actual = cfg['actual']
    date_col = cfg['date_col']
    dup_keys = cfg['dup_keys']
    use_period = cfg['use_period']
    retailer_col = cfg['retailer_col']

    # 오전/오후 구분이 필요한 경우
    period_expr = ''
    partition_extra = ''
    if use_period:
        period_expr = f"CASE WHEN EXTRACT(HOUR FROM {date_col}::timestamp) < 12 THEN 'AM' ELSE 'PM' END"
        partition_extra = f', {period_expr}'

    # 리테일러 필터
    retailer_where = ''
    if retailer_col and retailer:
        retailer_where = f"AND {retailer_col} = %s"

    sql = f"""
        SELECT sub.id, sub.record_data FROM (
            SELECT t.id, row_to_json(t.*) as record_data,
                   ROW_NUMBER() OVER (
                       PARTITION BY {dup_keys}{partition_extra}
                       ORDER BY {date_col} DESC
                   ) as rn
            FROM {actual} t
            WHERE DATE({date_col}::timestamp) = %s
              {retailer_where}
        ) sub
        WHERE sub.rn > 1
    """
    return sql, retailer_where


def get_anomaly_detail(cursor, target_date, table, retailer, days, page, page_size):
    """중복 검증 상세 조회 — plain dict 반환"""
    offset = (page - 1) * page_size
    if table == 'hhp_retail':
        return {
            'date': str(target_date),
            'table': table,
            'retailer': retailer,
            'select_cols': {'group': [], 'record': []},
            'editable_cols': [],
            'actual_table': '',
            'results': {
                'duplicates': [],
                'total_groups': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0
            }
        }

    duplicates = []
    total_groups = 0
    select_cols = {'group': [], 'record': []}

    if table == 'tv_retail':
        select_cols = {'group': ['item', 'retailer', 'period', 'dup_count', 'reason'], 'record': ['id', 'product_url', 'crawl_datetime', 'page_type', 'main_rank', 'bsr_rank']}
        # 전체 그룹 수
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period
                FROM tv_retail_com
                WHERE DATE(crawl_datetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date, retailer, retailer))
        total_groups = cursor.fetchone()[0]

        # 중복 그룹 찾기: item + 시간대 (오전/오후 각각 1건만 있어야 정상)
        # page_type은 무시 - main과 bsr에서 같은 item이 수집되는 건 정상
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period,
                       COUNT(*) as dup_count
                FROM tv_retail_com
                WHERE DATE(crawl_datetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, item, period
                LIMIT %s OFFSET %s
            )
            SELECT d.item, d.account_name, d.period, d.dup_count,
                   t.id, t.product_url, t.crawl_datetime, t.page_type, t.main_rank, t.bsr_rank
            FROM duplicate_groups d
            JOIN tv_retail_com t ON t.item IS NOT DISTINCT FROM d.item
                AND t.account_name = d.account_name
                AND DATE(t.crawl_datetime::timestamp) = %s
                AND CASE WHEN EXTRACT(HOUR FROM t.crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END = d.period
            ORDER BY d.dup_count DESC, d.item, d.period, t.crawl_datetime
        """, (target_date, retailer, retailer, page_size, offset, target_date))

        rows = cursor.fetchall()

        # 중복 그룹별로 묶기
        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # item, account_name, period
            if key not in dup_groups:
                dup_groups[key] = {
                    'item': row[0],
                    'retailer': row[1],
                    'period': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 item이 {row[2]}에 {row[3]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[4],
                'product_url': row[5],
                'crawl_datetime': str(row[6]) if row[6] else None,
                'page_type': row[7],
                'main_rank': row[8],
                'bsr_rank': row[9]
            })

        duplicates = list(dup_groups.values())

    elif table == 'hhp_retail':
        select_cols = {'group': ['item', 'retailer', 'period', 'dup_count', 'reason'], 'record': ['id', 'product_url', 'crawl_datetime', 'page_type', 'rank']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period
                FROM hhp_retail_com
                WHERE DATE(crawl_strdatetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date, retailer, retailer))
        total_groups = cursor.fetchone()[0]

        # 중복 그룹 찾기: item + 시간대 (오전/오후 각각 1건만 있어야 정상)
        # trend_rank는 Bestbuy만 있음
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period,
                       COUNT(*) as dup_count
                FROM hhp_retail_com
                WHERE DATE(crawl_strdatetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, item, period
                LIMIT %s OFFSET %s
            )
            SELECT d.item, d.account_name, d.period, d.dup_count,
                   h.id, h.product_url, h.crawl_strdatetime, h.page_type, h.main_rank, h.bsr_rank, h.trend_rank
            FROM duplicate_groups d
            JOIN hhp_retail_com h ON h.item IS NOT DISTINCT FROM d.item
                AND h.account_name = d.account_name
                AND DATE(h.crawl_strdatetime::timestamp) = %s
                AND CASE WHEN EXTRACT(HOUR FROM h.crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END = d.period
            ORDER BY d.dup_count DESC, d.item, d.period, h.crawl_strdatetime
        """, (target_date, retailer, retailer, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # item, account_name, period
            if key not in dup_groups:
                dup_groups[key] = {
                    'item': row[0],
                    'retailer': row[1],
                    'period': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 item이 {row[2]}에 {row[3]}건 수집됨',
                    'records': []
                }
            page_type = row[7]
            # page_type에 따라 해당 rank 선택
            if page_type == 'trend':
                rank = row[10]  # trend_rank (Bestbuy만)
            elif page_type == 'main':
                rank = row[8]   # main_rank
            elif page_type == 'bsr':
                rank = row[9]   # bsr_rank
            else:
                rank = row[8] or row[9]  # fallback
            dup_groups[key]['records'].append({
                'id': row[4],
                'product_url': row[5],
                'crawl_datetime': str(row[6]) if row[6] else None,
                'page_type': page_type,
                'rank': rank
            })

        duplicates = list(dup_groups.values())

    elif table == 'youtube_videos':
        select_cols = {
            'group': [
                'video_id', 'keyword', 'dup_count', 'reason'
            ],
            'record': ['id', 'title', 'created_at']
        }
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                FROM youtube_videos v
                WHERE v.category = 'HHP'
                  AND EXISTS (
                      SELECT 1
                      FROM youtube_country_collection_runs r
                      WHERE r.collection_date = %s
                        AND r.collection_country = v.collection_country
                        AND r.batch_id = v.collection_batch_id
                  )
                GROUP BY
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # 동일 국가·배치 안에서 같은 video_id+keyword가 반복된 경우만 중복이다.
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword,
                    COUNT(*) AS dup_count
                FROM youtube_videos v
                WHERE v.category = 'HHP'
                  AND EXISTS (
                      SELECT 1
                      FROM youtube_country_collection_runs r
                      WHERE r.collection_date = %s
                        AND r.collection_country = v.collection_country
                        AND r.batch_id = v.collection_batch_id
                  )
                GROUP BY
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                HAVING COUNT(*) > 1
                ORDER BY
                    COUNT(*) DESC,
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                LIMIT %s OFFSET %s
            )
            SELECT
                d.collection_country,
                d.collection_batch_id,
                d.video_id,
                d.keyword,
                d.dup_count,
                y.id,
                y.title,
                y.created_at
            FROM duplicate_groups d
            JOIN youtube_videos y
              ON y.collection_country = d.collection_country
             AND y.collection_batch_id = d.collection_batch_id
             AND y.video_id = d.video_id
             AND y.keyword = d.keyword
             AND y.category = 'HHP'
            ORDER BY
                d.dup_count DESC,
                d.collection_country,
                d.collection_batch_id,
                d.video_id,
                d.keyword,
                y.created_at
        """, (target_date, page_size, offset))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2], row[3])
            if key not in dup_groups:
                dup_groups[key] = {
                    'collection_country': row[0],
                    'collection_batch_id': str(row[1]) if row[1] else None,
                    'video_id': row[2],
                    'keyword': row[3],
                    'dup_count': row[4],
                    'reason': (
                        f'동일 국가·배치의 video_id+keyword가 '
                        f'{row[4]}건 수집됨'
                    ),
                    'records': []
                }
            # 제목 50자 제한
            title = row[6][:50] + '...' if row[6] and len(row[6]) > 50 else row[6]
            dup_groups[key]['records'].append({
                'id': row[5],
                'title': title,
                'created_at': str(row[7]) if row[7] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_trend':
        select_cols = {'group': ['keyword', 'dup_count', 'reason'], 'record': ['id', 'total_article_number', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT keyword
                FROM market_trend
                WHERE DATE(crawl_at_local_time) = %s
                GROUP BY keyword
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Trend 중복: 같은 날짜에 keyword 중복
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT keyword, COUNT(*) as dup_count
                FROM market_trend
                WHERE DATE(crawl_at_local_time) = %s
                GROUP BY keyword
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, keyword
                LIMIT %s OFFSET %s
            )
            SELECT d.keyword, d.dup_count,
                   m.id, m.total_article_number, m.crawl_at_local_time
            FROM duplicate_groups d
            JOIN market_trend m ON m.keyword = d.keyword
                AND DATE(m.crawl_at_local_time) = %s
            ORDER BY d.dup_count DESC, d.keyword, m.crawl_at_local_time
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = row[0]  # keyword
            if key not in dup_groups:
                dup_groups[key] = {
                    'keyword': row[0],
                    'dup_count': row[1],
                    'reason': f'동일 keyword가 {row[1]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[2],
                'total_article_number': row[3],
                'created_at': str(row[4]) if row[4] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_product':
        select_cols = {'group': ['batch_id', 'samsung_series_name', 'comp_brand', 'comp_series_name', 'dup_count', 'reason'], 'record': ['id', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT batch_id, samsung_series_name, comp_brand, comp_series_name
                FROM market_comp_product
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, samsung_series_name, comp_brand, comp_series_name
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Product 중복: batch_id + samsung_series_name + comp_brand + comp_series_name
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT batch_id, samsung_series_name, comp_brand, comp_series_name, COUNT(*) as dup_count
                FROM market_comp_product
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, samsung_series_name, comp_brand, comp_series_name
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, batch_id, samsung_series_name
                LIMIT %s OFFSET %s
            )
            SELECT d.batch_id, d.samsung_series_name, d.comp_brand, d.comp_series_name, d.dup_count,
                   m.id, m.created_at
            FROM duplicate_groups d
            JOIN market_comp_product m ON m.batch_id = d.batch_id
                AND m.samsung_series_name = d.samsung_series_name
                AND m.comp_brand = d.comp_brand
                AND m.comp_series_name = d.comp_series_name
                AND DATE(m.created_at) = %s
            ORDER BY d.dup_count DESC, d.batch_id, d.samsung_series_name, m.created_at
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2], row[3])  # batch_id, samsung_series_name, comp_brand, comp_series_name
            if key not in dup_groups:
                dup_groups[key] = {
                    'batch_id': row[0],
                    'samsung_series_name': row[1],
                    'comp_brand': row[2],
                    'comp_series_name': row[3],
                    'dup_count': row[4],
                    'reason': f'동일 조합이 {row[4]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[5],
                'created_at': str(row[6]) if row[6] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_event':
        select_cols = {'group': ['batch_id', 'comp_brand', 'comp_sku_name', 'dup_count', 'reason'], 'record': ['id', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT batch_id, comp_brand, comp_sku_name
                FROM market_comp_event
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, comp_brand, comp_sku_name
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Event 중복: batch_id + comp_brand + comp_sku_name
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT batch_id, comp_brand, comp_sku_name, COUNT(*) as dup_count
                FROM market_comp_event
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, comp_brand, comp_sku_name
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, batch_id, comp_brand
                LIMIT %s OFFSET %s
            )
            SELECT d.batch_id, d.comp_brand, d.comp_sku_name, d.dup_count,
                   m.id, m.created_at
            FROM duplicate_groups d
            JOIN market_comp_event m ON m.batch_id = d.batch_id
                AND m.comp_brand = d.comp_brand
                AND m.comp_sku_name = d.comp_sku_name
                AND DATE(m.created_at) = %s
            ORDER BY d.dup_count DESC, d.batch_id, d.comp_brand, m.created_at
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # batch_id, comp_brand, comp_sku_name
            if key not in dup_groups:
                dup_groups[key] = {
                    'batch_id': row[0],
                    'comp_brand': row[1],
                    'comp_sku_name': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 조합이 {row[3]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[4],
                'created_at': str(row[5]) if row[5] else None
            })

        duplicates = list(dup_groups.values())

    # 수정 가능 컬럼
    editable_cols = []
    actual_table = ''
    if table in ('tv_retail', 'hhp_retail') and retailer:
        product_line = 'tv' if table == 'tv_retail' else 'hhp'
        actual_table = 'tv_retail_com' if table == 'tv_retail' else 'hhp_retail_com'
        editable_cols = get_editable_columns(product_line, retailer)

    total_pages = (total_groups + page_size - 1) // page_size if total_groups > 0 else 0

    return {
        'date': str(target_date),
        'table': table,
        'retailer': retailer,
        'select_cols': select_cols,
        'editable_cols': editable_cols,
        'actual_table': actual_table,
        'results': {
            'duplicates': duplicates,
            'total_groups': total_groups,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        }
    }


def cleanup_duplicates(cursor, conn, table, ids, target_date, username):
    """
    중복 데이터 정리 — 백업 후 삭제.
    cursor/conn 을 받아 plain dict 를 반환한다.
    conn.commit() 는 이 함수 내에서 호출하지 않는다 (api 에서 처리).
    """
    import json as json_mod
    from datetime import datetime

    cfg = _DUP_TABLE_CONFIG[table]
    actual_table = cfg['actual']
    dup_keys = cfg['dup_keys'] or 'keyword_id'
    use_period = cfg.get('use_period', False)
    date_col = cfg.get('date_col', '')
    backup_table = 'monitoring_duplicate_deletes'

    now = datetime.now()

    # 1. 삭제 대상 전체 행 조회 (백업용)
    id_placeholders = ', '.join(['%s'] * len(ids))
    cursor.execute(
        f"SELECT id, row_to_json(t.*) as record_data FROM {actual_table} t WHERE id IN ({id_placeholders})",
        ids
    )
    rows = cursor.fetchall()

    if not rows:
        return {'success': True, 'deleted_count': 0, 'message': '해당 레코드가 존재하지 않습니다.'}

    # 2. 백업 INSERT + corrections 이력 저장
    for row in rows:
        record_id = row[0]
        record_data = row[1]

        if isinstance(record_data, str):
            record_json = record_data
            record_dict = json_mod.loads(record_data)
        else:
            record_json = json_mod.dumps(record_data, default=str)
            record_dict = record_data

        # 백업 (dup_group_key: 중복 판별 기준 컬럼명 + period 실제값)
        if use_period:
            date_val = str(record_dict.get(date_col, ''))
            try:
                hour = int(date_val[11:13])
                period_label = '오전' if hour < 12 else '오후'
            except (ValueError, IndexError):
                period_label = ''
            group_key_meta = dup_keys + ', period(' + period_label + ')'
        else:
            group_key_meta = dup_keys
        cursor.execute(f"""
            INSERT INTO {backup_table}
                (source_table, record_id, record_data, dup_group_key, crawl_date, deleted_by, deleted_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
        """, (
            actual_table, record_id, record_json,
            group_key_meta, target_date, username, now
        ))

        # corrections 이력
        item_col_name = dup_keys.split(',')[0].strip() if dup_keys else None
        item_value = str(record_dict.get(item_col_name, '')) if item_col_name else ''
        retailer_col = cfg.get('retailer_col')
        retailer_value = str(record_dict.get(retailer_col, '')) if retailer_col else ''
        cursor.execute("""
            INSERT INTO monitoring_corrections
                (layer, correction_type, column_name, table_name, record_id,
                 crawl_date, created_id, created_at, status, memo, retailer, item)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            2, 'duplicate_check', 'item', actual_table, record_id,
            target_date, username, now, 'corrected', '중복 삭제', retailer_value,
            item_value or None
        ))

    # 3. DELETE
    fetched_ids = [row[0] for row in rows]
    del_placeholders = ', '.join(['%s'] * len(fetched_ids))
    cursor.execute(f"DELETE FROM {actual_table} WHERE id IN ({del_placeholders})", fetched_ids)

    deleted_count = cursor.rowcount

    return {
        'success': True,
        'deleted_count': deleted_count,
        'backup_table': backup_table,
    }


def get_duplicate_count(cursor, table_name, date_col, dup_keys, target_date, use_period=False, group_by_col=None):
    """스케줄 기반 중복 검증 쿼리 실행"""
    dup_keys_sql = ', '.join(dup_keys)

    if use_period:
        period_expr = f"CASE WHEN EXTRACT(HOUR FROM {date_col}::timestamp) < 12 THEN '오전' ELSE '오후' END as period"
        if group_by_col:
            cursor.execute(f"""
                SELECT {group_by_col}, COUNT(*) as dup_groups FROM (
                    SELECT {dup_keys_sql}, {period_expr}
                    FROM {table_name}
                    WHERE DATE({date_col}::timestamp) = %s
                    GROUP BY {dup_keys_sql}, period
                    HAVING COUNT(*) > 1
                ) sub
                GROUP BY {group_by_col}
                ORDER BY {group_by_col}
            """, (target_date,))
            return {row[0]: row[1] for row in cursor.fetchall()}
        else:
            cursor.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT {dup_keys_sql}, {period_expr}
                    FROM {table_name}
                    WHERE DATE({date_col}::timestamp) = %s
                    GROUP BY {dup_keys_sql}, period
                    HAVING COUNT(*) > 1
                ) sub
            """, (target_date,))
            return cursor.fetchone()[0] or 0
    else:
        cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {dup_keys_sql}
                FROM {table_name}
                WHERE DATE({date_col}) = %s
                GROUP BY {dup_keys_sql}
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        return cursor.fetchone()[0] or 0


def _get_youtube_video_duplicate_stats(cursor, target_date):
    """신규 국가·배치에 연결된 HHP 영상만 대상으로 중복 통계를 구한다."""
    scope_sql = """
        FROM youtube_videos v
        WHERE v.category = 'HHP'
          AND EXISTS (
              SELECT 1
              FROM youtube_country_collection_runs r
              WHERE r.collection_date = %s
                AND r.collection_country = v.collection_country
                AND r.batch_id = v.collection_batch_id
          )
    """
    params = (target_date,)

    cursor.execute(f"SELECT COUNT(*) {scope_sql}", params)
    total_records = cursor.fetchone()[0] or 0

    cursor.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT {', '.join('v.' + key for key in _YOUTUBE_VIDEO_DUP_KEYS)}
            {scope_sql}
            GROUP BY {', '.join('v.' + key for key in _YOUTUBE_VIDEO_DUP_KEYS)}
            HAVING COUNT(*) > 1
        ) duplicate_groups
    """, params)
    duplicate_groups = cursor.fetchone()[0] or 0

    return {
        'total_records': total_records,
        'duplicate_groups': duplicate_groups,
        'duplicate_keys': list(_YOUTUBE_VIDEO_DUP_KEYS),
    }


def get_anomaly_stats(cursor, target_date, include_youtube=True):
    """중복 검증 통계 — 대시보드용"""
    total_anomaly_issues = 0
    anomaly_validation = {
        'type': 'duplicate',
        'type_name': '중복 검증',
        'type_name_en': 'Duplicate Validation',
        'description': '동일 시간대 동일 상품 중복 수집 탐지',
        'icon': '🔄',
        'tables': []
    }

    # TV Retail 중복 검증
    tv_dup_keys = get_retail_duplicate_keys('tv')
    if not tv_dup_keys:
        tv_dup_keys = ['item', 'account_name']
    tv_date_col = 'crawl_datetime'

    cursor.execute(f"SELECT COUNT(*) FROM tv_retail_com WHERE DATE({tv_date_col}::timestamp) = %s", (target_date,))
    tv_total_records = cursor.fetchone()[0] or 0

    retailer_list = get_retailer_list()
    tv_dup_dict = get_duplicate_count(cursor, 'tv_retail_com', tv_date_col, tv_dup_keys, target_date, use_period=True, group_by_col='account_name')

    # 정상처리 차감
    tv_dup_normal = {}
    try:
        cursor.execute("""
            SELECT retailer, COUNT(*) FROM monitoring_corrections
            WHERE table_name = 'tv_retail_com' AND crawl_date = %s
              AND correction_type = 'duplicate_check' AND status = 'normal'
            GROUP BY retailer
        """, (str(target_date),))
        for nr in cursor.fetchall():
            tv_dup_normal[nr[0]] = nr[1]
    except Exception:
        pass

    tv_dup_retailers = []
    tv_dup_total = 0
    for retailer_name in retailer_list:
        dup_count = max(0, tv_dup_dict.get(retailer_name, 0) - tv_dup_normal.get(retailer_name, 0))
        tv_dup_retailers.append({
            'retailer': retailer_name,
            'duplicate_groups': dup_count,
            'status': get_status(dup_count)
        })
        tv_dup_total += dup_count

    # TV Retail 가격 이상
    cursor.execute("""
        SELECT COUNT(*) FROM tv_retail_com
        WHERE DATE(crawl_datetime::timestamp) = %s
        AND final_sku_price ~ '^\$[\d,]+\.?\d*$'
        AND (
            CAST(REPLACE(REPLACE(final_sku_price, '$', ''), ',', '') AS DECIMAL) < 0
            OR CAST(REPLACE(REPLACE(final_sku_price, '$', ''), ',', '') AS DECIMAL) > 50000
        )
    """, (target_date,))
    tv_price_anomaly = cursor.fetchone()[0] or 0

    anomaly_validation['tables'].append({
        'table': 'tv_retail',
        'table_name': 'TV Retail',
        'total_records': tv_total_records,
        'total_issues': tv_dup_total,
        'duplicate_groups': tv_dup_total,
        'duplicate_keys': tv_dup_keys,
        'status': get_status(tv_dup_total),
        'retailers': tv_dup_retailers
    })
    total_anomaly_issues += tv_dup_total

    # HHP Retail 중복 검증
    hhp_dup_keys = get_retail_duplicate_keys('hhp')
    if not hhp_dup_keys:
        hhp_dup_keys = ['item', 'account_name']
    hhp_date_col = 'crawl_strdatetime'

    hhp_total_records = 0

    hhp_dup_dict = {}

    hhp_dup_normal = {}
    try:
        if False:
            cursor.execute("""
            SELECT retailer, COUNT(*) FROM monitoring_corrections
            WHERE table_name = 'hhp_retail_com' AND crawl_date = %s
              AND correction_type = 'duplicate_check' AND status = 'normal'
            GROUP BY retailer
            """, (str(target_date),))
            for nr in cursor.fetchall():
                hhp_dup_normal[nr[0]] = nr[1]
    except Exception:
        pass

    hhp_dup_retailers = []
    hhp_dup_total = 0
    for retailer_name in retailer_list:
        dup_count = max(0, hhp_dup_dict.get(retailer_name, 0) - hhp_dup_normal.get(retailer_name, 0))
        hhp_dup_retailers.append({
            'retailer': retailer_name,
            'duplicate_groups': dup_count,
            'status': get_status(dup_count)
        })
        hhp_dup_total += dup_count

    anomaly_validation['tables'].append({
        'table': 'hhp_retail',
        'table_name': 'HHP Retail',
        'total_records': hhp_total_records,
        'total_issues': hhp_dup_total,
        'duplicate_groups': hhp_dup_total,
        'duplicate_keys': hhp_dup_keys,
        'status': get_status(hhp_dup_total),
        'retailers': hhp_dup_retailers
    })
    total_anomaly_issues += hhp_dup_total
    anomaly_validation['tables'] = [t for t in anomaly_validation['tables'] if t.get('table') != 'hhp_retail']
    total_anomaly_issues -= hhp_dup_total

    if include_youtube:
        # 타 국가·타 배치는 서로 다른 정상 수집이므로 동일 범위만 비교한다.
        youtube_dup_stats = _get_youtube_video_duplicate_stats(
            cursor, target_date
        )
        ytv_dup_keys = youtube_dup_stats['duplicate_keys']
        ytv_total_records = youtube_dup_stats['total_records']
        ytv_dup_total = youtube_dup_stats['duplicate_groups']

        yt_total_issues = ytv_dup_total
        anomaly_validation['tables'].append({
            'table': 'youtube',
            'table_name': 'YouTube',
            'total_records': ytv_total_records,
            'total_issues': yt_total_issues,
            'duplicate_groups': yt_total_issues,
            'status': get_status(yt_total_issues),
            'retailers': [
                {
                    'retailer': 'Videos',
                    'total': ytv_total_records,
                    'duplicate_groups': ytv_dup_total,
                    'duplicate_keys': ytv_dup_keys,
                    'status': get_status(ytv_dup_total)
                }
            ]
        })
        total_anomaly_issues += yt_total_issues

    # Market 중복
    mt_dup_info = get_duplicate_key_columns('market_trend')
    mt_date_col = mt_dup_info['date_column'] if mt_dup_info else 'crawl_at_local_time'
    mt_dup_keys = mt_dup_info['duplicate_keys'] if mt_dup_info else ['keyword']

    cursor.execute(f"SELECT COUNT(*) FROM market_trend WHERE DATE({mt_date_col}) = %s", (target_date,))
    market_trend_total = cursor.fetchone()[0] or 0
    market_trend_dup = get_duplicate_count(cursor, 'market_trend', mt_date_col, mt_dup_keys, target_date)

    mp_dup_info = get_duplicate_key_columns('market_comp_product')
    mp_date_col = mp_dup_info['date_column'] if mp_dup_info else 'created_at'
    mp_dup_keys = mp_dup_info['duplicate_keys'] if mp_dup_info else ['batch_id', 'samsung_series_name', 'comp_brand', 'comp_series_name']

    cursor.execute(f"SELECT COUNT(*) FROM market_comp_product WHERE DATE({mp_date_col}) = %s", (target_date,))
    market_product_total = cursor.fetchone()[0] or 0
    market_product_dup = get_duplicate_count(cursor, 'market_comp_product', mp_date_col, mp_dup_keys, target_date)

    me_dup_info = get_duplicate_key_columns('market_comp_event')
    me_date_col = me_dup_info['date_column'] if me_dup_info else 'created_at'
    me_dup_keys = me_dup_info['duplicate_keys'] if me_dup_info else ['batch_id', 'comp_brand', 'comp_sku_name']

    cursor.execute(f"SELECT COUNT(*) FROM market_comp_event WHERE DATE({me_date_col}) = %s", (target_date,))
    market_event_total = cursor.fetchone()[0] or 0
    market_event_dup = get_duplicate_count(cursor, 'market_comp_event', me_date_col, me_dup_keys, target_date)

    market_total_dup = market_trend_dup + market_product_dup + market_event_dup
    anomaly_validation['tables'].append({
        'table': 'market',
        'table_name': 'Market',
        'total_records': market_trend_total + market_product_total + market_event_total,
        'total_issues': market_total_dup,
        'duplicate_groups': market_total_dup,
        'status': get_status(market_total_dup),
        'retailers': [
            {
                'retailer': 'Trend',
                'total': market_trend_total,
                'duplicate_groups': market_trend_dup,
                'duplicate_keys': mt_dup_keys,
                'status': get_status(market_trend_dup)
            },
            {
                'retailer': 'Product',
                'total': market_product_total,
                'duplicate_groups': market_product_dup,
                'duplicate_keys': mp_dup_keys,
                'status': get_status(market_product_dup)
            },
            {
                'retailer': 'Event',
                'total': market_event_total,
                'duplicate_groups': market_event_dup,
                'duplicate_keys': me_dup_keys,
                'status': get_status(market_event_dup)
            }
        ]
    })
    total_anomaly_issues += market_total_dup

    anomaly_validation['total_issues'] = total_anomaly_issues
    anomaly_validation['status'] = get_status(total_anomaly_issues)

    return anomaly_validation, total_anomaly_issues
