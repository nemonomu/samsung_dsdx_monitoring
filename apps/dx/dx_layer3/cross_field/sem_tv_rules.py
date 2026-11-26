"""Cross-field rules for the two SEM TV sources, with Layer 2 format guards."""

from decimal import Decimal


RULES = (
    ('mx_tv_savings_amount_match', '할인금액 일치', 'savings', 'original_sku_price',
     '같은 상품의 유효한 MXN 원가·최종가·절감액이 있을 때 원가 − 최종가와 절감액을 비교합니다.'),
    ('mx_tv_price_order', '가격 순서·할인율 확인', 'final_sku_price', 'original_sku_price',
     '최종가가 할인 전 가격을 초과하거나 양수 절감액이 있는데 두 가격이 같으면 이상입니다. '
     '절감액이 비어 있는 동일가와 계산 할인율 90% 이상은 원문 확인이 필요합니다.'),
    ('mx_tv_final_missing', '할인 정보가 있는데 최종가 누락', 'final_sku_price', 'original_sku_price',
     '유효한 할인 전 가격 또는 절감액이 있는데 최종가가 비어 있으면 이상입니다.'),
    ('mx_tv_original_missing', '절감액이 있는데 할인 전 가격 누락', 'original_sku_price', 'savings',
     '최종가와 절감액은 유효하지만 할인 전 가격이 비어 있으면 원문 확인이 필요합니다.'),
    ('mx_tv_savings_missing', '할인 가격이 있는데 절감액 누락', 'savings', 'original_sku_price',
     '최종가가 할인 전 가격보다 낮고 절감액이 비어 있으면 원문 확인이 필요합니다.'),
    ('mx_tv_rating_count', '별점과 평가 수의 0 여부', 'star_rating', 'count_of_star_ratings',
     '평균 별점과 평가 수의 0 여부가 다르거나 한쪽만 양수로 제공되면 원문과 수집기의 기본값을 확인합니다.'),
    ('mx_tv_written_review_count', '작성 리뷰 수와 전체 평가 수', 'count_of_reviews', 'count_of_star_ratings',
     '작성 리뷰 수가 전체 평가 수를 초과하면 두 값이 같은 상품의 같은 리뷰 범위를 가리키는지 확인합니다.'),
    ('mx_tv_rank_presence', '수집 목록 순위 누락', 'main_rank', 'bsr_rank',
     '수집된 상품에는 MAIN 또는 BSR 순위가 하나 이상 있어야 합니다.'),
)
RULE_KEYS = frozenset(rule[0] for rule in RULES)
PRICE_RULE_KEYS = frozenset(rule[0] for rule in RULES[:5])
WALMART_ONLY = frozenset(rule[0] for rule in RULES[5:])


def _blank(value):
    return value is None or str(value).strip() == ''


def evaluate(row, retailer, checks):
    """Return verdicts only for rules whose input data supports comparison."""
    def amount(field):
        value = row.get(field)
        if not _blank(value) and checks[field](value):
            return Decimal(str(value).strip().replace('$', '').replace(',', ''))
        return None

    final = amount('final_sku_price')
    original = amount('original_sku_price')
    savings = amount('savings')
    verdicts = {}
    if original is not None or savings is not None:
        if _blank(row.get('final_sku_price')):
            verdicts['mx_tv_final_missing'] = 'anomaly'
        elif final is not None:
            verdicts['mx_tv_final_missing'] = 'ok'

    if final is not None and savings is not None:
        if _blank(row.get('original_sku_price')):
            verdicts['mx_tv_original_missing'] = 'review_needed'
        elif original is not None:
            verdicts['mx_tv_original_missing'] = 'ok'

    if final is not None and original is not None:
        difference = original - final
        if difference < 0 or (difference == 0 and savings is not None):
            verdicts['mx_tv_price_order'] = 'anomaly'
        elif ((difference == 0 and _blank(row.get('savings')))
              or difference * 10 >= original * 9):
            verdicts['mx_tv_price_order'] = 'review_needed'
        elif difference > 0:
            verdicts['mx_tv_price_order'] = 'ok'
        if difference > 0:
            if _blank(row.get('savings')):
                verdicts['mx_tv_savings_missing'] = 'review_needed'
            elif savings is not None:
                verdicts['mx_tv_savings_missing'] = 'ok'
                verdicts['mx_tv_savings_amount_match'] = 'ok' if difference == savings else 'anomaly'

    if retailer == 'Walmart':
        rating = amount('star_rating')
        evaluations = amount('count_of_star_ratings')
        written = amount('count_of_reviews')
        if rating is not None and evaluations is not None:
            verdicts['mx_tv_rating_count'] = 'ok' if (rating == 0) == (evaluations == 0) else 'review_needed'
        elif ((rating and _blank(row.get('count_of_star_ratings')))
              or (evaluations and _blank(row.get('star_rating')))):
            verdicts['mx_tv_rating_count'] = 'review_needed'
        if written is not None and evaluations is not None:
            verdicts['mx_tv_written_review_count'] = 'ok' if written <= evaluations else 'review_needed'
        ranks = [row.get('main_rank'), row.get('bsr_rank')]
        if all(_blank(value) for value in ranks):
            verdicts['mx_tv_rank_presence'] = 'anomaly'
        elif any(not _blank(value) and checks[field](value)
                 for field, value in zip(('main_rank', 'bsr_rank'), ranks)):
            verdicts['mx_tv_rank_presence'] = 'ok'
    return verdicts
