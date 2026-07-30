"""
DX Layer 1 YouTube Repositories: 데이터베이스 I/O 쿼리 전담 계층
"""


def get_youtube_today(cursor, target_date_str):
    """국가별 최신 실행만 집계해 재실행에 의한 이중 집계를 방지한다."""
    cursor.execute("""
        WITH ranked_runs AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.collection_country
                    ORDER BY
                        r.started_at DESC NULLS LAST,
                        r.batch_id DESC NULLS LAST
                ) AS row_num
            FROM youtube_country_collection_runs r
            WHERE r.collection_date = %s::date
        ),
        latest_runs AS (
            SELECT *
            FROM ranked_runs
            WHERE row_num = 1
        )
        SELECT
            'HHP' AS category,
            COALESCE(SUM(keyword_count), 0) AS attempted_count,
            COALESCE(SUM(
                CASE WHEN status = 'completed' THEN keyword_count ELSE 0 END
            ), 0) AS completed_count,
            COALESCE(SUM(filtered_video_count), 0) AS video_count,
            COALESCE(SUM(comment_row_count), 0) AS comment_count,
            COUNT(DISTINCT collection_country) AS country_count,
            COUNT(DISTINCT collection_country) FILTER (
                WHERE status = 'completed'
            ) AS completed_country_count
        FROM latest_runs
        HAVING COUNT(*) > 0
    """, (target_date_str,))
    return cursor.fetchall()


def get_youtube_expected(cursor):
    """신규 10개국 HHP 그룹만 기대 수집량에 포함한다."""
    cursor.execute("""
        SELECT
            category,
            COUNT(*) AS expected_job_count,
            COUNT(DISTINCT collection_country) AS expected_country_count,
            COUNT(DISTINCT keyword) AS distinct_keyword_count
        FROM youtube_keywords
        WHERE status = 'active'
          AND category = 'HHP'
          AND collection_group = 'hhp_10_country'
        GROUP BY category
    """)
    return {
        row[0]: {
            'expected_jobs': row[1] or 0,
            'expected_countries': row[2] or 0,
            'distinct_keywords': row[3] or 0,
        }
        for row in cursor.fetchall()
    }


def get_youtube_avg(cursor, target_date_str):
    cursor.execute("""
        WITH ranked_runs AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.collection_date, r.collection_country
                    ORDER BY
                        r.started_at DESC NULLS LAST,
                        r.batch_id DESC NULLS LAST
                ) AS row_num
            FROM youtube_country_collection_runs r
            WHERE r.collection_date >= %s::date - INTERVAL '8 days'
              AND r.collection_date < %s::date
        ),
        daily_stats AS (
            SELECT
                collection_date,
                COALESCE(SUM(
                    CASE WHEN status = 'completed' THEN keyword_count ELSE 0 END
                ), 0) AS daily_job_count,
                COALESCE(SUM(comment_row_count), 0) AS daily_comment_count
            FROM ranked_runs
            WHERE row_num = 1
            GROUP BY collection_date
        )
        SELECT
            'HHP' AS category,
            ROUND(AVG(daily_job_count), 1) AS avg_job_count,
            ROUND(AVG(daily_comment_count), 1) AS avg_comment_count
        FROM daily_stats
        HAVING COUNT(*) > 0
    """, (target_date_str, target_date_str))
    return {
        row[0]: {
            'avg_video': float(row[1] or 0),
            'avg_comment': float(row[2] or 0),
        }
        for row in cursor.fetchall()
    }


def get_youtube_logs(cursor, target_date_str, category):
    columns = [
        'id', 'batch_id', 'collection_date', 'collection_country',
        'country_label', 'status', 'keyword_count', 'filtered_video_count',
        'raw_video_count', 'comment_row_count', 'started_at', 'completed_at',
        'error_message'
    ]
    query = """
        WITH ranked_runs AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.collection_country
                    ORDER BY
                        r.started_at DESC NULLS LAST,
                        r.batch_id DESC NULLS LAST
                ) AS row_num
            FROM youtube_country_collection_runs r
            WHERE r.collection_date = %s
        )
        SELECT
            id,
            batch_id,
            collection_date,
            collection_country,
            country_label,
            status,
            keyword_count,
            filtered_video_count,
            raw_video_count,
            comment_row_count,
            started_at,
            completed_at,
            error_message
        FROM ranked_runs
        WHERE row_num = 1
          AND %s = 'HHP'
        ORDER BY collection_country
        LIMIT 500
    """
    cursor.execute(query, (target_date_str, category))
    rows = cursor.fetchall()
    return columns, rows, len(rows)


