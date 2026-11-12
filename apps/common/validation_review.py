"""Read-only administrator review of retail validation decisions.

Reuse the audit store and NULL worklist's automatic decisions. A corrected
record need not still satisfy the anomaly predicate to be visible here.
"""
from collections import defaultdict
from contextlib import ExitStack
from datetime import date, timedelta
import json

from apps.common.db import dx_connection
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.monitoring_cache import monitoring_cached_value
from apps.common.seda_retail import seda_retailer_key
from apps.dx.dx_layer1.column_statistics.dates import day_sql, date_column
from apps.dx.dx_layer4.corrections import detail as audit, services as saved

KINDS = {
    'null_check': ('NULL 검증', 2, 'null_validation'),
    'format_check': ('형식 검증', 2, 'format_validation'),
    'cross_field': ('크로스필드 검증', 3, 'cross_field'),
    'field_missing': ('필드누락 검증', 3, 'field_missing'),
}
STATUSES = {'corrected': '값 수정', 'normal': '수동확인', 'auto': '자동확인',
            'error': '오류 확인', 'reverted': '확인 취소'}
DETAIL_TOOLS = {'null_check', 'cross_field'}
SEARCH_FIELDS = {'all': ('record_id', 'item', 'created_id', 'old_value', 'new_value'),
                 'id': ('record_id',), 'item': ('item',), 'reviewer': ('created_id',),
                 'value': ('old_value', 'new_value')}


def table_key(value):
    return str(value or '').removeprefix('public.')


def account_key(value):
    return str(value or '').strip().casefold()


def _source_account_key(source, value):
    """Match SEDA source aliases using the collection's existing policy."""
    return seda_retailer_key(value) if source['country'] == 'SEDA' else account_key(value)


def _source_account_sql(source, column):
    if source['country'] == 'SEDA':
        return f"LOWER(REPLACE(BTRIM({column}), ' ', ''))"
    return f'LOWER(BTRIM({column}))'


def _identity(row):
    return table_key(row['table_name']), str(row['record_id']), row['column_name'], account_key(row['retailer'])


def _source(day, kind):
    # Format events are a separate store. Other kinds must not read/project
    # every format decision merely to discard them in the PostgreSQL filter.
    if kind == 'format_check':
        return saved._current_source(day)
    return f'({saved._CURRENT_CORRECTIONS_SQL}) c', [str(day)], {}


def _matches(row, table='', retailer=None, field=None, rule=None):
    return ((not table or table_key(row['table_name']) == table_key(table))
            and (retailer is None or account_key(row['retailer']) == account_key(retailer))
            and (field is None or (row['column_name'] == field and row.get('rule_id') == rule)))


