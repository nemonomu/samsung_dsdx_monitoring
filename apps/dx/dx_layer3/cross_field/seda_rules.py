"""Approved SEDA cross-field rules, independent of database configuration."""

import re
from decimal import Decimal

from apps.common.seda_retail import SEDA_RETAILERS, display_seda_retailer


SEDA_DISPLAY_GROUPS = (
    ('star_rating', 'count_of_star_ratings', 'count_of_reviews'),
    ('original_sku_price', 'final_sku_price', 'savings'),
)


def expand_display_fields(fields):
    """Show the complete related group even when only one field is checked."""
    result = []
    for field in fields:
        group = next((group for group in SEDA_DISPLAY_GROUPS if field in group), (field,))
        result.extend(column for column in group if column not in result)
    return tuple(result)


def _spec(name, fields, description, retailers=SEDA_RETAILERS, editable=None):
    return {
        'detail_name': name, 'fields': tuple(fields), 'description': description,
        'retailers': tuple(retailers),
        'editable': tuple(editable if editable is not None else fields),
        'display_fields': expand_display_fields(fields),
    }


SEDA_RULE_SPECS = {
    'rank_page_type': _spec(
        '페이지 유형과 순위 필드 일치', ('page_type', 'main_rank', 'bsr_rank'),
        'MAIN이면 main_rank, BSR이면 bsr_rank가 있어야 합니다. 두 순위가 함께 있는 것은 허용합니다.',
        editable=('main_rank', 'bsr_rank')),
    'final_original_price': _spec(
        '원가보다 높은 최종가', ('original_sku_price', 'final_sku_price'),
        '두 가격이 유효한 브라질 헤알 금액일 때 원가 < 최종가이면 이상입니다. 같은 가격은 정상입니다.'),
    'review_zero_body': _spec(
        '리뷰 수 0인데 본문 있음', ('count_of_reviews', 'detailed_review_content'),
        '리뷰 수가 0인데 상세본문이 있으면 이상입니다. review 번호를 해석할 수 없어도 적용합니다.'),
    'review_body_over_count': _spec(
        '리뷰 수보다 많은 리뷰본문', ('count_of_reviews', 'detailed_review_content'),
        '리뷰 수가 양수이고 수집된 review 번호의 개수가 리뷰 수보다 많으면 이상입니다.'),
    'review_body_count': _spec(
        '리뷰본문 불일치 확인', ('count_of_reviews', 'detailed_review_content'),
        'Lowes 방식으로 리뷰 수가 양수인데 본문이 없거나, 리뷰 수가 20 이상인데 review20까지 '
        '수집되지 않았으면 확인 필요입니다. 본문 번호를 해석할 수 없는 경우도 확인 필요입니다. '
        '리뷰 수 0의 본문 존재와 본문 수 초과는 별도 이상치로 처리합니다.'),
    'rating_count_presence': _spec(
        '별점과 카운트의 0값 일치', ('star_rating', 'count_of_star_ratings', 'count_of_reviews'),
        '별점과 별점 수 중 한쪽만 0이면 이상입니다. Casas Bahia는 별점과 리뷰 수도 비교합니다. '
        'Magalu의 별점·별점 수가 양수이고 리뷰 수가 0인 경우는 허용합니다. 빈값은 0으로 바꾸지 않습니다.'),
    'reviews_require_rating': _spec(
        '리뷰 수가 있는데 별점 정보 없음', ('count_of_reviews', 'star_rating', 'count_of_star_ratings'),
        '리뷰 수가 양수인데 별점 또는 별점 수가 빈값이나 0이면 이상입니다.'),
    'review_count_match': _spec(
        '리뷰 수와 별점 수 일치', ('count_of_reviews', 'count_of_star_ratings'),
        'Casas Bahia의 숫자로 수집된 리뷰 수와 별점 수가 다르면 이상입니다.', ('Casas Bahia',)),
    'review_gt_star_count': _spec(
        '리뷰 수가 별점 수보다 많음', ('count_of_reviews', 'count_of_star_ratings'),
        'Magalu는 리뷰 수와 별점 수가 다를 수 있지만 리뷰 수가 별점 수보다 많으면 이상입니다.', ('Magalu',)),
    'summary_review_disappeared': _spec(
        '상세리뷰는 있으나 요약리뷰 사라짐',
        ('detailed_review_content', 'summarized_review_content'),
        '이전 5일 내 같은 리테일러·상품의 가장 최근 기록에 상세리뷰와 요약리뷰가 모두 있었으나, '
        '현재는 상세리뷰만 있고 요약리뷰가 없으면 확인 필요입니다. 비교 기록이 없으면 판정하지 않습니다.'),
    'recommendation_intent': _spec(
        '추천 의향 형식·범위', ('recommendation_intent', 'count_of_reviews'),
        '추천율 값이 있을 때 NN% recommend this product 형식과 정수 0~100% 범위를 검사합니다. '
        '빈값은 제외하며 리뷰 수와 추천율의 존재 여부를 연결하지 않습니다.',
        ('Casas Bahia',), editable=('recommendation_intent',)),
}


