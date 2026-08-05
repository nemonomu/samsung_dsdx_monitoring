"""
검수 확인/완료 비즈니스 로직
- check_status, check_save, check_delete, check_memo_update, check_log_list
"""

from datetime import datetime
from apps.common.db import dx_table
from apps.common.monitoring_exclusions import DISABLED_CHECK_TYPES

_CHECK_LOG = dx_table('monitoring_check_log')
_CHECK_LOG_DETAIL = dx_table('monitoring_check_log_detail')
_CHECK_LOG_KEYWORDS = dx_table('monitoring_check_log_keywords')
_CHECK_LOG_ISSUES = dx_table('monitoring_check_log_issues')


def _detail_text(value, max_len=100):
    if value is None:
        return ''
    return str(value)[:max_len]


def _detail_long_text(value):
    if value is None:
        return ''
    return str(value)


ALL_SECTIONS = [
    'retail', 'sentiment', 'youtube', 'market_trend',
    'market_competitor', 'market_competitor_event',
    'market_demand', 'market_promotion',
]


def get_target_sections(date_str):
    """해당 날짜의 검증 대상 섹션 수 계산 (스케줄 DB 기반)"""
    from datetime import date as date_cls
    from apps.common.dx_schedules import load_collection_schedules, is_target_date as check_target_date

    target_date = date_cls.fromisoformat(date_str)
    schedules = load_collection_schedules()

    target_types = set()
    for s in schedules:
        if (
            s['check_type'] not in DISABLED_CHECK_TYPES
            and check_target_date(s, target_date)
        ):
            target_types.add(s['check_type'])

    return len(target_types)


def get_check_status(cursor, date_str, layer, include_detail=False):
    """날짜별 검수 확인 상태 조회"""
    cursor.execute(f"""
        SELECT id, section, expected_count, actual_count, rate, status, memo,
               created_id, created_at, updated_id, updated_at, confirm_step
        FROM {_CHECK_LOG}
        WHERE crawl_date = %s AND layer = %s AND is_del = 0
        ORDER BY id
    """, (date_str, layer))

    rows = cursor.fetchall()
    sections = {}
    for row in rows:
        sections[row[1]] = {
            'id': row[0],
            'expected_count': row[2],
            'actual_count': row[3],
            'rate': float(row[4]) if row[4] else 0,
            'status': row[5],
            'memo': row[6] or '',
            'created_id': row[7],
            'created_at': row[8].isoformat() if row[8] else None,
            'updated_id': row[9],
            'updated_at': row[10].isoformat() if row[10] else None,
            'confirm_step': row[11],
        }

    check_log_ids = [sections[s]['id'] for s in sections]
    if include_detail and check_log_ids:
        placeholders = ','.join(['%s'] * len(check_log_ids))
        cursor.execute(f"""
            SELECT d.id, d.section, d.category, d.time_slot, d.retailer,
                   d.item_name, d.expected_count, d.actual_count, d.rate, d.status,
                   d.issue_id, d.confirm_step
            FROM {_CHECK_LOG_DETAIL} d
            WHERE d.check_log_id IN ({placeholders})
            ORDER BY d.confirm_step, d.id
        """, check_log_ids)
        for dr in cursor.fetchall():
            sec_key = dr[1]
            step = dr[11]
            if sec_key in sections:
                cur_step = sections[sec_key]['confirm_step']
                detail_key = 'details' if step == cur_step else 'details_step1'
                if detail_key not in sections[sec_key]:
                    sections[sec_key][detail_key] = []
                sections[sec_key][detail_key].append({
                    'detail_id': dr[0],
                    'category': dr[2], 'time_slot': dr[3],
                    'retailer': dr[4], 'item_name': dr[5],
                    'expected_count': dr[6], 'actual_count': dr[7],
                    'rate': float(dr[8]) if dr[8] else 0, 'status': dr[9],
                    'issue_id': dr[10],
                })

    # 수요증감율: 부족 키워드 조인
    if include_detail and check_log_ids:
        kw_map = {}
        cursor.execute(f"""
            SELECT check_log_id, category, product_name, event_name, event_date
            FROM {_CHECK_LOG_KEYWORDS}
            WHERE check_log_id IN ({','.join(['%s'] * len(check_log_ids))})
            ORDER BY id
        """, check_log_ids)
        for kr in cursor.fetchall():
            kw_map.setdefault(kr[0], []).append({
                'category': kr[1], 'product_name': kr[2],
                'event_name': kr[3], 'event_date': str(kr[4]) if kr[4] else ''
            })
        for sec_key, sec_data in sections.items():
            if sec_data['id'] in kw_map:
                sec_data['missing_keywords'] = kw_map[sec_data['id']]

    target_count = get_target_sections(date_str)
    return {
        'success': True,
        'checked_all': len(sections) >= target_count,
        'checked_count': len(sections),
        'total_sections': target_count,
        'sections': sections
    }