def _load(cursor, day, kind, table='', retailer=None, field=None, rule=None):
    registry = audit._sources()
    if table and table_key(table) not in registry:
        raise ValueError('등록된 원본을 선택하세요.')
    source, params, projected = _source(day, kind)
    aliases = sorted({alias for key, config in registry.items()
                      if not table or key == table_key(table)
                      for alias in (key, config['table_name'], 'public.' + key if '.' not in key else key)})
    clauses = ['c.correction_type = %s', 'c.table_name = ANY(%s)']
    params = [*params, kind, aliases]
    if retailer is not None:
        # Ordinary retailer names are ASCII. Keep non-ASCII/whitespace variants
        # as candidates for Python's exact strip/casefold semantics below.
        clauses.append("(LOWER(BTRIM(COALESCE(c.retailer, ''))) = %s OR c.retailer ~ '[^ -~]')")
        params.append(account_key(retailer))
    if field is not None:
        clauses.append('c.column_name = %s')
        params.append(field)
        if kind != 'null_check':
            clauses.append('c.rule_id IS NOT DISTINCT FROM %s')
            params.append(rule)
    cursor.execute(f'''SELECT c.*, r.detail_name AS rule_name FROM {source}
                       LEFT JOIN monitoring_validation_rules r ON c.rule_id = r.id
                       WHERE {' AND '.join(clauses)}
                       ORDER BY c.created_at DESC NULLS LAST, c.id DESC''',
                   params)
    # NULL's manual-over-auto identity does not include rule_id. Preserve all
    # manual decisions for this cell until automatic entries are deduplicated.
    rows = [row for row in audit._dicts(cursor)
            if _matches(row, table, retailer, field,
                        row.get('rule_id') if kind == 'null_check' else rule)]
    for row in rows:
        if row['id'] in projected:
            row.update(projected[row['id']])
            # FormatReviewEvent stores the confirmed snapshot in new_value;
            # old_value=None means "no edit", not that the original was NULL.
            row['old_value'] = row['new_value']
        row['value_known'] = True
    if kind == 'null_check':
        from apps.dx.dx_layer2.null_validation.services import get_auto_applied_null_reviews
        from apps.dx.dx_layer2.null_validation.review_history import _sources as null_sources
        category = null_sources().get(table_key(table), {}).get('history_category') if table else None
        # This calls the same evidence matcher used by the worklist; never infer
        # a new automatic approval from an old correction or from today's value.
        automatic = get_auto_applied_null_reviews(cursor, day, category=category, strict=True,
                                                 review_only=True)
        seen = {_identity(row) for row in rows}
        for entry in automatic:
            if table_key(entry['table_name']) not in registry:
                continue
            if not _matches(entry, table, retailer, field, entry.get('rule_id')):
                continue
            if _identity(entry) in seen:
                continue
            seen.add(_identity(entry))
            rows.append({**entry, 'status': 'auto', 'correction_type': kind,
                         'rule_id': None, 'rule_name': '', 'value_known': False})
        # Typed immutable evidence retains SQL NULL vs empty/string NULL/zero.
        ids = [r['id'] for r in rows if isinstance(r['id'], int) and r['id'] > 0]
        evidence_ids = [r['evidence_id'] for r in rows if r.get('evidence_id')]
        cursor.execute('''SELECT id, correction_id, value_snapshot
                          FROM public.monitoring_null_review_evidence
                          WHERE correction_id = ANY(%s) OR id = ANY(%s)''', [ids, evidence_ids])
        by_id, by_correction = {}, {}
        for eid, cid, snapshot in cursor.fetchall():
            snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            by_id[eid] = by_correction[cid] = snapshot
        for row in rows:
            snapshot = by_id.get(row.get('evidence_id')) or by_correction.get(row['id'])
            if snapshot and row['status'] in ('normal', 'auto', 'error', 'reverted'):
                row.update(old_value=snapshot['value'], new_value=snapshot['value'], value_known=True)
    for row in rows:
        config = registry[table_key(row['table_name'])]
        row.update(table_name=config['table_name'], country=config['country'], product=config['product'])
        # A confirmation does not mutate the value; new_value is NULL in the
        # legacy log schema even when the confirmed old value was not NULL.
        if row['status'] != 'corrected':
            row['new_value'] = row.get('old_value')
    return [row for row in rows if _matches(row, table, retailer, field, rule)]


def _review_rows(day, kind, table='', retailer=None, field=None, rule=None, *, get_cursor=None):
    """Reuse the list snapshot for drill-down, search and paging for at most 60s."""
    if table and table_key(table) not in audit._sources():
        raise ValueError('등록된 원본을 선택하세요.')
    identity = [str(day), kind, table_key(table), account_key(retailer) if retailer is not None else None, field, rule]
    broad = [str(day), kind, '', None, None, None]
    candidates = [broad]
    if table:
        candidates.append([str(day), kind, table_key(table), None, None, None])
    if retailer is not None:
        candidates.append([str(day), kind, table_key(table), account_key(retailer), None, None])
    for candidate in candidates:
        if candidate == identity:
            continue
        rows = monitoring_cached_value('admin-review-v1', candidate)
        if rows is not None:
            # Do not cache a derived subset: it must expire with the source.
            return [row for row in rows if _matches(row, table, retailer, field, rule)]

    def read():
        if get_cursor is not None:
            return _load(get_cursor(), day, kind, table, retailer, field, rule)
        with dx_connection() as (_, cursor):
            return _load(cursor, day, kind, table, retailer, field, rule)
    rows = monitoring_cached_value('admin-review-v1', identity, read, cacheable=lambda _rows: True)
    return [row for row in rows if _matches(row, table, retailer, field, rule)]


