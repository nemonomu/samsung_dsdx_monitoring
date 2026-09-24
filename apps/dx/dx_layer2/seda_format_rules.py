"""SEDA format rules; missing values belong to NULL validation."""
import calendar
import re
from urllib.parse import urlsplit

from apps.common.seda_retail import get_seda_product_line, seda_retailer_key

COMMON_FIELDS = (
    'account_name', 'calendar_week', 'country', 'detailed_review_content',
    'original_sku_price', 'final_sku_price', 'page_type', 'product',
    'sku_status', 'discount_type', 'delivery_availability', 'pick_up_availability',
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
    'main_rank', 'bsr_rank', 'product_url',
)
DISPLAY_GROUPS = (
    ('star_rating', 'count_of_star_ratings', 'count_of_reviews'),
    ('original_sku_price', 'final_sku_price', 'savings'),
)
MONEY = r'R\$\s*(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+),[0-9]{2}'
WEEKDAY = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
MONTH = '(?:' + '|'.join(calendar.month_name[1:]) + ')'
DELIVERY_DATE = rf'{WEEKDAY}, (?P<month>{MONTH}) (?P<day>0?[1-9]|[12][0-9]|3[01])'
CASAS_UNAVAILABLE = (
    'Delivery unavailable for your region at the moment. Try another ZIP code?',
    'Desculpe! No momento este produto não pode ser entregue na região informada.',
)


def columns(product_line, retailer=None):
    product = get_seda_product_line(product_line)
    if not product or (retailer is not None and seda_retailer_key(retailer) not in ('magalu', 'casasbahia')):
        return ()
    return COMMON_FIELDS + (('screen_size',) if product == 'seda_tv' else ())


def expand_fields(fields):
    result = []
    for field in fields:
        group = next((group for group in DISPLAY_GROUPS if field in group), (field,))
        result.extend(key for key in group if key not in result)
    return result


def valid_review_body(text):
    # Split only on a review boundary; ordinary punctuation/emojis are content.
    parts = re.split(r'\s*\|\|\|\s*(?=review[0-9]+\s*-)', text)
    for index, part in enumerate(parts, 1):
        match = re.fullmatch(r'review([1-9][0-9]*)\s*-\s*(.+)', part, re.DOTALL)
        if not match or int(match[1]) != index or not match[2].strip(' \t\r\n|'):
            return False
        if re.search(r'\breview[0-9]+\s*-', match[2]):
            return False
    return bool(parts)


def valid_delivery(text, retailer):
    if retailer == 'casasbahia' and text in CASAS_UNAVAILABLE:
        return True
    if retailer == 'magalu' and (text in ('Receive today', 'Receive tomorrow')
            or re.fullmatch(r'Receive within (?:1 business day|[2-9][0-9]* business days|1[0-9]+ business days)', text)):
        return True
    prefix = 'Normal by ' if retailer == 'casasbahia' else 'Receive by '
    match = re.fullmatch(re.escape(prefix) + DELIVERY_DATE, text)
    if not match:
        return False
    month = list(calendar.month_name).index(match['month'])
    return int(match['day']) <= calendar.monthrange(2000, month)[1]


