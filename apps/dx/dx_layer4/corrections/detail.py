"""Read-only audit context and administrator SELECT text for a saved correction."""
import re
from datetime import date, timedelta

from apps.common.db import dx_connection
from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_layer1.column_statistics.dates import day_sql, date_column


IDENTIFIER = re.compile(r'^[a-z_][a-z_0-9]*$')
DISPLAY_FIELDS = ('id', 'batch_id', 'account_name', 'item', 'retailer_sku_name',
                  'sku', 'final_sku_price', 'original_sku_price', 'savings',
                  'star_rating', 'count_of_reviews', 'count_of_star_ratings', 'product_url')
LIMIT = 300


def _sources():
    from apps.dx.dx_layer1.column_statistics.services import _sources as registered
    return {s['table_name'].removeprefix('public.'): s for s in registered()}


def _dicts(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _text(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value


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
    columns = list(dict.fromkeys(['id', stamp, *DISPLAY_FIELDS,
                                 *([field] if field in available else [])]))
    columns = [c for c in columns if c in available]
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
    def serialize(row):
        return {key: _text(value) for key, value in row.items()}
    return dict(success=True, correction=serialize(correction), country=context['source']['country'],
                product=context['source']['product'], source_date=context['end'],
                start_date=context['start'], days=days, field=context['field'],
                target=serialize(target) if target else None, field_available=context['field'] in context['columns'],
                columns=context['columns'], rows=[serialize(r) for r in rows],
                events=[serialize(e) for e in events], truncated=truncated,
                notice='원본의 현재 저장값입니다. 비교 행은 과거 시점의 변경 전 스냅샷을 보장하지 않습니다.')


def queries(correction_id, days=3):
    """Generate SELECT text only; HTTP administrator authorization is checked first."""
    with dx_connection() as (_, cursor):
        context = _context(cursor, correction_id, days)
        return dict(success=True, correction_id=correction_id,
                    source_date=context['end'], start_date=context['start'],
                    record_sql=cursor.mogrify(context['target_sql'], context['target_params']).decode('utf-8') + ';',
                    history_sql=cursor.mogrify(context['history_sql'], context['history_params']).decode('utf-8') + ';')
