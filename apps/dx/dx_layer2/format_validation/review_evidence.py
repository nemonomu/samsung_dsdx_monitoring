"""Bounded, validated images stored with review metadata, never in public static files."""
import base64
import binascii
import hashlib
import io
import warnings
from urllib.parse import urlsplit

MAX_CAPTURE_BYTES = 200 * 1024
MAX_CAPTURES = 3


def validate(evidence, targets):
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ValueError('확인 근거 형식이 올바르지 않습니다.')
    urls, captures = evidence.get('checked_urls', []), evidence.get('captures', [])
    if not isinstance(urls, list) or len(urls) > 100 or any(not isinstance(u, str) for u in urls):
        raise ValueError('확인 URL은 최대 100개까지 선택하세요.')
    allowed = {r['url'] for t in targets for r in t['records']}
    for url in urls:
        parsed = urlsplit(url)
        if url not in allowed or parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('선택한 처리 대상의 상품 URL만 확인 근거로 저장할 수 있습니다.')
    if not isinstance(captures, list) or len(captures) > MAX_CAPTURES:
        raise ValueError('캡처는 최대 3장까지 첨부하세요.')
    images = []
    for capture in captures:
        if not isinstance(capture, dict):
            raise ValueError('캡처 정보가 올바르지 않습니다.')
        encoded, name = capture.get('data'), capture.get('name')
        if not isinstance(encoded, str) or len(encoded) > (MAX_CAPTURE_BYTES + 2) // 3 * 4:
            raise ValueError('캡처 한 장은 200KB 이하여야 합니다.')
        if not isinstance(name, str) or not 1 <= len(name) <= 150:
            raise ValueError('캡처 파일명이 올바르지 않습니다.')
        from PIL import Image
        try:
            content = base64.b64decode(encoded, validate=True)
            if not 0 < len(content) <= MAX_CAPTURE_BYTES:
                raise ValueError()
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as img:
                    fmt = img.format
                    if fmt not in ('PNG', 'JPEG', 'WEBP') or img.width * img.height > 16000000 or getattr(img, 'n_frames', 1) != 1:
                        raise ValueError()
                    img.verify()
                with Image.open(io.BytesIO(content)) as img:
                    img.load()
        except (ValueError, OSError, binascii.Error, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ValueError('캡처는 정상적인 PNG·JPEG·WebP 정지 이미지여야 합니다 (최대 1,600만 화소).') from exc
        images.append({'name': name, 'content_type': {'PNG':'image/png', 'JPEG':'image/jpeg', 'WEBP':'image/webp'}[fmt],
                       'content': content, 'sha256': hashlib.sha256(content).hexdigest()})
    return {'checked_urls': sorted(set(urls)), 'captures': images}


def signature(evidence):
    return {'checked_urls': evidence['checked_urls'],
            'captures': [{k: c[k] for k in ('name', 'content_type', 'sha256')} for c in evidence['captures']]}
