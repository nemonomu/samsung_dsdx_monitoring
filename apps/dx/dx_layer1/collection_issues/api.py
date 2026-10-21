import json
from datetime import date

from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.dx.dx_layer1.models import CollectionIssue as Issue, CollectionIssueScan as Scan
from apps.dx.dx_layer1.column_statistics.services import catalog, daily_counts
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, KST
from .queries import sql_queries, raw_counts
from .services import START_DATE, environment, serialize, event, reconcile_day
from .errors import storage_error


def reply(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def authenticated(request):
    return getattr(request, 'user', None) and request.user.is_authenticated


@login_required
@require_GET
def page(request):
    from apps.dx.dx_layer1.common.context import build_context
    return render(request, 'dx_layer1_past_review.html', build_context('past_review', request))


@require_GET
def listing(request):
    if not authenticated(request):
        return reply({'error': '로그인이 필요합니다.'}, 401)
    try:
        filters = {k:request.GET[k] for k in ('country', 'product', 'retailer') if request.GET.get(k)}
        jobs = [dict(country=s['country'], product=s['product'], retailer=r)
                for s in catalog() for r in s['retailers']
                if all(dict(country=s['country'], product=s['product'], retailer=r)[k] == v for k,v in filters.items())]
        if not jobs:
            raise ValueError()
        status = request.GET.get('status', 'open')
        if status not in ('open', 'resolved', 'excepted', 'all'):
            raise ValueError()
        records = Issue.objects.filter(environment=environment(), source_date__gte=START_DATE, **filters)
        if status != 'all':
            records = records.filter(status=status)
        rows = list(records.order_by('source_date', 'country', 'retailer', 'product', 'column'))
        # Whole-collection incidents are one row, not one copy per affected field.
        whole = {(r.country,r.product,r.retailer,r.source_date) for r in rows if not r.column and r.status=='open'}
        rows = [r for r in rows if not r.column or (r.country,r.product,r.retailer,r.source_date) not in whole]
        scans = list(Scan.objects.filter(environment=environment(), **filters).values(
            'country', 'product', 'retailer', 'coverage_start', 'start_basis',
            'scanned_through', 'last_checked_at', 'error'))
        return reply({'start_date': str(START_DATE), 'issues': [serialize(r) for r in rows],
                      'scans': scans, 'target_count': len(jobs)})
    except (ValueError, TypeError):
        return reply({'error': '조회 조건을 확인해주세요.'}, 400)
    except Exception as exc:
        return reply(storage_error(exc, 'listing'), 503)


@require_GET
def detail(request, issue_id):
    if not authenticated(request):
        return reply({'error': '로그인이 필요합니다.'}, 401)
    record = Issue.objects.filter(pk=issue_id, environment=environment()).first()
    if record is None:
        return reply({'error': '해당 이력이 없습니다.'}, 404)
    return reply({'issue': serialize(record, detail=True),
                  'queries': sql_queries(record.country,record.product,record.retailer,record.source_date)})


@require_GET
def queries(request):
    if not authenticated(request):
        return reply({'error': '로그인이 필요합니다.'}, 401)
    try:
        day = date.fromisoformat(request.GET.get('source_date', ''))
        if day > timezone.now().astimezone(KST).date():
            raise ValueError()
        result = sql_queries(request.GET.get('country'), request.GET.get('product'),
                             request.GET.get('retailer'), day)
        return reply({'source_date': str(day), 'queries': result})
    except (ValueError, TypeError):
        return reply({'error': '국가·제품군·리테일러·수집 날짜를 확인해주세요.'}, 400)


@require_POST
def action(request, issue_id):
    if not authenticated(request):
        return reply({'error': '로그인이 필요합니다.'}, 401)
    try:
        payload = json.loads(request.body)
        kind, revision = payload.get('action'), payload.get('revision')
        if kind not in ('acknowledge', 'except', 'reopen', 'recheck') or type(revision) is not int:
            raise ValueError()
        record = Issue.objects.filter(pk=issue_id, environment=environment()).first()
        if not record:
            return reply({'error': '해당 이력이 없습니다.'}, 404)
        if kind == 'recheck':
            target = record.source_date
            data = daily_counts(record.country,record.product,record.retailer,target,29)
            totals = raw_counts(record.country,record.product,record.retailer,target,target)
            now = timezone.now()
            complete = {d['date']:collection_complete(record.country,record.product,record.retailer,
                        date.fromisoformat(d['date']),now) for d in data['daily']}
            reconcile_day(data,target,complete,totals.get(str(target),0),now=now)
            record.refresh_from_db()
            return reply({'issue': serialize(record,detail=True)})
        reason = payload.get('reason','')
        if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 1000:
            raise ValueError()
        with transaction.atomic():
            record = Issue.objects.get(pk=issue_id,environment=environment())
            if record.revision != revision:
                return reply({'error':'다른 처리 결과가 저장되었습니다. 새로고침 후 확인하세요.'},409)
            if kind in ('acknowledge','except') and record.status != 'open':
                raise ValueError()
            if kind == 'reopen' and record.status != 'excepted':
                raise ValueError()
            status = {'except':'excepted','reopen':'open'}.get(kind,record.status)
            now = timezone.now()
            changed = Issue.objects.filter(pk=record.pk,revision=revision).update(
                status=status,revision=revision+1,resolved_at=now if status=='excepted' else None)
            if not changed:
                return reply({'error':'처리 결과가 변경되었습니다. 다시 조회해주세요.'},409)
            event(record,kind,now,username=request.user.get_username(),reason=reason.strip())
            record.refresh_from_db()
        return reply({'issue':serialize(record,detail=True)})
    except (ValueError,TypeError,AttributeError):
        return reply({'error':'처리 동작과 사유(1~1,000자)를 확인해주세요.'},400)
    except Exception:
        return reply({'error':'처리하지 못했습니다. 기존 미해결 이력을 유지합니다.'},503)
