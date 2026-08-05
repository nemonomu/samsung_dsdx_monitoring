"""
Layer 3 대시보드 API — 전체 통계 오케스트레이터
"""

from datetime import datetime, timedelta
from django.http import JsonResponse
from apps.common.db import dx_connection
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.response import log_error
from apps.common.retail_validation import get_tv_validation_condition
from .services import (
    validate_table_name as _validate_table_name,
    load_timeseries_rules,
    validate_all_category_specs,
    validate_crossfield,
    get_crossfield_normal_counts,
    get_status,
    apply_tv_retail_am_filter,
)


def layer_stats(request):
    """Layer 3 통계 API - 이상치 탐지 및 크로스 필드 검증"""
    date_str = request.GET.get('date')
    product_line = request.GET.get('type', 'all')
    section = request.GET.get('section', '')


    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    prev_date = target_date - timedelta(days=1)
    prev_week = target_date - timedelta(days=7)

    results = {
        'timestamp': datetime.now().isoformat(),
        'date': str(target_date),
        'layer': 3,
        'name': '이상치/특수 케이스 검수',
        'product_line': product_line.upper(),
        'checks': [],
        'summary': {
            'total_checked': 0,
            'passed': 0,
            'failed': 0,
            'pass_rate': 0,
            'status': 'OK'
        }
    }

    total_checked = 0
    total_anomalies = 0

    tv_total = 0
    hhp_total = 0
    yt_comment_total = 0

    try:
        with dx_connection() as (conn, cursor):

            run_timeseries = section in ('', 'time_series')
            run_crossfield = section in ('', 'cross_field')
            run_catspec = section in ('', 'category_spec')
            run_market = section in ('', 'category_spec', 'cross_field')

            timeseries_rules = load_timeseries_rules() if run_timeseries else []

            if product_line != 'all':
                timeseries_rules = [r for r in timeseries_rules if r['product_line'] == product_line]

            table_totals = {}

            hhp_needed = any(r['product_line'] == 'hhp' for r in timeseries_rules)

            if hhp_needed:
                with dx_connection() as (hhp_conn, hhp_cursor):
                    for rule in timeseries_rules:
                        table_name = rule['table_name']
                        _validate_table_name(table_name)
                        date_column = rule['date_column']
                        check_type = rule['check_type']
                        pl = rule['product_line']

                        if pl == 'hhp':
                            curr_cursor = hhp_cursor
                        else:
                            curr_cursor = cursor

                        if table_name not in table_totals:
                            try:
                                time_filter = ""
                                curr_cursor.execute(f"""
                                    SELECT COUNT(*) FROM {table_name}
                                    WHERE DATE({date_column}::timestamp) = %s
                                    {f'AND {get_tv_validation_condition()}' if table_name == 'tv_retail_com' else ''}
                                    {time_filter}
                                """, (target_date,))
                                table_totals[table_name] = curr_cursor.fetchone()[0] or 0
                            except Exception as e:
                                log_error(e)
                                table_totals[table_name] = 0

                        table_total = table_totals[table_name]

                        anomaly_count = 0
                        try:
                            stored_query = rule.get('query', '')
                            if stored_query:
                                stored_query = apply_tv_retail_am_filter(stored_query, table_name, date_column)
                                count_sql = f"SELECT COUNT(*) FROM ({stored_query}) _sub"
                                curr_cursor.execute(count_sql, (target_date, target_date, prev_date))
                                anomaly_count = curr_cursor.fetchone()[0] or 0
                        except Exception as e:
                            log_error(e)

                        total_checked += table_total
                        total_anomalies += anomaly_count

                        pct = rule.get('threshold_pct')
                        if pct is not None:
                            if check_type == 'price':
                                threshold_str = f">{int(pct)}%"
                            else:
                                threshold_str = f"+{int(pct)}%"
                        else:
                            threshold_str = '-'

                        results['checks'].append({
                            'category': '시계열 이상치',
                            'name': rule['detail_name'],
                            'detail_code': rule['detail_code'],
                            'description': rule['error_message'],
                            'checked': table_total,
                            'passed': table_total - anomaly_count,
                            'failed': anomaly_count,
                            'threshold': threshold_str,
                            'status': get_status(anomaly_count, table_total, needs_review=(check_type == 'review' and anomaly_count > 0))
                        })

                    hhp_total = table_totals.get('hhp_retail_com', 0)

                    if False and run_crossfield and hhp_total == 0 and product_line in ['hhp', 'all']:
                        try:
                            hhp_cursor.execute("""
                                SELECT COUNT(*) FROM hhp_retail_com
                                WHERE DATE(crawl_strdatetime) = %s
                            """, (target_date,))
                            hhp_total = hhp_cursor.fetchone()[0] or 0
                            table_totals['hhp_retail_com'] = hhp_total
                        except:
                            pass

            else:
                for rule in timeseries_rules:
                    table_name = rule['table_name']
                    _validate_table_name(table_name)
                    date_column = rule['date_column']
                    check_type = rule['check_type']

                    if table_name not in table_totals:
                        try:
                            time_filter = ""
                            cursor.execute(f"""
                                SELECT COUNT(*) FROM {table_name}
                                WHERE DATE({date_column}::timestamp) = %s
                                {f'AND {get_tv_validation_condition()}' if table_name == 'tv_retail_com' else ''}
                                {time_filter}
                            """, (target_date,))
                            table_totals[table_name] = cursor.fetchone()[0] or 0
                        except Exception as e:
                            log_error(e)
                            table_totals[table_name] = 0

                    table_total = table_totals[table_name]

                    anomaly_count = 0
                    try:
                        stored_query = rule.get('query', '')
                        if stored_query:
                            stored_query = apply_tv_retail_am_filter(stored_query, table_name, date_column)
                            count_sql = f"SELECT COUNT(*) FROM ({stored_query}) _sub"
                            cursor.execute(count_sql, (target_date, target_date, prev_date))
                            anomaly_count = cursor.fetchone()[0] or 0
                    except Exception as e:
                        log_error(e)

                    total_checked += table_total
                    total_anomalies += anomaly_count

                    pct = rule.get('threshold_pct')
                    if pct is not None:
                        if check_type == 'price':
                            threshold_str = f">{int(pct)}%"
                        else:
                            threshold_str = f"+{int(pct)}%"
                    else:
                        threshold_str = '-'

                    results['checks'].append({
                        'category': '시계열 이상치',
                        'name': rule['detail_name'],
                        'detail_code': rule['detail_code'],
                        'description': rule['error_message'],
                        'checked': table_total,
                        'passed': table_total - anomaly_count,
                        'failed': anomaly_count,
                        'threshold': threshold_str,
                        'status': get_status(anomaly_count, table_total, needs_review=(check_type == 'review' and anomaly_count > 0))
                    })

            tv_total = table_totals.get('tv_retail_com', 0)
            if not hhp_needed:
                hhp_total = table_totals.get('hhp_retail_com', 0)

            if run_crossfield:
                if tv_total == 0 and product_line in ['tv', 'all']:
                    try:
                        cursor.execute("""
                            SELECT COUNT(*) FROM tv_retail_com
                            WHERE DATE(crawl_datetime::timestamp) = %s
                              AND NOT (account_name = 'Amazon' AND redirect IS TRUE)
                        """, (target_date,))
                        tv_total = cursor.fetchone()[0] or 0
                        table_totals['tv_retail_com'] = tv_total
                    except:
                        pass

                if False and hhp_total == 0 and product_line in ['hhp', 'all'] and not hhp_needed:
                    with dx_connection() as (hhp_conn, hhp_cursor):
                        try:
                            hhp_cursor.execute("""
                                SELECT COUNT(*) FROM hhp_retail_com
                                WHERE DATE(crawl_strdatetime) = %s
                            """, (target_date,))
                            hhp_total = hhp_cursor.fetchone()[0] or 0
                            table_totals['hhp_retail_com'] = hhp_total
                        except:
                            pass

            if run_crossfield and product_line in ['tv', 'all']:
                tv_cross_total = tv_total
                try:
                    tv_crossfield_result = validate_crossfield(target_date, 'tv_retail')
                    tv_cross_errors = tv_crossfield_result['total_errors']
                    tv_normal = get_crossfield_normal_counts(target_date, 'tv_retail_com')
                    tv_cross_errors = max(0, tv_cross_errors - sum(tv_normal.values()))
                except Exception as e:
                    log_error(e)
                    tv_cross_errors = 0

                total_checked += tv_cross_total
                total_anomalies += tv_cross_errors

                results['checks'].append({
                    'category': '크로스 필드 검증',
                    'name': 'TV 논리적 일관성',
                    'description': 'star_rating↔count, page_type↔rank, 가격, count_of_reviews↔detail_review_content 검증',
                    'checked': tv_cross_total,
                    'passed': tv_cross_total - tv_cross_errors,
                    'failed': tv_cross_errors,
                    'status': get_status(tv_cross_errors, tv_cross_total)
                })

            if False and run_crossfield and product_line in ['hhp', 'all']:
                hhp_cross_total = hhp_total
                try:
                    hhp_crossfield_result = validate_crossfield(target_date, 'hhp_retail')
                    hhp_cross_errors = hhp_crossfield_result['total_errors']
                    hhp_normal = get_crossfield_normal_counts(target_date, 'hhp_retail_com')
                    hhp_cross_errors = max(0, hhp_cross_errors - sum(hhp_normal.values()))
                except Exception as e:
                    log_error(e)
                    hhp_cross_errors = 0

                total_checked += hhp_cross_total
                total_anomalies += hhp_cross_errors

                results['checks'].append({
                    'category': '크로스 필드 검증',
                    'name': 'HHP 논리적 일관성',
                    'description': 'star_rating↔count, page_type↔rank, 가격, count_of_reviews↔detail_review_content 검증',
                    'checked': hhp_cross_total,
                    'passed': hhp_cross_total - hhp_cross_errors,
                    'failed': hhp_cross_errors,
                    'status': get_status(hhp_cross_errors, hhp_cross_total)
                })

            if run_crossfield and product_line in ['tv', 'all']:
                tv_sentiment_cross_total = 0
                tv_sentiment_cross_anomaly = 0
                try:
                    with dx_connection() as (sent_conn, sent_cursor):
                        sent_cursor.execute("""
                            SELECT COUNT(*)
                            FROM tv_retail_sentiment s
                            JOIN tv_retail_com r ON s.retail_com_id = r.id
                            WHERE DATE(r.crawl_datetime::timestamp) = %s
                            AND NOT (r.account_name = 'Amazon' AND r.redirect IS TRUE)
                            AND s.sentiment_score IS NOT NULL
                            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
                        """, (target_date,))
                        tv_sentiment_cross_total = sent_cursor.fetchone()[0] or 0

                        sent_cursor.execute("""
                            SELECT COUNT(*)
                            FROM tv_retail_sentiment s
                            JOIN tv_retail_com r ON s.retail_com_id = r.id
                            WHERE DATE(r.crawl_datetime::timestamp) = %s
                            AND NOT (r.account_name = 'Amazon' AND r.redirect IS TRUE)
                            AND s.sentiment_score IS NOT NULL
                            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
                            AND (
                                r.count_of_star_ratings IS NULL
                                OR r.count_of_star_ratings = ''
                                OR r.count_of_star_ratings = '0'
                                OR r.count_of_star_ratings = 'No reviews'
                                OR r.count_of_star_ratings = 'No ratings'
                            )
                        """, (target_date,))
                        tv_sentiment_cross_anomaly = sent_cursor.fetchone()[0] or 0
                except Exception as e:
                    log_error(e)

                total_checked += tv_sentiment_cross_total
                total_anomalies += tv_sentiment_cross_anomaly

                results['checks'].append({
                    'category': '크로스 필드 검증',
                    'name': 'TV Sentiment↔리뷰 일관성',
                    'description': 'sentiment 점수가 있는데 원본 리뷰 수가 NULL/빈값/0/리뷰없음',
                    'checked': tv_sentiment_cross_total,
                    'passed': tv_sentiment_cross_total - tv_sentiment_cross_anomaly,
                    'failed': tv_sentiment_cross_anomaly,
                    'status': get_status(tv_sentiment_cross_anomaly, tv_sentiment_cross_total)
                })

            if False and run_crossfield and product_line in ['hhp', 'all']:
                hhp_sentiment_cross_total = 0
                hhp_sentiment_cross_anomaly = 0
                try:
                    with dx_connection() as (sent_conn, sent_cursor):
                        sent_cursor.execute("""
                            SELECT COUNT(*)
                            FROM hhp_retail_sentiment s
                            JOIN hhp_retail_com r ON s.retail_com_id = r.id
                            WHERE DATE(r.crawl_strdatetime::timestamp) = %s
                            AND s.sentiment_score IS NOT NULL
                            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
                        """, (target_date,))
                        hhp_sentiment_cross_total = sent_cursor.fetchone()[0] or 0

                        sent_cursor.execute("""
                            SELECT COUNT(*)
                            FROM hhp_retail_sentiment s
                            JOIN hhp_retail_com r ON s.retail_com_id = r.id
                            WHERE DATE(r.crawl_strdatetime::timestamp) = %s
                            AND s.sentiment_score IS NOT NULL
                            AND LOWER(s.sentiment_score::text) NOT IN ('none', 'null', '')
                            AND (
                                r.count_of_star_ratings IS NULL
                                OR r.count_of_star_ratings = ''
                                OR r.count_of_star_ratings = '0'
                                OR r.count_of_star_ratings = 'No reviews'
                                OR r.count_of_star_ratings = 'No ratings'
                            )
                        """, (target_date,))
                        hhp_sentiment_cross_anomaly = sent_cursor.fetchone()[0] or 0
                except Exception as e:
                    log_error(e)

                total_checked += hhp_sentiment_cross_total
                total_anomalies += hhp_sentiment_cross_anomaly

                results['checks'].append({
                    'category': '크로스 필드 검증',
                    'name': 'HHP Sentiment↔리뷰 일관성',
                    'description': 'sentiment 점수가 있는데 원본 리뷰 수가 NULL/빈값/0/리뷰없음',
                    'checked': hhp_sentiment_cross_total,
                    'passed': hhp_sentiment_cross_total - hhp_sentiment_cross_anomaly,
                    'failed': hhp_sentiment_cross_anomaly,
                    'status': get_status(hhp_sentiment_cross_anomaly, hhp_sentiment_cross_total)
                })

            if run_catspec:
                try:
                    category_spec_results = validate_all_category_specs(target_date)
                    for cat_result in category_spec_results:
                        sec_code = cat_result.get('section_code', '').lower()
                        if product_line == 'tv' and 'hhp' in sec_code:
                            continue
                        if product_line == 'hhp' and 'tv' in sec_code and 'hhp' not in sec_code:
                            continue
                        if product_line not in ['market', 'all'] and 'market' in sec_code:
                            continue

                        cat_total = cat_result.get('total', 0)
                        cat_anomaly = cat_result.get('anomaly', 0)

                        total_checked += cat_total
                        total_anomalies += cat_anomaly

                        results['checks'].append({
                            'category': '카테고리별 특성',
                            'name': cat_result.get('section_name', sec_code),
                            'description': cat_result.get('description', ''),
                            'checked': cat_total,
                            'passed': cat_total - cat_anomaly,
                            'failed': cat_anomaly,
                            'status': get_status(cat_anomaly, cat_total)
                        })
                except Exception as e:
                    log_error(e)

            if (
                run_market
                and product_line in ['market', 'all']
                and 'market_comp_product' not in DISABLED_SOURCE_TABLES
            ):
                with dx_connection() as (market_conn, market_cursor):
                    first_day_of_month = target_date.replace(day=1)
                    month_start = first_day_of_month.strftime('%Y-%m-%d')
                    if target_date.month == 12:
                        month_end_date = target_date.replace(year=target_date.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        month_end_date = target_date.replace(month=target_date.month + 1, day=1) - timedelta(days=1)
                    month_end = month_end_date.strftime('%Y-%m-%d')

                    comp_product_total = 0
                    comp_product_cross_anomaly = 0
                    comp_product_batch_id = None
                    try:
                        market_cursor.execute("""
                            SELECT batch_id, MAX(created_at) as last_run
                            FROM market_comp_product
                            WHERE batch_id IS NOT NULL
                              AND created_at >= %s AND created_at < %s::date + INTERVAL '1 day'
                            GROUP BY batch_id
                            ORDER BY last_run DESC
                            LIMIT 1
                        """, (month_start, month_end))
                        batch_row = market_cursor.fetchone()
                        comp_product_batch_id = batch_row[0] if batch_row else None

                        if comp_product_batch_id:
                            market_cursor.execute("""
                                SELECT COUNT(*) FROM market_comp_product
                                WHERE batch_id = %s
                            """, (comp_product_batch_id,))
                            comp_product_total = market_cursor.fetchone()[0] or 0
                            market_cursor.execute("""
                                SELECT COUNT(*) FROM market_comp_product
                                WHERE batch_id = %s
                                AND LOWER(samsung_series_name) LIKE '%%' || LOWER(comp_brand) || '%%'
                            """, (comp_product_batch_id,))
                            comp_product_cross_anomaly = market_cursor.fetchone()[0] or 0
                    except Exception as e:
                        log_error(e)

                    total_anomalies += comp_product_cross_anomaly

                    results['checks'].append({
                        'category': '크로스 필드 검증',
                        'name': 'Comp Product 자사/경쟁사 구분',
                        'description': 'samsung_series_name에 comp_brand가 포함된 논리 오류',
                        'checked': comp_product_total,
                        'passed': comp_product_total - comp_product_cross_anomaly,
                        'failed': comp_product_cross_anomaly,
                        'status': get_status(comp_product_cross_anomaly, comp_product_total)
                    })

    except Exception as e:
        results['error'] = log_error(e)

    summary_checked = sum(check.get('checked', 0) for check in results['checks'])
    summary_failed = sum(check.get('failed', 0) for check in results['checks'])
    summary_passed = summary_checked - summary_failed

    results['summary'] = {
        'total_checked': summary_checked,
        'passed': summary_passed,
        'failed': summary_failed,
        'pass_rate': round((summary_passed / summary_checked * 100), 2) if summary_checked > 0 else 0,
        'status': 'OK' if summary_failed == 0 else ('WARNING' if summary_failed < summary_checked * 0.05 else 'CRITICAL')
    }

    return JsonResponse(results)
