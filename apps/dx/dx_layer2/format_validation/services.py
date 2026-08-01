"""
형식 검증 서비스 — 순수 비즈니스 로직 (DB 커넥션/HTTP 무관)
"""

from datetime import timedelta

from apps.common.retail_columns import (
    validate_field,
    build_format_error_sql,
    build_per_field_error_sql,
    get_editable_columns,
)
from apps.common.db import dx_table
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer2.common.context import get_status


# table 파라미터 화이트리스트
VALID_TABLES_FORMAT = {
    'tv_retail',
    'market',
}
VALID_TABLES_RULES = {
    'tv_retail_com',
    'market_trend', 'market_comp_product', 'market_comp_event',
    'openai_forecast_results',
}


# ── thin wrappers ──────────────────────────────────────────

def validate_tv_field(field_name, value, account_name='Amazon'):
    """TV Retail 필드별 형식 검증. 오류 시 메시지 반환, 정상이면 None"""
    return validate_field('tv_retail_com', field_name, value, account_name, product_line='TV')


def validate_hhp_field(field_name, value, account_name='Amazon'):
    """HHP Retail 필드별 형식 검증. 오류 시 메시지 반환, 정상이면 None"""
    return validate_field('hhp_retail_com', field_name, value, account_name, product_line='HHP')


# ── 형식 오류 상세 조회 ───────────────────────────────────

