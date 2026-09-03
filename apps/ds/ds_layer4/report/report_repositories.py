"""
DS Layer 4 Report Repository: 보고서 및 데이터베이스 SQL 처리 전담
"""
from datetime import datetime, timedelta, date
from apps.common.db import ds_connection
from apps.common.targets import load_monitoring_targets


_SYSTEM_CAUSE_MARKERS = {'crawler_null_capture'}


def _user_cause(value):
    cause = str(value or '').strip()
    if cause.casefold() in _SYSTEM_CAUSE_MARKERS:
        return ''
    return cause


def get_monitoring_targets():
    return load_monitoring_targets()

def is_report_closed(target_date, existing=None):
    with ds_connection(existing=existing) as (conn, cursor):
        cursor.execute("""
            SELECT is_closed FROM ssd_crawl_db.ds_monitoring_report_close
            WHERE crawl_date = %s
        """, (target_date,))
        close_row = cursor.fetchone()
        is_closed = close_row[0] == 1 if close_row else False
        return {'success': True, 'date': target_date, 'is_closed': is_closed}

def check_close_status(cursor, crawl_date):
    cursor.execute("""
        SELECT is_closed FROM ssd_crawl_db.ds_monitoring_report_close
        WHERE crawl_date = %s
    """, (crawl_date,))
    row = cursor.fetchone()
    return row and row[0] == 1

def check_all_retailers_saved(cursor, crawl_date, total_count):
    cursor.execute("""
        SELECT COUNT(*) FROM ssd_crawl_db.ds_monitoring_report_daily
        WHERE crawl_date = %s AND is_del = 0
    """, (crawl_date,))
    return cursor.fetchone()[0]

def execute_save_file_info(crawl_date, user_id, file_info_cache, targets_list, duplicate_retailers=None):
    with ds_connection() as (conn, cursor):
        if check_close_status(cursor, crawl_date):
            return {'success': False, 'error': '이미 마감된 날짜입니다.'}

        # 저장된 리테일러 목록 조회
        cursor.execute("""
            SELECT d.retailer_id, t.retailer
            FROM ssd_crawl_db.ds_monitoring_report_daily d
            JOIN ssd_crawl_db.ds_monitoring_targets t ON d.retailer_id = t.retailer_id
            WHERE d.crawl_date = %s AND d.is_del = 0
        """, (crawl_date,))
        saved_retailers = {row[1]: row[0] for row in cursor.fetchall()}

        if not saved_retailers:
            return {'success': False, 'error': '현황 저장이 먼저 필요합니다.'}

        # 저장된 리테일러 중 파일서버에 중복 파일이 있는지 체크
        if duplicate_retailers:
            saved_duplicates = [r for r in duplicate_retailers if r in saved_retailers]
            if saved_duplicates:
                return {
                    'success': False,
                    'error': f'파일서버에 중복 파일이 있는 리테일러가 있습니다. ({", ".join(sorted(saved_duplicates))})'
                }

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        updated_count = 0
        for retailer, retailer_id in saved_retailers.items():
            retailer_file = file_info_cache.get(retailer, {})
            file_name = retailer_file.get('file_name', '')
            file_size = retailer_file.get('file_size', 0)

            cursor.execute("""
                UPDATE ssd_crawl_db.ds_monitoring_report_daily
                SET file_name = %s, file_size = %s, updated_at = %s, updated_id = %s
                WHERE crawl_date = %s AND retailer_id = %s AND is_del = 0
            """, (file_name, file_size, now, user_id, crawl_date, retailer_id))
            updated_count += cursor.rowcount

        conn.commit()

        return {
            'success': True,
            'message': f'{crawl_date} 파일 정보 저장 완료 ({updated_count}건)',
            'updated_count': updated_count,
            'file_info_count': len(file_info_cache)
        }

def check_report_saved(cursor, crawl_date):
    """보고서(문서) 저장 여부 확인"""
    cursor.execute("""
        SELECT COUNT(*) FROM ssd_crawl_db.ds_monitoring_documents
        WHERE crawl_date = %s AND is_del = 0
    """, (crawl_date,))
    return cursor.fetchone()[0] > 0


