"""Read-only audit context and administrator SELECT text for a saved correction."""
import re
from datetime import date, timedelta

from apps.common.db import dx_connection
from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_layer1.column_statistics.dates import day_sql, date_column


IDENTIFIER = re.compile(r'^[a-z_][a-z_0-9]*$')
PRICE_FIELDS = ('final_sku_price', 'original_sku_price', 'savings')
RATING_FIELDS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
LIMIT = 300


def context_columns(available, stamp, field):
    related = PRICE_FIELDS if field in PRICE_FIELDS else RATING_FIELDS if field in RATING_FIELDS else ()
    wanted = ('id', stamp, 'batch_id', 'item', 'retailer_sku_name', field, *related, 'product_url')
    return [column for column in dict.fromkeys(wanted) if column in available]


def _sources():
    from apps.dx.dx_layer1.column_statistics.services import _sources as registered
    return {s['table_name'].removeprefix('public.'): s for s in registered()}


def _dicts(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _text(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


def enrich_list(cursor, items, days=1):
    """Batch-load visible retail identity and links; return non-retail legacy rows."""
    registry = _sources()
    groups, legacy = {}, []
    for item in items:
        source = registry.get(str(item.get('table_name', '')).removeprefix('public.'))
        if not source:
            legacy.append(item)
            continue
        item.update(country=source['country'], product=source['product'],
                    category_label=source['country'] + ' ' + source['product'],
                    product_url='', retailer_sku_name='', crawl_time='', source_available=False)
        groups.setdefault(source['table_name'], (source, []))[1].append(item)
    for table, (source, logs) in groups.items():
        schema, name = table.split('.') if '.' in table else ('public', table)
        if not all(IDENTIFIER.fullmatch(part) for part in (schema, name)):
            continue
        cursor.execute('''SELECT column_name FROM information_schema.columns
                          WHERE table_schema = %s AND table_name = %s''', (schema, name))
        available = {row[0] for row in cursor.fetchall()}
        stamp = date_column(source)
        columns = [c for c in ('id', 'account_name', 'item', stamp, 'product_url', 'retailer_sku_name') if c in available]
        if not {'id', 'account_name', 'item'}.issubset(columns):
            continue
        ids = sorted({int(log['record_id']) for log in logs if log.get('record_id')})
        if not ids:
            continue
        # Identifiers come from the registry, with fixed column names only.
        cursor.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE id = ANY(%s)", (ids,))
        rows = {row['id']: row for row in _dicts(cursor)}
        for log in logs:
            row = rows.get(log['record_id'])
            if not row:
                continue
            account = lambda value: str(value).strip().casefold() if value is not None else None
            if account(row.get('account_name')) != account(log.get('retailer')) or row.get('item') != log.get('item'):
                continue
            log.update(product_url=row.get('product_url') or '', retailer_sku_name=row.get('retailer_sku_name') or '',
                       crawl_time=_text(row.get(stamp)) or '', source_available=True)
        if days <= 1 or stamp not in available:
            continue
        day = day_sql(source)
        # Anchor each audited row to its own original date, including the explicit SIEL exception.
        cursor.execute(f"SELECT id, {day} AS source_date FROM {table} source WHERE id = ANY(%s)", (ids,))
        dates = {row[0]: str(row[1]) for row in cursor.fetchall() if row[1]}
        ranges, pairs = {}, set()
        for log in logs:
            end = dates.get(log['record_id']) if log['source_available'] else None
            if not end:
                end = resolve_monitoring_date(log['crawl_date'], source['country'], source['key'])['source_date']
            try:
                end = date.fromisoformat(end)
            except ValueError:
                log['history_notice'] = '원본 수집일을 해석할 수 없어 비교 이력을 생략했습니다.'
                continue
            ranges[log['id']] = (end - timedelta(days=days - 1), end)
            if log.get('item') is not None and str(log['item']).strip():
                pairs.add((str(log.get('retailer') or '').strip().lower(), log['item']))
        if not pairs or not ranges:
            continue
        comparison_columns = list(dict.fromkeys([*columns, *[l['column_name'] for l in logs if l['column_name'] in available]]))
        selection = ', '.join('source.' + col for col in comparison_columns)
        clauses, params = [], []
        for account, item in sorted(pairs):
            clauses.append('(LOWER(BTRIM(source.account_name)) = %s AND source.item = %s)')
            params.extend([account, item])
        start, end = min(r[0] for r in ranges.values()), max(r[1] for r in ranges.values())
        cursor.execute(f'''SELECT {selection}, {day} AS source_date FROM {table} source
                           WHERE ({' OR '.join(clauses)}) AND ({day}) BETWEEN %s AND %s
                           ORDER BY ({day}) DESC, source.id DESC LIMIT 1501''', [*params, str(start), str(end)])
        comparisons = _dicts(cursor)
        for log in logs:
            if log['id'] not in ranges:
                continue
            start, end = ranges[log['id']]
            account = str(log.get('retailer') or '').strip().casefold()
            candidates = [row for row in comparisons[:1500]
                          if str(row.get('account_name') or '').strip().casefold() == account
                          and row.get('item') == log.get('item') and row['id'] != log['record_id']
                          and str(start) <= str(row['source_date']) <= str(end)]
            # Keep a bounded number of rows per correction; disclose every truncation.
            log['history_truncated'] = len(comparisons) > 1500 or len(candidates) > 60
            log['comparison_rows'] = [dict(id=row['id'], source_date=str(row['source_date']),
                                           crawl_time=_text(row.get(stamp)), value=_text(row.get(log['column_name'])),
                                           field_available=log['column_name'] in comparison_columns,
                                           batch_id=row.get('batch_id'), product_url=row.get('product_url') or '')
                                      for row in reversed(candidates[:60])]
    return legacy


def _context(cursor, correction_id, days):
    cursor.execute('''SELECT id, table_name, record_id, retailer, item, column_name,
                            crawl_date, old_value, new_value, status, reason, memo,
                            created_id, created_at, updated_id, updated_at, cancel_memo
                     FROM monitoring_corrections WHERE id = %s AND status IS NOT NULL''',
                   (correction_id,))
    records = _dicts(cursor)
    if not records:
        raise LookupError('검수기록을 찾을 수 없습니다.')
    correction = records[0]
    source = _sources().get(str(correction['table_name']).removeprefix('public.'))
    if source is None:
        raise ValueError('이 원본은 상세 수집 이력 조회를 지원하지 않습니다.')
    table = source['table_name']
    schema, name = table.split('.') if '.' in table else ('public', table)
    if not all(IDENTIFIER.fullmatch(part) for part in (schema, name)):
        raise ValueError('원본 테이블 설정이 올바르지 않습니다.')
    cursor.execute('''SELECT column_name FROM information_schema.columns
                      WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position''',
                   (schema, name))
    available = {row[0] for row in cursor.fetchall() if IDENTIFIER.fullmatch(row[0])}
    field, stamp = correction['column_name'], date_column(source)
    if not {'id', 'account_name', 'item', stamp}.issubset(available):
        raise ValueError('원본 조회에 필요한 컬럼이 없습니다.')
    # The saved field is data, never an identifier until verified against the schema.
    columns = context_columns(available, stamp, field)
    selection = ', '.join('source.' + c for c in columns)
    day = day_sql(source)
    identity = 'LOWER(BTRIM(source.account_name)) IS NOT DISTINCT FROM %s AND source.item IS NOT DISTINCT FROM %s'
    account = str(correction['retailer']).strip().lower() if correction['retailer'] is not None else None
    params = [account, correction['item']]
    target_sql = f'SELECT {selection}, {day} AS _source_date FROM {table} source WHERE source.id = %s AND {identity}'
    target_params = [correction['record_id'], *params]
    cursor.execute(target_sql, target_params)
    targets = _dicts(cursor)
    mapping = resolve_monitoring_date(correction['crawl_date'], source['country'], source['key'])
    end = date.fromisoformat(str(targets[0]['_source_date'] if targets else mapping['source_date']))
    start = end - timedelta(days=days - 1)
    # Compare the logged product across batches; never substitute a later batch for the audited row.
    if correction['item'] is None or str(correction['item']).strip() == '':
        history_sql, history_params = target_sql + ' ORDER BY source.id', target_params
    else:
        history_sql = (f'SELECT {selection}, {day} AS _source_date FROM {table} source '
                       f'WHERE {identity} AND ({day}) BETWEEN %s AND %s '
                       f'ORDER BY ({day}) DESC, source.id DESC LIMIT {LIMIT + 1}')
        history_params = [*params, str(start), str(end)]
    return dict(correction=correction, source=source, columns=columns, field=field,
                target=targets[0] if targets else None, start=str(start), end=str(end),
                target_sql=target_sql, target_params=target_params,
                history_sql=history_sql, history_params=history_params)


def detail(correction_id, days=3):
    with dx_connection() as (_, cursor):
        context = _context(cursor, correction_id, days)
        cursor.execute(context['history_sql'], context['history_params'])
        rows = _dicts(cursor)
        truncated = len(rows) > LIMIT
        rows = rows[:LIMIT]
        target = context['target']
        if target and not any(r['id'] == target['id'] for r in rows):
            rows.append(target)
        correction = context['correction']
        # Audit history remains available even if the original row has been removed.
        cursor.execute('''SELECT id, column_name, old_value, new_value, status, reason, memo,
                                 created_id, created_at, updated_id, updated_at, cancel_memo
                          FROM monitoring_corrections
                          WHERE table_name = %s AND record_id = %s AND column_name = %s
                            AND retailer IS NOT DISTINCT FROM %s AND item IS NOT DISTINCT FROM %s
                          ORDER BY created_at DESC, id DESC LIMIT 100''',
                       (correction['table_name'], correction['record_id'], context['field'],
                        correction['retailer'], correction['item']))
        events = _dicts(cursor)
    review_events = []
    if correction.get('column_name'):
        from .format_reviews import record_history
        review_events = record_history(correction)
    def serialize(row):
        return {key: _text(value) for key, value in row.items()}
    return dict(success=True, correction=serialize(correction), country=context['source']['country'],
                product=context['source']['product'], source_date=context['end'],
                start_date=context['start'], days=days, field=context['field'],
                target=serialize(target) if target else None, field_available=context['field'] in context['columns'],
                columns=context['columns'], rows=[serialize(r) for r in rows],
                events=[serialize(e) for e in events], truncated=truncated,
                review_events=review_events,
                notice='원본의 현재 저장값입니다. 비교 행은 과거 시점의 변경 전 스냅샷을 보장하지 않습니다.')


def queries(correction_id, days=3):
    """Generate SELECT text only; HTTP administrator authorization is checked first."""
    with dx_connection() as (_, cursor):
        context = _context(cursor, correction_id, days)
        sql = context['history_sql'].replace(', ' + day_sql(context['source']) + ' AS _source_date', '', 1)
        sql = (sql.replace('SELECT ', 'SELECT\n    ', 1).replace(', source.', ',\n    source.')
               .replace(' FROM ', '\nFROM ', 1).replace(' WHERE ', '\nWHERE ', 1)
               .replace(' ORDER BY ', '\nORDER BY ', 1).replace(' LIMIT ', '\nLIMIT ', 1))
        return dict(success=True, correction_id=correction_id,
                    source_date=context['end'], start_date=context['start'],
                    sql=cursor.mogrify(sql, context['history_params']).decode('utf-8') + ';')
