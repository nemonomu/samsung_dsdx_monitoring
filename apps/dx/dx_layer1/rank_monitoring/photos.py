"""Optional, immutable rank review evidence; never mixed into source snapshots."""
import hashlib
import io
import warnings

from PIL import Image, UnidentifiedImageError
from apps.dx.dx_layer1.models import RetailRankReviewImage

MAX_PHOTOS = 5
MAX_IMAGE = 5 * 1024 * 1024
MAX_TOTAL = 15 * 1024 * 1024
TYPES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


class PhotoError(ValueError):
    pass


def current(record):
    return record.history[-1].get('photos', []) if record and record.history else []


def validate_refs(refs, uploads):
    if not isinstance(refs, list) or len(refs) > MAX_PHOTOS or len(uploads) > MAX_PHOTOS:
        raise PhotoError('사진은 최대 5장까지 첨부할 수 있습니다.')
    seen = set()
    for ref in refs:
        if not (type(ref) is int and ref > 0) and ref not in [f'new:{i}' for i in range(len(uploads))]:
            raise PhotoError('사진 첨부 목록을 확인하세요.')
        if ref in seen:
            raise PhotoError('중복된 사진 첨부 요청입니다.')
        seen.add(ref)
    if any(f'new:{i}' not in seen for i in range(len(uploads))):
        raise PhotoError('사진 첨부 목록을 확인하세요.')


def read_uploads(uploads):
    if sum(f.size for f in uploads) > MAX_TOTAL:
        raise PhotoError('사진 합계는 15MB 이하여야 합니다.')
    result = []
    for upload in uploads:
        if upload.size > MAX_IMAGE:
            raise PhotoError('사진 한 장은 5MB 이하여야 합니다.')
        raw = upload.read(MAX_IMAGE + 1)
        if len(raw) > MAX_IMAGE:
            raise PhotoError('사진 한 장은 5MB 이하여야 합니다.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as img:
                    fmt = img.format
                    if fmt not in TYPES or img.width * img.height > 20000000 or getattr(img, 'n_frames', 1) != 1:
                        raise PhotoError('PNG·JPG·WEBP 정지 이미지(2천만 화소 이하)를 첨부하세요.')
                    img.verify()
                with Image.open(io.BytesIO(raw)) as img:
                    img.load()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise PhotoError('사진 파일을 읽을 수 없습니다.') from exc
        result.append(dict(name=(upload.name or '사진')[:200], content=raw,
                           content_type=TYPES[fmt], size=len(raw), digest=hashlib.sha256(raw).hexdigest()))
    return result


def retained_photos(record, refs, uploads):
    """Accept only photos in this exact review's current revision."""
    ids = [ref for ref in refs if type(ref) is int]
    allowed = {p['id'] for p in current(record)}
    if not set(ids) <= allowed:
        raise PhotoError('현재 확인 기록의 사진만 유지할 수 있습니다. 상품 확인 창을 다시 열어주세요.')
    found = {p.pk: p for p in record.images.filter(pk__in=ids).defer('content')}
    if len(found) != len(ids):
        raise PhotoError('사진을 찾을 수 없습니다. 상품 확인 창을 다시 열어주세요.')
    if sum(p.size for p in found.values()) + sum(p['size'] for p in uploads) > MAX_TOTAL:
        raise PhotoError('사진 합계는 15MB 이하여야 합니다.')
    return found


def metadata(photo):
    return {'id': photo.pk, 'name': photo.name, 'size': photo.size,
            'url': f'/dx/layer1/rank/api/review/images/{photo.pk}/'}


def save(record, revision, refs, uploads, retained, now):
    created = {f'new:{i}': RetailRankReviewImage.objects.create(
        review=record, revision=revision, created_at=now, **values) for i, values in enumerate(uploads)}
    return [metadata(retained[ref] if type(ref) is int else created[ref]) for ref in refs]
