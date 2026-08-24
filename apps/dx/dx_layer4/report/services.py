"""
Layer 4 보고서 Services — 보고서 데이터 조회
"""

from apps.common.db import dx_connection


def _merge_tse_auto_null_reviews(
        auto_reviews, type_summary, reason_summary, table_summary, details):
    """Merge virtual daily carry-forward records into the report payload."""
    if not auto_reviews:
        return

    null_summary = type_summary.setdefault('null_check', {})
    null_summary['normal'] = null_summary.get('normal', 0) + len(auto_reviews)

    auto_reason = '해당값정상 확인 (자동 적용)'
    reason_row = next((
        row for row in reason_summary
        if row['reason'] == auto_reason
        and row['correction_type'] == 'null_check'
    ), None)
    if reason_row is None:
        reason_row = {
            'reason': auto_reason,
            'correction_type': 'null_check',
            'count': 0,
        }
        reason_summary.append(reason_row)
    reason_row['count'] += len(auto_reviews)

    for review in auto_reviews:
        table_name = review['table_name']
        table_null = table_summary.setdefault(
            table_name, {}
        ).setdefault('null_check', {})
        table_null['normal'] = table_null.get('normal', 0) + 1
        details.append({
            'correction_type': 'null_check',
            'table_name': table_name,
            'column_name': review['column_name'],
            'record_id': review['record_id'],
            'old_value': None,
            'new_value': None,
            'status': 'normal',
            'memo': review.get('memo', ''),
            'reason': auto_reason,
            'created_id': review.get('created_id', ''),
            'retailer': review.get('retailer', ''),
            'item': review.get('item', ''),
            'rule_id': None,
            'rule_name': '',
            'detail_code': '',
            'auto_applied': True,
            'original_crawl_date': review.get('original_crawl_date', ''),
            'original_created_at': review.get('original_created_at', ''),
        })


