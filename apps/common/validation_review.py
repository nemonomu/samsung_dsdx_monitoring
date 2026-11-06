"""Read-only administrator review of retail validation decisions.

Reuse the audit store and NULL worklist's automatic decisions. A corrected
record need not still satisfy the anomaly predicate to be visible here.
"""
from collections import defaultdict
from datetime import date, timedelta
import json

from apps.common.db import dx_connection
from apps.common.inspection_dates import resolve_monitoring_date
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


def table_key(value):
    return str(value or '').removeprefix('public.')


def account_key(value):
    return str(value or '').strip().casefold()


def _identity(row):
    return table_key(row['table_name']), str(row['record_id']), row['column_name'], account_key(row['retailer'])


def _load(cursor, day, kind, table=''):
    registry = audit._sources()
    if table and table_key(table) not in registry:
        raise ValueError('등록된 원본을 선택하세요.')
    source, params, projected = saved._current_source(day)
    aliases = sorted({alias for key, config in registry.items()
                      if not table or key == table_key(table)
                      for alias in (key, config['table_name'], 'public.' + key if '.' not in key else key)})
    cursor.execute(f'''SELECT c.*, r.detail_name AS rule_name FROM {source}
                       LEFT JOIN monitoring_validation_rules r ON c.rule_id = r.id
                       WHERE c.correction_type = %s AND c.table_name = ANY(%s)
                       ORDER BY c.created_at DESC NULLS LAST, c.id DESC''',
                   [*params, kind, aliases])
    rows = audit._dicts(cursor)
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
        automatic = get_auto_applied_null_reviews(cursor, day, category=category)
        seen = {_identity(row) for row in rows}
        for entry in automatic:
            if table_key(entry['table_name']) not in registry:
                continue
            if table and table_key(entry['table_name']) != table_key(table):
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
    return rows


def _counts(rows):
    result = dict.fromkeys(STATUSES, 0)
    for row in rows:
        result[row['status']] = result.get(row['status'], 0) + 1
    return result


def summary(day, kind, table='', retailer=None):
    with dx_connection() as (_, cursor):
        rows = _load(cursor, day, kind, table)
    if retailer is not None:
        rows = [r for r in rows if account_key(r['retailer']) == account_key(retailer)]
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


def _context(cursor, logs, days, day):
    """Batch-read source context; saved values only overwrite the audited field.

    Other fields are current reference values, not fabricated audit snapshots.
    All source dates use the registered source policy, including SIEL.
    """
    source = audit._sources()[table_key(logs[0]['table_name'])]
    table = source['table_name']
    schema, name = table.split('.') if '.' in table else ('public', table)
    if not all(audit.IDENTIFIER.fullmatch(p) for p in (schema, name)):
        raise ValueError('원본 설정이 올바르지 않습니다.')
    cursor.execute('''SELECT column_name FROM information_schema.columns
                      WHERE table_schema = %s AND table_name = %s''', [schema, name])
    available = {r[0] for r in cursor.fetchall() if audit.IDENTIFIER.fullmatch(r[0])}
    field, stamp = logs[0]['column_name'], date_column(source)
    columns = audit.context_columns(available, stamp, field)
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
        if target and account_key(target.get('account_name')) == account_key(log['retailer']) and target.get('item') == log.get('item'):
            log.update(target=target, source_date=str(target['_source_date']), context_available=True)
        if log.get('item') is not None and str(log['item']).strip():
            pairs.add((account_key(log['retailer']), log['item']))
    if days == 1 or not pairs:
        return columns
    ends = [date.fromisoformat(r['source_date']) for r in logs]
    clauses, params = [], []
    for retailer, item in sorted(pairs, key=str):
        clauses.append('(LOWER(BTRIM(source.account_name)) = %s AND source.item = %s)')
        params.extend([retailer, item])
    cursor.execute(f'''SELECT {selection}, {date_expr} AS _source_date FROM {table} source
                       WHERE ({' OR '.join(clauses)}) AND ({date_expr}) BETWEEN %s AND %s
                       ORDER BY ({date_expr}) DESC, source.id DESC LIMIT 1501''',
                   [*params, str(min(ends) - timedelta(days=days - 1)), str(max(ends))])
    comparisons = audit._dicts(cursor)
    for log in logs:
        start = str(date.fromisoformat(log['source_date']) - timedelta(days=days - 1))
        matches = [r for r in comparisons[:1500]
                   if account_key(r.get('account_name')) == account_key(log['retailer'])
                   and r.get('item') == log.get('item') and str(r['id']) != str(log['record_id'])
                   and start <= str(r['_source_date']) <= log['source_date']]
        log['comparisons'] = list(reversed(matches[:60]))
        log['truncated'] = len(comparisons) > 1500 or len(matches) > 60
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


def records(day, kind, table, retailer, field, rule=None, page=1, days=3, q='', status='all'):
    with dx_connection() as (_, cursor):
        logs = [r for r in _load(cursor, day, kind, table)
                if account_key(r['retailer']) == account_key(retailer)
                and r['column_name'] == field and r.get('rule_id') == rule]
        counts = _counts(logs)
        if status != 'all':
            logs = [r for r in logs if r['status'] == status]
        if q:
            logs = [r for r in logs if q.casefold() in ' '.join(str(r[k]) if r.get(k) is not None else '' for k in (
                'record_id', 'item', 'created_id', 'old_value', 'new_value')).casefold()]
        total = len(logs)
        page_size = 10
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        logs = logs[(page - 1) * page_size:page * page_size]
        columns = _context(cursor, logs, days, day) if logs else []
    return dict(success=True, groups=[dict(id=r['id'], rows=paired_rows(r), truncated=r.get('truncated', False)) for r in logs],
                columns=columns, field=field, total=total, counts=counts, page=page, pages=pages)