def _counts(rows):
    result = dict.fromkeys(STATUSES, 0)
    for row in rows:
        result[row['status']] = result.get(row['status'], 0) + 1
    return result


def summary(day, kind, table='', retailer=None):
    rows = _review_rows(day, kind, table, retailer)
    groups = defaultdict(list)
    for row in rows:
        key = (row['column_name'], row.get('rule_id')) if table and retailer is not None else (
            row['table_name'], account_key(row['retailer']))
        groups[key].append(row)
    items = []
    for records in groups.values():
        row = records[0]
        items.append({key: row.get(key) for key in (
            'table_name', 'country', 'product', 'retailer', 'column_name', 'rule_id', 'rule_name')})
        items[-1].update(total=len(records), counts=_counts(records))
    return dict(success=True, items=items, total=len(rows), counts=_counts(rows))


def _display_query(cursor, source, columns, logs, days, tools, stamp_type, context_rows=()):
    """Compact, copyable SELECT for the visible source columns and page items."""
    stamp = date_column(source)
    shown = [c for c in dict.fromkeys((
        'id', stamp, 'item', 'retailer_sku_name', logs[0]['column_name'],
        *tools['selected_columns'], 'product_url',
    )) if c in columns]
    observed = [log.get('target') or {} for log in logs] + list(context_rows)
    truncated = len(context_rows) > 1500
    if source['country'] == 'SIEL':
        date_filter = f"{stamp} AT TIME ZONE 'Asia/Seoul'"
    elif not truncated and stamp_type in ('text', 'character varying', 'character', 'date', 'timestamp without time zone'):
        date_filter = stamp
        values = [row.get(stamp) for row in observed]
        if any(isinstance(value, str) and value != value.strip(' ') for value in values):
            date_filter = f'BTRIM({stamp})'
    else:
        # Unknown/native timezone types retain the registered date policy.
        date_filter = day_sql(source).replace('source.', '')

    groups = defaultdict(list)
    for log in logs:
        groups[(log['source_date'], _source_account_key(source, log['retailer']))].append(log)
    clauses, params = [], []
    for (end, retailer), entries in groups.items():
        end = date.fromisoformat(end)
        parts = [f'{date_filter} >= %s', f'{date_filter} < %s']
        params.extend([str(end - timedelta(days=days - 1)), str(end + timedelta(days=1))])
        names = list(dict.fromkeys(row['account_name'] for row in observed
                     if 'account_name' in row and _source_account_key(source, row['account_name']) == retailer))
        if not names:
            # No source row remains: use the saved retailer spelling.
            names = list(dict.fromkeys(entry['retailer'] for entry in entries))
        if truncated or source['country'] == 'SEDA':
            # Include historical aliases even if the current row is missing.
            parts.append(f"{_source_account_sql(source, 'account_name')} = %s")
            params.append(retailer)
        elif names == [None]:
            parts.append('account_name IS NULL')
        else:
            parts.append('account_name = %s' if len(names) == 1 else 'account_name IN %s')
            params.append(names[0] if len(names) == 1 else tuple(names))
        items = list(dict.fromkeys(entry['item'] for entry in entries
                     if entry.get('item') is not None and str(entry['item']).strip()))
        item_parts = []
        if items:
            item_parts.append('item IN %s')
            params.append(tuple(items))
        for entry in entries:
            item = entry.get('item')
            if item is not None and str(item).strip():
                continue
            item_parts.append('(item IS NULL AND id = %s)' if item is None else '(item = %s AND id = %s)')
            params.extend([entry['record_id']] if item is None else [item, entry['record_id']])
        parts.append(item_parts[0] if len(item_parts) == 1 else '(' + ' OR '.join(item_parts) + ')')
        clauses.append('\n  AND '.join(parts))
    where = clauses[0] if len(clauses) == 1 else '(' + ')\n   OR ('.join(clauses) + ')'
    table = source['table_name']
    table = table if '.' in table else 'public.' + table
    selection = ',\n       '.join(', '.join(shown[i:i+4]) for i in range(0, len(shown), 4))
    query = f'SELECT {selection}\nFROM {table}\nWHERE {where}\nORDER BY item, {stamp};'
    tools['query'] = cursor.mogrify(query, params).decode('utf-8')