def execute_close_report(crawl_date, user_id):
    with ds_connection() as (conn, cursor):
        if check_close_status(cursor, crawl_date):
            return {'success': False, 'error': '이미 마감된 날짜입니다.'}

        all_retailers_count = len(get_monitoring_targets())
        saved_count = check_all_retailers_saved(cursor, crawl_date, all_retailers_count)

        if saved_count < all_retailers_count:
            return {'success': False, 'error': f'일괄 현황 저장이 먼저 필요합니다. (저장: {saved_count}/{all_retailers_count})'}

        if not check_report_saved(cursor, crawl_date):
            return {'success': False, 'error': '보고서 저장이 먼저 필요합니다.'}

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT INTO ssd_crawl_db.ds_monitoring_report_close
                (crawl_date, is_closed, closed_at, closed_id, created_at, updated_at)
            VALUES (%s, 1, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                is_closed = 1, closed_at = %s, closed_id = %s, updated_at = %s
        """, (crawl_date, now, user_id, now, now, now, user_id, now))

        cursor.execute("""
            INSERT INTO ssd_crawl_db.ds_monitoring_report_close_history
                (crawl_date, action, action_at, action_id)
            VALUES (%s, 'close', %s, %s)
        """, (crawl_date, now, user_id))

        conn.commit()
        return {'success': True, 'message': f'{crawl_date} 마감 완료'}

def execute_cancel_close_report(crawl_date, user_id, memo):
    with ds_connection() as (conn, cursor):
        if not check_close_status(cursor, crawl_date):
            return {'success': False, 'error': '마감되지 않은 날짜입니다.'}

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            UPDATE ssd_crawl_db.ds_monitoring_report_close
            SET is_closed = 0, updated_at = %s
            WHERE crawl_date = %s
        """, (now, crawl_date))

        cursor.execute("""
            INSERT INTO ssd_crawl_db.ds_monitoring_report_close_history
                (crawl_date, action, action_at, action_id, memo)
            VALUES (%s, 'cancel', %s, %s, %s)
        """, (crawl_date, now, user_id, memo))

        conn.commit()
        return {'success': True, 'message': f'{crawl_date} 마감 취소 완료'}

def update_anomaly_report(body, user_id):
    with ds_connection() as (conn, cursor):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if 'updates' in body:
            updates = body['updates']
            if not updates or not isinstance(updates, list):
                return {'success': False, 'error': 'updates 배열이 필요합니다.'}

            updated_count = 0
            for item in updates:
                anomaly_id = item.get('anomaly_id')
                if not anomaly_id: continue

                update_fields, update_values = [], []
                if 'cause' in item:
                    update_fields.append('cause = %s'); update_values.append(item['cause'])
                if 'memo' in item:
                    update_fields.append('memo = %s'); update_values.append(item['memo'])
                if 'screenshot_id' in item:
                    update_fields.append('screenshot_id = %s'); update_values.append(item['screenshot_id'])

                if update_fields:
                    update_fields.extend(['updated_at = %s', 'updated_id = %s'])
                    update_values.extend([now, user_id, anomaly_id])
                    
                    query = f"""
                        UPDATE ssd_crawl_db.ds_monitoring_report_anomaly
                        SET {', '.join(update_fields)}
                        WHERE id = %s AND is_del = 0
                    """
                    cursor.execute(query, update_values)
                    updated_count += cursor.rowcount

            conn.commit()
            return {'success': True, 'message': f'{updated_count}건 저장 완료', 'updated_count': updated_count}

        anomaly_id = body.get('anomaly_id')
        if not anomaly_id: return {'success': False, 'error': 'anomaly_id가 필요합니다.'}

        update_fields, update_values = [], []
        if 'cause' in body:
            update_fields.append('cause = %s'); update_values.append(body['cause'])
        if 'memo' in body:
            update_fields.append('memo = %s'); update_values.append(body['memo'])
        if 'screenshot_id' in body:
            update_fields.append('screenshot_id = %s'); update_values.append(body['screenshot_id'])

        if not update_fields: return {'success': False, 'error': '수정할 필드가 없습니다.'}

        update_fields.extend(['updated_at = %s', 'updated_id = %s'])
        update_values.extend([now, user_id, anomaly_id])

        query = f"""
            UPDATE ssd_crawl_db.ds_monitoring_report_anomaly
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_del = 0
        """
        cursor.execute(query, update_values)
        updated = cursor.rowcount
        conn.commit()

        if updated == 0: return {'success': False, 'error': '해당 데이터를 찾을 수 없습니다.'}
        return {'success': True, 'message': '수정 완료', 'anomaly_id': anomaly_id}