def get_format_detail(cursor, target_date, table, retailer, days):
    """
    형식 오류 상세 조회.
    Returns dict: {date, table, retailer, column_names, editable_cols, actual_table, normal_reviews, results}
    """
    results = []
    select_cols = []
    column_names = []
    next_date = target_date + timedelta(days=1)
    if table == 'hhp_retail':
        return {
            'date': str(target_date),
            'table': table,
            'retailer': retailer,
            'column_names': [],
            'editable_cols': [],
            'actual_table': '',
            'normal_reviews': {},
            'results': []
        }

    # TV Retail 형식 오류 상세 조회 - SQL 조건으로 오류 행 직접 필터링
    if table == 'tv_retail':
        select_cols = ['id', 'item', 'crawl_datetime', 'product_url']
        all_fields = [
            'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
            'final_sku_price', 'original_sku_price',
            'count_of_reviews', 'star_rating', 'count_of_star_ratings',
            'detailed_review_content',
            'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
            'sku_popularity', 'retailer_membership_discounts',
            'rank_1', 'rank_2', 'summarized_review_content',
            'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
            'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
        ]
        column_names = ['id', 'crawl_datetime'] + all_fields

        # 형식 규칙 → SQL WHERE 조건 변환
        error_where = build_format_error_sql('tv_retail_com', 'TV', retailer)

        query = f"""
            SELECT
                id, crawl_datetime, account_name, {', '.join(all_fields)}
            FROM tv_retail_com
            WHERE crawl_datetime::timestamp >= %s AND crawl_datetime::timestamp < %s
              AND {get_tv_validation_condition()}
        """
        params = [str(target_date), str(next_date)]
        if retailer:
            query += " AND account_name = %s"
            params.append(retailer)
        query += f" AND ({error_where})"
        query += " ORDER BY account_name, crawl_datetime"

        cursor.execute(query, params)
        for row in cursor.fetchall():
            record_id = row[0]
            crawl_dt = row[1]
            account_name = row[2]
            values = list(row[3:])

            record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
            for field, value in zip(all_fields, values):
                record[field] = str(value) if value is not None else None

            # 오류 행 내 개별 필드 오류 식별 (Python 검증, 소수 행만 대상)
            error_fields = []
            error_details = {}
            for field, value in zip(all_fields, values):
                error = validate_tv_field(field, value, account_name)
                if error:
                    error_fields.append(field)
                    error_details[field] = {
                        'rule': error.split(':', 1)[0] if ':' in error else error,
                        'reason': error.split(':', 1)[1].strip() if ':' in error else error
                    }

            if error_fields:
                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # HHP Retail 형식 오류 상세 조회 - SQL 조건으로 오류 행 직접 필터링
    elif table == 'hhp_retail':
        select_cols = ['id', 'item', 'crawl_datetime', 'product_url']
        cursor.execute("SELECT DISTINCT item FROM hhp_item_mst")
        hhp_valid_items = set(row[0] for row in cursor.fetchall())

        hhp_fields = [
            'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
            'final_sku_price', 'original_sku_price',
            'count_of_reviews', 'star_rating', 'count_of_star_ratings',
            'detailed_review_content', 'trade_in', 'sku_status',
            'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
            'sku_popularity', 'retailer_membership_discounts',
            'rank_1', 'rank_2', 'summarized_review_content',
            'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
            'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
        ]
        column_names = ['id', 'crawl_datetime'] + hhp_fields

        # 형식 규칙 → SQL WHERE 조건 변환 + item 참조 무결성 체크
        error_where = build_format_error_sql('hhp_retail_com', 'HHP', retailer)
        item_check = "item IS NOT NULL AND TRIM(item::text) != '' AND item NOT IN (SELECT DISTINCT item FROM hhp_item_mst)"
        full_error_where = f"({error_where}) OR ({item_check})"

        query = f"""
            SELECT
                id, crawl_strdatetime, account_name, {', '.join(hhp_fields)}
            FROM hhp_retail_com
            WHERE crawl_strdatetime::timestamp >= %s AND crawl_strdatetime::timestamp < %s
        """
        params = [str(target_date), str(next_date)]
        if retailer:
            query += " AND account_name = %s"
            params.append(retailer)
        query += f" AND ({full_error_where})"
        query += " ORDER BY account_name, crawl_strdatetime"

        cursor.execute(query, params)
        for row in cursor.fetchall():
            record_id = row[0]
            crawl_dt = row[1]
            account_name = row[2]
            values = list(row[3:])

            record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
            for field, value in zip(hhp_fields, values):
                record[field] = str(value) if value is not None else None

            # 오류 행 내 개별 필드 오류 식별 (Python 검증, 소수 행만 대상)
            error_fields = []
            error_details = {}
            for field, value in zip(hhp_fields, values):
                error = validate_hhp_field(field, value, account_name)
                if error:
                    error_fields.append(field)
                    error_details[field] = {
                        'rule': error.split(':', 1)[0] if ':' in error else error,
                        'reason': error.split(':', 1)[1].strip() if ':' in error else error
                    }

            item = values[0]  # hhp_fields[0] = 'item'
            if item and item not in hhp_valid_items:
                error_fields.append('item')
                error_details['item'] = {
                    'rule': '참조 무결성',
                    'reason': '마스터 테이블에 등록되지 않은 item'
                }

            if error_fields:
                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # YouTube 형식 오류 상세 조회 — 규칙 테이블 기반
    elif table == 'youtube_logs' or (table == 'youtube' and retailer == 'Logs'):
        db_table = 'youtube_collection_logs'
        account_name = 'Logs'
        date_col = 'started_at'
        all_fields = ['keyword', 'status', 'videos_collected', 'comments_collected', 'started_at']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'id, ' + ', '.join(all_fields + case_cols) if case_cols else 'id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    elif table == 'youtube_videos' or (table == 'youtube' and retailer == 'Videos'):
        db_table = 'youtube_videos'
        account_name = 'Videos'
        date_col = 'created_at'
        all_fields = ['video_id', 'keyword', 'channel_custom_url', 'category',
                      'engagement_rate', 'product_sentiment_score', 'published_at', 'created_at',
                      'channel_subscriber_count', 'channel_video_count', 'view_count', 'like_count', 'comment_count']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = ', '.join(all_fields + case_cols) if case_cols else ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                values = list(row[:len(all_fields)])
                err_flags = list(row[len(all_fields):])

                record = {'id': values[0]}  # video_id as id
                for field, value in zip(all_fields, values):
                    if field in ('engagement_rate', 'product_sentiment_score'):
                        record[field] = float(value) if value is not None else None
                    elif field in ('published_at', 'created_at'):
                        record[field] = str(value)[:19] if value else None
                    else:
                        record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    elif table == 'youtube_comments' or (table == 'youtube' and retailer == 'Comments'):
        db_table = 'youtube_comments'
        account_name = 'Comments'
        date_col = 'created_at'
        all_fields = ['video_id', 'comment_type', 'parent_comment_id', 'like_count', 'reply_count', 'published_at', 'created_at']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'comment_id, ' + ', '.join(all_fields + case_cols) if case_cols else 'comment_id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY comment_id DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    if field in ('published_at', 'created_at'):
                        record[field] = str(value)[:19] if value else None
                    else:
                        record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # Market 형식 오류 상세 조회 — 규칙 테이블 기반
    elif table == 'market' and retailer in ('Trend', 'Comp Product', 'Comp Event', 'Forecast'):
        market_config = {
            'Trend': ('market_trend', 'crawl_at_local_time', ['keyword', 'total_article_number', 'calendar_week', 'crawl_at_local_time']),
            'Comp Product': ('market_comp_product', 'created_at', ['samsung_series_name', 'comp_brand', 'calender_week', 'category', 'created_at']),
            'Comp Event': ('market_comp_event', 'created_at', ['comp_brand', 'comp_sku_name', 'calender_week', 'category', 'created_at']),
            'Forecast': ('openai_forecast_results', 'crawled_at', ['product_name', 'event', 'metric_type', 'event_offset', 'event_value', 'week', 'crawled_at']),
        }
        db_table, date_col, all_fields = market_config[retailer]
        account_name = retailer
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'id, ' + ', '.join(all_fields + case_cols) if case_cols else 'id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # retail + days > 1: 오류 item으로 N일치 확장 재조회
    if days > 1 and table in ('tv_retail', 'hhp_retail') and results:
        error_items = list(set(r['item'] for r in results if r.get('item')))
        if error_items:
            start_date = target_date - timedelta(days=days - 1)
            placeholders = ', '.join(['%s'] * len(error_items))
            results = []

            if table == 'tv_retail':
                query = f"""
                    SELECT
                        id, crawl_datetime, account_name, item, page_type, product_url,
                        main_rank, bsr_rank, final_sku_price, original_sku_price,
                        count_of_reviews, star_rating, count_of_star_ratings,
                        detailed_review_content,
                        number_of_units_purchased_past_month, available_quantity_for_purchase,
                        sku_popularity, retailer_membership_discounts,
                        rank_1, rank_2, summarized_review_content,
                        savings, offer, retailer_sku_name_similar, recommendation_intent,
                        number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
                    FROM tv_retail_com
                    WHERE crawl_datetime::timestamp >= %s AND crawl_datetime::timestamp < %s
                      AND {get_tv_validation_condition()}
                      AND account_name = %s AND item IN ({placeholders})
                    ORDER BY item, crawl_datetime
                """
                expand_params = [str(start_date), str(next_date), retailer] + error_items
                cursor.execute(query, expand_params)
                rows = cursor.fetchall()
                all_fields = [
                    'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
                    'final_sku_price', 'original_sku_price',
                    'count_of_reviews', 'star_rating', 'count_of_star_ratings',
                    'detailed_review_content',
                    'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
                    'sku_popularity', 'retailer_membership_discounts',
                    'rank_1', 'rank_2', 'summarized_review_content',
                    'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
                    'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
                ]
                for row in rows:
                    record_id = row[0]
                    crawl_dt = row[1]
                    account_name = row[2]
                    values = list(row[3:])

                    record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
                    for field, value in zip(all_fields, values):
                        record[field] = str(value) if value is not None else None

                    error_fields = []
                    error_details = {}
                    for field, value in zip(all_fields, values):
                        error = validate_tv_field(field, value, account_name)
                        if error:
                            error_fields.append(field)
                            error_details[field] = {
                                'rule': error.split(':', 1)[0] if ':' in error else error,
                                'reason': error.split(':', 1)[1].strip() if ':' in error else error
                            }
                    record['error_fields'] = error_fields
                    record['error_details'] = error_details
                    results.append(record)

            elif table == 'hhp_retail':
                query = f"""
                    SELECT
                        id, crawl_strdatetime, account_name, item, page_type, product_url,
                        main_rank, bsr_rank, trend_rank, final_sku_price, original_sku_price,
                        count_of_reviews, star_rating, count_of_star_ratings,
                        detailed_review_content, trade_in, sku_status,
                        number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
                        sku_popularity, retailer_membership_discounts,
                        rank_1, rank_2, summarized_review_content,
                        savings, offer, retailer_sku_name_similar, recommendation_intent,
                        number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
                    FROM hhp_retail_com
                    WHERE crawl_strdatetime::timestamp >= %s AND crawl_strdatetime::timestamp < %s
                      AND account_name = %s AND item IN ({placeholders})
                    ORDER BY item, crawl_strdatetime
                """
                expand_params = [str(start_date), str(next_date), retailer] + error_items
                cursor.execute(query, expand_params)
                rows = cursor.fetchall()
                hhp_fields = [
                    'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
                    'final_sku_price', 'original_sku_price',
                    'count_of_reviews', 'star_rating', 'count_of_star_ratings',
                    'detailed_review_content', 'trade_in', 'sku_status',
                    'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
                    'sku_popularity', 'retailer_membership_discounts',
                    'rank_1', 'rank_2', 'summarized_review_content',
                    'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
                    'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
                ]
                for row in rows:
                    record_id = row[0]
                    crawl_dt = row[1]
                    account_name = row[2]
                    values = list(row[3:])

                    record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
                    for field, value in zip(hhp_fields, values):
                        record[field] = str(value) if value is not None else None

                    error_fields = []
                    error_details = {}
                    for field, value in zip(hhp_fields, values):
                        error = validate_hhp_field(field, value, account_name)
                        if error:
                            error_fields.append(field)
                            error_details[field] = {
                                'rule': error.split(':', 1)[0] if ':' in error else error,
                                'reason': error.split(':', 1)[1].strip() if ':' in error else error
                            }
                    record['error_fields'] = error_fields
                    record['error_details'] = error_details
                    results.append(record)

    # 수정 가능 컬럼 + actual_table 설정
    editable_cols = []
    actual_table = ''
    if table in ('tv_retail', 'hhp_retail') and retailer:
        product_line = 'tv' if table == 'tv_retail' else 'hhp'
        actual_table = 'tv_retail_com' if table == 'tv_retail' else 'hhp_retail_com'
        editable_cols = get_editable_columns(product_line, retailer)
    elif table in ('youtube_logs',) or (table == 'youtube' and retailer == 'Logs'):
        actual_table = 'youtube_collection_logs'
    elif table in ('youtube_videos',) or (table == 'youtube' and retailer == 'Videos'):
        actual_table = 'youtube_videos'
    elif table in ('youtube_comments',) or (table == 'youtube' and retailer == 'Comments'):
        actual_table = 'youtube_comments'
    elif table == 'market' and retailer:
        market_table_map = {
            'Trend': 'market_trend',
            'Comp Product': 'market_comp_product',
            'Comp Event': 'market_comp_event',
            'Forecast': 'openai_forecast_results',
        }
        actual_table = market_table_map.get(retailer, '')

    # 형식 검증 정상 처리 건 조회
    normal_reviews = {}
    if actual_table:
        cursor.execute("""
            SELECT record_id, column_name, memo, created_id, created_at, reason
            FROM monitoring_corrections
            WHERE table_name = %s AND crawl_date = %s
              AND correction_type = 'format_check' AND status = 'normal'
        """, (actual_table, str(target_date)))
        for nr_row in cursor.fetchall():
            normal_reviews[f"{nr_row[0]}_{nr_row[1]}"] = {
                'memo': nr_row[2],
                'created_id': nr_row[3],
                'created_at': nr_row[4].strftime('%Y-%m-%d %H:%M:%S') if nr_row[4] else None,
                'reason': nr_row[5]
            }

    # 정상 처리된 필드는 error_fields에서 제외 (null_detail의 normal_set 패턴)
    if normal_reviews:
        normal_set = set(normal_reviews.keys())
        for record in results:
            if 'error_fields' in record:
                record_id = record.get('id')
                record['error_fields'] = [
                    f for f in record['error_fields']
                    if f"{record_id}_{f}" not in normal_set
                ]

    # 필드별 건수 집계 (프론트에서 재계산하지 않도록 백엔드에서 계산)
    field_counts = {}
    total_format_count = 0
    for record in results:
        for field in record.get('error_fields', []):
            field_counts[field] = field_counts.get(field, 0) + 1
            total_format_count += 1

    return {
        'date': str(target_date),
        'table': table,
        'retailer': retailer,
        'column_names': column_names,
        'editable_cols': editable_cols,
        'actual_table': actual_table,
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': field_counts,
        'total_format_count': total_format_count,
    }


