"""DS cause provenance: immutable source snapshots and explicit legacy evidence."""
import json
from datetime import date, timedelta

from apps.ds.ds_layer2.report.anomaly_causes import anomaly_signature, _normalized_sku


SOURCE_FIELDS = (
    'id', 'crawl_date', 'retailersku', 'title', 'retailprice', 'ships_from',
    'sold_by', 'imageurl', 'screenshot_id', 'cause', 'created_at', 'created_id',
    'updated_at', 'updated_id',
)


def record_cause_application(cursor, anomaly_id, cause, user_id, now, source=None):
    cause = str(cause or '').strip()
    if cause.casefold() == 'crawler_null_capture':
        cause = ''
    cursor.execute("""
        SELECT cause FROM ssd_crawl_db.ds_monitoring_cause_history
        WHERE anomaly_id = %s ORDER BY id DESC LIMIT 1
    """, (anomaly_id,))
    latest = cursor.fetchone()
    if latest and latest[0] == cause:
        return
    snapshot = {key: source.get(key) for key in SOURCE_FIELDS} if source else None
    cursor.execute("""
        INSERT INTO ssd_crawl_db.ds_monitoring_cause_history
            (anomaly_id, application_type, cause, source_snapshot, applied_at, applied_by)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (anomaly_id, 'automatic' if source else 'manual', cause,
          json.dumps(snapshot, ensure_ascii=False, default=str) if snapshot else None,
          now, user_id))


def fetch_cause_applications(cursor, anomaly_ids):
    if not anomaly_ids:
        return {}
    placeholders = ','.join(['%s'] * len(anomaly_ids))
    cursor.execute(f"""
        SELECT h.anomaly_id, h.application_type, h.cause, h.source_snapshot,
               h.applied_at, h.applied_by
        FROM ssd_crawl_db.ds_monitoring_cause_history h
        JOIN (
            SELECT MAX(id) AS id FROM ssd_crawl_db.ds_monitoring_cause_history
            WHERE anomaly_id IN ({placeholders}) GROUP BY anomaly_id
        ) latest ON latest.id = h.id
    """, list(anomaly_ids))
    return {
        row[0]: {
            'status': row[1], 'cause': row[2],
            'source': json.loads(row[3]) if row[3] else None,
            'applied_at': str(row[4]), 'applied_by': row[5],
        }
        for row in cursor.fetchall()
    }


def attach_cause_history(cursor, anomalies, target_date):
    histories = fetch_cause_applications(cursor, [a['id'] for a in anomalies])
    legacy = []
    for anomaly in anomalies:
        history = histories.get(anomaly['id'])
        if history and history['cause'] == str(anomaly.get('cause') or '').strip():
            anomaly['cause_history'] = history
        else:
            anomaly['cause_history'] = {'status': 'unrecorded' if anomaly.get('cause') else 'none'}
            if anomaly.get('cause'):
                legacy.append(anomaly)
    if not legacy:
        return

    # Legacy rows have no provenance. Show comparison evidence, never claim an automatic event.
    retailer_ids = sorted({a['retailer_id'] for a in legacy})
    placeholders = ','.join(['%s'] * len(retailer_ids))
    previous_date = date.fromisoformat(str(target_date)[:10]) - timedelta(days=1)
    cursor.execute(f"""
        SELECT a.id, a.crawl_date, a.retailersku, a.title, a.retailprice,
               a.ships_from, a.sold_by, a.imageurl, a.screenshot_id, a.cause,
               a.created_at, a.created_id, a.updated_at, a.updated_id, a.retailer_id
        FROM ssd_crawl_db.ds_monitoring_report_anomaly a
        LEFT JOIN ssd_crawl_db.ds_monitoring_anomaly_causes_options o
          ON o.retailer_id = a.retailer_id AND o.option_name = a.cause
        WHERE a.crawl_date = %s AND a.retailer_id IN ({placeholders})
          AND a.is_del = 0 AND a.cause IS NOT NULL AND TRIM(a.cause) != ''
          AND LOWER(TRIM(a.cause)) != 'crawler_null_capture'
          AND (o.option_id IS NULL OR o.is_active = 1)
    """, [previous_date, *retailer_ids])
    candidates = {}
    for row in cursor.fetchall():
        source = dict(zip(SOURCE_FIELDS, row[:14]))
        sku = _normalized_sku(source['retailersku'])
        signature = anomaly_signature(source)
        if sku and signature:
            candidates.setdefault((row[14], sku, signature), []).append(source)
    for anomaly in legacy:
        matches = candidates.get((anomaly['retailer_id'], _normalized_sku(anomaly['retailersku']),
                                  anomaly_signature(anomaly)), [])
        causes = {str(row['cause']).strip() for row in matches}
        if causes == {str(anomaly['cause']).strip()}:
            source = max(matches, key=lambda row: row['id'])
            anomaly['cause_history'] = {
                'status': 'legacy_match',
                'source': json.loads(json.dumps(source, ensure_ascii=False, default=str)),
            }