def save_check(cursor, conn, date_str, layer, step, sections, username):
    """검수 확인 저장 (step=1: 1차 확인, step=2: 2차 완료)"""
    now = datetime.now()

    for s in sections:
        section = s.get('section', '')
        if section not in ALL_SECTIONS or section in DISABLED_CHECK_TYPES:
            continue

        details = s.get('details', [])
        if details:
            expected = sum(d.get('expected_count', 0) for d in details)
            actual = sum(d.get('actual_count', 0) for d in details)
        else:
            expected = s.get('expected_count', 0)
            actual = s.get('actual_count', 0)
        rate = round(actual / expected * 100) if expected > 0 else s.get('rate', 0)

        if step == 2:
            # 2차 완료: 미해결 이슈 체크
            cursor.execute(f"""
                SELECT COUNT(*) FROM {_CHECK_LOG_ISSUES}
                WHERE crawl_date = %s AND section = %s AND is_del = 0
                  AND resolution_status = 'open'
            """, (date_str, section))
            open_count = cursor.fetchone()[0]
            if open_count > 0:
                conn.rollback()
                return {
                    'success': False,
                    'error': '미해결 이슈 ' + str(open_count) + '건이 있습니다. 이슈를 먼저 처리하세요.'
                }

            # 2차 완료: 완료율 100% 체크 (retail 제외)
            if section != 'retail' and rate < 100:
                conn.rollback()
                return {
                    'success': False,
                    'error': f'완료율이 {rate}%입니다. 100% 달성 후 완료 처리하세요.',
                    'level': 'warning'
                }

            # 2차 완료: NULL 상태 detail 체크 (이슈 미등록 시에만 차단)
            null_items = [d for d in details if d.get('status') == 'NULL']
            if null_items:
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {_CHECK_LOG_ISSUES}
                    WHERE crawl_date = %s AND section = %s AND is_del = 0
                """, (date_str, section))
                issue_count = cursor.fetchone()[0]
                if issue_count == 0:
                    null_names = ', '.join(d.get('item_name', '') or d.get('retailer', '') for d in null_items)
                    conn.rollback()
                    return {
                        'success': False,
                        'error': 'NULL 상태 항목이 ' + str(len(null_items)) + '건 있습니다 (' + null_names + '). 이슈를 먼저 등록하세요.',
                        'level': 'warning'
                    }

            # check_log UPDATE (confirm_step=2, 최신 수치 반영)
            cursor.execute(f"""
                UPDATE {_CHECK_LOG}
                SET confirm_step = 2, expected_count = %s, actual_count = %s,
                    rate = %s, status = %s, updated_id = %s, updated_at = %s
                WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
            """, (expected, actual, rate, s.get('status', 'OK'),
                  username, now, date_str, layer, section))

            # 기존 check_log_id 조회
            cursor.execute(f"""
                SELECT id FROM {_CHECK_LOG}
                WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
            """, (date_str, layer, section))
            row = cursor.fetchone()
            if not row:
                # 1차 없이 바로 2차 (100% 섹션)
                cursor.execute(f"""
                    INSERT INTO {_CHECK_LOG}
                        (crawl_date, layer, section, expected_count, actual_count,
                         rate, status, memo, confirm_step, created_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 2, %s, %s)
                    RETURNING id
                """, (
                    date_str, layer, section,
                    expected, actual, rate, s.get('status', 'OK'),
                    s.get('memo', ''), username, now
                ))
                row = cursor.fetchone()
            check_log_id = row[0]

            # detail 전체 INSERT (confirm_step=2)
            for d in details:
                cursor.execute(f"""
                    INSERT INTO {_CHECK_LOG_DETAIL}
                        (check_log_id, crawl_date, layer, section,
                         category, time_slot, retailer, item_name,
                         expected_count, actual_count, rate, status, confirm_step)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2)
                """, (
                    check_log_id, date_str, layer, section,
                    _detail_text(d.get('category', '')),
                    _detail_text(d.get('time_slot', '')),
                    _detail_text(d.get('retailer', '')),
                    _detail_long_text(d.get('item_name', '')),
                    d.get('expected_count', 0), d.get('actual_count', 0),
                    d.get('rate', 0), _detail_text(d.get('status', 'OK'))
                ))

        else:
            # 1차 확인: 기존 soft-delete → INSERT 패턴
            cursor.execute(f"""
                UPDATE {_CHECK_LOG}
                SET is_del = 1, updated_id = %s, updated_at = %s
                WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
            """, (username, now, date_str, layer, section))

            cursor.execute(f"""
                INSERT INTO {_CHECK_LOG}
                    (crawl_date, layer, section, expected_count, actual_count,
                     rate, status, memo, confirm_step, created_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                RETURNING id
            """, (
                date_str, layer, section,
                expected, actual,
                rate, s.get('status', 'OK'), s.get('memo', ''),
                username, now
            ))
            check_log_id = cursor.fetchone()[0]

            # detail: 이상치(status≠OK)만 INSERT (confirm_step=1)
            for d in details:
                if d.get('status', 'OK') != 'OK':
                    cursor.execute(f"""
                        INSERT INTO {_CHECK_LOG_DETAIL}
                            (check_log_id, crawl_date, layer, section,
                             category, time_slot, retailer, item_name,
                             expected_count, actual_count, rate, status, confirm_step)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """, (
                        check_log_id, date_str, layer, section,
                        _detail_text(d.get('category', '')),
                        _detail_text(d.get('time_slot', '')),
                        _detail_text(d.get('retailer', '')),
                        _detail_long_text(d.get('item_name', '')),
                        d.get('expected_count', 0), d.get('actual_count', 0),
                        d.get('rate', 0), _detail_text(d.get('status', 'OK'))
                    ))

            # 수요증감율 부족 키워드 저장
            keywords = s.get('keywords', [])
            if keywords:
                for kw in keywords:
                    cursor.execute(f"""
                        INSERT INTO {_CHECK_LOG_KEYWORDS}
                            (check_log_id, crawl_date, category, event_name,
                             product_name, event_date, created_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        check_log_id, date_str,
                        kw.get('category', ''), kw.get('event_name', ''),
                        kw.get('product_name', ''), kw.get('event_date'),
                        username, now
                    ))

    conn.commit()
    return {'success': True, 'saved_count': len(sections), 'step': step}