# ── 형식 검증 규칙 조회 ──────────────────────────────────

def _get_description_for_type(rule_type, rule_value, allowed):
    """규칙 타입별 설명 생성"""
    if rule_type == 'regex':
        if rule_value == '^[A-Za-z0-9]+$':
            return '알파벳+숫자만 허용'
        elif '\\$' in rule_value:
            return '$금액 형식'
        elif '\\d' in rule_value:
            return '숫자 형식'
        elif 'http' in rule_value:
            return 'http:// 또는 https:// 시작'
        else:
            return '정규식 패턴'
    return '형식 검증'


def get_format_rules(cursor, table_name, retailer):
    """
    형식검증 규칙 조회.
    Returns dict: {rules: [...]}
    """
    tbl_rules = dx_table('monitoring_format_rules')
    tbl_templates = dx_table('monitoring_format_templates')

    cursor.execute(f"""
        SELECT r.column_name, t.check_type, t.pattern,
               r.rule_value, r.extra_allowed,
               r.error_message
        FROM {tbl_rules} r
        LEFT JOIN {tbl_templates} t ON r.template_id = t.id
        WHERE r.table_name = %s AND r.account_name = %s
          AND r.is_active = TRUE AND r.is_del = FALSE
          AND (t.id IS NULL OR t.is_active = TRUE)
        ORDER BY r.column_name
    """, (table_name, retailer))

    cols = [desc[0] for desc in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

    result = []
    for row in rows:
        check_type = row.get('check_type') or ''
        pattern = row.get('pattern') or ''
        rule_value = row.get('rule_value') or ''
        extra_allowed = row.get('extra_allowed') or ''
        error_message = row.get('error_message') or ''

        patterns = []
        description = ''

        # 메인 검증 규칙 (template 기반)
        if check_type:
            if check_type in ('regex', 'regex_clean'):
                patterns.append(pattern)
                description = error_message or _get_description_for_type(check_type, pattern, [])
            elif check_type == 'range':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} ~ {parts[1]}')
                    description = error_message or f'{parts[0]}~{parts[1]} 범위 정수'
            elif check_type == 'range_float':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} ~ {parts[1]}')
                    description = error_message or f'{parts[0]}~{parts[1]} 범위'
            elif check_type == 'enum':
                allowed_list = [v.strip() for v in rule_value.split('|') if v.strip()] if rule_value else []
                patterns.append(' | '.join(allowed_list))
                description = error_message or '허용값만'
            elif check_type == 'starts_with':
                patterns.append(f'"{rule_value}..."')
                description = error_message or f'{rule_value}로 시작'
            elif check_type == 'separator_count':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} 구분자 {parts[1]}개')
                    description = error_message or f'{parts[0]} 구분자 {parts[1]}개 필요'
            elif check_type == 'fk_check':
                patterns.append(f'참조: {rule_value}')
                description = error_message or 'FK 참조 검증'
            elif check_type == 'min':
                patterns.append(f'>= {rule_value}')
                description = error_message or f'{rule_value} 이상'

        # extra_allowed 표시
        if extra_allowed:
            allowed_list = [v.strip() for v in extra_allowed.split('|') if v.strip()]
            for val in allowed_list:
                patterns.append(f'"{val}"')

        if patterns:
            result.append({
                'field': row['column_name'],
                'description': description or '형식 검증',
                'pattern': '\n'.join(patterns)
            })

    # 필드명 알파벳순 정렬
    result.sort(key=lambda x: x['field'])

    return {'rules': result}


