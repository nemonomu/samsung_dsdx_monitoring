"""Seven Bestbuy dryer relationships; malformed values belong to format checks."""
from decimal import Decimal
import re

RULES = {
    'review_count_match': '리뷰 수와 별점 수가 같아야 합니다.',
    'rating_count_presence': 'Not yet reviewed 또는 별점 0이면 리뷰 수·별점 수가 모두 0이어야 하며, 양수 별점이면 두 수가 모두 1 이상이어야 합니다.',
    'final_original_price': '판매가는 원가를 초과할 수 없습니다. 같은 금액이면 할인액은 공란 또는 0이어야 합니다.',
    'savings_missing': '원가가 판매가보다 높으면 할인액이 있어야 합니다.',
    'original_missing': '판매가와 양수 할인액이 있으면 원가가 있어야 합니다.',
    'final_missing': '원가나 할인액이 있으면 판매가가 있어야 합니다.',
    'savings_amount_match': '원가에서 판매가를 뺀 금액과 할인액이 센트 단위로 일치해야 합니다.',
}
INTEGER = r'(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)'
MONEY = re.compile(r'\$' + INTEGER + r'(?:\.[0-9]{1,2})?')


def present(value):
    return value is not None and bool(str(value).strip())


def number(value, pattern):
    text = str(value).strip()
    return Decimal(text.replace('$', '').replace(',', '')) if re.fullmatch(pattern, text) else None


def evaluate(row):
    errors = set()
    reviews = number(row.get('count_of_reviews'), INTEGER)
    stars = number(row.get('count_of_star_ratings'), INTEGER)
    raw_rating = str(row.get('star_rating') or '').strip()
    rating = Decimal(0) if raw_rating == 'Not yet reviewed' else number(row.get('star_rating'), r'\d+(?:\.\d+)?')
    if reviews is not None and stars is not None and reviews != stars:
        errors.add('review_count_match')
    if rating is not None and 0 <= rating <= 5:
        if any(count is not None and ((rating == 0) != (count == 0)) for count in (reviews, stars)):
            errors.add('rating_count_presence')

    final, original, savings = [number(row.get(field), MONEY) for field in
                                ('final_sku_price', 'original_sku_price', 'savings')]
    if final is not None and original is not None:
        if final > original:
            errors.add('final_original_price')
        if original > final and not present(row.get('savings')):
            errors.add('savings_missing')
        if savings is not None and original - final != savings:
            errors.add('savings_amount_match')
    if final is not None and savings is not None and savings > 0 and not present(row.get('original_sku_price')):
        errors.add('original_missing')
    if not present(row.get('final_sku_price')) and (original is not None or savings is not None):
        errors.add('final_missing')
    return errors