def update_daily_memo_db(body, user_id):
    with ds_connection() as (conn, cursor):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if 'memos' in body:
            memos = body['memos']
            if not memos or not isinstance(memos, list):
                return {'success': False, 'error': 'memos 배열이 필요합니다.'}

            updated_count = 0
            for item in memos:
                daily_id = item.get('daily_id')
                memo = item.get('memo', '')
                file_memo = item.get('file_memo')
                if daily_id:
                    if file_memo is not None:
                        cursor.execute("""
                            UPDATE ssd_crawl_db.ds_monitoring_report_daily
                            SET memo = %s, file_memo = %s, updated_at = %s, updated_id = %s
                            WHERE id = %s AND is_del = 0
                        """, (memo, file_memo, now, user_id, daily_id))
                    else:
                        cursor.execute("""
                            UPDATE ssd_crawl_db.ds_monitoring_report_daily
                            SET memo = %s, updated_at = %s, updated_id = %s
                            WHERE id = %s AND is_del = 0
                        """, (memo, now, user_id, daily_id))
                    updated_count += cursor.rowcount

            conn.commit()
            return {'success': True, 'message': f'{updated_count}건 메모 저장 완료', 'updated_count': updated_count}

        daily_id = body.get('daily_id')
        if not daily_id: return {'success': False, 'error': 'daily_id가 필요합니다.'}
        if 'memo' not in body and 'file_memo' not in body: return {'success': False, 'error': 'memo 또는 file_memo 필드가 필요합니다.'}

        update_fields = []
        update_values = []
        if 'memo' in body:
            update_fields.append('memo = %s')
            update_values.append(body['memo'])
        if 'file_memo' in body:
            update_fields.append('file_memo = %s')
            update_values.append(body['file_memo'])
        update_fields.extend(['updated_at = %s', 'updated_id = %s'])
        update_values.extend([now, user_id, daily_id])

        cursor.execute(f"""
            UPDATE ssd_crawl_db.ds_monitoring_report_daily
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_del = 0
        """, update_values)
        updated = cursor.rowcount
        conn.commit()

        if updated == 0: return {'success': False, 'error': '해당 데이터를 찾을 수 없습니다.'}
        return {'success': True, 'message': '메모 수정 완료', 'daily_id': daily_id}