def missing(value):
    return value is None or not str(value).strip()


def number(value, *, count=False):
    text = str(value).strip() if value is not None else ''
    pattern = r'[0-9]+' if count else r'[0-9]+(?:\.[0-9]+)?'
    return Decimal(text) if re.fullmatch(pattern, text) else None


def money(value):
    text = str(value).strip() if value is not None else ''
    if not re.fullmatch(r'R\$\s*(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+),[0-9]{2}', text):
        return None
    return Decimal(text.replace('R$', '').replace('.', '').replace(',', '.').strip())


def body_numbers(value):
    return sorted({int(number) for number in re.findall(
        r'\breview\s*([0-9]+)\s*-', str(value or ''), flags=re.IGNORECASE,
    ) if int(number) > 0})


def recommendation_valid(value):
    if missing(value):
        return True
    match = re.fullmatch(r'([0-9]{1,3})% recommend this product', str(value).strip())
    return bool(match and 0 <= int(match.group(1)) <= 100)


def evaluate_seda_row(row):
    """Return rule -> (severity, issue) without coercing missing/invalid values to zero."""
    retailer = display_seda_retailer(row.get('account_name'))
    if retailer not in SEDA_RETAILERS:
        return {}
    findings = {}

    def add(key, issue=None, level='anomaly'):
        findings[key] = (level, issue or SEDA_RULE_SPECS[key]['detail_name'])

    page = str(row.get('page_type') or '').strip().upper()
    if ((page == 'MAIN' and missing(row.get('main_rank')))
            or (page == 'BSR' and missing(row.get('bsr_rank')))):
        add('rank_page_type')
    original, final = money(row.get('original_sku_price')), money(row.get('final_sku_price'))
    if original is not None and final is not None and original < final:
        add('final_original_price')

    reviews = number(row.get('count_of_reviews'), count=True)
    stars = number(row.get('count_of_star_ratings'), count=True)
    rating = number(row.get('star_rating'))
    if rating is not None and stars is not None and (rating == 0) != (stars == 0):
        add('rating_count_presence')
    if retailer == 'Casas Bahia' and rating is not None and reviews is not None:
        if (rating == 0) != (reviews == 0):
            add('rating_count_presence')
    if reviews is not None and reviews > 0:
        if any(missing(row.get(field)) or value == 0
               for field, value in (('star_rating', rating), ('count_of_star_ratings', stars))):
            add('reviews_require_rating')
    if reviews is not None and stars is not None:
        if retailer == 'Casas Bahia' and reviews != stars:
            add('review_count_match')
        if retailer == 'Magalu' and reviews > stars:
            add('review_gt_star_count')

    body = row.get('detailed_review_content')
    numbers = body_numbers(body)
    if reviews == 0 and not missing(body):
        add('review_zero_body')
    elif reviews is not None and reviews > 0:
        if len(numbers) > reviews:
            add('review_body_over_count')
        elif missing(body):
            add('review_body_count', '리뷰 수 있음 · 리뷰본문 없음', 'review_needed')
        elif not numbers:
            add('review_body_count', '리뷰본문 번호 해석 불가', 'review_needed')
        elif reviews >= 20 and max(numbers) < 20:
            add('review_body_count', 'review20 없음', 'review_needed')
    if retailer == 'Casas Bahia' and not recommendation_valid(row.get('recommendation_intent')):
        add('recommendation_intent')
    return findings
