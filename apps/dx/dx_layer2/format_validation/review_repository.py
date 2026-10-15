from django.apps import apps
from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone


class ReviewConflict(ValueError):
    pass


def ready(evidence=False):
    if not apps.ready or not apps.is_installed('apps.dx.dx_layer2'):
        return False
    from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewCapture
    tables = connection.introspection.table_names()
    required = (FormatReviewScope, FormatReviewCapture) if evidence else (FormatReviewScope,)
    return all(model._meta.db_table in tables for model in required)


def scopes():
    if not ready():
        return {}
    from apps.dx.dx_layer2.models import FormatReviewScope
    return {row.fingerprint: row for row in FormatReviewScope.objects.all()}


def history(scope, limit=100):
    if not scope or not ready(evidence=True):
        return []
    return [{
        'id': row.pk, 'action': row.action, 'actor': row.actor,
        'reason': row.reason, 'inspection_date': str(row.inspection_date),
        'created_at': timezone.localtime(row.created_at).strftime('%Y-%m-%d %H:%M:%S'),
        'is_del': row.is_del, 'count': sum(t['count'] for t in row.targets),
        'groups': len(row.targets),
        'capture_count': row.capture_count,
        'shared_normal': row.action == 'normal' or (row.action in ('revoke', 'undo')
                         and any(t.get('shared_normal', True) for t in row.targets)),
    } for row in scope.formatreviewevent_set.annotate(capture_count=Count('captures')).order_by('-id')[:limit]]


@transaction.atomic
def save(context, fingerprint, revision, action, targets, reason, actor, day, evidence=None,
         expected_shared_revision=None):
    from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewEvent, FormatReviewCapture
    evidence = evidence or {'checked_urls': [], 'captures': []}
    if expected_shared_revision is not None:
        from .review_service import shared_revision
        current = {row.fingerprint: row for row in FormatReviewScope.objects.select_for_update()}
        if shared_revision(context, current) != expected_shared_revision:
            raise ReviewConflict('다른 상품군의 정상 기준이 변경됐습니다. 다시 확인하세요.')
    scope, _ = FormatReviewScope.objects.get_or_create(
        fingerprint=fingerprint, defaults={'context': context},
    )
    if scope.revision != revision:
        raise ReviewConflict('다른 사용자의 처리가 반영됐습니다. 새로 조회한 뒤 다시 확인하세요.')
    policies = dict(scope.policies)
    targets = [{**t, 'shared_normal': action == 'normal' or
                (action == 'revoke' and t.get('shared_normal', True))} for t in targets]
    previous = {target['key']: policies.get(target['key']) for target in targets}
    event = FormatReviewEvent.objects.create(
        scope=scope, inspection_date=day, action=action, actor=actor,
        reason=reason, targets=targets, previous=previous, created_at=timezone.now(),
        checked_urls=evidence['checked_urls'],
    )
    FormatReviewCapture.objects.bulk_create([
        FormatReviewCapture(event=event, name=c['name'], content_type=c['content_type'], content=c['content'])
        for c in evidence['captures']
    ])
    for target in targets:
        key = target['key']
        policies[key] = {
            'key': key, 'field': target['field'], 'value': target['value'],
            'action': action, 'event_id': event.pk, 'actor': actor, 'reason': reason,
            'date': str(day), 'source_date': target['source_date'],
            'record_ids': [r['id'] for r in target['records']],
            'created_at': timezone.localtime(event.created_at).strftime('%Y-%m-%d %H:%M:%S'),
            'is_del': action == 'revoke',
            'shared_normal': action == 'normal' or (action == 'revoke' and target.get('shared_normal', True)),
        }
    updated = FormatReviewScope.objects.filter(pk=scope.pk, revision=revision).update(
        policies=policies, revision=revision + 1,
    )
    if updated != 1:
        raise ReviewConflict('동시 처리로 기준이 변경됐습니다. 다시 조회하세요.')
    return event.pk


def evidence_detail(fingerprint, event_id):
    from apps.dx.dx_layer2.models import FormatReviewEvent
    event = FormatReviewEvent.objects.filter(scope__fingerprint=fingerprint, pk=event_id).first()
    if not event:
        raise ValueError('이 범위의 처리 이력을 찾을 수 없습니다.')
    return {
        'id': event.pk, 'action': event.action, 'actor': event.actor, 'reason': event.reason,
        'created_at': timezone.localtime(event.created_at).strftime('%Y-%m-%d %H:%M:%S'),
        'inspection_date': str(event.inspection_date), 'is_del': event.is_del,
        'context': event.scope.context, 'targets': event.targets, 'checked_urls': event.checked_urls,
        'captures': [{'id': c.pk, 'name': c.name, 'url': f'/dx/layer2/api/format-review/capture/{c.pk}/'}
                     for c in event.captures.defer('content').all()],
    }


def capture(capture_id, environment):
    from apps.dx.dx_layer2.models import FormatReviewCapture
    return FormatReviewCapture.objects.filter(
        pk=capture_id, event__scope__context__environment=environment,
    ).only('content', 'content_type').first()


@transaction.atomic
def undo(fingerprint, revision, event_id, actor, reason, expected_shared_revision=None):
    from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewEvent
    current_scopes = {row.fingerprint: row for row in FormatReviewScope.objects.select_for_update()}
    scope = current_scopes[fingerprint]
    if expected_shared_revision is not None:
        from .review_service import shared_revision
        if shared_revision(scope.context, current_scopes) != expected_shared_revision:
            raise ReviewConflict('다른 상품군의 정상 기준이 변경됐습니다. 다시 확인하세요.')
    if scope.revision != revision:
        raise ReviewConflict('기준이 변경됐습니다. 새로 조회하세요.')
    event = scope.formatreviewevent_set.filter(pk=event_id, is_del=False).first()
    if not event or event.action == 'undo':
        raise ReviewConflict('취소할 처리를 찾을 수 없습니다.')
    from .review_service import effective_policies
    current = effective_policies(scope.context, current_scopes)
    if any(current.get(t['key'], {}).get('event_id', 0) > event.pk for t in event.targets):
        raise ReviewConflict('다른 상품군에서 이후 변경한 기준이 있습니다. 해당 기준을 개별 취소하세요.')
    policies = dict(scope.policies)
    if any(policies.get(t['key'], {}).get('event_id') != event.pk for t in event.targets):
        raise ReviewConflict('이후 변경된 기준이 있습니다. 해당 기준을 개별 취소하세요.')
    for key, previous in event.previous.items():
        if previous is None:
            policies.pop(key, None)
        else:
            policies[key] = previous
    if FormatReviewScope.objects.filter(pk=scope.pk, revision=revision).update(
        policies=policies, revision=revision + 1,
    ) != 1:
        raise ReviewConflict('동시 처리로 기준이 변경됐습니다. 다시 조회하세요.')
    event.is_del = True
    event.save(update_fields=['is_del'])
    FormatReviewEvent.objects.create(
        scope=scope, inspection_date=event.inspection_date, action='undo', actor=actor,
        reason=reason, targets=event.targets, created_at=timezone.now(),
    )