def _context(cursor, logs, days, day, extra_columns=None, tools=None):
    """Batch-read source context; saved values only overwrite the audited field.

    Other fields are current reference values, not fabricated audit snapshots.
    All source dates use the registered source policy, including SIEL.
    """
    source = audit._sources()[table_key(logs[0]['table_name'])]
    table = source['table_name']
    schema, name = table.split('.') if '.' in table else ('public', table)
    if not all(audit.IDENTIFIER.fullmatch(p) for p in (schema, name)):
        raise ValueError('원본 설정이 올바르지 않습니다.')
    cursor.execute('''SELECT column_name, data_type FROM information_schema.columns
                      WHERE table_schema = %s AND table_name = %s''', [schema, name])
    types = {r[0]: r[1] if len(r) > 1 else None for r in cursor.fetchall() if audit.IDENTIFIER.fullmatch(r[0])}
    available = set(types)
    field, stamp = logs[0]['column_name'], date_column(source)
    columns = audit.context_columns(available, stamp, field)
    if tools is not None:
        fixed = {'id', 'item', 'retailer_sku_name', 'product_url', field}
        choices = sorted(available - fixed)
        defaults = [c for c in columns if c not in fixed | {stamp, 'batch_id'}]
        if field in (*audit.RATING_FIELDS, 'detailed_review_content', 'summarized_review_content'):
            defaults.extend(c for c in ('sku', *audit.RATING_FIELDS, 'detailed_review_content')
                            if c in choices and c not in defaults)
        selected = list(dict.fromkeys(defaults if extra_columns is None else extra_columns))
        if any(c not in choices for c in selected):
            raise ValueError('원본에 존재하는 추가 컬럼을 선택하세요.')
        columns = list(dict.fromkeys([c for c in columns if c in fixed | {stamp}] + selected))
        tools.update(available_columns=choices, selected_columns=selected, default_columns=defaults, query='')
    fallback = resolve_monitoring_date(day, source['country'], source['key'])['source_date']
    for log in logs:
        log.update(source_date=str(log.get('source_date') or fallback), target=None, comparisons=[], context_available=False)
    if not {'id', 'account_name', 'item', stamp}.issubset(available):
        return columns
    selection = ', '.join('source.' + c for c in dict.fromkeys([*columns, 'account_name']))
    date_expr = day_sql(source)
    ids = [r['record_id'] for r in logs if r.get('record_id') is not None]
    cursor.execute(f'''SELECT {selection}, {date_expr} AS _source_date
                       FROM {table} source WHERE source.id = ANY(%s)''', [ids])
    targets = {str(r['id']): r for r in audit._dicts(cursor)}
    pairs = set()
    for log in logs:
        target = targets.get(str(log['record_id']))
        if target and _source_account_key(source, target.get('account_name')) == _source_account_key(source, log['retailer']) and target.get('item') == log.get('item'):
            log.update(target=target, source_date=str(target['_source_date']), context_available=True)
        if log.get('item') is not None and str(log['item']).strip():
            pairs.add((_source_account_key(source, log['retailer']), log['item']))
    if days == 1 or not pairs:
        if tools is not None:
            _display_query(cursor, source, columns, logs, days, tools, types.get(stamp))
        return columns
    ends = [date.fromisoformat(r['source_date']) for r in logs]
    clauses, params = [], []
    for retailer, item in sorted(pairs, key=str):
        clauses.append(f"({_source_account_sql(source, 'source.account_name')} = %s AND source.item = %s)")
        params.extend([retailer, item])
    cursor.execute(f'''SELECT {selection}, {date_expr} AS _source_date FROM {table} source
                       WHERE ({' OR '.join(clauses)}) AND ({date_expr}) BETWEEN %s AND %s
                       ORDER BY ({date_expr}) DESC, source.id DESC LIMIT 1501''',
                   [*params, str(min(ends) - timedelta(days=days - 1)), str(max(ends))])
    comparisons = audit._dicts(cursor)
    for log in logs:
        start = str(date.fromisoformat(log['source_date']) - timedelta(days=days - 1))
        matches = [r for r in comparisons[:1500]
                   if _source_account_key(source, r.get('account_name')) == _source_account_key(source, log['retailer'])
                   and r.get('item') == log.get('item') and str(r['id']) != str(log['record_id'])
                   and start <= str(r['_source_date']) <= log['source_date']]
        log['comparisons'] = list(reversed(matches[:60]))
        log['truncated'] = len(comparisons) > 1500 or len(matches) > 60
    if tools is not None:
        _display_query(cursor, source, columns, logs, days, tools, types.get(stamp), comparisons)
    return columns


