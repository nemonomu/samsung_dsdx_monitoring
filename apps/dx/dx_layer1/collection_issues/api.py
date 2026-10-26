import json
from datetime import date, timedelta

from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_layer1.models import CollectionIssue as Issue, CollectionIssueScan as Scan
from apps.dx.dx_layer1.column_statistics.services import catalog, daily_counts
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, KST
from apps.dx.dx_layer1.column_statistics.dates import active_from
from .queries import sql_queries, raw_counts, daily_batch_ids, selection
from .services import START_DATE, POLICY_VERSION, environment, serialize, event, reconcile_day
from .errors import storage_error
from . import volume


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
        for job in jobs:
            source, _ = selection(**job)
            start = active_from(source, job['retailer'])
            if start:
                records = records.exclude(**job, source_date__lt=start)
        inspection_date = request.GET.get('inspection_date', timezone.now().astimezone(KST).date().isoformat())
        # D-1 is the current inspection's source day, not a past incident.
        # Filter the listing only: retain the original evidence and recovery scans.
        cutoffs = {}
        for country in {job['country'] for job in jobs}:
            current_source_date = resolve_monitoring_date(
                inspection_date, country, country.lower() + '_tv')['source_date']
            records = records.exclude(country=country, source_date__gte=current_source_date)
            cutoffs[country] = date.fromisoformat(current_source_date) - timedelta(days=1)
        if status != 'all':
            records = records.filter(status=status)
        rows = list(records.order_by('source_date', 'country', 'retailer', 'product', 'column'))
        rows = volume.hide_confirmed(rows) if status == 'open' else rows
        # Whole-collection incidents are one row, not one copy per affected field.
        whole = {(r.country,r.product,r.retailer,r.source_date) for r in rows if not r.column and r.status=='open'}
        rows = [r for r in rows if not r.column or r.column.startswith('__')
                or (r.country,r.product,r.retailer,r.source_date) not in whole]
        scans = list(Scan.objects.filter(environment=environment(), **filters).values(
            'country', 'product', 'retailer', 'coverage_start', 'start_basis',
            'scanned_through', 'last_checked_at', 'error', 'policy_version'))
        scopes = {(j['country'],j['product'],j['retailer']) for j in jobs}
        scans = [s for s in scans if (s['country'],s['product'],s['retailer']) in scopes]
        for scan in scans:
            current_policy = scan['policy_version'] == POLICY_VERSION
            if not current_policy:
                scan['scanned_through'] = None
                scan['last_checked_at'] = None
            last_due = cutoffs.get(scan['country'])
            not_started = scan['coverage_start'] and last_due and scan['coverage_start'] > last_due
            scan['pending'] = bool(not current_policy or (not not_started and (not scan['scanned_through']
                or (last_due and scan['scanned_through'] < last_due))))
        return reply({'policy_version': POLICY_VERSION,
                      'start_date': str(START_DATE), 'inspection_date': inspection_date,
                      'issues': [serialize(r) for r in rows],
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
            batches = daily_batch_ids(record.country,record.product,record.retailer,target,target)
            volumes = volume.load_days(record.country,record.product,record.retailer,
                [target] if totals.get(str(target),0) > 0 else [])
            with transaction.atomic():
                reconcile_day(data,target,complete,totals.get(str(target),0),now=now)
                if complete.get(str(target)):
                    volume.reconcile(record.country,record.product,record.retailer,target,
                        volumes.get(str(target),[]),batches.get(str(target),[]),now=now)
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