# ── 대시보드용 헬퍼 / 통계 ─────────────────────────────────

def get_tv_format_errors(cursor, table_name, date_field, target_date, retailer):
    """TV 형식 오류 데이터 조회 - validate_tv_field 기반"""
    errors = []
    all_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]
    cursor.execute(f"""
        SELECT
            id, item, {date_field}, product_url,
            page_type, main_rank, bsr_rank,
            final_sku_price, original_sku_price,
            count_of_reviews, star_rating, count_of_star_ratings,
            detailed_review_content,
            number_of_units_purchased_past_month, available_quantity_for_purchase,
            sku_popularity, retailer_membership_discounts,
            rank_1, rank_2, summarized_review_content,
            savings, offer, retailer_sku_name_similar, recommendation_intent,
            number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
        FROM {table_name}
        WHERE DATE({date_field}::timestamp) = %s
          AND account_name = %s
          AND {get_tv_validation_condition()}
        ORDER BY id
    """, (target_date, retailer))
    for row in cursor.fetchall():
        record_id = row[0]
        item = row[1]
        crawl_dt = row[2]
        product_url = row[3]
        values = [item] + list(row[4:])
        row_errors = []
        for field, value in zip(all_fields, values):
            error = validate_tv_field(field, value, retailer)
            if error:
                row_errors.append(field)
        if row_errors:
            errors.append({
                'id': record_id,
                'item': item,
                'error_field': ', '.join(row_errors),
                'error_value': ', '.join(row_errors),
                'collected_at': str(crawl_dt) if crawl_dt else None
            })
    return errors


