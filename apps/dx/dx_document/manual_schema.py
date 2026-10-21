"""Validation for expandable manual structure. This never writes collection config."""
import re
from urllib.parse import urlparse
from .manual_catalog import COUNTRIES, PRODUCTS

IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,119}$')
TEXT_KEYS = ('label', 'scope', 'page', 'position', 'original', 'example', 'note')


def text(value, limit=20000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('문구의 형식 또는 길이를 확인하세요.')


def url(value):
    text(value, 4000)
    if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
        raise ValueError('주소는 http 또는 https로 입력하세요.')


def validate_structure(data, seed):
    if not isinstance(data, dict) or set(data) - set(seed) - {'schemaVersion'} or not set(seed) <= set(data):
        raise ValueError('매뉴얼 데이터 형식이 올바르지 않습니다.')
    if data.get('schemaVersion', 2) != 2:
        raise ValueError('지원하지 않는 매뉴얼 버전입니다.')
    for key in set(seed) - {'profiles', 'datasets', 'photos'}:
        if data[key] != seed[key]:
            raise ValueError('기준 자료는 변경할 수 없습니다.')
    profiles = data['profiles']
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 200:
        raise ValueError('쇼핑몰은 최대 200개까지 등록할 수 있습니다.')
    seen = set()
    for key, profile in profiles.items():
        if not isinstance(key, str) or not re.fullmatch(r'[A-Z]{2,8}/[a-z0-9_-]{1,100}', key) or not isinstance(profile, dict):
            raise ValueError('쇼핑몰 식별자가 올바르지 않습니다.')
        if profile.get('country') != COUNTRIES.get(key.split('/')[0]):
            raise ValueError('쇼핑몰의 국가를 확인하세요.')
        name = profile.get('name')
        text(name, 100)
        identity = (profile['country'], re.sub(r'\W', '', name).casefold())
        if not name.strip() or identity in seen:
            raise ValueError('같은 국가에 같은 이름의 쇼핑몰이 있습니다.')
        seen.add(identity)
        for prop, value in profile.items():
            if prop in ('queries', 'bsr'):
                if not isinstance(value, dict):
                    raise ValueError('쇼핑몰 방문 정보가 올바르지 않습니다.')
                for category, entry in value.items():
                    if category not in PRODUCTS:
                        raise ValueError('지원하지 않는 제품군입니다.')
                    (url if prop == 'bsr' else text)(entry)
            elif prop in ('mainBase', 'homepage'):
                url(value)
            elif isinstance(value, str):
                text(value)
            elif prop not in ('capacity', 'bsrSearch', 'searchUI'):
                raise ValueError('쇼핑몰 정보 형식이 올바르지 않습니다.')
    for key, original in seed['profiles'].items():
        if key not in profiles or any(profiles[key].get(prop) != value for prop, value in original.items() if prop not in ('queries', 'bsr')):
            raise ValueError('기존 쇼핑몰의 기준 정보를 변경할 수 없습니다.')
        for prop in ('queries', 'bsr'):
            if any(profiles[key].get(prop, {}).get(category) != value for category, value in original.get(prop, {}).items()):
                raise ValueError('기존 방문 정보를 변경할 수 없습니다.')
    rows = data['datasets']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1200:
        raise ValueError('제품군 구성이 올바르지 않습니다.')
    by_key = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('retailer') not in profiles or row.get('category') not in {*PRODUCTS, 'all'}:
            raise ValueError('제품군의 쇼핑몰과 이름을 확인하세요.')
        key = row['retailer'] + '/' + row['category']
        if row.get('key') != key or key in by_key:
            raise ValueError('제품군 식별자가 중복되거나 올바르지 않습니다.')
        text(row.get('title'), 150)
        by_key[key] = row
        fields = row.get('fields')
        if not isinstance(fields, list) or len(fields) > 200:
            raise ValueError('제품군별 컬럼은 최대 200개입니다.')
        numbers, names = set(), set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get('field'), str) or not IDENTIFIER.fullmatch(field['field']):
                raise ValueError('컬럼명은 영문·숫자·밑줄로 입력하세요.')
            if field['field'] in names or type(field.get('n')) is not int or field['n'] < 1 or field['n'] in numbers:
                raise ValueError('컬럼명 또는 번호가 중복되거나 올바르지 않습니다.')
            names.add(field['field']); numbers.add(field['n'])
            if type(field.get('direct')) is not bool:
                raise ValueError('화면 표시 여부를 확인하세요.')
            for flag in ('commonEdited', 'userEdited', 'verified'):
                if flag in field and type(field[flag]) is not bool:
                    raise ValueError('컬럼 편집 상태가 올바르지 않습니다.')
            for prop in TEXT_KEYS:
                text(field.get(prop))
            details = field.get('details', [])
            if not isinstance(details, list) or len(details) > 20:
                raise ValueError('상세내용은 컬럼별로 최대 20개까지 추가할 수 있습니다.')
            for detail in details:
                if not isinstance(detail, dict) or set(detail) != {'title', 'content'}:
                    raise ValueError('상세내용의 제목과 내용을 확인하세요.')
                text(detail['title'], 150)
                text(detail['content'])
                if not detail['title'].strip() or not detail['content'].strip():
                    raise ValueError('상세내용의 제목과 내용을 모두 입력하세요.')
            if not field['label'].strip() or len(field['label']) > 150:
                raise ValueError('컬럼 이름은 1~150자로 입력하세요.')
            if field['field'] == 'product_url' and field['example'].startswith(('http', 'javascript:', 'data:')):
                url(field['example'])
            if not isinstance(field.get('images'), list) or any(not isinstance(v, str) or not re.fullmatch(r'[\w-]{1,150}', v, re.ASCII) for v in field['images']):
                raise ValueError('이미지 참조가 올바르지 않습니다.')
            variants = field.get('legacyVariants', [])
            if not isinstance(variants, list) or len(variants) > 10:
                raise ValueError('기존 설명 정보가 올바르지 않습니다.')
            for variant in variants:
                if not isinstance(variant, dict) or variant.get('category') not in PRODUCTS:
                    raise ValueError('기존 설명의 제품군이 올바르지 않습니다.')
                for prop, value in variant.items():
                    text(value)
    # Original source identifiers remain immutable; additions are manual-only.
    for original in seed['datasets']:
        row = by_key.get(original['key'])
        if row is None:
            raise ValueError('기존 제품군은 삭제할 수 없습니다.')
        fields = {f['field']: f for f in row['fields']}
        for field in original['fields']:
            current = fields.get(field['field'])
            if current is None or any(current.get(prop) != field.get(prop) for prop in ('n', 'direct')):
                raise ValueError('기존 컬럼의 식별자와 번호는 변경할 수 없습니다.')
    return data
