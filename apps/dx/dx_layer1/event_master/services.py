"""Monthly receipt checks; event content and batch completeness are not assessed."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import repositories

KST = timezone(timedelta(hours=9))
COUNTRIES = json.loads(Path(__file__).with_name('countries.json').read_text(encoding='utf-8'))['countries']
BY_NAME = {name: code for code, name in COUNTRIES.items()}
ALIASES = {'NEW ZELAND': 'NEW ZEALAND'}


def first_monday(day):
    first = day.replace(day=1)
    return first + timedelta(days=(-first.weekday()) % 7)


def build_check(selected, groups, now=None):
    selected = date.fromisoformat(str(selected))
    now = now or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    due = first_monday(selected)
    starts = datetime(due.year, due.month, due.day, 0, 30, tzinfo=KST)
    ends = (starts + timedelta(days=2)).replace(hour=0, minute=0)
    next_due = first_monday((due.replace(day=28) + timedelta(days=4)).replace(day=1))
    pending = selected < due or now < starts
    collecting = not pending and now < ends
    empty_status = 'COLLECTING' if collecting else 'PENDING'
    scheduled = due if pending or collecting else next_due
    rows = {code: {'country': name, 'country_code': code, 'count': 0,
                   'issues': [], 'issue_count': 0, 'status': empty_status,
                   'execution_date': None, 'scheduled_date': str(scheduled)} for code, name in COUNTRIES.items()}
    extra = {}
    for raw_name, raw_code, count, execution_date in ([] if pending else groups):
        name = (raw_name or '').strip().upper()
        canonical = ALIASES.get(name, name)
        code = BY_NAME.get(canonical)
        prefix = (raw_code or '').strip().upper().split('_', 1)[0]
        problems = []
        if not code:
            key = (name, prefix)
            row = extra.setdefault(key, {'country': raw_name or '(국가명 없음)',
                'country_code': raw_code or '-', 'count': 0, 'issues': [],
                'issue_count': 0, 'status': 'REVIEW', 'execution_date': str(due)})
            problems.append('대상 외 국가 또는 국가명 오류')
        else:
            row = rows[code]
            if name != canonical:
                problems.append(f'국가명 오류: {raw_name} → {canonical}')
            if prefix != code:
                problems.append(f'국가코드 불일치: {raw_code or "(없음)"} (기준 {code})')
        row['count'] += int(count)
        row['execution_date'] = max(row['execution_date'] or '', str(execution_date))
        if problems:
            row['issue_count'] += int(count)
            for problem in problems:
                if problem not in row['issues']:
                    row['issues'].append(problem)
        row['status'] = 'REVIEW' if row['issues'] else 'OK'
    countries = sorted(rows.values(), key=lambda row: row['country'])
    extras = sorted(extra.values(), key=lambda row: row['country'])
    received = sum(row['count'] > 0 for row in countries)
    missing = len(countries) - received
    review = sum(row['status'] == 'REVIEW' for row in countries) + len(extras)
    status = ('PENDING' if pending else 'REVIEW' if review
              else empty_status if missing else 'OK')
    return {'name': 'Event Master', 'check_type': 'event_master', 'status': status,
            'inspection_date': str(selected), 'execution_date': str(due),
            'execution_end_date': str(due + timedelta(days=1)),
            'query_end_date': str(min(selected, due + timedelta(days=1), now.date())),
            'before_start': pending, 'scheduled_date': str(scheduled),
            'description': '매월 첫 월요일 · 국가별 최종 결과 적재 확인',
            'expected': len(countries), 'actual': received, 'missing': missing,
            'review_count': review, 'unexpected_count': len(extras),
            'issue_count': sum(row['issue_count'] for row in countries + extras),
            'countries': countries, 'unexpected': extras,
            'display_group': 'periodic', 'is_target_date': not pending}


def get_layer1_stats(cursor, target_date, now=None):
    check = build_check(target_date, [], now)
    if check['before_start']:
        return {'check': check, 'failed_items': []}
    # A missing source table or query failure must not abort the other checks.
    cursor.execute('SAVEPOINT layer1_event_master')
    try:
        groups = repositories.country_counts(cursor, check['execution_date'], check['query_end_date'])
        check = build_check(target_date, groups, now)
    except Exception:
        cursor.execute('ROLLBACK TO SAVEPOINT layer1_event_master')
        check.update(status='ERROR', actual=None, missing=None, countries=[], unexpected=[],
                     description='Event Master 조회 실패 · 잠시 후 다시 조회해 주세요.')
    finally:
        cursor.execute('RELEASE SAVEPOINT layer1_event_master')
    return {'check': check, 'failed_items': [
        {'source': 'Event Master', 'error_type': '미수집' if check['status'] == 'CRITICAL' else '조회 오류',
         'expected': check['expected'], 'actual': check['actual'], 'timestamp': check['execution_date']}
    ] if check['status'] in ('CRITICAL', 'ERROR') else []}