def delete_check(cursor, conn, date_str, layer, section, step, delete_memo, username):
    """검수 확인 취소 (step에 따라 다른 동작)"""
    now = datetime.now()

    if step == 2 and section:
        # 2차 완료 취소
        cursor.execute(f"""
            SELECT id, updated_at FROM {_CHECK_LOG}
            WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
        """, (date_str, layer, section))
        row = cursor.fetchone()
        if row:
            check_log_id = row[0]
            has_step1 = row[1] is not None
            cursor.execute(f"""
                DELETE FROM {_CHECK_LOG_DETAIL}
                WHERE check_log_id = %s AND confirm_step = 2
            """, (check_log_id,))
            if has_step1:
                cursor.execute(f"""
                    UPDATE {_CHECK_LOG}
                    SET confirm_step = 1, updated_id = %s, updated_at = %s, delete_memo = %s
                    WHERE id = %s
                """, (username, now, delete_memo, check_log_id))
            else:
                cursor.execute(f"DELETE FROM {_CHECK_LOG_KEYWORDS} WHERE check_log_id = %s", (check_log_id,))
                cursor.execute(f"""
                    UPDATE {_CHECK_LOG}
                    SET is_del = 1, updated_id = %s, updated_at = %s, delete_memo = %s
                    WHERE id = %s
                """, (username, now, delete_memo, check_log_id))
    elif section:
        # 1차 확인 취소
        cursor.execute(f"""
            SELECT id FROM {_CHECK_LOG}
            WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
        """, (date_str, layer, section))
        del_row = cursor.fetchone()
        if del_row:
            cursor.execute(f"DELETE FROM {_CHECK_LOG_KEYWORDS} WHERE check_log_id = %s", (del_row[0],))
        cursor.execute(f"""
            UPDATE {_CHECK_LOG}
            SET is_del = 1, updated_id = %s, updated_at = %s, delete_memo = %s
            WHERE crawl_date = %s AND layer = %s AND section = %s AND is_del = 0
        """, (username, now, delete_memo, date_str, layer, section))
    else:
        cursor.execute(f"""
            UPDATE {_CHECK_LOG}
            SET is_del = 1, updated_id = %s, updated_at = %s, delete_memo = %s
            WHERE crawl_date = %s AND layer = %s AND is_del = 0
        """, (username, now, delete_memo, date_str, layer))

    conn.commit()
    return {'success': True, 'deleted': cursor.rowcount}
