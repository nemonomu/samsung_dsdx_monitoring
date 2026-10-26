"""Read saved format decisions without re-running validation or reading source rows."""
from datetime import timezone as tz

from django.apps import apps
from django.conf import settings
from django.utils import timezone


def environment():
    return 'test' if settings.DEBUG else 'production'


def events():
    from apps.dx.dx_layer2.models import FormatReviewEvent
    return FormatReviewEvent.objects.filter(
        scope__context__environment=environment(),
    ).select_related('scope').defer('scope__policies')


def stamp(value):
    return timezone.localtime(value).strftime('%Y-%m-%d %H:%M:%S')


def family(context):
    from apps.dx.dx_layer2.format_validation.review_service import retailer_key
    return context['country'], retailer_key(context['retailer'])


def cancellation(event, target, candidates):
    for other in candidates:
        if other.pk <= event.pk or family(other.scope.context) != family(event.scope.context):
            continue
        for changed in other.targets:
            if (changed.get('field'), changed.get('value')) != (target.get('field'), target.get('value')):
                continue
            if other.action == 'undo':
                if event.is_del and other.scope_id == event.scope_id:
                    return other
            elif other.action == 'revoke' and not other.is_del:
                shared = changed.get('shared_normal', True)
                if event.action == 'normal' and shared:
                    return other
                if event.action == 'error' and not shared and other.scope_id == event.scope_id:
                    # Error decisions remain local to the originating source/records.
                    previous = other.previous.get(changed.get('key'), {}) or {}
                    if previous.get('event_id') == event.pk:
                        return other
    return None


def cancellations_for(selected):
    families = {family(event.scope.context) for event in selected}
    return [event for event in events().filter(
        pk__gt=min(event.pk for event in selected), action__in=('revoke', 'undo'),
        scope__context__country__in={country for country, _ in families},
    ).order_by('pk').iterator() if family(event.scope.context) in families]


def project(event, target_index, record_index, cancelled=None):
    context = event.scope.context
    target = event.targets[target_index]
    record = target['records'][record_index]
    status = 'normal' if event.action == 'normal' else 'error'
    if event.is_del or cancelled:
        status = 'reverted'
    return dict(
        layer=2, correction_type='format_check', table_name=context['source_table'],
        record_id=record['id'], column_name=target['field'], old_value=None,
        new_value=target['value'], crawl_date=str(event.inspection_date), status=status,
        memo='', created_id=event.actor, created_at=stamp(event.created_at), reason=event.reason,
        retailer=context.get('retailer_name', context['retailer']), item=record.get('item', ''),
        rule_id=None, rule_name='', updated_id=cancelled.actor if cancelled else '',
        updated_at=stamp(cancelled.created_at) if cancelled else '',
        cancel_memo=cancelled.reason if cancelled else '',
        country=context['country'], product=context['product'],
        category_label=context['country'] + ' ' + context['product'],
        retailer_sku_name=record.get('name', ''), product_url=record.get('url', ''),
        crawl_time=record.get('collected_at') or target.get('source_date', ''),
        source_date=target.get('source_date', ''), comparison_rows=[],
        review_source='format_review', review_event_id=event.pk,
        review_target=target_index, review_record=record_index,
        review_action=event.action, shared_normal=event.action == 'normal',
        origin_product=context['product'],
    )


def list_rows(day):
    # Keep legacy installations/tests usable when the format-review app is absent.
    if not apps.is_installed('apps.dx.dx_layer2'):
        return []
    selected = list(events().filter(inspection_date=day, action__in=('normal', 'error'))
                    .order_by('-created_at', '-pk'))
    if not selected:
        return []
    cancellations = cancellations_for(selected)
    rows = []
    for event in selected:
        for ti, target in enumerate(event.targets):
            cancelled = cancellation(event, target, cancellations)
            for ri, _ in enumerate(target.get('records', [])):
                row = project(event, ti, ri, cancelled)
                # Negative IDs are query-local union keys, never mutation IDs.
                row['id'] = -len(rows) - 1
                row['_sort_created_at'] = event.created_at.astimezone(tz.utc).replace(tzinfo=None).isoformat(sep=' ')
                rows.append(row)
    return rows