def paired_rows(log):
    """Keep both states adjacent on the same original source date and ID."""
    field = log['column_name']
    current = log.get('target') or {}
    base = {**current, 'id': log['record_id'], 'item': log.get('item'),
            'retailer_sku_name': current.get('retailer_sku_name') or log.get('retailer_sku_name', ''),
            'product_url': current.get('product_url') or log.get('product_url', ''),
            '_source_date': log['source_date'], '_known': log['value_known'],
            '_context_available': log['context_available']}
    modified = log['status'] == 'corrected'
    before = {**base, field: log.get('old_value'), '_phase': '수정 전' if modified else '확인 전',
              '_state': '', '_reason': '', '_reviewer': '', '_reviewed_at': ''}
    after = {**base, field: log.get('new_value'), '_phase': '수정 후' if modified else '확인 후',
             '_state': STATUSES.get(log['status'], log['status']), '_status': log['status'],
             '_reason': log.get('reason') or log.get('memo') or '',
             '_memo': log.get('memo') or '', '_reviewer': log.get('created_id') or '',
             '_reviewed_at': log.get('original_created_at') if log['status'] == 'auto' else log.get('created_at'),
             '_cancel_memo': log.get('cancel_memo') or ''}
    history = [{**r, '_phase': '비교 이력', '_known': True} for r in log.get('comparisons', [])]
    return [*history, before, after]


def records(day, kind, table, retailer, field, rule=None, page=1, days=3, q='', status='all', extra_columns=None,
            q_field='all', sort_by='', sort_order='asc'):
    if q_field not in SEARCH_FIELDS or sort_by not in ('', 'id', 'item') or sort_order not in ('asc', 'desc'):
        raise ValueError('검색 항목과 정렬 조건을 확인하세요.')
    tools = {} if kind in DETAIL_TOOLS else None
    with ExitStack() as stack:
        connection = []
        def get_cursor():
            if not connection:
                connection.append(stack.enter_context(dx_connection()))
            return connection[0][1]

        logs = _review_rows(day, kind, table, retailer, field, rule, get_cursor=get_cursor)
        counts = _counts(logs)
        if status != 'all':
            logs = [r for r in logs if r['status'] == status]
        if q:
            logs = [r for r in logs if q.casefold() in ' '.join(
                str(r[k]) if r.get(k) is not None else '' for k in SEARCH_FIELDS[q_field]).casefold()]
        if sort_by:
            # Sort whole review groups before pagination; before/after rows
            # and their comparison history must always travel together.
            key = 'record_id' if sort_by == 'id' else 'item'
            def sort_value(row):
                value = row.get(key)
                if value is None:
                    return 0 if sort_by == 'id' else ''
                return int(value) if sort_by == 'id' else str(value).casefold()
            logs = sorted(logs, key=sort_value, reverse=sort_order == 'desc')
            logs.sort(key=lambda row: row.get(key) is None)
        total = len(logs)
        page_size = 10
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        logs = logs[(page - 1) * page_size:page * page_size]
        options = dict(extra_columns=extra_columns, tools=tools) if tools is not None else {}
        columns = []
        if logs:
            columns = _context(get_cursor(), logs, days, day, **options)
    return dict(success=True, groups=[dict(id=r['id'], rows=paired_rows(r), truncated=r.get('truncated', False)) for r in logs],
                columns=columns, field=field, total=total, counts=counts, page=page, pages=pages,
                **(tools or {}))
