"""
DS Layer 2 Report Repository: 현황 저장/삭제 쿼리 전담
"""
from apps.common.db import ds_connection
from apps.common.response import log_error

def fetch_retailer_save_status(target_date):
    try:
        with ds_connection() as (conn, cursor):
            cursor.execute("""
                SELECT t.retailer, d.anomaly_total, d.anomaly_title_null, d.anomaly_image_null,
                       d.anomaly_partial_null, d.anomaly_price_zero, d.created_at, d.created_id
                FROM ssd_crawl_db.ds_monitoring_report_daily d
                LEFT JOIN ssd_crawl_db.ds_monitoring_targets t ON d.retailer_id = t.retailer_id
                WHERE d.crawl_date = %s AND d.is_del = 0
            """, (target_date,))
            saved_retailers = {}
            for row in cursor.fetchall():
                saved_retailers[row[0]] = {
                    'retailer': row[0], 'anomaly_total': row[1], 'anomaly_title_null': row[2],
                    'anomaly_image_null': row[3], 'anomaly_partial_null': row[4], 'anomaly_price_zero': row[5],
                    'created_at': row[6].strftime('%Y-%m-%d %H:%M:%S') if row[6] else None, 'created_id': row[7]
                }
            return saved_retailers
    except Exception as e:
        log_error(e)
        return None

def fetch_target_info(cursor, retailer):
    cursor.execute("SELECT retailer_id, table_name, country, mall_name FROM ssd_crawl_db.ds_monitoring_targets WHERE retailer = %s AND is_active = 1", (retailer,))
    return cursor.fetchone()


def fetch_previous_anomalies_with_causes(cursor, crawl_date, retailer_id):
    """Return prior-day anomalies whose saved cause is still selectable."""
    cursor.execute("""
        SELECT a.retailersku, a.title, a.retailprice, a.ships_from,
               a.sold_by, a.imageurl, a.cause
        FROM ssd_crawl_db.ds_monitoring_report_anomaly a
        INNER JOIN ssd_crawl_db.ds_monitoring_anomaly_causes_options o
            ON o.retailer_id = a.retailer_id
           AND o.option_name = a.cause
           AND o.is_active = 1
        WHERE a.crawl_date = %s
          AND a.retailer_id = %s
          AND a.is_del = 0
          AND a.retailersku IS NOT NULL
          AND TRIM(a.retailersku) != ''
          AND a.cause IS NOT NULL
          AND TRIM(a.cause) != ''
    """, (crawl_date, retailer_id))
    return [
        {
            'retailersku': row[0],
            'title': row[1],
            'retailprice': row[2],
            'ships_from': row[3],
            'sold_by': row[4],
            'imageurl': row[5],
            'cause': row[6],
        }
        for row in cursor.fetchall()
    ]