def get_report_list_db(target_date, retailer_filter, view_mode):
    with ds_connection() as (conn, cursor):
        cursor.execute("""
            SELECT is_closed, closed_at, closed_id FROM ssd_crawl_db.ds_monitoring_report_close
            WHERE crawl_date = %s
        """, (target_date,))
        close_row = cursor.fetchone()
        is_closed = close_row[0] == 1 if close_row else False
        closed_at = close_row[1].strftime('%Y-%m-%d %H:%M:%S') if close_row and close_row[1] else None
        closed_id = close_row[2] if close_row else None

        daily_query = """
            SELECT d.id, t.retailer, d.expected_count, d.final_batch_count, d.total_count,
                   d.completion_rate, d.rerun_count, d.anomaly_total, d.anomaly_title_null,
                   d.anomaly_image_null, d.anomaly_partial_null, d.anomaly_price_zero,
                   d.memo, d.created_at, d.created_id, d.file_name, d.file_size,
                   t.instance_id, d.file_memo
            FROM ssd_crawl_db.ds_monitoring_report_daily d
            LEFT JOIN ssd_crawl_db.ds_monitoring_targets t ON d.retailer_id = t.retailer_id
            WHERE d.crawl_date = %s AND d.is_del = 0
        """
        params = [target_date]
        if retailer_filter:
            daily_query += " AND t.retailer = %s"
            params.append(retailer_filter)
        daily_query += " ORDER BY t.sort_order, t.retailer"

        cursor.execute(daily_query, params)
        daily_rows = cursor.fetchall()
        daily_reports = []
        for row in daily_rows:
            instance_id = row[17] if len(row) > 17 else None
            daily_reports.append({
                'id': row[0], 'retailer': row[1], 'expected_count': row[2], 'final_batch_count': row[3],
                'total_count': row[4], 'completion_rate': float(row[5]) if row[5] else 0,
                'rerun_count': row[6], 'anomaly_total': row[7], 'anomaly_title_null': row[8],
                'anomaly_image_null': row[9], 'anomaly_partial_null': row[10], 'anomaly_price_zero': row[11],
                'memo': row[12] or '', 'created_at': row[13].strftime('%Y-%m-%d %H:%M:%S') if row[13] else None,
                'created_id': row[14], 'file_name': row[15] or '', 'file_size': row[16] or 0,
                'has_screenshot': bool(instance_id),
                'file_memo': row[18] if len(row) > 18 else ''
            })

        anomalies = []
        cause_options = {}

        if view_mode == 'detail':
            anomaly_query = """
                SELECT a.id, t.retailer, a.country_code, a.title, a.retailprice, a.ships_from, a.sold_by,
                       a.imageurl, a.producturl, a.retailersku, a.screenshot_id, a.cause, a.memo, a.created_at, a.created_id,
                       a.updated_at, a.updated_id
                FROM ssd_crawl_db.ds_monitoring_report_anomaly a
                LEFT JOIN ssd_crawl_db.ds_monitoring_targets t ON a.retailer_id = t.retailer_id
                WHERE a.crawl_date = %s AND a.is_del = 0
            """
            params = [target_date]
            if retailer_filter:
                anomaly_query += " AND t.retailer = %s"
                params.append(retailer_filter)
            anomaly_query += " ORDER BY t.sort_order, t.retailer, a.id"

            cursor.execute(anomaly_query, params)
            anomaly_rows = cursor.fetchall()

            for row in anomaly_rows:
                cause = _user_cause(row[11])
                anomalies.append({
                    'id': row[0], 'retailer': row[1], 'country_code': row[2], 'title': row[3],
                    'retailprice': row[4], 'ships_from': row[5], 'sold_by': row[6],
                    'imageurl': row[7], 'producturl': row[8], 'retailersku': row[9] or '',
                    'screenshot_id': row[10], 'cause': cause, 'memo': row[12],
                    'created_at': row[13].strftime('%Y-%m-%d %H:%M:%S') if row[13] else None,
                    'created_id': row[14], 'updated_at': row[15].strftime('%Y-%m-%d %H:%M:%S') if row[15] else None,
                    'updated_id': row[16]
                })

            cursor.execute("""
                SELECT t.retailer, o.option_name
                FROM ssd_crawl_db.ds_monitoring_anomaly_causes_options o
                JOIN ssd_crawl_db.ds_monitoring_targets t ON o.retailer_id = t.retailer_id
                WHERE o.is_active = 1
                ORDER BY t.retailer, o.sort_order, o.option_id
            """)
            cause_rows = cursor.fetchall()
            for row in cause_rows:
                retailer = row[0]
                option_name = row[1]
                if retailer not in cause_options:
                    cause_options[retailer] = []
                cause_options[retailer].append(option_name)

        cause_summary_query = """
            SELECT t.retailer, COALESCE(a.cause, '') as cause, COUNT(*) as cnt
            FROM ssd_crawl_db.ds_monitoring_report_anomaly a
            LEFT JOIN ssd_crawl_db.ds_monitoring_targets t ON a.retailer_id = t.retailer_id
            WHERE a.crawl_date = %s AND a.is_del = 0
            GROUP BY t.retailer, a.cause
            ORDER BY t.retailer, cnt DESC
        """
        cursor.execute(cause_summary_query, [target_date])
        cause_summary_rows = cursor.fetchall()
        cause_summary = {}
        for row in cause_summary_rows:
            retailer = row[0]
            cause = _user_cause(row[1])
            if not cause: continue
            if retailer not in cause_summary:
                cause_summary[retailer] = {}
            cause_summary[retailer][cause] = row[2]

        summary_query = """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN a.cause IS NOT NULL AND TRIM(a.cause) != ''
                                 AND LOWER(TRIM(a.cause)) != 'crawler_null_capture'
                            THEN 1 ELSE 0 END) as filled_cause,
                   SUM(CASE WHEN a.memo IS NOT NULL AND a.memo != '' THEN 1 ELSE 0 END) as filled_memo
            FROM ssd_crawl_db.ds_monitoring_report_anomaly a
            WHERE a.crawl_date = %s AND a.is_del = 0
        """
        summary_params = [target_date]
        if retailer_filter:
            summary_query += """ AND a.retailer_id IN (
                SELECT t.retailer_id FROM ssd_crawl_db.ds_monitoring_targets t WHERE t.retailer = %s
            )"""
            summary_params.append(retailer_filter)
        cursor.execute(summary_query, summary_params)
        summary_row = cursor.fetchone()
        total_anomalies = summary_row[0] if summary_row else 0
        filled_cause = summary_row[1] if summary_row else 0
        filled_memo = summary_row[2] if summary_row else 0

        screenshot_query = """
            SELECT t.retailer, COUNT(*) as total,
                   SUM(CASE WHEN a.screenshot_id IS NOT NULL THEN 1 ELSE 0 END) as captured
            FROM ssd_crawl_db.ds_monitoring_report_anomaly a
            LEFT JOIN ssd_crawl_db.ds_monitoring_targets t ON a.retailer_id = t.retailer_id
            WHERE a.crawl_date = %s AND a.is_del = 0
            GROUP BY t.retailer
        """
        cursor.execute(screenshot_query, [target_date])
        screenshot_rows = cursor.fetchall()
        screenshot_status_by_retailer = {}
        total_screenshots = captured_screenshots = 0
        for row in screenshot_rows:
            screenshot_status_by_retailer[row[0]] = {'total': row[1], 'captured': row[2]}
            total_screenshots += row[1]
            captured_screenshots += row[2]

        running_captures = {}
        try:
            cursor.execute("""
                UPDATE ssd_crawl_db.ds_monitoring_capture_log
                SET status = 'failed'
                WHERE crawl_date = %s AND status = 'running'
                AND triggered_at < %s
            """, (target_date, datetime.now() - timedelta(minutes=30)))
            if cursor.rowcount > 0: conn.commit()

            cursor.execute("""
                SELECT t.retailer, cl.triggered_at
                FROM ssd_crawl_db.ds_monitoring_capture_log cl
                JOIN ssd_crawl_db.ds_monitoring_targets t ON cl.retailer_id = t.retailer_id
                WHERE cl.crawl_date = %s AND cl.status = 'running'
                AND cl.triggered_at >= %s
            """, (target_date, datetime.now() - timedelta(minutes=30)))
            for row in cursor.fetchall():
                running_captures[row[0]] = row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else None
        except:
            pass

        for report in daily_reports:
            retailer = report['retailer']
            status = screenshot_status_by_retailer.get(retailer, {'total': 0, 'captured': 0})
            report['all_screenshots_captured'] = status['total'] > 0 and status['total'] == status['captured']
            report['capture_running'] = retailer in running_captures

        total_retailers = len(get_monitoring_targets())

        return {
            'success': True,
            'date': target_date,
            'view': view_mode,
            'is_closed': is_closed,
            'closed_at': closed_at,
            'closed_id': closed_id,
            'daily_reports': daily_reports,
            'anomalies': anomalies,
            'total_anomalies': total_anomalies,
            'filled_cause': filled_cause,
            'filled_memo': filled_memo,
            'total_screenshots': total_screenshots,
            'captured_screenshots': captured_screenshots,
            'total_retailers': total_retailers,
            'cause_options': cause_options,
            'cause_summary': cause_summary
        }

def get_file_size_history_db(start_date, end_date):
    with ds_connection() as (conn, cursor):
        cursor.execute("""
            SELECT t.retailer, d.crawl_date, d.file_size
            FROM ssd_crawl_db.ds_monitoring_report_daily d
            JOIN ssd_crawl_db.ds_monitoring_targets t ON d.retailer_id = t.retailer_id
            WHERE d.crawl_date BETWEEN %s AND %s AND d.is_del = 0
            ORDER BY t.sort_order, t.retailer, d.crawl_date
        """, (start_date, end_date))
        return cursor.fetchall()