def record_history(correction):
    """Original human decisions for this source row; shared effects are not new reviews."""
    if not apps.is_installed('apps.dx.dx_layer2'):
        return []
    table = correction['table_name'].removeprefix('public.')
    aliases = [table, 'public.' + table] if '.' not in table else [table]
    from apps.dx.dx_layer2.format_validation.review_service import retailer_key
    selected = events().filter(scope__context__source_table__in=aliases,
                               scope__context__retailer=retailer_key(correction['retailer']),
                               action__in=('normal', 'error')).order_by('-created_at', '-pk')
    rows = []
    for event in selected.iterator():
        for ti, target in enumerate(event.targets):
            if target.get('field') != correction['column_name']:
                continue
            for ri, record in enumerate(target.get('records', [])):
                if str(record['id']) == str(correction['record_id']) and record.get('item', '') == (correction['item'] or ''):
                    rows.append(project(event, ti, ri))
                    if len(rows) == 100:
                        return rows
    return rows


def correction_history(review):
    """Read only saved correction logs, never the collected product table."""
    from apps.common.db import dx_connection
    table = review['table_name'].removeprefix('public.')
    aliases = [table, 'public.' + table] if '.' not in table else [table]
    with dx_connection() as (_, cursor):
        cursor.execute('''SELECT old_value, new_value, status, reason, memo,
                                 created_id, created_at, updated_id, updated_at, cancel_memo
                          FROM monitoring_corrections
                          WHERE table_name = ANY(%s) AND record_id = %s AND column_name = %s
                            AND correction_type = 'format_check'
                            AND LOWER(BTRIM(retailer)) = %s AND item IS NOT DISTINCT FROM %s
                          ORDER BY created_at DESC, id DESC LIMIT 100''',
                       [aliases, review['record_id'], review['column_name'],
                        review['retailer'].strip().lower(), review['item']])
        names = [column[0] for column in cursor.description]
        return [{key: value.isoformat() if hasattr(value, 'isoformat') else value
                 for key, value in zip(names, row)} for row in cursor.fetchall()]


def detail(event_id, target_index, record_index):
    event = events().filter(pk=event_id, action__in=('normal', 'error')).first()
    if event is None:
        raise LookupError('형식 확인 기록을 찾을 수 없습니다.')
    if not 0 <= target_index < len(event.targets):
        raise ValueError('확인 대상이 올바르지 않습니다.')
    target = event.targets[target_index]
    if not 0 <= record_index < len(target.get('records', [])):
        raise ValueError('확인 레코드가 올바르지 않습니다.')
    record = target['records'][record_index]
    context = event.scope.context
    from apps.dx.dx_layer2.format_validation.review_repository import evidence_detail
    related = []
    # Include shared normal history, but never another product's error confirmation.
    for other in events().filter(scope__context__country=context['country']).order_by('-pk').iterator():
        if family(other.scope.context) != family(context):
            continue
        matches = [t for t in other.targets if (t.get('field'), t.get('value')) ==
                   (target.get('field'), target.get('value'))]
        matches = [t for t in matches if
                   other.action == 'normal' or
                   (other.action in ('revoke', 'undo') and t.get('shared_normal', True)) or
                   (other.scope_id == event.scope_id and
                    (any(str(r['id']) == str(record['id']) for r in t.get('records', [])) or
                     str(record['id']) in {str(i) for i in t.get('record_ids', [])}))]
        if matches:
            related.append(other)
        if len(related) > 100:
            break
    cancelled = cancellation(event, target, cancellations_for([event]))
    saved = evidence_detail(event.scope.fingerprint, event.pk)
    saved.pop('targets', None)  # Return only the selected saved value group.
    saved.update(success=True, review_source='format_review',
                 correction=project(event, target_index, record_index, cancelled),
                 field=target['field'], value=target['value'], records=target.get('records', []),
                 source_date=target.get('source_date'), shared_normal=event.action == 'normal',
                 origin_product=context['product'], history_truncated=len(related) > 100,
                 history=[dict(id=e.pk, action=e.action, actor=e.actor, reason=e.reason,
                               created_at=stamp(e.created_at), product=e.scope.context['product'],
                               is_del=e.is_del) for e in related[:100]])
    return saved