def get_hhp_format_errors(cursor, table_name, date_field, target_date, retailer):
    """HHP 형식 오류 데이터 조회 - validate_hhp_field 기반"""
    errors = []
    hhp_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content', 'trade_in', 'sku_status',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]
    cursor.execute(f"""
        SELECT
            id, item, {date_field}, product_url,
            page_type, main_rank, bsr_rank, trend_rank,
            final_sku_price, original_sku_price,
            count_of_reviews, star_rating, count_of_star_ratings,
            detailed_review_content, trade_in, sku_status,
            number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
            sku_popularity, retailer_membership_discounts,
            rank_1, rank_2, summarized_review_content,
            savings, offer, retailer_sku_name_similar, recommendation_intent,
            number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
        FROM {table_name}
        WHERE DATE({date_field}::timestamp) = %s
          AND account_name = %s
        ORDER BY id
    """, (target_date, retailer))
    for row in cursor.fetchall():
        record_id = row[0]
        item = row[1]
        crawl_dt = row[2]
        product_url = row[3]
        values = [item] + list(row[4:])
        row_errors = []
        for field, value in zip(hhp_fields, values):
            error = validate_hhp_field(field, value, retailer)
            if error:
                row_errors.append(field)
        if row_errors:
            errors.append({
                'id': record_id,
                'item': item,
                'error_field': ', '.join(row_errors),
                'error_value': ', '.join(row_errors),
                'collected_at': str(crawl_dt) if crawl_dt else None
            })
    return errors