def get_youtube_videos(cursor, target_date_str, category):
    columns = [
        'collection_country', 'collection_batch_id', 'video_id', 'keyword',
        'title', 'description', 'published_at', 'channel_country',
        'channel_custom_url', 'channel_subscriber_count', 'channel_video_count',
        'view_count', 'like_count', 'comment_count', 'category_id', 'category',
        'engagement_rate', 'reviewed_brand', 'reviewed_series', 'reviewed_item',
        'product_sentiment_score', 'product_sentiment_score_comment',
        'comment_text_summary', 'created_at'
    ]
    base_query = """
        WITH ranked_runs AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.collection_country
                    ORDER BY
                        r.started_at DESC NULLS LAST,
                        r.batch_id DESC NULLS LAST
                ) AS row_num
            FROM youtube_country_collection_runs r
            WHERE r.collection_date = %s
        ),
        latest_runs AS (
            SELECT batch_id, collection_country
            FROM ranked_runs
            WHERE row_num = 1
        )
        {select_clause}
        FROM youtube_videos v
        JOIN latest_runs r
          ON r.batch_id = v.collection_batch_id
         AND r.collection_country = v.collection_country
        WHERE v.category = %s
        {order_limit}
    """
    params = (target_date_str, category)

    cursor.execute(base_query.format(
        select_clause="""SELECT
            v.collection_country,
            v.collection_batch_id,
            v.video_id,
            v.keyword,
            v.title,
            v.description,
            v.published_at,
            v.channel_country,
            v.channel_custom_url,
            v.channel_subscriber_count,
            v.channel_video_count,
            v.view_count,
            v.like_count,
            v.comment_count,
            v.category_id,
            v.category,
            v.engagement_rate,
            v.reviewed_brand,
            v.reviewed_series,
            v.reviewed_item,
            v.product_sentiment_score,
            v.product_sentiment_score_comment,
            v.comment_text_summary,
            v.created_at""",
        order_limit="ORDER BY v.created_at DESC LIMIT 500",
    ), params)
    rows = cursor.fetchall()

    cursor.execute(base_query.format(
        select_clause="SELECT COUNT(*)",
        order_limit="",
    ), params)
    total_count = cursor.fetchone()[0]
    return columns, rows, total_count


def get_youtube_comments(cursor, target_date_str, category):
    columns = [
        'collection_country', 'collection_batch_id', 'comment_id', 'video_id',
        'comment_type', 'parent_comment_id', 'comment_text_display',
        'like_count', 'reply_count', 'published_at', 'sentiment_score',
        'created_at'
    ]
    base_query = """
        WITH ranked_runs AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.collection_country
                    ORDER BY
                        r.started_at DESC NULLS LAST,
                        r.batch_id DESC NULLS LAST
                ) AS row_num
            FROM youtube_country_collection_runs r
            WHERE r.collection_date = %s
        ),
        latest_runs AS (
            SELECT batch_id, collection_country
            FROM ranked_runs
            WHERE row_num = 1
        )
        {select_clause}
        FROM youtube_comments c
        JOIN latest_runs r
          ON r.batch_id = c.collection_batch_id
         AND r.collection_country = c.collection_country
        WHERE EXISTS (
              SELECT 1
              FROM youtube_videos v
              WHERE v.collection_batch_id = c.collection_batch_id
                AND v.collection_country = c.collection_country
                AND v.video_id = c.video_id
                AND v.category = %s
          )
        {order_limit}
    """
    params = (target_date_str, category)

    cursor.execute(base_query.format(
        select_clause="""SELECT
            c.collection_country,
            c.collection_batch_id,
            c.comment_id,
            c.video_id,
            c.comment_type,
            c.parent_comment_id,
            c.comment_text_display,
            c.like_count,
            c.reply_count,
            c.published_at,
            c.sentiment_score,
            c.created_at""",
        order_limit="ORDER BY c.created_at DESC LIMIT 500",
    ), params)
    rows = cursor.fetchall()

    cursor.execute(base_query.format(
        select_clause="SELECT COUNT(*)",
        order_limit="",
    ), params)
    total_count = cursor.fetchone()[0]
    return columns, rows, total_count
