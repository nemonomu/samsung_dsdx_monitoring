"""Expert format rules for populated CSV fields; no cross-field checks."""
import re
from urllib.parse import urlsplit


COMMON = ('final_sku_price', 'original_sku_price', 'savings', 'star_rating',
          'count_of_reviews', 'count_of_star_ratings', 'product_url')
EXTRAS = {
    'seg_tv': ('screen_size',),
    'seg_ref': ('ref_capacity', 'ref_refrigerator_type'),
    'seg_ldy': ('ldy_capacity', 'ldy_loading_type'),
    'seg_ldy_dryer': ('capacity', 'loading_type'),
}


def _match(pattern):
    return lambda value: re.fullmatch(pattern, value) is not None


def _url(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ('http', 'https') and bool(parsed.hostname)
                and not re.search(r'\s', value) and parsed.port != 0)
    except ValueError:
        return False


PRICE = (_match(r'(?:0|[1-9][0-9]{0,2}(?:\.[0-9]{3})*),[0-9]{2}\s?€'),
         '독일식 유로 금액', '189,99 € / 1.299,00 €')
COUNT = (_match(r'[0-9]+'), '0 이상의 정수', '0 / 128 / 1018')
CAPACITY = (_match(r'[0-9]+(?:\.[0-9]+)?\s+kg'), '숫자와 kg 단위', '8 kg / 7.5 kg')
LOADING = (lambda value: value in ('Front Load', 'Top Load'),
           '로딩 방식 허용값', 'Front Load / Top Load')
REF_TYPES = ('Refrigerator', 'Fridge-freezer Combination', 'Side by Side',
             'Mini Refrigerator', 'French Door')
RULES = {
    'final_sku_price': (
        lambda value: value == 'Artikel ist derzeit nicht verfügbar' or PRICE[0](value),
        '독일식 유로 금액 또는 구매 불가 상태',
        PRICE[2] + ' / Artikel ist derzeit nicht verfügbar'),
    'original_sku_price': PRICE,
    'savings': (_match(r'[0-9]+%'), '정수 할인율 표기', '0% / 4% / 31%'),
    'star_rating': (_match(r'(?:[0-4](?:\.[0-9]+)?|5(?:\.0+)?)'),
                    '0~5 범위 숫자', '0.0 / 4.8 / 5.0'),
    'count_of_reviews': COUNT,
    'count_of_star_ratings': COUNT,
    'product_url': (_url, 'HTTP/HTTPS URL', 'https://www.expert.de/...'),
    'screen_size': (_match(r'[0-9]+(?:\.[0-9]+)?\s+inch'),
                    '숫자와 inch 단위', '55 inch'),
    'ref_capacity': (_match(r'[0-9]+(?:\.[0-9]+)?\s+L'),
                     '숫자와 L 단위', '136 L'),
    'ref_refrigerator_type': (lambda value: value in REF_TYPES,
                              '냉장고 유형 허용값', ' / '.join(REF_TYPES)),
    'ldy_capacity': CAPACITY,
    'capacity': CAPACITY,
    'ldy_loading_type': LOADING,
    'loading_type': LOADING,
}


def columns(product):
    return (*COMMON, *EXTRAS[product]) if product in EXTRAS else ()


def evaluate(row, product):
    return {field: f'{RULES[field][1]} 형식이 아닙니다.'
            for field in columns(product)
            if row.get(field) is not None and str(row[field]).strip()
            and not RULES[field][0](str(row[field]).strip())}


def rule_details(product):
    return [{'field': field, 'description': RULES[field][1],
             'pattern': RULES[field][2]} for field in columns(product)]