def get_format_stats(cursor, target_date):
    """형식 검증 통계 — 대시보드용"""

    total_format_issues = 0
    format_validation = {
        'type': 'format',
        'type_name': '형식 검증',
        'type_name_en': 'Format Validation',
        'description': '데이터 형식 및 패턴 검증',
        'icon': '📋',
        'tables': []
    }

    # tv_item_mst에서 유효한 item 목록 조회
    cursor.execute("SELECT DISTINCT item FROM tv_item_mst")
    tv_valid_items = set(row[0] for row in cursor.fetchall())

    # TV Retail 형식 검증 - 청크 단위 전수검사
    tv_format_errors = []
    tv_format_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    tv_format_total_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    tv_format_rows_count = 0

    all_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]

    CHUNK_SIZE = 5000
    tv_offset = 0
    while True:
        cursor.execute("""
            SELECT
                account_name, id, item, page_type, product_url,
                main_rank, bsr_rank, final_sku_price, original_sku_price,
                count_of_reviews, star_rating, count_of_star_ratings,
                detailed_review_content,
                number_of_units_purchased_past_month, available_quantity_for_purchase,
                sku_popularity, retailer_membership_discounts,
                rank_1, rank_2, summarized_review_content,
                savings, offer, retailer_sku_name_similar, recommendation_intent,
                number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
            FROM tv_retail_com
            WHERE DATE(crawl_datetime::timestamp) = %s
              AND {get_tv_validation_condition()}
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (target_date, CHUNK_SIZE, tv_offset))

        chunk = cursor.fetchall()
        if not chunk:
            break
        tv_format_rows_count += len(chunk)

        for row in chunk:
            account_name = row[0] or 'Unknown'
            item_value = row[2]
            errors = []

            if account_name in tv_format_total_by_retailer:
                tv_format_total_by_retailer[account_name] += 1
            else:
                tv_format_total_by_retailer[account_name] = 1

            values = list(row[2:])

            for field, value in zip(all_fields, values):
                error = validate_tv_field(field, value, account_name)
                if error:
                    errors.append({'field': field, 'value': str(value)[:30] if value else '', 'error': error})

            if item_value and item_value not in tv_valid_items:
                errors.append({
                    'field': 'item (참조 무결성)',
                    'value': str(item_value)[:30],
                    'error': '마스터 테이블에 등록되지 않은 item'
                })

            if errors:
                if len(tv_format_errors) < 30:
                    tv_format_errors.append({
                        'id': row[1],
                        'account_name': account_name,
                        'item': row[2],
                        'errors': errors[:5]
                    })
                if account_name in tv_format_by_retailer:
                    tv_format_by_retailer[account_name] += len(errors)
                else:
                    tv_format_by_retailer[account_name] = len(errors)

        tv_offset += CHUNK_SIZE

    tv_format_retailers = []
    tv_format_issue_total = 0
    for retailer, count in tv_format_by_retailer.items():
        tv_format_retailers.append({
            'retailer': retailer,
            'total': tv_format_total_by_retailer.get(retailer, 0),
            'issue_count': count,
            'status': get_status(count)
        })
        tv_format_issue_total += count

    format_validation['tables'].append({
        'table': 'tv_retail',
        'table_name': 'TV Retail',
        'total_checked': tv_format_rows_count,
        'total_issues': tv_format_issue_total,
        'status': get_status(tv_format_issue_total),
        'retailers': tv_format_retailers,
        'sample_errors': tv_format_errors
    })
    total_format_issues += tv_format_issue_total

    # hhp_item_mst
    hhp_valid_items = set()

    # HHP Retail - 청크 단위 전수검사
    hhp_format_errors = []
    hhp_format_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    hhp_format_total_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    hhp_format_rows_count = 0

    hhp_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content', 'trade_in', 'sku_status',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]

    hhp_offset = 0
    while False:
        cursor.execute("""
            SELECT
                account_name, id, item, page_type, product_url,
                main_rank, bsr_rank, trend_rank, final_sku_price, original_sku_price,
                count_of_reviews, star_rating, count_of_star_ratings,
                detailed_review_content, trade_in, sku_status,
                number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
                sku_popularity, retailer_membership_discounts,
                rank_1, rank_2, summarized_review_content,
                savings, offer, retailer_sku_name_similar, recommendation_intent,
                number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
            FROM hhp_retail_com
            WHERE DATE(crawl_strdatetime::timestamp) = %s
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (target_date, CHUNK_SIZE, hhp_offset))

        chunk = cursor.fetchall()
        if not chunk:
            break
        hhp_format_rows_count += len(chunk)

        for row in chunk:
            account_name = row[0] or 'Unknown'
            item_value = row[2]
            errors = []

            if account_name in hhp_format_total_by_retailer:
                hhp_format_total_by_retailer[account_name] += 1
            else:
                hhp_format_total_by_retailer[account_name] = 1

            values = list(row[2:])

            for field, value in zip(hhp_fields, values):
                error = validate_hhp_field(field, value, account_name)
                if error:
                    errors.append({'field': field, 'value': str(value)[:30] if value else '', 'error': error})

            if item_value and item_value not in hhp_valid_items:
                errors.append({
                    'field': 'item (참조 무결성)',
                    'value': str(item_value)[:30],
                    'error': '마스터 테이블에 등록되지 않은 item'
                })

            if errors:
                if len(hhp_format_errors) < 30:
                    hhp_format_errors.append({
                        'id': row[1],
                        'account_name': account_name,
                        'item': row[2],
                        'errors': errors[:5]
                    })
                if account_name in hhp_format_by_retailer:
                    hhp_format_by_retailer[account_name] += len(errors)
                else:
                    hhp_format_by_retailer[account_name] = len(errors)

        hhp_offset += CHUNK_SIZE

    hhp_format_retailers = []
    hhp_format_issue_total = 0
    for retailer, count in hhp_format_by_retailer.items():
        hhp_format_retailers.append({
            'retailer': retailer,
            'total': hhp_format_total_by_retailer.get(retailer, 0),
            'issue_count': count,
            'status': get_status(count)
        })
        hhp_format_issue_total += count

    format_validation['tables'].append({
        'table': 'hhp_retail',
        'table_name': 'HHP Retail',
        'total_checked': hhp_format_rows_count,
        'total_issues': hhp_format_issue_total,
        'status': get_status(hhp_format_issue_total),
        'retailers': hhp_format_retailers,
        'sample_errors': hhp_format_errors
    })
    total_format_issues += hhp_format_issue_total
    format_validation['tables'] = [t for t in format_validation['tables'] if t.get('table') != 'hhp_retail']
    total_format_issues -= hhp_format_issue_total

    # Market 형식 검증
    try:
        market_tables = [
            ('market_trend', 'Trend', 'crawl_at_local_time'),
            ('market_comp_product', 'Comp Product', 'created_at'),
            ('market_comp_event', 'Comp Event', 'created_at'),
            ('openai_forecast_results', 'Forecast', 'crawled_at'),
        ]
        market_total_format_issues = 0
        market_total_format_checked = 0
        market_format_retailers = []

        for mkt_table, mkt_retailer, mkt_date_col in market_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {mkt_table} WHERE DATE({mkt_date_col}) = %s", (target_date,))
            mkt_total = cursor.fetchone()[0] or 0

            error_where = build_format_error_sql(mkt_table, 'ALL', mkt_retailer)
            if error_where != 'FALSE':
                cursor.execute(f"SELECT COUNT(*) FROM {mkt_table} WHERE DATE({mkt_date_col}) = %s AND ({error_where})", (target_date,))
                mkt_issues = cursor.fetchone()[0] or 0
            else:
                mkt_issues = 0

            market_total_format_checked += mkt_total
            market_total_format_issues += mkt_issues
            market_format_retailers.append({
                'retailer': mkt_retailer,
                'total': mkt_total,
                'issue_count': mkt_issues,
                'status': get_status(mkt_issues),
            })

        format_validation['tables'].append({
            'table': 'market',
            'table_name': 'Market',
            'total_checked': market_total_format_checked,
            'total_issues': market_total_format_issues,
            'status': get_status(market_total_format_issues),
            'retailers': market_format_retailers
        })
        total_format_issues += market_total_format_issues
    except Exception as e:
        print(f'[WARN] layer_stats market_format: {e}')

    format_validation['total_issues'] = total_format_issues
    format_validation['status'] = get_status(total_format_issues)

    return format_validation, total_format_issues