def db_save_retailer_transaction(crawl_date, retailer_id, stats, anomalies, memo, user_id, now, cursor, conn):
    cursor.execute("UPDATE ssd_crawl_db.ds_monitoring_report_daily SET is_del = 1, updated_at = %s, updated_id = %s WHERE crawl_date = %s AND retailer_id = %s AND is_del = 0", (now, user_id, crawl_date, retailer_id))
    cursor.execute("UPDATE ssd_crawl_db.ds_monitoring_report_anomaly SET is_del = 1, updated_at = %s, updated_id = %s WHERE crawl_date = %s AND retailer_id = %s AND is_del = 0", (now, user_id, crawl_date, retailer_id))
    
    cursor.execute("SELECT id FROM ssd_crawl_db.ds_monitoring_report_daily WHERE crawl_date = %s AND retailer_id = %s AND is_del = 1 ORDER BY updated_at DESC LIMIT 1", (crawl_date, retailer_id))
    old_daily = cursor.fetchone()
    
    if old_daily:
        report_daily_id = old_daily[0]
        cursor.execute("""
            UPDATE ssd_crawl_db.ds_monitoring_report_daily
            SET is_del = 0, expected_count = %s, final_batch_count = %s, total_count = %s,
                completion_rate = %s, rerun_count = %s, anomaly_total = %s, anomaly_title_null = %s, anomaly_image_null = %s,
                anomaly_partial_null = %s, anomaly_price_zero = %s, memo = %s, updated_at = %s, updated_id = %s WHERE id = %s
        """, (stats['expected_count'], stats['final_batch_count'], stats['total_count'], stats['completion_rate'], stats['rerun_count'], stats['anomaly_total'], stats['anomaly_title_null'], stats['anomaly_image_null'], stats['anomaly_partial_null'], stats['anomaly_price_zero'], memo, now, user_id, report_daily_id))
    else:
        cursor.execute("""
            INSERT INTO ssd_crawl_db.ds_monitoring_report_daily (
                crawl_date, retailer_id, expected_count, final_batch_count, total_count, completion_rate, rerun_count, file_name, file_size,
                anomaly_total, anomaly_title_null, anomaly_image_null, anomaly_partial_null, anomaly_price_zero, memo, is_del, created_at, created_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, '', 0, %s, %s, %s, %s, %s, %s, 0, %s, %s)
        """, (crawl_date, retailer_id, stats['expected_count'], stats['final_batch_count'], stats['total_count'], stats['completion_rate'], stats['rerun_count'], stats['anomaly_total'], stats['anomaly_title_null'], stats['anomaly_image_null'], stats['anomaly_partial_null'], stats['anomaly_price_zero'], memo, now, user_id))
        report_daily_id = cursor.lastrowid
        
    cursor.execute("SELECT id, retailersku, screenshot_id, cause, memo FROM ssd_crawl_db.ds_monitoring_report_anomaly WHERE crawl_date = %s AND retailer_id = %s AND is_del = 1", (crawl_date, retailer_id))
    old_anomaly_map = {row[1]: {'id': row[0], 'screenshot_id': row[2], 'cause': row[3], 'memo': row[4]} for row in cursor.fetchall() if row[1]}
    
    anomaly_ids = []
    for anomaly in anomalies:
        sku = anomaly.get('retailersku', '')
        old = old_anomaly_map.pop(sku, None) if sku else None
        if old:
            cursor.execute("""
                UPDATE ssd_crawl_db.ds_monitoring_report_anomaly
                SET is_del = 0, country_code = %s, title = %s, retailprice = %s, ships_from = %s, sold_by = %s, imageurl = %s, producturl = %s, updated_at = %s, updated_id = %s
                WHERE id = %s
            """, (anomaly.get('country_code', ''), anomaly.get('title', ''), anomaly.get('retailprice'), anomaly.get('ships_from', ''), anomaly.get('sold_by', ''), anomaly.get('imageurl', ''), anomaly.get('producturl', ''), now, user_id, old['id']))
            anomaly_ids.append(old['id'])
        else:
            cursor.execute("""
                INSERT INTO ssd_crawl_db.ds_monitoring_report_anomaly (
                    crawl_date, retailer_id, country_code, title, retailprice, ships_from, sold_by, imageurl, producturl, retailersku, screenshot_id, cause, memo, is_del, created_at, created_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
            """, (crawl_date, retailer_id, anomaly.get('country_code', ''), anomaly.get('title', ''), anomaly.get('retailprice'), anomaly.get('ships_from', ''), anomaly.get('sold_by', ''), anomaly.get('imageurl', ''), anomaly.get('producturl', ''), anomaly.get('retailersku', ''), anomaly.get('screenshot_id'), anomaly.get('cause', ''), anomaly.get('memo', ''), now, user_id))
            anomaly_ids.append(cursor.lastrowid)

    orphan_screenshot_ids = [v['screenshot_id'] for v in old_anomaly_map.values() if v['screenshot_id']]
    if orphan_screenshot_ids:
        placeholders = ','.join(['%s'] * len(orphan_screenshot_ids))
        cursor.execute(f"UPDATE ssd_crawl_db.ds_monitoring_file SET is_del = 1, updated_at = %s WHERE file_id IN ({placeholders}) AND is_del = 0", [now] + orphan_screenshot_ids)
    
    conn.commit()
    return report_daily_id, anomaly_ids

def db_delete_retailer_transaction(crawl_date, retailer_id, user_id, now, cursor, conn):
    cursor.execute("UPDATE ssd_crawl_db.ds_monitoring_report_daily SET is_del = 1, updated_at = %s, updated_id = %s WHERE crawl_date = %s AND retailer_id = %s AND is_del = 0", (now, user_id, crawl_date, retailer_id))
    daily_deleted = cursor.rowcount
    cursor.execute("UPDATE ssd_crawl_db.ds_monitoring_report_anomaly SET is_del = 1, updated_at = %s, updated_id = %s WHERE crawl_date = %s AND retailer_id = %s AND is_del = 0", (now, user_id, crawl_date, retailer_id))
    anomaly_deleted = cursor.rowcount
    conn.commit()
    return daily_deleted, anomaly_deleted
