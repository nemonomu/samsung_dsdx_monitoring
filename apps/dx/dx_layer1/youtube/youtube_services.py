from datetime import datetime, timedelta
from apps.common.db import dx_connection
from apps.common.response import log_error
from apps.common.dx_schedules import get_schedule_kst_info, get_kst_time_info
from apps.dx.dx_layer1.common.context import SECTION_TITLES
from . import youtube_repositories as repo


def get_layer1_stats(cursor, target_date, now):
    result = {'check': None, 'failed_items': []}

    try:
        youtube_info = get_schedule_kst_info('youtube', target_date, now)

        if not youtube_info:
            kst_start = get_kst_time_info(4, target_date)
            youtube_info = {
                'us_start_hour': 4,
                'collection_duration_min': 240,
                'kst_start': kst_start,
                'kst_end': {'full_display': f"{target_date} 22:00"},
                'time_status': None,
                'is_pending': False,
                'is_collecting': False,
                'collection_done': True
            }

        target_date_str = target_date.strftime('%Y-%m-%d')
        youtube_today = repo.get_youtube_today(cursor, target_date_str)
        youtube_expected_map = repo.get_youtube_expected(cursor)

        today_by_category = {
            row[0]: {
                'attempted_count': row[1] or 0,
                'completed_count': row[2] or 0,
                'video_count': row[3] or 0,
                'comment_count': row[4] or 0,
                'country_count': row[5] or 0,
                'completed_country_count': row[6] or 0,
            }
            for row in youtube_today
        }

        youtube_categories = []
        youtube_total_actual = 0
        youtube_total_expected = 0
        youtube_statuses = []

        category_names = {'HHP'} | set(youtube_expected_map) | set(today_by_category)
        for category in category_names:
            if category == 'TV':
                continue

            today_data = today_by_category.get(category, {})
            attempted_count = today_data.get('attempted_count', 0)
            completed_count = today_data.get('completed_count', 0)
            video_count = today_data.get('video_count', 0)
            comment_count = today_data.get('comment_count', 0)
            country_count = today_data.get('country_count', 0)
            completed_country_count = today_data.get(
                'completed_country_count', 0
            )

            expected_data = youtube_expected_map.get(category, {})
            expected = expected_data.get('expected_jobs', 0)
            expected_country_count = expected_data.get(
                'expected_countries', 0
            )
            distinct_keyword_count = expected_data.get(
                'distinct_keywords', 0
            )
            avg_7day = expected

            if expected > 0:
                rate = (completed_count / expected) * 100
            else:
                rate = 100 if completed_count > 0 else 0

            if youtube_info['is_pending']:
                status = 'PENDING'
            elif expected == 0:
                status = 'OK' if completed_count > 0 else 'WARNING'
            elif rate >= 100:
                status = 'OK'
            elif youtube_info['is_collecting']:
                status = 'COLLECTING'
            elif rate >= 90:
                status = 'WARNING'
            else:
                status = 'CRITICAL'

            youtube_statuses.append(status)
            youtube_total_actual += completed_count
            youtube_total_expected += expected

            youtube_categories.append({
                'name': category,
                'log_count': completed_count,
                'attempted_count': attempted_count,
                'video_count': video_count,
                'comment_count': comment_count,
                'expected': expected,
                'country_count': country_count,
                'completed_country_count': completed_country_count,
                'expected_country_count': expected_country_count,
                'distinct_keyword_count': distinct_keyword_count,
                'avg_7day': round(avg_7day),
                'rate': round(rate, 1),
                'status': status
            })

        if youtube_total_expected > 0:
            youtube_overall_rate = (youtube_total_actual / youtube_total_expected) * 100
        else:
            youtube_overall_rate = 100 if youtube_total_actual > 0 else 0

        if youtube_info['is_pending']:
            youtube_overall_status = 'PENDING'
        elif youtube_total_expected == 0:
            youtube_overall_status = 'OK' if youtube_total_actual > 0 else 'WARNING'
        elif youtube_overall_rate >= 100:
            youtube_overall_status = 'OK'
        elif youtube_info['is_collecting']:
            youtube_overall_status = 'COLLECTING'
        elif youtube_overall_rate >= 90:
            youtube_overall_status = 'WARNING'
        else:
            youtube_overall_status = 'CRITICAL'

        youtube_ok_count = len([s for s in youtube_statuses if s == 'OK'])

        category_order = {'TV': 0, 'HHP': 1}
        youtube_categories.sort(key=lambda x: category_order.get(x['name'], 99))

        result['check'] = {
            'name': SECTION_TITLES['youtube'],
            'description': f'{youtube_ok_count}/{len(youtube_statuses)} 카테고리 정상',
            'actual': youtube_total_actual,
            'expected': round(youtube_total_expected),
            'rate': round(youtube_overall_rate, 1),
            'status': youtube_overall_status,
            'check_type': 'youtube',
            'us_time': f'{target_date} {youtube_info["us_start_hour"]:02d}:00',
            'kr_time': youtube_info['kst_start']['full_display'],
            'kr_time_end': youtube_info['kst_end']['full_display'],
            'is_dst': youtube_info['kst_start']['is_dst'],
            'categories': youtube_categories
        }

    except Exception as e:
        log_error(e)

    return result


def get_youtube_raw_data(category, data_type, target_date):
    results = {
        'category': category,
        'date': str(target_date),
        'data_type': data_type,
        'columns': [],
        'data': [],
        'total_count': 0
    }

    try:
        target_date_str = target_date.strftime('%Y-%m-%d')
        with dx_connection() as (conn, cursor):
            if data_type == 'logs':
                columns, rows, total_count = repo.get_youtube_logs(
                    cursor, target_date_str, category
                )
            elif data_type == 'videos':
                columns, rows, total_count = repo.get_youtube_videos(
                    cursor, target_date_str, category
                )
            elif data_type == 'comments':
                columns, rows, total_count = repo.get_youtube_comments(
                    cursor, target_date_str, category
                )
            else:
                columns, rows, total_count = [], [], 0

        results['columns'] = columns
        results['total_count'] = total_count
        results['data'] = rows

    except Exception as e:
        results['error'] = log_error(e)

    return results
