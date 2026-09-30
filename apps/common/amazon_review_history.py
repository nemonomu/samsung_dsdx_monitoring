"""SEG/SIEL Amazon review-body presence over the preceding ten source days."""
from collections import defaultdict
from datetime import date, timedelta

from apps.common.seg_retail import get_seg_source
from apps.common.siel_retail import SIEL_BUSINESS_TIMEZONE, get_siel_source

RULE_KEY = 'amazon_review_body_history'
LOOKBACK_DAYS = 10
EMPTY_BODY_VALUES = ('', '-', 'none', 'null', 'n/a')
RULE_SPEC = {
    'detail_name': 'Amazon 최근 10일 이력 기준 리뷰본문 누락',
    'guide_description': (
        '현재 리뷰본문이 NULL·빈값인 Amazon 상품만 검사합니다. 당일을 제외한 이전 10일 중 같은 상품의 '
        '리뷰본문이 한 번이라도 있었으면 이상입니다. 과거 수집 이력은 있지만 본문은 계속 없었다면 정상입니다. '
        '과거 수집 이력 자체가 없으면 현재 별점이 0보다 크고 별점 수 또는 리뷰 수가 1 이상인 경우 이상입니다.'
    ),
    'field1': 'detailed_review_content',
    'field2': 'star_rating|count_of_star_ratings|count_of_reviews',
    'retailers': ('Amazon',),
    'display_fields': ('issue_type', 'star_rating', 'count_of_star_ratings', 'count_of_reviews',
                       'detailed_review_content', 'review_history_days', 'review_history_start',
                       'review_history_end', 'previous_source_date'),
    'error_message': '최근 10일 내 리뷰본문이 있었으나 현재 누락되었거나, 과거 수집 이력 없이 별점·평가/리뷰 수만 있습니다.',
}


def has_body(value):
    return value is not None and str(value).strip().lower() not in EMPTY_BODY_VALUES


def _item(row):
    value = str(row.get('item') or '').strip()
    return value if value.lower() not in EMPTY_BODY_VALUES else ''


def _dict_rows(cursor):
    columns = [column[0] for column in (cursor.description or ())]
    return [dict(row) if isinstance(row, dict) else dict(zip(columns, row)) for row in cursor.fetchall()]


def load_findings(cursor, country, product_line, rows, *, date_of, parse_number):
    source = {'SEG': get_seg_source, 'SIEL': get_siel_source}[country](product_line)
    if 'Amazon' not in source['retailers']:
        return {}, []
    column = source['date_column']
    candidates = [row for row in rows if str(row.get('account_name') or '').strip().lower() == 'amazon'
                  and not has_body(row.get('detailed_review_content')) and _item(row)
                  and row.get('redirect') is not True]
    if not candidates:
        return {}, []
    days = [date.fromisoformat(date_of(row, column)) for row in candidates]
    start, end = min(days) - timedelta(days=LOOKBACK_DAYS), max(days)
    items = sorted({_item(row) for row in candidates})
    table = source['table_name']
    if country == 'SEG':
        day_sql = f'LEFT(BTRIM(CAST(source.{column} AS TEXT)), 10)'
        range_sql = f'{day_sql} >= %s AND {day_sql} < %s'
    else:
        day_sql = f"(source.{column} AT TIME ZONE '{SIEL_BUSINESS_TIMEZONE}')::date"
        range_sql = (f"source.{column} >= (%s::date::timestamp AT TIME ZONE '{SIEL_BUSINESS_TIMEZONE}') "
                     f"AND source.{column} < (%s::date::timestamp AT TIME ZONE '{SIEL_BUSINESS_TIMEZONE}')")
    item_sql = 'BTRIM(CAST(source.item AS TEXT))'
    body_sql = ("LOWER(BTRIM(COALESCE(CAST(source.detailed_review_content AS TEXT), ''), "
                "' ' || CHR(9) || CHR(10) || CHR(13))) NOT IN ('', '-', 'none', 'null', 'n/a')")
    # All valid MAIN/BSR collections count as history. Do not reduce history to
    # the most recent row: an older nonempty body inside the window is evidence.
    cursor.execute(f"""
        SELECT {item_sql} AS item, {day_sql} AS source_date,
               COUNT(*) AS history_rows,
               MAX(source.id) FILTER (WHERE {body_sql}) AS body_record_id
        FROM {table} source
        WHERE {range_sql}
          AND UPPER(BTRIM(CAST(source.country AS TEXT))) = %s
          AND LOWER(BTRIM(CAST(source.account_name AS TEXT))) = 'amazon'
          AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) IN ('main', 'bsr')
          AND source.redirect IS NOT TRUE
          AND {item_sql} = ANY(%s)
        GROUP BY {item_sql}, {day_sql}
    """, (str(start), str(end), country, items))
    history = defaultdict(list)
    for old in _dict_rows(cursor):
        history[_item(old)].append(old)
    findings, evidence_ids = {}, set()
    for row, day in zip(candidates, days):
        lower = day - timedelta(days=LOOKBACK_DAYS)
        previous = [old for old in history[_item(row)]
                    if str(lower) <= str(old['source_date'])[:10] < str(day)]
        with_body = [old for old in previous if old['body_record_id'] is not None]
        evidence = max(with_body, key=lambda old: str(old['source_date'])) if with_body else None
        rating = parse_number(row.get('star_rating'))
        counts = [parse_number(row.get(key)) for key in ('count_of_star_ratings', 'count_of_reviews')]
        if not evidence and (previous or rating is None or rating <= 0
                             or not any(count is not None and count >= 1 for count in counts)):
            continue
        issue = ('최근 10일 내 본문 존재 · 현재 본문 누락' if evidence
                 else '최근 10일 수집 이력 없음 · 별점/평가 수 존재 · 본문 누락')
        findings[str(row['id'])] = {
            'issue_type': issue, 'validation_tag': issue,
            'review_history_days': len(previous), 'review_history_start': str(lower),
            'review_history_end': str(day - timedelta(days=1)),
            'previous_source_date': str(evidence['source_date'])[:10] if evidence else None,
        }
        if evidence:
            evidence_ids.add(evidence['body_record_id'])
    if not evidence_ids:
        return findings, []
    cursor.execute(f"SELECT source.* FROM {table} source WHERE source.id = ANY(%s)", (sorted(evidence_ids),))
    return findings, _dict_rows(cursor)
