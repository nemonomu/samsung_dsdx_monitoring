"""Shared, persistent acknowledgements, separate from source values and audits."""
from django.apps import apps
from django.conf import settings
from django.utils import timezone

from . import validation_review as review


def _model():
    return apps.get_model('dx_layer2', 'AdminValidationReviewCheck')


def _scope(day, kind):
    return dict(environment='test' if settings.DEBUG else 'production',
                inspection_date=day, kind=kind)


def _value(row):
    return dict(checked=row.checked, actor=row.actor,
                updated_at=timezone.localtime(row.updated_at).isoformat())


def attach(items, day, kind):
    if not items:
        return
    saved = {(r.table_name, r.retailer): _value(r)
             for r in _model().objects.filter(**_scope(day, kind))}
    for item in items:
        item['check'] = saved.get((review.table_key(item['table_name']),
                                  review.account_key(item['retailer'])), {'checked': False})


def _identity(kind, table, retailer):
    if kind not in review.KINDS or not isinstance(table, str) or not isinstance(retailer, str):
        raise ValueError('검수 범위를 확인하세요.')
    table, retailer = review.table_key(table), review.account_key(retailer)
    if len(table) > 200 or len(retailer) > 200 or table not in review.audit._sources():
        raise ValueError('등록된 검수 대상을 선택하세요.')
    return table, retailer


def get_checked(day, kind, table, retailer):
    table, retailer = _identity(kind, table, retailer)
    row = _model().objects.filter(**_scope(day, kind), table_name=table, retailer=retailer).first()
    return _value(row) if row else {'checked': False}


def set_checked(day, kind, table, retailer, checked, actor):
    table, retailer = _identity(kind, table, retailer)
    if type(checked) is not bool:
        raise ValueError('체크 여부를 확인하세요.')
    row, _ = _model().objects.update_or_create(
        **_scope(day, kind), table_name=table, retailer=retailer,
        defaults=dict(checked=checked, actor=actor, updated_at=timezone.now()),
    )
    return _value(row)
