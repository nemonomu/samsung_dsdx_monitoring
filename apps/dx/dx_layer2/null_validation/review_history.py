"""Read-only, all-country NULL review history and server-side filtering.

Automatic rows are reconstructed by the worklist's existing decision function;
this module never creates, revokes, or changes review evidence.
"""

from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from math import ceil
from threading import Lock
from time import monotonic

from apps.common.null_review_evidence import KOREA, POLICY_START
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.common.seg_retail import SEG_SOURCE_CONFIG
from apps.common.siel_retail import SIEL_SOURCE_CONFIG
from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.common.sem_retail import SEM_SOURCE_CONFIG
from apps.common.tse_retail import TSE_SOURCE_CONFIG


PAGE_SIZE = 50
COUNTRIES = ('SEA', 'SEG', 'SIEL', 'SEDA', 'SEM', 'TSE')
PRODUCTS = ('TV', 'REF', 'LDY')
_HISTORY_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_TTL = 60


def _table_key(value):
    return str(value or '').removeprefix('public.')


def _sources():
    result = {}
    for country, sources in zip(COUNTRIES, (
            SEA_RETAIL_SOURCES, SEG_SOURCE_CONFIG, SIEL_SOURCE_CONFIG,
            SEDA_SOURCE_CONFIG, SEM_SOURCE_CONFIG, TSE_SOURCE_CONFIG)):
        for key, source in sources.items():
            result[_table_key(source['table_name'])] = {
                **source, 'country': country,
                'product_line': key.rsplit('_', 1)[-1].upper(),
                'history_category': ('tv_retail' if country == 'SEA' and key == 'tv'
                                     else f'{country.lower()}_{key.rsplit("_", 1)[-1]}_retail'),
            }
    return result


def _day(value):
    if isinstance(value, datetime):
        return _korean_time(value).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _korean_time(value):
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (value.replace(tzinfo=KOREA) if value.tzinfo is None
            else value.astimezone(KOREA))


def parse_filters(params, today=None):
    today = today or datetime.now(KOREA).date()
    # Retain the old single-date API query as an inclusive one-day range.
    mode = params.get('period') or ('calendar' if params.get('date') else 'today')
    if mode not in ('today', 'all', 'calendar'):
        raise ValueError('기간은 오늘, 전체 또는 달력으로 선택해 주세요.')
    start = end = None
    if mode == 'today':
        start = end = today
    elif mode == 'calendar':
        try:
            start = date.fromisoformat(params.get('start_date') or params.get('date') or '')
            end = date.fromisoformat(params.get('end_date') or params.get('date') or '')
        except (ValueError, TypeError):
            raise ValueError('시작일과 종료일을 올바르게 선택해 주세요.') from None
        if start > end:
            raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
    country = params.get('country', '').upper()
    product = params.get('product_line', '').upper()
    kind = params.get('kind', 'all')
    if country and country not in COUNTRIES:
        raise ValueError('올바른 국가를 선택해 주세요.')
    if product and product not in PRODUCTS:
        raise ValueError('올바른 제품군을 선택해 주세요.')
    if kind not in ('all', 'manual', 'auto'):
        raise ValueError('올바른 확인 구분을 선택해 주세요.')
    try:
        page = int(params.get('page', 1))
        if page < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('페이지 번호가 올바르지 않습니다.') from None
    return dict(period=mode, start=start, end=end, today=today, country=country,
                product_line=product, retailer=params.get('retailer', '').strip(),
                kind=kind, memo_only=params.get('memo_only') == '1',
                q=params.get('q', '').strip().casefold(), page=page,
                refresh=params.get('refresh') == '1')


def _manual_rows(cursor, sources):
    aliases = [alias for key, source in sources.items()
               for alias in {key, source['table_name']}]
    cursor.execute("""
        SELECT c.id, c.table_name, c.record_id, c.retailer, c.item,
               c.column_name, c.reason, c.memo, c.crawl_date,
               c.created_id, c.created_at, e.id, e.country, e.product_line,
               e.product_name, e.reviewed_at, e.reviewer, e.memo,
               e.revoked_at
        FROM monitoring_corrections c
        LEFT JOIN public.monitoring_null_review_evidence e ON e.correction_id = c.id
        WHERE c.layer = 2 AND c.correction_type = 'null_check'
          AND c.status = 'normal' AND c.table_name = ANY(%s)
        ORDER BY c.created_at DESC, c.id DESC
    """, (aliases,))
    logs = []
    for row in cursor.fetchall():
        source = sources[_table_key(row[1])]
        reviewed = _korean_time(row[15] or row[10])
        logs.append(dict(
            id=f'manual:{row[0]}', correction_id=row[0], table_name=row[1],
            record_id=row[2], retailer=row[3], item=row[4], column_name=row[5],
            reason=row[6], memo=row[17] if row[11] else row[7],
            crawl_date=str(row[8]), applied_date=reviewed.date().isoformat(),
            created_id=row[16] or row[9], created_at=reviewed.isoformat(),
            original_created_at=reviewed.isoformat(), evidence_id=row[11],
            country=row[12] or source['country'],
            product_line=row[13] or source['product_line'],
            retailer_sku_name=row[14] or '', revoked_at=row[18],
            auto_applied=False, application_type='수동확인',
        ))
    return logs


