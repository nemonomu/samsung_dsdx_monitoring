from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone


class ReviewConflict(ValueError):
    pass


def ready():
    if not apps.ready or not apps.is_installed('apps.dx.dx_layer2'):
        return False
    from apps.dx.dx_layer2.models import FormatReviewScope
    return FormatReviewScope._meta.db_table in connection.introspection.table_names()


def scopes():
    if not ready():
        return {}
    from apps.dx.dx_layer2.models import FormatReviewScope
    return {row.fingerprint: row for row in FormatReviewScope.objects.all()}


def history(scope, limit=100):
    if not scope:
        return []
    return [{
        'id': row.pk, 'action': row.action, 'actor': row.actor,
        'reason': row.reason, 'inspection_date': str(row.inspection_date),
        'created_at': timezone.localtime(row.created_at).strftime('%Y-%m-%d %H:%M:%S'),
        'is_del': row.is_del, 'count': sum(t['count'] for t in row.targets),
        'groups': len(row.targets),
    } for row in scope.formatreviewevent_set.order_by('-id')[:limit]]


@transaction.atomic
def save(context, fingerprint, revision, action, targets, reason, actor, day):
    from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewEvent
    scope, _ = FormatReviewScope.objects.get_or_create(
        fingerprint=fingerprint, defaults={'context': context},
    )
    if scope.revision != revision:
        raise ReviewConflict('다른 사용자의 처리가 반영됐습니다. 새로 조회한 뒤 다시 확인하세요.')
    policies = dict(scope.policies)
    previous = {target['key']: policies.get(target['key']) for target in targets}
    event = FormatReviewEvent.objects.create(
        scope=scope, inspection_date=day, action=action, actor=actor,
        reason=reason, targets=targets, previous=previous, created_at=timezone.now(),
    )
    for target in targets:
        key = target['key']
        policies[key] = {
            'key': key, 'field': target['field'], 'value': target['value'],
            'action': action, 'event_id': event.pk, 'actor': actor, 'reason': reason,
            'date': str(day), 'source_date': target['source_date'],
            'record_ids': [r['id'] for r in target['records']],
            'created_at': timezone.localtime(event.created_at).strftime('%Y-%m-%d %H:%M:%S'),
            'is_del': action == 'revoke',
        }
    updated = FormatReviewScope.objects.filter(pk=scope.pk, revision=revision).update(
        policies=policies, revision=revision + 1,
    )
    if updated != 1:
        raise ReviewConflict('동시 처리로 기준이 변경됐습니다. 다시 조회하세요.')
    return event.pk


@transaction.atomic
def undo(fingerprint, revision, event_id, actor, reason):
    from apps.dx.dx_layer2.models import FormatReviewScope, FormatReviewEvent
    scope = FormatReviewScope.objects.get(fingerprint=fingerprint)
    if scope.revision != revision:
        raise ReviewConflict('기준이 변경됐습니다. 새로 조회하세요.')
    event = scope.formatreviewevent_set.filter(pk=event_id, is_del=False).first()
    if not event or event.action == 'undo':
        raise ReviewConflict('취소할 처리를 찾을 수 없습니다.')
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