def get_report_data(target_date):
    """보고서 데이터 조회"""
    with dx_connection() as (conn, cursor):
        cursor.execute("""
            SELECT section, expected_count, actual_count, rate, status, memo
            FROM monitoring_check_log
            WHERE crawl_date = %s AND layer = 1 AND is_del = 0 AND confirm_step = 2
            ORDER BY id
        """, (str(target_date),))
        collection_status = []
        for row in cursor.fetchall():
            if (row[0] or '').lower() in {'retail_hhp', 'hhp_retail'}:
                continue
            collection_status.append({
                'section': row[0],
                'expected': row[1] or 0,
                'actual': row[2] or 0,
                'rate': float(row[3]) if row[3] else 0,
                'status': row[4] or '',
                'memo': row[5] or '',
            })

        cursor.execute("""
            SELECT id, section, title, issue_date, symptom, cause, action,
                   resolution_status, resolution_memo
            FROM monitoring_check_log_issues
            WHERE crawl_date = %s AND is_del = 0
            ORDER BY section, id
        """, (str(target_date),))
        collection_issues = []
        for row in cursor.fetchall():
            collection_issues.append({
                'id': row[0],
                'section': row[1],
                'title': row[2],
                'issue_date': row[3] or '',
                'symptom': row[4] or '',
                'cause': row[5] or '',
                'action': row[6] or '',
                'resolution_status': row[7] or 'open',
                'resolution_memo': row[8] or '',
            })

        cursor.execute("""
            SELECT correction_type, status, COUNT(*) as cnt
            FROM monitoring_corrections
            WHERE crawl_date = %s AND status IS NOT NULL AND table_name <> 'hhp_retail_com'
            GROUP BY correction_type, status
            ORDER BY correction_type, status
        """, (str(target_date),))
        type_summary = {}
        for row in cursor.fetchall():
            ct = row[0]
            if ct not in type_summary:
                type_summary[ct] = {}
            type_summary[ct][row[1]] = row[2]

        cursor.execute("""
            SELECT reason, correction_type, COUNT(*) as cnt
            FROM monitoring_corrections
            WHERE crawl_date = %s AND status = 'normal' AND table_name <> 'hhp_retail_com'
            GROUP BY reason, correction_type
            ORDER BY cnt DESC
        """, (str(target_date),))
        reason_summary = []
        for row in cursor.fetchall():
            reason_summary.append({
                'reason': row[0] or '미지정',
                'correction_type': row[1],
                'count': row[2],
            })

        cursor.execute("""
            SELECT table_name, correction_type, status, COUNT(*) as cnt
            FROM monitoring_corrections
            WHERE crawl_date = %s AND status IS NOT NULL AND table_name <> 'hhp_retail_com'
            GROUP BY table_name, correction_type, status
            ORDER BY table_name, correction_type
        """, (str(target_date),))
        table_summary = {}
        for row in cursor.fetchall():
            tn = row[0]
            if tn not in table_summary:
                table_summary[tn] = {}
            ct = row[1]
            if ct not in table_summary[tn]:
                table_summary[tn][ct] = {}
            table_summary[tn][ct][row[2]] = row[3]

        cursor.execute("""
            SELECT c.correction_type, c.table_name, c.column_name,
                   c.record_id, c.old_value, c.new_value, c.status, c.memo,
                   c.reason, c.created_id, c.retailer, c.item,
                   c.rule_id, r.detail_name, r.detail_code
            FROM monitoring_corrections c
            LEFT JOIN monitoring_validation_rules r ON c.rule_id = r.id
            WHERE c.crawl_date = %s AND c.status IN ('corrected', 'normal')
              AND c.table_name <> 'hhp_retail_com'
            ORDER BY c.correction_type, c.table_name, c.created_at
        """, (str(target_date),))
        details = []
        for row in cursor.fetchall():
            details.append({
                'correction_type': row[0],
                'table_name': row[1],
                'column_name': row[2],
                'record_id': row[3],
                'old_value': row[4],
                'new_value': row[5],
                'status': row[6],
                'memo': row[7] or '',
                'reason': row[8] or '',
                'created_id': row[9] or '',
                'retailer': row[10] or '',
                'item': row[11] or '',
                'rule_id': row[12],
                'rule_name': row[13] or '',
                'detail_code': row[14] or '',
            })

        from apps.dx.dx_layer2.null_validation.services import (
            get_tse_auto_applied_null_reviews,
        )
        auto_null_reviews = get_tse_auto_applied_null_reviews(
            cursor, target_date
        )
        _merge_tse_auto_null_reviews(
            auto_null_reviews,
            type_summary,
            reason_summary,
            table_summary,
            details,
        )

        cursor.execute("""
            SELECT h.table_name, h.item_id,
                   m_tv.account_name as account_name,
                   m_tv.item as item
            FROM item_mst_history h
            LEFT JOIN tv_item_mst m_tv ON h.table_name = 'tv_item_mst' AND h.item_id = m_tv.id
            WHERE h.field_name = 'is_product'
              AND h.table_name = 'tv_item_mst'
              AND h.old_value = 'True' AND h.new_value = 'False'
              AND DATE(h.changed_at) = DATE(%s) + INTERVAL '1 day'
            ORDER BY h.table_name, h.changed_at
        """, (str(target_date),))
        excluded_items = []
        for row in cursor.fetchall():
            excluded_items.append({
                'category': 'TV',
                'account_name': row[2] or '',
                'item': row[3] or '',
            })

        cursor.execute("""
            SELECT k.event_name, k.category, k.product_name, k.event_date
            FROM monitoring_check_log_keywords k
            JOIN monitoring_check_log cl ON k.check_log_id = cl.id
            WHERE cl.crawl_date = %s AND cl.section = 'market_demand' AND cl.is_del = 0
            ORDER BY k.event_name, k.category, k.product_name
        """, (str(target_date),))
        missing_keywords = []
        for row in cursor.fetchall():
            missing_keywords.append({
                'event_name': row[0],
                'category': row[1],
                'product_name': row[2],
                'event_date': str(row[3]) if row[3] else '',
            })

    grouped_details = {}
    for d in details:
        ct = d['correction_type']
        tn = d['table_name']
        if ct not in grouped_details:
            grouped_details[ct] = {}
        if tn not in grouped_details[ct]:
            grouped_details[ct][tn] = []
        grouped_details[ct][tn].append(d)

    return {
        'success': True,
        'date': str(target_date),
        'collection_status': collection_status,
        'collection_issues': collection_issues,
        'missing_keywords': missing_keywords,
        'type_summary': type_summary,
        'reason_summary': reason_summary,
        'table_summary': table_summary,
        'details': details,
        'grouped_details': grouped_details,
        'excluded_items': excluded_items,
    }