def _auto_days(cursor, filters, manual, sources):
    """Bound reconstruction by evidence availability, including revoked history."""
    cursor.execute("""
        SELECT table_name, MIN(inspection_date)
        FROM public.monitoring_null_review_evidence
        WHERE policy_version = 1
        GROUP BY table_name
    """)
    end = min(filters['end'] or filters['today'], filters['today'])
    days = set()
    for table, first in cursor.fetchall():
        source = sources.get(_table_key(table))
        if not source or any(filters[key] and filters[key] != source[key]
                             for key in ('country', 'product_line')):
            continue
        day = max(_day(first), POLICY_START, filters['start'] or _day(first))
        while day <= end:
            days.add((day, source['history_category']))
            day += timedelta(days=1)
    # Before the immutable-evidence policy, TSE carried approvals for 14 days.
    for log in manual:
        original = _day(log['crawl_date'])
        if log['country'] != 'TSE' or original >= POLICY_START:
            continue
        for offset in range(1, 14):
            day = original + timedelta(days=offset)
            if day < POLICY_START and day <= end and (
                    not filters['start'] or day >= filters['start']):
                days.add((day, ''))
    return sorted(days, reverse=True)


def _enrich_rows(cursor, logs, sources):
    grouped = defaultdict(list)
    for log in logs:
        key = _table_key(log.get('table_name'))
        if key in sources:
            grouped[key].append(log)
    for key, entries in grouped.items():
        source = sources[key]
        # Only fixed registry identifiers are interpolated. JSON field access
        # supports older tables lacking SKU/URL without selecting private data.
        cursor.execute(f"""
            SELECT id, to_jsonb(s)->>'sku', to_jsonb(s)->>'product_url',
                   COALESCE(to_jsonb(s)->>'crawl_strdatetime',
                            to_jsonb(s)->>'crawl_datetime'),
                   to_jsonb(s)->>'retailer_sku_name', to_jsonb(s)->>'item'
            FROM {source['table_name']} s WHERE id = ANY(%s)
        """, (sorted({int(row['record_id']) for row in entries}),))
        records = {str(row[0]): row for row in cursor.fetchall()}
        for log in entries:
            log['country'] = source['country']
            log['product_line'] = source['product_line']
            row = records.get(str(log['record_id']))
            if row:
                log.update(sku=row[1], product_url=row[2], collected_at=row[3])
                log['retailer_sku_name'] = log.get('retailer_sku_name') or row[4]
                log['item'] = log.get('item') or row[5]


SEARCH_FIELDS = (
    'country', 'product_line', 'retailer', 'item', 'sku', 'record_id',
    'collected_at', 'retailer_sku_name', 'product_url', 'application_type',
    'column_name', 'reason', 'memo', 'created_id', 'original_created_at',
    'applied_date', 'crawl_date',
)


def paginate(logs, filters):
    retailers = sorted({str(row['retailer']) for row in logs if row.get('retailer')},
                       key=str.casefold)
    matched = []
    for log in logs:
        if any(filters[key] and str(log.get(key, '')).casefold() != filters[key].casefold()
               for key in ('country', 'product_line', 'retailer')):
            continue
        automatic = bool(log.get('auto_applied'))
        if filters['kind'] != 'all' and automatic != (filters['kind'] == 'auto'):
            continue
        if filters['q'] and not any(filters['q'] in str(log.get(key) or '').casefold()
                                    for key in SEARCH_FIELDS):
            continue
        matched.append(log)
    memo_count = sum(bool(str(row.get('memo') or '').strip()) for row in matched)
    if filters['memo_only']:
        matched = [row for row in matched if str(row.get('memo') or '').strip()]
    matched.sort(key=lambda row: (
        str(row.get('applied_date') or ''),
        str(row.get('original_created_at') or row.get('created_at') or ''),
        str(row.get('id') or ''),
    ), reverse=True)
    total = len(matched)
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(filters['page'], pages)
    return dict(logs=matched[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
                total=total, memo_count=memo_count, page=page, pages=pages,
                page_size=PAGE_SIZE, retailers=retailers,
                start_date=str(filters['start'] or ''),
                end_date=str(filters['end'] or ''), period=filters['period'],
                supports_null_auto_review=True)


def get_review_history(cursor, filters, auto_loader):
    # Reuse one read-only result for pagination/search. An explicit 조회 always
    # rebuilds it, and background changes become visible within 60 seconds.
    cache_key = tuple(filters[key] for key in (
        'period', 'start', 'end', 'today', 'country', 'product_line', 'kind'))
    with _CACHE_LOCK:
        cached = _HISTORY_CACHE.get(cache_key)
        if not filters['refresh'] and cached and monotonic() - cached[0] < _CACHE_TTL:
            _HISTORY_CACHE.move_to_end(cache_key)
            return paginate(cached[1], filters)
    sources = _sources()
    manual = _manual_rows(cursor, sources)
    logs = list(manual) if filters['kind'] != 'auto' else []
    if filters['kind'] != 'manual':
        for day, category in _auto_days(cursor, filters, manual, sources):
            rows = auto_loader(cursor, day, **({'category': category} if category else {}))
            logs.extend(dict(row) for row in rows)
    logs = [row for row in logs if
            (not filters['start'] or _day(row['applied_date']) >= filters['start'])
            and (not filters['end'] or _day(row['applied_date']) <= filters['end'])]
    _enrich_rows(cursor, logs, sources)
    with _CACHE_LOCK:
        if len(logs) <= 50000:
            _HISTORY_CACHE[cache_key] = (monotonic(), logs)
            _HISTORY_CACHE.move_to_end(cache_key)
            while len(_HISTORY_CACHE) > 4:
                _HISTORY_CACHE.popitem(last=False)
        else:
            _HISTORY_CACHE.pop(cache_key, None)
    return paginate(logs, filters)
