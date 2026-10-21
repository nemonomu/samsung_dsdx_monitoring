"""Authenticated manual viewing, validated edits and append-only version history."""
from functools import lru_cache, wraps
import hashlib
import io
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse, urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from . import manual_storage as storage
from .manual_catalog import prepare_data, configured_columns
from .manual_schema import validate_structure
from .manual_links import requested_target

DATA_DIR = Path(__file__).with_name('manual_data')
IMAGE_URL = '/dx/documents/manual/images/'
MAX_DATA_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def is_manual_category(category):
    name = re.sub(r'\s+', '', category.get('category_name', '')).lower()
    return name in {'dx검수매뉴얼', 'dx검수메뉴얼', 'dx매뉴얼', 'dx메뉴얼'}


def dx_access(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        allowed = user.is_staff or user.is_superuser
        if not allowed:
            try:
                allowed = user.profile.can_access_dx
            except (ObjectDoesNotExist, AttributeError):
                allowed = False
        if not allowed:
            return JsonResponse({'error': 'DX 접근 권한이 필요합니다.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


@lru_cache(maxsize=1)
def seed_data():
    return json.loads((DATA_DIR / 'seed.json').read_text(encoding='utf-8'))


def metadata(revision):
    return {'version': revision.version if revision else 0,
            'created_by': revision.created_by if revision else '',
            'created_at': revision.created_at.isoformat() if revision else None}


def current_revision():
    return storage.revisions().first()


@dx_access
@require_GET
@never_cache
def page(request):
    from .document.document_services import get_categories_list
    categories = get_categories_list()
    for category in categories:
        category['is_manual'] = is_manual_category(category)
    query = urlencode({k: request.GET[k] for k in ('country', 'product', 'retailer', 'column') if k in request.GET})
    return render(request, 'dx_document/manual.html', {'categories': categories, 'manual_query': query})


@dx_access
@require_GET
@never_cache
@ensure_csrf_cookie
@xframe_options_sameorigin
def content(request):
    revision = current_revision()
    catalog, warning = configured_columns()
    data = prepare_data(revision.data if revision else seed_data(), catalog)
    target, target_error = requested_target(data, request.GET)
    return render(request, 'dx_document/manual_content.html', {
        'guide_data': data,
        'guide_meta': {**metadata(revision), 'catalogWarning': warning, 'target': target, 'targetError': target_error},
    })


def validate_data(data):
    """Validate manual additions and edits without changing source identifiers."""
    validate_structure(data, seed_data())
    rows = data['datasets']
    photos = data['photos']
    if not isinstance(photos, list) or not 0 <= len(photos) <= 2000:
        raise ValueError('이미지는 최대 2000개까지 저장할 수 있습니다.')
    names = set()
    image_refs = set()
    fields_by_retailer = {}
    for row in rows:
        fields_by_retailer.setdefault(row['retailer'], set()).update(f['field'] for f in row['fields'])
    for photo in photos:
        if not isinstance(photo, dict):
            raise ValueError('이미지 구성이 올바르지 않습니다.')
        name = photo.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', name):
            raise ValueError('이미지 이름이 올바르지 않거나 중복되었습니다.')
        if photo.get('retailer') not in fields_by_retailer or photo.get('category') not in {'tv', 'ref', 'ldy', 'ldy_dryer', 'dryer', 'hhp', 'all'}:
            raise ValueError('이미지의 리테일러·제품군을 확인하세요.')
        identity = (photo['retailer'], photo['category'], name)
        if identity in names:
            raise ValueError('같은 제품군의 이미지 이름이 중복되었습니다.')
        names.add(identity)
        for key in ('stage', 'region', 'note', 'date', 'url', 'commonExample'):
            text_value(photo.get(key, ''), 20000)
        url = photo.get('url', '')
        if url and (urlparse(url).scheme not in {'http', 'https'} or not urlparse(url).netloc):
            raise ValueError('출처 URL은 http 또는 https 주소여야 합니다.')
        for key in ('width', 'height'):
            finite_number(photo.get(key), 1, 30000)
        boxes = photo.get('boxes')
        if not isinstance(boxes, list) or len(boxes) > 300:
            raise ValueError('번호 박스 구성이 올바르지 않습니다.')
        for box in boxes:
            if not isinstance(box, dict):
                raise ValueError('번호 박스를 확인하세요.')
            for key in ('x', 'y', 'w', 'h'):
                finite_number(box.get(key), -100000 if key in ('x', 'y') else 0, 100000)
            if not isinstance(box.get('fields'), list) or not box['fields'] or any(f not in fields_by_retailer[photo['retailer']] for f in box['fields']):
                raise ValueError('번호 박스의 연결 컬럼을 확인하세요.')
        samples = photo.get('sampleValues', {})
        if not isinstance(samples, dict):
            raise ValueError('이미지의 예시 값을 확인하세요.')
        for value in samples.values():
            text_value(value, 20000)
        ref = photo.get('customImage') or data['assets'].get(name)
        if not isinstance(ref, str) or not re.fullmatch(re.escape(IMAGE_URL) + r'[a-f0-9]{64}/', ref):
            raise ValueError('이미지를 먼저 업로드하세요.')
        image_refs.add(ref.split('/')[-2])
    missing = [digest for digest in image_refs if not (DATA_DIR / 'images' / digest).is_file()]
    if missing and storage.images().filter(digest__in=missing).count() != len(missing):
        raise ValueError('저장되지 않은 이미지가 있습니다. 다시 업로드하세요.')
    return data


def text_value(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('문구의 형식 또는 길이를 확인하세요.')


def finite_number(value, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('이미지 크기와 번호 박스 좌표를 확인하세요.')


@dx_access
@require_POST
@never_cache
def save(request):
    if len(request.body) > MAX_DATA_BYTES:
        return JsonResponse({'error': '매뉴얼 데이터가 너무 큽니다.'}, status=413)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] < 0:
            raise ValueError('저장 버전이 올바르지 않습니다.')
        data = validate_data(payload.get('data'))
        version = payload['version']
        revision = storage.save_revision(version, data, request.user.username)
        return JsonResponse({'success': True, **metadata(revision)})
    except (IntegrityError, storage.RevisionConflict):
        return JsonResponse({'error': '다른 사용자가 먼저 저장했습니다. 최신 버전을 확인하세요.'}, status=409)
    except (ValueError, TypeError, KeyError) as exc:
        return JsonResponse({'error': str(exc) or '저장 내용을 확인하세요.'}, status=400)


@dx_access
@require_GET
@never_cache
def history(request):
    version = request.GET.get('version')
    if version is not None:
        if not version.isdigit():
            return JsonResponse({'error': '버전이 올바르지 않습니다.'}, status=400)
        if int(version) == 0:
            return JsonResponse({'data': prepare_data(seed_data()), **metadata(None)})
        revision = storage.revisions().filter(version=int(version)).first()
        if not revision:
            raise Http404
        return JsonResponse({'data': prepare_data(revision.data), **metadata(revision)})
    revisions = storage.revisions().defer('data')[:30]
    return JsonResponse({'revisions': [metadata(r) for r in revisions] + [metadata(None)]})


@dx_access
@require_POST
def upload(request):
    file = request.FILES.get('image')
    if not file or file.size > MAX_IMAGE_BYTES:
        return JsonResponse({'error': '15MB 이하의 PNG, JPG, WEBP 이미지를 선택하세요.'}, status=400)
    raw = file.read()
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(picture.format)
            if not mime or picture.width * picture.height > 40_000_000:
                raise ValueError
            picture.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return JsonResponse({'error': '유효한 PNG, JPG, WEBP 이미지가 아닙니다.'}, status=400)
    digest = hashlib.sha256(raw).hexdigest()
    storage.images().get_or_create(digest=digest, defaults={
        'content': raw, 'content_type': mime, 'created_by': request.user.username,
    })
    return JsonResponse({'url': IMAGE_URL + digest + '/'})


@dx_access
@require_GET
def image(request, digest):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise Http404
    path = DATA_DIR / 'images' / digest
    if path.is_file():
        with Image.open(path) as picture:
            mime = Image.MIME[picture.format]
        response = FileResponse(path.open('rb'), content_type=mime)
    else:
        stored = storage.images().filter(digest=digest).first()
        if not stored:
            raise Http404
        response = HttpResponse(bytes(stored.content), content_type=stored.content_type)
    response['Cache-Control'] = 'private, max-age=86400'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