def evaluate(row, product_line, retailer):
    fields = columns(product_line, retailer)
    retailer = seda_retailer_key(retailer)
    product = get_seda_product_line(product_line)
    errors = {}
    patterns = {
        'calendar_week': r'w(?:[1-9]|[1-4][0-9]|5[0-3])',
        'original_sku_price': MONEY, 'final_sku_price': MONEY,
        'star_rating': r'(?:[0-4](?:\.[0-9])?|5(?:\.0)?)',
        'count_of_star_ratings': r'[0-9]+', 'count_of_reviews': r'[0-9]+',
        'main_rank': r'[1-9][0-9]*', 'bsr_rank': r'[1-9][0-9]*',
        'screen_size': r'(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)\s*(?:inches|inch|Polegadas|polegadas|")',
    }
    for field in fields:
        value = row.get(field)
        if value is None or not str(value).strip():
            continue
        text = str(value).strip()
        valid = True
        if field in patterns:
            valid = bool(re.fullmatch(patterns[field], text))
        elif field == 'account_name':
            valid = text in ('Magalu', 'CasasBahia', 'Casas Bahia') and seda_retailer_key(text) == retailer
        elif field == 'country':
            valid = text == 'SEDA'
        elif field == 'product':
            valid = text == product.removeprefix('seda_').upper()
        elif field == 'page_type':
            valid = text in ('main', 'bsr')
        elif field == 'sku_status':
            valid = text == 'Sponsored'
        elif field == 'detailed_review_content':
            valid = valid_review_body(text)
        elif field == 'discount_type':
            if retailer == 'magalu':
                valid = bool(re.fullmatch(r'Coupon R\$ (?:[1-9][0-9]*(?:,[0-9]{2})?|[1-9][0-9]{0,2}(?:\.[0-9]{3})+(?:,[0-9]{2})?|0,(?:0[1-9]|[1-9][0-9])) off', text))
            else:
                valid = bool(re.fullmatch(r'USE O CUPOM DESCONTO (?:[1-9][0-9]?|100)%', text))
        elif field == 'delivery_availability':
            valid = valid_delivery(text, retailer)
        elif field == 'pick_up_availability':
            valid = text in (('Pick up in store', 'Pick up in store starting tomorrow')
                            if retailer == 'magalu' else ('Pick up in store', 'Fast pickup in 2h'))
        elif field == 'product_url':
            try:
                url = urlsplit(text)
                domain = 'magazineluiza.com.br' if retailer == 'magalu' else 'casasbahia.com.br'
                valid = (url.scheme in ('http', 'https') and bool(url.hostname)
                         and (url.hostname == domain or url.hostname.endswith('.' + domain))
                         and not re.search(r'\s', text) and not url.username and not url.password)
            except ValueError:
                valid = False
        if not valid:
            errors[field] = rule_details(product_line, retailer, field)['description']
    return errors


def rule_details(product_line, retailer, field):
    descriptions = {
        'account_name': 'Magalu 또는 CasasBahia(Casas Bahia)이며 해당 리테일러와 일치해야 합니다.',
        'calendar_week': 'w1~w53 형식이어야 합니다.',
        'country': 'SEDA여야 합니다.',
        'product': f"{get_seda_product_line(product_line).removeprefix('seda_').upper()}여야 합니다.",
        'page_type': 'main 또는 bsr여야 합니다.',
        'detailed_review_content': 'review1 - 본문으로 시작하고, |||로 구분한 리뷰 번호가 연속되며 각 본문이 있어야 합니다.',
        'original_sku_price': 'R$2.199,00 형태의 음수가 아닌 브라질 헤알 금액이어야 합니다.',
        'final_sku_price': 'R$2.199,00 형태의 음수가 아닌 브라질 헤알 금액이어야 합니다.',
        'star_rating': '0~5 숫자이며 소수점은 한 자리까지 허용합니다.',
        'count_of_star_ratings': '0 이상의 정수여야 합니다.', 'count_of_reviews': '0 이상의 정수여야 합니다.',
        'main_rank': '1 이상의 정수여야 합니다.', 'bsr_rank': '1 이상의 정수여야 합니다.',
        'screen_size': '양수 숫자 + inches, Polegadas 또는 인치 기호(") 형식이어야 합니다.',
        'sku_status': 'Sponsored여야 합니다.',
        'discount_type': ('Coupon R$ 양수금액 off 형식이어야 합니다.' if seda_retailer_key(retailer) == 'magalu'
                          else 'USE O CUPOM DESCONTO 1~100% 형식이어야 합니다.'),
        'delivery_availability': ('Receive by 요일, 월 날짜 / Receive today·tomorrow / Receive within N business day(s) 형식이어야 합니다.'
                                  if seda_retailer_key(retailer) == 'magalu' else 'Normal by 요일, 월 날짜 또는 확인된 배송 불가 문구여야 합니다. Delivery unavailable for this ZIP code는 이상입니다.'),
        'pick_up_availability': ('Pick up in store 또는 Pick up in store starting tomorrow여야 합니다.'
                                 if seda_retailer_key(retailer) == 'magalu' else 'Pick up in store 또는 Fast pickup in 2h여야 합니다.'),
        'product_url': '해당 리테일러 도메인의 유효한 HTTP(S) URL이어야 합니다.',
    }
    return {'field': field, 'description': descriptions[field], 'pattern': descriptions[field]}
