"""Human-managed check URLs. Source collection data is never modified."""
import json
import logging
import re
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import DatabaseError, IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from apps.dx.dx_document.manual import dx_access, current_revision, seed_data
from apps.dx.dx_document.manual_catalog import prepare_data, retailer_token
from apps.dx.dx_document.manual_links import guide_urls, key
from apps.dx.dx_layer1.models import ColumnCheckLink
from apps.dx.dx_layer1.collection_issues.services import environment
from .services import catalog


def serialize(record):
    return dict(key=key(record.country, record.product, record.retailer, record.column),
                url=record.url, revision=record.revision, updated_by=record.updated_by,
                updated_at=record.updated_at.isoformat())


def selection(data):
    country, product, retailer, column = (data.get(k) for k in ('country', 'product', 'retailer', 'column'))
    if not all(isinstance(v, str) for v in (country, product, retailer, column)):
        raise ValueError('국가·제품군·리테일러·컬럼을 확인하세요.')
    if column and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,119}', column):
        raise ValueError('컬럼명이 올바르지 않습니다.')
    token = retailer_token(retailer)
    if not any(s['country'] == country and s['product'] == product and
               any(retailer_token(r) == token for r in s['retailers']) for s in catalog()):
        raise ValueError('등록된 국가·제품군·리테일러를 선택하세요.')
    return dict(environment=environment(), country=country, product=product, retailer=token, column=column)


@dx_access
@require_http_methods(['GET', 'POST'])
@never_cache
def links(request):
    try:
        if request.method == 'GET':
            records = [serialize(record) for record in ColumnCheckLink.objects.filter(environment=environment())]
            try:
                revision = current_revision()
                guides = guide_urls(prepare_data(revision.data if revision else seed_data()))
                manual_error = False
            except DatabaseError:
                logging.getLogger(__name__).exception('Column alert manual lookup failed')
                guides, manual_error = {}, True
            return JsonResponse(dict(links=records, guides=guides, manual_error=manual_error))
        if len(request.body) > 16000:
            return JsonResponse({'error': '입력 내용이 너무 큽니다.'}, status=413)
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('요청 형식이 올바르지 않습니다.')
        identity = selection(data)
        url, version = data.get('url'), data.get('revision')
        if not isinstance(url, str) or len(url) > 4000 or any(ord(ch) < 32 for ch in url):
            raise ValueError('URL을 확인하세요.')
        url = url.strip()
        URLValidator(schemes=['http', 'https'])(url)
        if urlsplit(url).username is not None or urlsplit(url).password is not None:
            raise ValueError('사용자 정보가 포함된 URL은 저장할 수 없습니다.')
        if type(version) is not int or version < 0:
            raise ValueError('저장 버전이 올바르지 않습니다.')
        with transaction.atomic():
            record = ColumnCheckLink.objects.select_for_update().filter(**identity).first()
            if (record.revision if record else 0) != version:
                return JsonResponse({'error': '다른 사용자가 수정했습니다. 목록을 새로고침한 후 다시 시도하세요.'}, status=409)
            now = timezone.now()
            entry = dict(url=url, username=request.user.username, at=now.isoformat())
            if record:
                updated = ColumnCheckLink.objects.filter(pk=record.pk, revision=version).update(
                    url=url, revision=version + 1, updated_by=request.user.username,
                    updated_at=now, history=[*record.history, entry])
                if not updated:
                    return JsonResponse({'error': '다른 사용자가 수정했습니다. 목록을 새로고침하세요.'}, status=409)
                record.refresh_from_db()
            else:
                record = ColumnCheckLink.objects.create(**identity, url=url, revision=1,
                    updated_by=request.user.username, updated_at=now, history=[entry])
            return JsonResponse({'link': serialize(record)})
    except IntegrityError:
        return JsonResponse({'error': '다른 사용자가 먼저 등록했습니다. 목록을 새로고침하세요.'}, status=409)
    except (ValueError, TypeError, ValidationError):
        return JsonResponse({'error': '등록 대상과 URL을 확인하세요. http 또는 https 주소를 입력하세요.'}, status=400)
    except DatabaseError:
        logging.getLogger(__name__).exception('Column check URL storage failed')
        return JsonResponse({'error': 'URL 저장소에 접근하지 못했습니다. 서버 상태를 확인한 후 다시 시도하세요.'}, status=503)
