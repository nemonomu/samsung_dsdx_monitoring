"""Format rules for SIEL Jiomart retail fields."""

import re

from apps.common.siel_retail import get_siel_format_editable_columns


_INR = re.compile(r'^₹(?:0|[1-9][0-9]*|[1-9][0-9]?(?:,[0-9]{2})*,[0-9]{3})(?:\.[0-9]{1,2})?$')
_PERCENT = re.compile(r'^(?:100|[1-9]?[0-9])%$')
_RATING = re.compile(r'^(?:[0-4](?:\.[0-9])?|5(?:\.0)?)$')
_INTEGER = re.compile(r'^[0-9]+$')
_NUMBER = r'(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)'
_INCHES = re.compile(rf'^{_NUMBER}\s*inch(?:es)?$', re.I)
_LITERS = re.compile(rf'^{_NUMBER}\s*L$', re.I)
_KILOGRAMS = re.compile(rf'^{_NUMBER}\s*kg(?:\s*,\s*{_NUMBER}\s*kg)?$', re.I)
_MINI_WASHER = re.compile(r'\b(?:portable\s+mini|mini\s+portable|mini|portable)\s+(?:washing machine|washer)\b', re.I)
_CONSUMABLE_OR_ACCESSORY = re.compile(r'\b(?:detergent|cleanser|dishwash|hand\s*wash|cover|accessor(?:y|ies))\b', re.I)

_PRICE_DESCRIPTION = '₹ 기호가 붙은 금액. 인도식 쉼표를 쓸 수 있으며 소수점 이하 두 자리까지 허용합니다.'
_PRICE_EXAMPLES = '₹25,990 / ₹1,29,990 / ₹599.50'
_RULES = {
    'country': (re.compile(r'SIEL', re.I), '국가 코드 SIEL. 대소문자 무관.', 'SIEL'),
    'account_name': (re.compile(r'Jiomart', re.I), '계정명 Jiomart. 대소문자 무관.', 'Jiomart'),
    'final_sku_price': (_INR, _PRICE_DESCRIPTION, _PRICE_EXAMPLES),
    'original_sku_price': (_INR, _PRICE_DESCRIPTION, _PRICE_EXAMPLES),
    'savings': (_PERCENT, '0~100의 정수 뒤에 %를 붙인 할인율.', '10% / 62% / 100%'),
    'star_rating': (_RATING, '0~5의 숫자. 소수점 이하 한 자리까지 허용합니다.', '0 / 4.3 / 5'),
    'count_of_star_ratings': (_INTEGER, '0 이상의 정수.', '0 / 12 / 100'),
    'count_of_reviews': (_INTEGER, '0 이상의 정수.', '0 / 12 / 100'),
    'screen_size': (_INCHES, '양수(소수 허용)에 inch 또는 inches를 붙입니다.', '55 inch / 54.6 inch / 55 inches'),
    'ref_capacity': (_LITERS, '양수(소수 허용)에 L을 붙입니다.', '650 L / 183 L / 93.5 L'),
    'ldy_capacity': (_KILOGRAMS,
                     '양수 kg 한 값 또는 세탁·건조 용량 kg 두 값을 쉼표로 구분합니다. '
                     '상품명에서 소형·휴대용 세탁기가 확인되면 L 용량도 허용합니다.',
                     '8 kg / 8.5 kg, 5 kg'),
}


def rule_details(product_line):
    return [
        {'field': field, 'description': _RULES[field][1], 'pattern': _RULES[field][2]}
        for field in get_siel_format_editable_columns(product_line, 'Jiomart')
    ]


def evaluate(row, product_line):
    errors = {}
    for field in get_siel_format_editable_columns(product_line, 'Jiomart'):
        value = row.get(field)
        if value is None or not (text := str(value).strip()):
            continue
        pattern, description, _examples = _RULES[field]
        if pattern.fullmatch(text):
            continue
        if field == 'ldy_capacity' and _LITERS.fullmatch(text):
            name = str(row.get('retailer_sku_name') or '')
            if _MINI_WASHER.search(name) and not _CONSUMABLE_OR_ACCESSORY.search(name):
                continue
        errors[field] = description
    return errors
