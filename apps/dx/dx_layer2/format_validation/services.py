"""
형식 검증 서비스 — 순수 비즈니스 로직 (DB 커넥션/HTTP 무관)
"""

from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from apps.common.retail_columns import (
    validate_field,
    build_format_error_sql,
    build_per_field_error_sql,
    get_editable_columns,
)
from apps.common.db import dx_table
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.common.retail_validation import get_tv_validation_condition
from apps.dx.dx_layer2.common.context import get_status

try:
    from apps.common.retail_columns import get_tse_retailer_columns
    from apps.common.tse_retail import (
        TSE_COUNTRY,
        TSE_SOURCE_CONFIG,
        get_tse_editable_columns,
    )
except ImportError:  # Backward-compatible fallback for isolated legacy tests.
    get_tse_retailer_columns = None
    TSE_COUNTRY = 'TSE'
    TSE_SOURCE_CONFIG = {}
    get_tse_editable_columns = None

try:
    from apps.common.tse_retail import (
        get_tse_format_fields,
        tse_retailer_include_unassigned,
        tse_retailer_supports_column,
    )
except (ImportError, AttributeError):
    def get_tse_format_fields(_product_line, _retailer):
        return TSE_FORMAT_FIELDS

    def tse_retailer_include_unassigned(_retailer):
        return False

    def tse_retailer_supports_column(_product_line, _retailer, _column):
        return True

try:
    from apps.common.inspection_dates import resolve_monitoring_date
    from apps.common.sea_retail import SEA_RETAIL_SOURCES
except (ImportError, AttributeError):
    resolve_monitoring_date = None
    SEA_RETAIL_SOURCES = {}

try:
    from apps.common.siel_retail import (
        SIEL_BUSINESS_TIMEZONE,
        SIEL_SOURCE_CONFIG,
    )
except (ImportError, AttributeError):
    SIEL_BUSINESS_TIMEZONE = 'Asia/Seoul'
    SIEL_SOURCE_CONFIG = {}


SEA_FORMAT_SECTION_BY_PRODUCT = {
    'ref': 'sea_ref_retail',
    'ldy': 'sea_ldy_retail',
}
SEA_FORMAT_PRODUCT_BY_SECTION = {
    section_code: product_key
    for product_key, section_code in SEA_FORMAT_SECTION_BY_PRODUCT.items()
}
SEA_FORMAT_COMMON_FIELDS = (
    'item', 'account_name', 'country', 'product', 'page_type',
    'product_url', 'count_of_reviews', 'count_of_star_ratings',
    'star_rating', 'final_sku_price', 'original_sku_price', 'savings',
    'detailed_review_content', 'calendar_week',
)
SEA_FORMAT_EXTRA_FIELDS = {
    'ref': ('ref_capacity',),
    'ldy': ('ldy_capacity', 'ldy_loading_type'),
}

SIEL_FORMAT_SECTION_BY_SOURCE = {
    source_key: f'{source_key}_retail'
    for source_key in SIEL_SOURCE_CONFIG
}
SIEL_FORMAT_SOURCE_BY_SECTION = {
    section_code: source_key
    for source_key, section_code in SIEL_FORMAT_SECTION_BY_SOURCE.items()
}
SIEL_FORMAT_COMMON_FIELDS = (
    'account_name', 'calendar_week', 'country',
    'detailed_review_content', 'original_sku_price', 'page_type',
    'product', 'product_url', 'star_rating',
)
SIEL_FORMAT_FIELDS = {
    'siel_tv': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'screen_size',
            'estimated_annual_electricity_use', 'model_year',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'screen_size',
            'estimated_annual_electricity_use', 'model_year',
        ),
    },
    'siel_ref': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'ref_capacity',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'ref_capacity',
            'ref_refrigerator_type',
        ),
    },
    'siel_ldy': {
        'amazon': (
            'final_sku_price', 'count_of_star_ratings', 'ldy_capacity',
        ),
        'flipkart': (
            'final_sku_price', 'count_of_reviews',
            'count_of_star_ratings', 'ldy_capacity',
        ),
    },
}


def _sea_format_section_codes():
    return {
        section_code
        for product_key, section_code in SEA_FORMAT_SECTION_BY_PRODUCT.items()
        if SEA_RETAIL_SOURCES.get(product_key)
    }


def _sea_format_rule_tables():
    return {
        str(SEA_RETAIL_SOURCES[product_key]['table_name']).split('.')[-1]
        for product_key in SEA_FORMAT_SECTION_BY_PRODUCT
        if SEA_RETAIL_SOURCES.get(product_key)
    }


def _siel_format_section_codes():
    return {
        section_code
        for source_key, section_code in SIEL_FORMAT_SECTION_BY_SOURCE.items()
        if SIEL_SOURCE_CONFIG.get(source_key)
    }


# table 파라미터 화이트리스트
VALID_TABLES_FORMAT = {
    'tv_retail',
    'market',
} | _sea_format_section_codes() | _siel_format_section_codes() | {
    source['section_code'] for source in TSE_SOURCE_CONFIG.values()
}
VALID_TABLES_RULES = {
    'tv_retail_com',
    'market_trend', 'market_comp_product', 'market_comp_event',
    'openai_forecast_results',
} | _sea_format_rule_tables() | set(SIEL_SOURCE_CONFIG) | set(TSE_SOURCE_CONFIG)
VALID_TABLES_RULES -= DISABLED_SOURCE_TABLES


TSE_FORMAT_FIELDS = (
    'final_sku_price',
    'original_sku_price',
    'savings',
    'count_of_reviews',
    'count_of_star_ratings',
    'star_rating',
)

TSE_FORMAT_RULES = (
    {
        'field': 'final_sku_price',
        'description': '태국 바트 금액 또는 품절 표시',
        'pattern': '฿10,820, ฿10,820.00 또는 สินค้าหมด',
    },
    {
        'field': 'original_sku_price',
        'description': '값이 있으면 태국 바트 금액 형식',
        'pattern': '฿13,820 또는 ฿13,820.00',
    },
    {
        'field': 'savings',
        'description': '값이 있으면 할인금액과 음수 할인율 형식',
        'pattern': '฿3,000 (-3%) 또는 ฿9 (-0%)',
    },
    {
        'field': 'original_sku_price / savings',
        'description': '할인정보가 있으면 원가가 있어야 함',
        'pattern': 'savings 있음 → original_sku_price 있음',
    },
    {
        'field': 'count_of_reviews',
        'description': '0 이상의 정수',
        'pattern': '0, 128, 1,234',
    },
    {
        'field': 'count_of_star_ratings',
        'description': '0 이상의 정수',
        'pattern': '0, 128, 1,234',
    },
    {
        'field': 'star_rating',
        'description': '0~5 범위, 소수점 한 자리까지',
        'pattern': '0, 4.5, 5.0',
    },
)

TSE_LOTUSS_FORMAT_RULES = {
    'item': {
        'field': 'item',
        'description': 'Lotuss 8자리 상품번호',
        'pattern': '50173824',
    },
    'product_url': {
        'field': 'product_url',
        'description': 'Lotuss 상품 상세 URL',
        'pattern': 'https://www.lotuss.com/th/product/{상품 slug 또는 번호}',
    },
    'final_sku_price': {
        'field': 'final_sku_price',
        'description': '태국 바트 금액 또는 영문 품절 표시',
        'pattern': '฿10,820, ฿10,820.00 또는 Out of stock',
    },
    'original_sku_price': {
        'field': 'original_sku_price',
        'description': '값이 있으면 태국 바트 금액 형식',
        'pattern': '฿13,820 또는 ฿13,820.00',
    },
    'savings': {
        'field': 'savings',
        'description': '값이 있으면 음수 할인율 형식',
        'pattern': '-57%',
    },
    'screen_size': {
        'field': 'screen_size',
        'description': '숫자와 inch 형식',
        'pattern': '32 inch',
    },
    'ref_capacity': {
        'field': 'ref_capacity',
        'description': '숫자와 cu ft, l 또는 liter 단위',
        'pattern': '7.5 cu ft, 300 l 또는 300 liter',
    },
    'ref_refrigerator_type': {
        'field': 'ref_refrigerator_type',
        'description': '값이 있을 때 냉장고 타입 표준값',
        'pattern': 'Freezer-on-Top (Top Mount), Side-by-Side 등',
    },
    'ldy_capacity': {
        'field': 'ldy_capacity',
        'description': '숫자와 kg 형식',
        'pattern': '10 kg',
    },
    'ldy_loading_type': {
        'field': 'ldy_loading_type',
        'description': '값이 있을 때 세탁기 로딩 타입 표준값',
        'pattern': 'Front Load, Top Load 또는 Twin Tub',
    },
}

TSE_LAZADA_FORMAT_RULES = {
    'product_url': {
        'field': 'product_url',
        'description': 'Lazada Thailand product URL',
        'pattern': 'https://www.lazada.co.th/products/...',
    },
    'final_sku_price': {
        'field': 'final_sku_price',
        'description': 'Thai baht price with optional 1-2 decimals',
        'pattern': '\u0e3f1,299 / \u0e3f1,299.9 / \u0e3f1,299.00',
    },
    'original_sku_price': {
        'field': 'original_sku_price',
        'description': 'Optional Thai baht original price',
        'pattern': '\u0e3f1,299 / \u0e3f1,299.9 / \u0e3f1,299.00',
    },
    'savings': {
        'field': 'savings',
        'description': 'Optional Lazada discount percentage',
        'pattern': '-54%',
    },
    'count_of_reviews': dict(next(
        rule for rule in TSE_FORMAT_RULES
        if rule['field'] == 'count_of_reviews'
    )),
    'count_of_star_ratings': dict(next(
        rule for rule in TSE_FORMAT_RULES
        if rule['field'] == 'count_of_star_ratings'
    )),
    'star_rating': dict(next(
        rule for rule in TSE_FORMAT_RULES
        if rule['field'] == 'star_rating'
    )),
    'screen_size': {
        'field': 'screen_size',
        'description': 'Numeric screen size in inches',
        'pattern': '32 inch',
    },
    'ref_capacity': {
        'field': 'ref_capacity',
        'description': 'Refrigerator capacity in cu ft or liters',
        'pattern': '7.3 cu ft / 113 L',
    },
    'ref_refrigerator_type': {
        'field': 'ref_refrigerator_type',
        'description': 'Known Lazada refrigerator type when present',
        'pattern': 'Freezer / Multi Door / Side-by-Side / French Door',
    },
    'ldy_capacity': {
        'field': 'ldy_capacity',
        'description': 'Laundry capacity in kilograms or liters',
        'pattern': '10 kg / 8.5 L',
    },
    'ldy_loading_type': {
        'field': 'ldy_loading_type',
        'description': 'Known Lazada loading type when present',
        'pattern': 'Front Load / Top Load',
    },
}

_TSE_MONEY_PATTERN = re.compile(
    r'^฿(?:0|[1-9]\d{0,2}(?:,\d{3})*)(?:\.\d{2})?$'
)
_TSE_SAVINGS_PATTERN = re.compile(
    r'^฿(?:0|[1-9]\d{0,2}(?:,\d{3})*)(?:\.\d{2})? '
    r'\(-(?:100|[1-9]?\d)%\)$'
)
_TSE_COUNT_PATTERN = re.compile(
    r'^(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)$'
)
_TSE_RATING_PATTERN = re.compile(r'^(?:[0-4](?:\.\d)?|5(?:\.0)?)$')
_TSE_OUT_OF_STOCK_VALUES = frozenset({'สินค้าหมด'})
_TSE_LOTUSS_OUT_OF_STOCK_VALUE = 'Out of stock'
_TSE_LOTUSS_SAVINGS_PATTERN = re.compile(
    r'^-(?:100|[1-9]?\d)%$'
)
_TSE_LOTUSS_ITEM_PATTERN = re.compile(r'^\d{8}$')
_TSE_LOTUSS_PRODUCT_URL_PATTERN = re.compile(
    r'^https://www\.lotuss\.com/(?:th|en)/product/'
    r'[^\s/?#]+/?(?:[?#][^\s]*)?$'
)
_TSE_LAZADA_MONEY_PATTERN = re.compile(
    r'^\u0e3f(?:0|[1-9]\d{0,2}(?:,\d{3})*)(?:\.\d{1,2})?$'
)
_TSE_LAZADA_SAVINGS_PATTERN = re.compile(r'^-(?:100|[1-9]?\d)%$')
_TSE_LAZADA_PRODUCT_URL_PATTERN = re.compile(
    r'^https://www\.lazada\.co\.th/products/[^\s?#]+(?:[?#][^\s]*)?$'
)
_TSE_SCREEN_SIZE_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s+inch$', re.IGNORECASE
)
_TSE_REF_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*(?:cu\s+ft|l|liter)$', re.IGNORECASE
)
_TSE_LDY_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*kg$', re.IGNORECASE
)
_TSE_LAZADA_LDY_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*(?:kg|l|liter)$', re.IGNORECASE
)
_TSE_REF_TYPE_VALUES = frozenset({
    'freezer-on-top (top mount)',
    'side-by-side',
    'single door',
    'bottom freezer',
    'french door',
})
_TSE_LDY_LOADING_TYPE_VALUES = frozenset({
    'front load', 'top load', 'twin tub',
})
_TSE_LAZADA_REF_TYPE_VALUES = frozenset({
    'freezer', 'multi door', 'side-by-side', 'french door',
    'freezer-on-bottom (bottom mount)',
})


_SIEL_MONEY_PATTERN = re.compile(
    r'^₹(?:0|[1-9]\d{0,2}(?:,\d{3})*)(?:\.\d{1,2})?$'
)
_SIEL_COUNT_PATTERN = re.compile(
    r'^(?:0|[1-9]\d{0,2}|[1-9]\d{0,2}(?:,\d{3})+)$'
)
_SIEL_CALENDAR_WEEK_PATTERN = re.compile(
    r'^w(?:[1-9]|[1-4]\d|5[0-3])$'
)
_SIEL_STAR_RATING_PATTERN = re.compile(r'^\d+(?:\.\d)?$')
_SIEL_AMAZON_PRICE_STATUS_VALUES = frozenset({
    'Currently unavailable.',
    'No featured offers available',
})
_SIEL_AMAZON_STAR_STATUS_VALUES = frozenset({'No customer reviews'})
_SIEL_PAGE_TYPE_VALUES = frozenset({'main', 'bsr'})
_SIEL_AMAZON_PRODUCT_URL_PATTERN = re.compile(
    r'^https://www\.amazon\.in/dp/[a-z0-9]{10}(?:[/?#][^\s]*)?$',
    re.IGNORECASE,
)
_SIEL_FLIPKART_PRODUCT_URL_PATTERN = re.compile(
    r'^https://www\.flipkart\.com/[^\s?#]+/p/[^\s/?#]+'
    r'(?:\?[^\s#]*)?(?:#[^\s]*)?$',
    re.IGNORECASE,
)
_SIEL_AMAZON_SCREEN_SIZE_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s+inch(?:es)?$', re.IGNORECASE
)
_SIEL_FLIPKART_SCREEN_SIZE_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*cm\s*\('
    r'\d+(?:\.\d+)?\s*inch(?:es)?\)$',
    re.IGNORECASE,
)
_SIEL_REF_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*(?:l|liters?|litres?|cubic\s+feet?)$',
    re.IGNORECASE,
)
_SIEL_AMAZON_LDY_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*(?:kg|g|l)$', re.IGNORECASE
)
_SIEL_FLIPKART_LDY_CAPACITY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*kg$', re.IGNORECASE
)
_SIEL_AMAZON_ENERGY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s+(?:Watts|Kilowatts|Kilowatt Hours)'
    r'(?: Per Year)?$',
    re.IGNORECASE,
)
_SIEL_FLIPKART_ENERGY_PATTERN = re.compile(
    r'^\d+(?:\.\d+)?\s*W'
    r'(?:,\s*\d+(?:\.\d+)?\s*W)?'
    r'(?:\s*\(Standby\))?$',
    re.IGNORECASE,
)
_SIEL_MODEL_YEAR_PATTERN = re.compile(r'^20\d{2}$')
_SIEL_FLIPKART_REF_TYPE_VALUES = frozenset({
    'bottom freezer',
    'bottom freezer refrigerator',
    'bottom mount',
    'compact',
    'compact refrigerator',
    'drawer refrigerator',
    'french door refrigerator',
    'multi-door refrigerator',
    'side by side',
    'side by side refrigerator',
    'top freezer',
    'top freezer refrigerator',
    'top mount',
})

SIEL_FORMAT_RULE_DETAILS = {
    'account_name': {
        'field': 'account_name',
        'description': '선택한 SIEL 리테일러명과 일치',
        'pattern': 'Amazon 또는 Flipkart',
    },
    'calendar_week': {
        'field': 'calendar_week',
        'description': '소문자 w와 1~53 범위의 주차',
        'pattern': 'w28, w33',
    },
    'country': {
        'field': 'country',
        'description': 'SIEL 국가 코드',
        'pattern': 'SIEL',
    },
    'detailed_review_content': {
        'field': 'detailed_review_content',
        'description': '리뷰본문은 "review1 - "로 시작',
        'pattern': 'review1 - ...',
    },
    'original_sku_price': {
        'field': 'original_sku_price',
        'description': '인도 루피 원가 형식',
        'pattern': '₹10,999',
    },
    'page_type': {
        'field': 'page_type',
        'description': 'SIEL 수집 페이지 구분',
        'pattern': 'main, bsr',
    },
    'product': {
        'field': 'product',
        'description': '선택한 SIEL 제품군과 일치',
        'pattern': 'TV, REF, LDY',
    },
    'product_url': {
        'field': 'product_url',
        'description': '리테일러별 SIEL 상품 상세 URL',
        'pattern': 'Amazon /dp/{ASIN}, Flipkart /p/{상품키}',
    },
    'star_rating': {
        'field': 'star_rating',
        'description': '숫자 평점 또는 허용된 평가 없음 문구',
        'pattern': 'Amazon: 4.3, No customer reviews / Flipkart: 4.3',
    },
    'final_sku_price': {
        'field': 'final_sku_price',
        'description': '인도 루피 금액 형식',
        'pattern': '₹10,999',
    },
    'count_of_reviews': {
        'field': 'count_of_reviews',
        'description': '0 이상의 정수와 올바른 천 단위 쉼표',
        'pattern': '0, 128, 1,234',
    },
    'count_of_star_ratings': {
        'field': 'count_of_star_ratings',
        'description': '0 이상의 정수와 올바른 천 단위 쉼표',
        'pattern': '0, 128, 1,234',
    },
    'screen_size': {
        'field': 'screen_size',
        'description': '리테일러별 화면 크기 형식',
        'pattern': 'Amazon: 43 Inches / Flipkart: 109 cm (43 inch)',
    },
    'estimated_annual_electricity_use': {
        'field': 'estimated_annual_electricity_use',
        'description': '리테일러별 전력·연간 전력량 형식',
        'pattern': (
            'Amazon: 164.25 Kilowatt Hours, 141 Kilowatts / '
            'Flipkart: 100 W, 0.5 W (Standby)'
        ),
    },
    'model_year': {
        'field': 'model_year',
        'description': '20으로 시작하는 4자리 연도',
        'pattern': '2025, 2026',
    },
    'ref_capacity': {
        'field': 'ref_capacity',
        'description': '숫자와 L/Liter/Litre 또는 cubic foot/feet 단위',
        'pattern': '192 L, 300 Liters, 3.3 cubic feet',
    },
    'ref_refrigerator_type': {
        'field': 'ref_refrigerator_type',
        'description': 'Flipkart 냉장고 타입 표준값',
        'pattern': 'Top Mount, Side by Side, Multi-Door Refrigerator 등',
    },
    'ldy_capacity': {
        'field': 'ldy_capacity',
        'description': '리테일러별 세탁 용량 형식',
        'pattern': 'Amazon: 8 kg, 800 g, 11 L / Flipkart: 8 kg',
    },
}


def _has_tse_format_value(value):
    return value is not None and str(value).strip() != ''


def _has_tse_optional_value(value):
    if not _has_tse_format_value(value):
        return False
    return str(value).strip().casefold() not in {'-', 'none', 'null', 'n/a'}


def _infer_tse_format_product_line(row, product_line):
    value = str(product_line or '').strip().lower()
    if value in TSE_SOURCE_CONFIG:
        return value
    if any(key in row for key in ('ref_capacity', 'ref_refrigerator_type')):
        return 'tse_ref'
    if any(key in row for key in ('ldy_capacity', 'ldy_loading_type')):
        return 'tse_ldy'
    return 'tse_tv'


def _evaluate_lotuss_format_row(row, product_line):
    """Return Lotuss-only format errors for one product row."""
    errors = {}

    item = row.get('item')
    if (
        _has_tse_format_value(item)
        and not _TSE_LOTUSS_ITEM_PATTERN.fullmatch(str(item).strip())
    ):
        errors['item'] = '8자리 숫자 상품번호가 아닙니다.'

    product_url = row.get('product_url')
    if (
        _has_tse_format_value(product_url)
        and not _TSE_LOTUSS_PRODUCT_URL_PATTERN.fullmatch(
            str(product_url).strip()
        )
    ):
        errors['product_url'] = 'Lotuss 상품 상세 URL 형식이 아닙니다.'

    final_price = row.get('final_sku_price')
    if _has_tse_format_value(final_price):
        normalized = str(final_price).strip()
        if (
            normalized != _TSE_LOTUSS_OUT_OF_STOCK_VALUE
            and not _TSE_MONEY_PATTERN.fullmatch(normalized)
        ):
            errors['final_sku_price'] = (
                '฿10,820 금액 또는 Out of stock 품절 표시가 아닙니다.'
            )

    if product_line == 'tse_tv':
        original_price = row.get('original_sku_price')
        savings = row.get('savings')
        original_present = _has_tse_optional_value(original_price)
        savings_present = _has_tse_optional_value(savings)
        if original_present and not _TSE_MONEY_PATTERN.fullmatch(
            str(original_price).strip()
        ):
            errors['original_sku_price'] = '฿13,820 형식이 아닙니다.'
        if savings_present and not _TSE_LOTUSS_SAVINGS_PATTERN.fullmatch(
            str(savings).strip()
        ):
            errors['savings'] = '-57% 형식이 아닙니다.'
        screen_size = row.get('screen_size')
        if (
            _has_tse_format_value(screen_size)
            and not _TSE_SCREEN_SIZE_PATTERN.fullmatch(
                str(screen_size).strip()
            )
        ):
            errors['screen_size'] = '32 inch 형식이 아닙니다.'

    elif product_line == 'tse_ref':
        capacity = row.get('ref_capacity')
        if (
            _has_tse_format_value(capacity)
            and not _TSE_REF_CAPACITY_PATTERN.fullmatch(
                str(capacity).strip()
            )
        ):
            errors['ref_capacity'] = (
                '숫자와 cu ft, l 또는 liter 단위 형식이 아닙니다.'
            )
        refrigerator_type = row.get('ref_refrigerator_type')
        if (
            _has_tse_format_value(refrigerator_type)
            and str(refrigerator_type).strip().casefold()
            not in _TSE_REF_TYPE_VALUES
        ):
            errors['ref_refrigerator_type'] = (
                '허용된 냉장고 타입이 아닙니다.'
            )

    elif product_line == 'tse_ldy':
        capacity = row.get('ldy_capacity')
        if (
            _has_tse_format_value(capacity)
            and not _TSE_LDY_CAPACITY_PATTERN.fullmatch(
                str(capacity).strip()
            )
        ):
            errors['ldy_capacity'] = '숫자와 kg 단위 형식이 아닙니다.'
        loading_type = row.get('ldy_loading_type')
        if (
            _has_tse_format_value(loading_type)
            and str(loading_type).strip().casefold()
            not in _TSE_LDY_LOADING_TYPE_VALUES
        ):
            errors['ldy_loading_type'] = (
                'Front Load, Top Load 또는 Twin Tub 값이 아닙니다.'
            )

    return errors


def _evaluate_lazada_format_row(row, product_line):
    """Return Lazada-specific format errors derived from the CSV feed."""
    errors = {}

    product_url = row.get('product_url')
    if (
        _has_tse_format_value(product_url)
        and not _TSE_LAZADA_PRODUCT_URL_PATTERN.fullmatch(
            str(product_url).strip()
        )
    ):
        errors['product_url'] = 'Invalid Lazada Thailand product URL.'

    final_price = row.get('final_sku_price')
    if (
        _has_tse_format_value(final_price)
        and not _TSE_LAZADA_MONEY_PATTERN.fullmatch(
            str(final_price).strip()
        )
    ):
        errors['final_sku_price'] = 'Invalid Lazada Thai baht price.'

    original_price = row.get('original_sku_price')
    savings = row.get('savings')
    original_present = _has_tse_optional_value(original_price)
    savings_present = _has_tse_optional_value(savings)
    if (
        original_present
        and not _TSE_LAZADA_MONEY_PATTERN.fullmatch(
            str(original_price).strip()
        )
    ):
        errors['original_sku_price'] = 'Invalid Lazada original price.'
    if (
        savings_present
        and not _TSE_LAZADA_SAVINGS_PATTERN.fullmatch(str(savings).strip())
    ):
        errors['savings'] = 'Invalid Lazada discount percentage.'
    if savings_present and not original_present:
        errors['original_sku_price'] = (
            'original_sku_price is required when savings is present.'
        )

    for field in ('count_of_reviews', 'count_of_star_ratings'):
        value = row.get(field)
        if (
            _has_tse_format_value(value)
            and not _TSE_COUNT_PATTERN.fullmatch(str(value).strip())
        ):
            errors[field] = 'Review counts must be non-negative integers.'

    rating = row.get('star_rating')
    if (
        _has_tse_format_value(rating)
        and not _TSE_RATING_PATTERN.fullmatch(str(rating).strip())
    ):
        errors['star_rating'] = 'star_rating must be between 0 and 5.'

    if product_line == 'tse_tv':
        screen_size = row.get('screen_size')
        if (
            _has_tse_format_value(screen_size)
            and not _TSE_SCREEN_SIZE_PATTERN.fullmatch(
                str(screen_size).strip()
            )
        ):
            errors['screen_size'] = 'Invalid Lazada screen size.'
    elif product_line == 'tse_ref':
        capacity = row.get('ref_capacity')
        if (
            _has_tse_format_value(capacity)
            and not _TSE_REF_CAPACITY_PATTERN.fullmatch(str(capacity).strip())
        ):
            errors['ref_capacity'] = 'Invalid Lazada refrigerator capacity.'
        refrigerator_type = row.get('ref_refrigerator_type')
        if (
            _has_tse_format_value(refrigerator_type)
            and str(refrigerator_type).strip().casefold()
            not in _TSE_LAZADA_REF_TYPE_VALUES
        ):
            errors['ref_refrigerator_type'] = (
                'Invalid Lazada refrigerator type.'
            )
    elif product_line == 'tse_ldy':
        capacity = row.get('ldy_capacity')
        if (
            _has_tse_format_value(capacity)
            and not _TSE_LAZADA_LDY_CAPACITY_PATTERN.fullmatch(
                str(capacity).strip()
            )
        ):
            errors['ldy_capacity'] = 'Invalid Lazada laundry capacity.'
        loading_type = row.get('ldy_loading_type')
        if (
            _has_tse_format_value(loading_type)
            and str(loading_type).strip().casefold()
            not in _TSE_LDY_LOADING_TYPE_VALUES
        ):
            errors['ldy_loading_type'] = 'Invalid Lazada loading type.'

    return errors


def evaluate_tse_format_row(row, product_line=None, retailer=None):
    """Return field-keyed TSE format errors without NULL-rule overlap."""
    retailer_key = str(
        retailer if retailer is not None else row.get('account_name') or ''
    ).strip().casefold()
    resolved_product_line = _infer_tse_format_product_line(
        row, product_line
    )
    if retailer_key == 'lotuss':
        return _evaluate_lotuss_format_row(row, resolved_product_line)
    if retailer_key == 'lazada':
        return _evaluate_lazada_format_row(row, resolved_product_line)

    errors = {}
    final_price = row.get('final_sku_price')
    original_price = row.get('original_sku_price')
    savings = row.get('savings')
    original_present = _has_tse_optional_value(original_price)
    savings_present = _has_tse_optional_value(savings)

    if _has_tse_format_value(final_price):
        normalized_final_price = str(final_price).strip()
        if (
            normalized_final_price not in _TSE_OUT_OF_STOCK_VALUES
            and not _TSE_MONEY_PATTERN.fullmatch(normalized_final_price)
        ):
            errors['final_sku_price'] = (
                '฿10,820 금액 또는 สินค้าหมด 품절 표시가 아닙니다.'
            )
    if original_present and not _TSE_MONEY_PATTERN.fullmatch(
        str(original_price).strip()
    ):
        errors['original_sku_price'] = '฿13,820 형식이 아닙니다.'
    if (
        retailer_key != 'powerbuy'
        and savings_present
        and not _TSE_SAVINGS_PATTERN.fullmatch(
            str(savings).strip()
        )
    ):
        errors['savings'] = '฿3,000 (-3%) 형식이 아닙니다.'

    if savings_present and not original_present:
        errors['original_sku_price'] = 'savings가 있으면 original_sku_price도 필요합니다.'

    for field in ('count_of_reviews', 'count_of_star_ratings'):
        value = row.get(field)
        if _has_tse_format_value(value) and not _TSE_COUNT_PATTERN.fullmatch(
            str(value).strip()
        ):
            errors[field] = '0 이상의 정수 형식이 아닙니다.'

    rating = row.get('star_rating')
    if _has_tse_format_value(rating) and not _TSE_RATING_PATTERN.fullmatch(
        str(rating).strip()
    ):
        errors['star_rating'] = '0~5 범위의 숫자 형식이 아닙니다.'
    return errors


def _tse_format_product_line(table):
    value = str(table or '').strip().lower()
    for product_line, source in TSE_SOURCE_CONFIG.items():
        if value in (product_line, source['section_code'].lower()):
            return product_line
    return None


def _resolve_tse_format_retailer(product_line, retailer):
    if not get_tse_retailer_columns:
        return None
    configs = get_tse_retailer_columns(product_line)
    retailer_key = str(retailer or '').strip().casefold()
    if not retailer_key:
        unassigned_configs = [
            (display_name, config)
            for display_name, config in configs.items()
            if tse_retailer_include_unassigned(
                config.get('retailer') or display_name
            )
        ]
        if len(unassigned_configs) == 1:
            return unassigned_configs[0]
    for display_name, config in configs.items():
        if retailer_key in {
            str(display_name).strip().casefold(),
            str(config.get('retailer') or '').strip().casefold(),
        }:
            return display_name, config
    return None


def _safe_tse_format_editable_columns(product_line, retailer_config):
    if not get_tse_editable_columns:
        return []
    allowed = set(get_tse_editable_columns(product_line))
    return [
        column for column in retailer_config.get('editable_columns', [])
        if column in allowed and tse_retailer_supports_column(
            product_line, retailer_config.get('retailer'), column
        )
    ]


def _sea_format_product_key(table):
    value = str(table or '').strip().lower()
    if value in SEA_FORMAT_PRODUCT_BY_SECTION:
        return SEA_FORMAT_PRODUCT_BY_SECTION[value]
    for product_key, source in SEA_RETAIL_SOURCES.items():
        if product_key not in SEA_FORMAT_SECTION_BY_PRODUCT:
            continue
        table_name = str(source.get('table_name') or '').strip().lower()
        if value in {
            product_key,
            str(source.get('key') or '').strip().lower(),
            table_name,
            table_name.split('.')[-1],
        }:
            return product_key
    return None


def _resolve_sea_format_retailer(source, retailer):
    retailer_key = str(retailer or '').strip().casefold()
    for configured in source.get('retailers', ()):
        if retailer_key == str(configured).strip().casefold():
            return configured
    return None


def _get_sea_format_fields(product_key):
    return tuple(dict.fromkeys(
        SEA_FORMAT_COMMON_FIELDS + SEA_FORMAT_EXTRA_FIELDS.get(
            product_key, ()
        )
    ))


def _fetch_sea_format_rows(
        cursor, start_date, end_date, source, retailer_value):
    """Fetch each day's latest SEA MAIN-anchored appliance batch."""
    canonical_table = source['table_name']
    date_column = source['date_column']
    product_key = source['product_key']
    format_fields = _get_sea_format_fields(product_key)
    select_columns = list(dict.fromkeys((
        'id', 'batch_id', 'country', 'product', 'account_name', 'page_type',
        'item', 'sku', 'retailer_sku_name', *format_fields,
        date_column, 'product_url',
    )))
    source_date_sql = (
        f"LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10)"
    )
    cursor.execute(f"""
        WITH latest_batches AS (
            SELECT DISTINCT ON ({source_date_sql})
                   {source_date_sql} AS crawl_date,
                   source.batch_id,
                   source.id
            FROM {canonical_table} source
            WHERE {source_date_sql} >= %s
              AND {source_date_sql} <= %s
              AND LOWER(TRIM(source.account_name)) = LOWER(TRIM(%s))
              AND UPPER(TRIM(COALESCE(source.page_type, ''))) = 'MAIN'
            ORDER BY crawl_date, source.id DESC
        )
        SELECT {', '.join('source.' + column for column in select_columns)}
        FROM {canonical_table} source
        JOIN latest_batches latest
          ON {source_date_sql} = latest.crawl_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE {source_date_sql} >= %s
          AND {source_date_sql} <= %s
          AND (
              LOWER(TRIM(source.account_name)) = LOWER(TRIM(%s))
              OR source.account_name IS NULL
              OR TRIM(CAST(source.account_name AS TEXT)) = ''
          )
          AND (
              UPPER(TRIM(COALESCE(source.country, ''))) = 'SEA'
              OR source.country IS NULL
              OR TRIM(CAST(source.country AS TEXT)) = ''
          )
          AND UPPER(TRIM(COALESCE(source.page_type, '')))
              IN ('MAIN', 'BSR')
        ORDER BY source.item, {source_date_sql}, source.id
    """, (
        str(start_date), str(end_date), retailer_value,
        str(start_date), str(end_date), retailer_value,
    ))
    return [
        dict(zip(select_columns, row))
        for row in cursor.fetchall()
    ]


def evaluate_sea_format_row(row, product_key, retailer):
    """Return DB-configured SEA REF/LDY format errors for one row."""
    source = SEA_RETAIL_SOURCES.get(product_key)
    if not source:
        return {}
    table_name = str(source['table_name']).split('.')[-1]
    errors = {}
    for field in _get_sea_format_fields(product_key):
        error = validate_field(
            table_name, field, row.get(field), retailer,
            product_line='ALL', row_context=row,
        )
        if error:
            errors[field] = error
    return errors


def _format_sea_record(row, product_key, retailer):
    record = {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }
    error_map = evaluate_sea_format_row(row, product_key, retailer)
    record['error_fields'] = list(error_map)
    record['error_details'] = {}
    for field, error in error_map.items():
        rule, separator, reason = str(error).partition(':')
        record['error_details'][field] = {
            'rule': rule.strip() or 'SEA 형식 검증',
            'reason': reason.strip() if separator else str(error),
        }
    return record


def _load_sea_format_normal_reviews(
        cursor, canonical_table, inspection_date, retailer_value):
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s
          AND correction_type = 'format_check' AND status = 'normal'
          AND LOWER(retailer) = LOWER(%s)
    """, (canonical_table, str(inspection_date), retailer_value))
    reviews = {}
    for row in cursor.fetchall():
        reviews[f'{row[0]}_{row[1]}'] = {
            'memo': row[2],
            'created_id': row[3],
            'created_at': (
                row[4].strftime('%Y-%m-%d %H:%M:%S')
                if hasattr(row[4], 'strftime') else str(row[4] or '') or None
            ),
            'reason': row[5],
        }
    return reviews


def _get_sea_format_detail(cursor, target_date, table, retailer, days):
    product_key = _sea_format_product_key(table)
    source = SEA_RETAIL_SOURCES.get(product_key)
    retailer_value = (
        _resolve_sea_format_retailer(source, retailer) if source else None
    )
    if not source or not retailer_value or not resolve_monitoring_date:
        return {
            'date': str(target_date), 'table': table, 'retailer': retailer,
            'column_names': [], 'editable_cols': [], 'actual_table': '',
            'normal_reviews': {}, 'results': [], 'field_counts': {},
            'total_format_count': 0,
        }

    date_mapping = resolve_monitoring_date(
        target_date, 'SEA', source['source_key']
    )
    inspection_date = date_mapping['inspection_date']
    source_date = date.fromisoformat(date_mapping['source_date'])
    target_rows = _fetch_sea_format_rows(
        cursor, source_date, source_date, source, retailer_value
    )
    normal_reviews = _load_sea_format_normal_reviews(
        cursor, source['table_name'], inspection_date, retailer_value
    )

    target_records = []
    for row in target_rows:
        record = _format_sea_record(row, product_key, retailer_value)
        record['error_fields'] = [
            field for field in record['error_fields']
            if f"{record['id']}_{field}" not in normal_reviews
        ]
        if record['error_fields']:
            target_records.append(record)

    history_days = min(max(int(days or 1), 1), 30)
    results = target_records
    if history_days > 1 and target_records:
        error_items = {
            str(record.get('item') or '').strip().casefold()
            for record in target_records
            if str(record.get('item') or '').strip()
        }
        history_rows = _fetch_sea_format_rows(
            cursor,
            source_date - timedelta(days=history_days - 1),
            source_date,
            source,
            retailer_value,
        )
        results = [
            _format_sea_record(row, product_key, retailer_value)
            for row in history_rows
            if str(row.get('item') or '').strip().casefold() in error_items
        ]

    field_counts = {}
    for record in target_records:
        for field in record['error_fields']:
            field_counts[field] = field_counts.get(field, 0) + 1

    format_fields = _get_sea_format_fields(product_key)
    date_column = source['date_column']
    column_names = list(dict.fromkeys((
        'id', date_column, 'account_name', 'page_type', 'item', 'sku',
        'retailer_sku_name', *format_fields, 'product_url',
    )))
    editable_columns = set(get_editable_columns(
        source['product_line'], retailer_value
    ))
    return {
        'date': inspection_date,
        'inspection_date': inspection_date,
        'source_date': source_date.isoformat(),
        'editable_date': source_date.isoformat(),
        'offset_days': date_mapping['offset_days'],
        'table': table,
        'retailer': retailer_value,
        'column_names': column_names,
        'select_cols': column_names,
        'editable_cols': [
            column for column in column_names if column in editable_columns
        ],
        'actual_table': source['table_name'],
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': field_counts,
        'total_format_count': sum(field_counts.values()),
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': date_column,
        'latest_batch_only': history_days == 1,
    }


def _append_sea_format_stats(cursor, target_date, validation):
    if not resolve_monitoring_date:
        return 0
    savepoint = 'layer2_sea_format_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    total_issues = 0
    try:
        for product_key, section_code in SEA_FORMAT_SECTION_BY_PRODUCT.items():
            source = SEA_RETAIL_SOURCES.get(product_key)
            if not source:
                continue
            date_mapping = resolve_monitoring_date(
                target_date, 'SEA', source['source_key']
            )
            source_date = date.fromisoformat(date_mapping['source_date'])
            retailer_rows = []
            table_checked = 0
            table_issues = 0
            for retailer_value in source.get('retailers', ()):
                rows = _fetch_sea_format_rows(
                    cursor, source_date, source_date, source, retailer_value
                )
                normal_reviews = _load_sea_format_normal_reviews(
                    cursor, source['table_name'],
                    date_mapping['inspection_date'], retailer_value,
                )
                issue_count = 0
                for row in rows:
                    for field in evaluate_sea_format_row(
                        row, product_key, retailer_value
                    ):
                        if f"{row['id']}_{field}" not in normal_reviews:
                            issue_count += 1
                retailer_rows.append({
                    'retailer': retailer_value,
                    'total': len(rows),
                    'issue_count': issue_count,
                    'status': get_status(issue_count),
                })
                table_checked += len(rows)
                table_issues += issue_count

            validation['tables'].append({
                'table': section_code,
                'table_name': f"SEA {source['category']}",
                'total_checked': table_checked,
                'total_issues': table_issues,
                'status': get_status(table_issues),
                'retailers': retailer_rows,
                'inspection_date': date_mapping['inspection_date'],
                'source_date': date_mapping['source_date'],
                'offset_days': date_mapping['offset_days'],
            })
            total_issues += table_issues
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        print(f'[WARN] layer2_sea_format_stats: {exc}')
        return 0
    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    return total_issues


def _fetch_tse_format_rows(
        cursor, start_date, end_date, source, retailer_value,
        include_unassigned=False):
    """Fetch each day's latest TSE retailer batch in a bounded date range."""
    canonical_table = source['table_name']
    account_scope = 'LOWER(source.account_name) = LOWER(%s)'
    if include_unassigned:
        account_scope = f"""(
            {account_scope}
            OR source.account_name IS NULL
            OR TRIM(CAST(source.account_name AS TEXT)) = ''
        )"""
    country_scope = """(
        source.country = %s
        OR source.country IS NULL
        OR TRIM(CAST(source.country AS TEXT)) = ''
    )"""
    select_columns = [
        'id', 'batch_id', 'country', 'account_name', 'item', 'sku',
        'retailer_sku_name', 'final_sku_price', 'original_sku_price',
        'savings', 'count_of_reviews', 'count_of_star_ratings',
        'star_rating', 'crawl_datetime', 'product_url',
    ]
    for column in source.get('extra_format_columns', ()):
        if column not in select_columns:
            select_columns.append(column)
    cursor.execute(f"""
        WITH latest_batches AS (
            SELECT DISTINCT ON (LEFT(TRIM(source.crawl_datetime), 10))
                   LEFT(TRIM(source.crawl_datetime), 10) AS crawl_date,
                   source.batch_id
            FROM {canonical_table} source
            WHERE LEFT(TRIM(source.crawl_datetime), 10) >= %s
              AND LEFT(TRIM(source.crawl_datetime), 10) <= %s
              AND LOWER(source.account_name) = LOWER(%s)
              AND {country_scope}
            ORDER BY LEFT(TRIM(source.crawl_datetime), 10), source.id DESC
        )
        SELECT {', '.join('source.' + column for column in select_columns)}
        FROM {canonical_table} source
        JOIN latest_batches latest
          ON LEFT(TRIM(source.crawl_datetime), 10) = latest.crawl_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LEFT(TRIM(source.crawl_datetime), 10) >= %s
          AND LEFT(TRIM(source.crawl_datetime), 10) <= %s
          AND {account_scope}
          AND {country_scope}
        ORDER BY source.item, source.crawl_datetime, source.id
    """, (
        str(start_date), str(end_date), retailer_value, TSE_COUNTRY,
        str(start_date), str(end_date), retailer_value, TSE_COUNTRY,
    ))
    return [
        dict(zip(select_columns, row))
        for row in cursor.fetchall()
    ]


def _load_tse_format_normal_reviews(
        cursor, canonical_table, target_date, retailer_value):
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s
          AND correction_type = 'format_check' AND status = 'normal'
          AND LOWER(retailer) = LOWER(%s)
    """, (canonical_table, str(target_date), retailer_value))
    reviews = {}
    for row in cursor.fetchall():
        reviews[f'{row[0]}_{row[1]}'] = {
            'memo': row[2],
            'created_id': row[3],
            'created_at': (
                row[4].strftime('%Y-%m-%d %H:%M:%S')
                if hasattr(row[4], 'strftime') else str(row[4] or '') or None
            ),
            'reason': row[5],
        }
    return reviews


def _format_tse_record(row, product_line=None, retailer=None):
    record = {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }
    error_map = evaluate_tse_format_row(row, product_line, retailer)
    record['error_fields'] = list(error_map)
    record['error_details'] = {
        field: {'rule': 'TSE 형식 검증', 'reason': reason}
        for field, reason in error_map.items()
    }
    return record


def _get_tse_format_detail(cursor, target_date, table, retailer, days):
    product_line = _tse_format_product_line(table)
    source = TSE_SOURCE_CONFIG.get(product_line)
    resolved = (
        _resolve_tse_format_retailer(product_line, retailer)
        if source else None
    )
    if not source or not resolved:
        return {
            'date': str(target_date), 'table': table, 'retailer': retailer,
            'column_names': [], 'editable_cols': [], 'actual_table': '',
            'normal_reviews': {}, 'results': [], 'field_counts': {},
            'total_format_count': 0,
        }

    display_name, retailer_config = resolved
    retailer_value = retailer_config['retailer']
    include_unassigned = tse_retailer_include_unassigned(retailer_value)
    target_rows = _fetch_tse_format_rows(
        cursor, target_date, target_date, source, retailer_value,
        include_unassigned,
    )
    normal_reviews = _load_tse_format_normal_reviews(
        cursor, source['table_name'], target_date, retailer_value,
    )
    target_records = []
    for row in target_rows:
        record = _format_tse_record(row, product_line, retailer_value)
        record['error_fields'] = [
            field for field in record['error_fields']
            if f"{record['id']}_{field}" not in normal_reviews
        ]
        if record['error_fields']:
            target_records.append(record)

    history_days = min(max(int(days or 1), 1), 30)
    results = target_records
    if history_days > 1 and target_records:
        identities = {
            (
                str(record.get('item') or '').strip().casefold(),
                str(record.get('retailer_sku_name') or '').strip().casefold(),
            )
            for record in target_records
        }
        history_rows = _fetch_tse_format_rows(
            cursor, target_date - timedelta(days=history_days - 1),
            target_date, source, retailer_value, include_unassigned,
        )
        results = [
            _format_tse_record(row, product_line, retailer_value)
            for row in history_rows
            if (
                str(row.get('item') or '').strip().casefold(),
                str(row.get('retailer_sku_name') or '').strip().casefold(),
            ) in identities
        ]

    field_counts = {}
    for record in target_records:
        for field in record['error_fields']:
            field_counts[field] = field_counts.get(field, 0) + 1

    format_fields = get_tse_format_fields(product_line, retailer_value)
    column_names = [
        'id', 'crawl_datetime', 'item', 'retailer_sku_name',
        *format_fields, 'sku', 'product_url',
    ]
    column_names = list(dict.fromkeys(column_names))
    query_columns = list(dict.fromkeys([
        'id', 'item', 'sku', 'retailer_sku_name', *format_fields,
        'crawl_datetime', 'product_url',
    ]))
    return {
        'date': str(target_date),
        'table': table,
        'retailer': display_name,
        'column_names': column_names,
        'select_cols': column_names,
        'editable_cols': _safe_tse_format_editable_columns(
            product_line, retailer_config
        ),
        'actual_table': source['table_name'],
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': field_counts,
        'total_format_count': sum(field_counts.values()),
        'query_config': {
            field: query_columns for field in format_fields
        },
        'query_retailer': retailer_value,
        'query_include_unassigned': include_unassigned,
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': 'crawl_datetime',
    }


def _append_tse_format_stats(cursor, target_date, validation):
    if not TSE_SOURCE_CONFIG or not get_tse_retailer_columns:
        return 0
    savepoint = 'layer2_tse_format_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    total_issues = 0
    try:
        for product_line, source in TSE_SOURCE_CONFIG.items():
            configs = get_tse_retailer_columns(product_line)
            retailer_rows = []
            table_checked = 0
            table_issues = 0
            for display_name, retailer_config in configs.items():
                retailer_value = retailer_config['retailer']
                rows = _fetch_tse_format_rows(
                    cursor, target_date, target_date, source, retailer_value,
                    tse_retailer_include_unassigned(retailer_value),
                )
                normal_reviews = _load_tse_format_normal_reviews(
                    cursor, source['table_name'], target_date, retailer_value,
                )
                issue_count = 0
                for row in rows:
                    for field in evaluate_tse_format_row(
                        row, product_line, retailer_value
                    ):
                        if f"{row['id']}_{field}" not in normal_reviews:
                            issue_count += 1
                retailer_rows.append({
                    'retailer': display_name,
                    'total': len(rows),
                    'issue_count': issue_count,
                    'status': get_status(issue_count),
                })
                table_checked += len(rows)
                table_issues += issue_count
            if retailer_rows:
                validation['tables'].append({
                    'table': source['section_code'],
                    'table_name': source['display_name'],
                    'total_checked': table_checked,
                    'total_issues': table_issues,
                    'status': get_status(table_issues),
                    'retailers': retailer_rows,
                })
                total_issues += table_issues
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        print(f'[WARN] layer2_tse_format_stats: {exc}')
        return 0
    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    return total_issues


def _siel_format_source_key(table):
    value = str(table or '').strip().lower()
    if value in SIEL_SOURCE_CONFIG:
        return value
    if value in SIEL_FORMAT_SOURCE_BY_SECTION:
        return SIEL_FORMAT_SOURCE_BY_SECTION[value]
    for source_key, source in SIEL_SOURCE_CONFIG.items():
        table_name = str(source.get('table_name') or '').strip().lower()
        if value in {table_name, table_name.split('.')[-1]}:
            return source_key
    return None


def _resolve_siel_format_retailer(source, retailer):
    retailer_key = str(retailer or '').strip().casefold()
    for configured in source.get('retailers', ()):
        if retailer_key == str(configured).strip().casefold():
            return configured
    return None


def _get_siel_format_fields(source_key, retailer):
    retailer_key = str(retailer or '').strip().casefold()
    retailer_fields = SIEL_FORMAT_FIELDS.get(source_key, {}).get(
        retailer_key, ()
    )
    return tuple(dict.fromkeys((
        *SIEL_FORMAT_COMMON_FIELDS,
        *retailer_fields,
    )))


def _has_siel_format_value(value):
    return value is not None and str(value).strip() != ''


def evaluate_siel_format_row(row, source_key, retailer):
    """Return SIEL-only syntax errors without Layer3 cross-field rules."""
    source = SIEL_SOURCE_CONFIG.get(source_key)
    retailer_value = (
        _resolve_siel_format_retailer(source, retailer) if source else None
    )
    if not source or not retailer_value:
        return {}

    fields = set(_get_siel_format_fields(source_key, retailer_value))
    retailer_key = retailer_value.casefold()
    errors = {}

    account_name = row.get('account_name')
    if (
        'account_name' in fields
        and _has_siel_format_value(account_name)
        and str(account_name).strip() != retailer_value
    ):
        errors['account_name'] = '허용된 리테일러명이 아닙니다.'

    calendar_week = row.get('calendar_week')
    if (
        'calendar_week' in fields
        and _has_siel_format_value(calendar_week)
        and not _SIEL_CALENDAR_WEEK_PATTERN.fullmatch(
            str(calendar_week).strip()
        )
    ):
        errors['calendar_week'] = 'w1~w53 형식의 주차가 아닙니다.'

    country = row.get('country')
    if (
        'country' in fields
        and _has_siel_format_value(country)
        and str(country).strip() != 'SIEL'
    ):
        errors['country'] = '국가 코드가 SIEL이 아닙니다.'

    review_content = row.get('detailed_review_content')
    if (
        'detailed_review_content' in fields
        and _has_siel_format_value(review_content)
        and not str(review_content).strip().startswith('review1 - ')
    ):
        errors['detailed_review_content'] = (
            '리뷰본문은 "review1 - "로 시작해야 합니다.'
        )

    original_price = row.get('original_sku_price')
    if (
        'original_sku_price' in fields
        and _has_siel_format_value(original_price)
        and not _SIEL_MONEY_PATTERN.fullmatch(str(original_price).strip())
    ):
        errors['original_sku_price'] = (
            '₹10,999 인도 루피 원가 형식이 아닙니다.'
        )

    page_type = row.get('page_type')
    if (
        'page_type' in fields
        and _has_siel_format_value(page_type)
        and str(page_type).strip() not in _SIEL_PAGE_TYPE_VALUES
    ):
        errors['page_type'] = 'page_type은 main 또는 bsr이어야 합니다.'

    product = row.get('product')
    expected_product = str(source.get('category') or '').strip()
    if (
        'product' in fields
        and _has_siel_format_value(product)
        and str(product).strip() != expected_product
    ):
        errors['product'] = f'product는 {expected_product}이어야 합니다.'

    product_url = row.get('product_url')
    if 'product_url' in fields and _has_siel_format_value(product_url):
        url_pattern = (
            _SIEL_AMAZON_PRODUCT_URL_PATTERN
            if retailer_key == 'amazon'
            else _SIEL_FLIPKART_PRODUCT_URL_PATTERN
        )
        if not url_pattern.fullmatch(str(product_url).strip()):
            errors['product_url'] = (
                'SIEL 리테일러별 상품 상세 URL 형식이 아닙니다.'
            )

    star_rating = row.get('star_rating')
    if 'star_rating' in fields and _has_siel_format_value(star_rating):
        normalized_rating = str(star_rating).strip()
        allowed_status = (
            retailer_key == 'amazon'
            and normalized_rating in _SIEL_AMAZON_STAR_STATUS_VALUES
        )
        if (
            not allowed_status
            and not _SIEL_STAR_RATING_PATTERN.fullmatch(normalized_rating)
        ):
            errors['star_rating'] = (
                '숫자 평점 또는 허용된 평가 없음 문구가 아닙니다.'
            )

    final_price = row.get('final_sku_price')
    if 'final_sku_price' in fields and _has_siel_format_value(final_price):
        normalized = str(final_price).strip()
        allowed_status = (
            retailer_key == 'amazon'
            and normalized in _SIEL_AMAZON_PRICE_STATUS_VALUES
        )
        if not allowed_status and not _SIEL_MONEY_PATTERN.fullmatch(normalized):
            errors['final_sku_price'] = (
                '₹10,999 인도 루피 금액 형식이 아닙니다.'
            )

    for field in ('count_of_reviews', 'count_of_star_ratings'):
        value = row.get(field)
        if (
            field in fields
            and _has_siel_format_value(value)
            and not _SIEL_COUNT_PATTERN.fullmatch(str(value).strip())
        ):
            errors[field] = (
                '0 이상의 정수와 올바른 천 단위 쉼표 형식이 아닙니다.'
            )

    screen_size = row.get('screen_size')
    if 'screen_size' in fields and _has_siel_format_value(screen_size):
        pattern = (
            _SIEL_AMAZON_SCREEN_SIZE_PATTERN
            if retailer_key == 'amazon'
            else _SIEL_FLIPKART_SCREEN_SIZE_PATTERN
        )
        if not pattern.fullmatch(str(screen_size).strip()):
            errors['screen_size'] = (
                'Amazon은 43 Inches, Flipkart는 '
                '109 cm (43 inch) 형식이어야 합니다.'
            )

    energy = row.get('estimated_annual_electricity_use')
    if (
        'estimated_annual_electricity_use' in fields
        and _has_siel_format_value(energy)
    ):
        pattern = (
            _SIEL_AMAZON_ENERGY_PATTERN
            if retailer_key == 'amazon'
            else _SIEL_FLIPKART_ENERGY_PATTERN
        )
        if not pattern.fullmatch(str(energy).strip()):
            errors['estimated_annual_electricity_use'] = (
                'SIEL 리테일러별 전력·연간 전력량 형식이 아닙니다.'
            )

    model_year = row.get('model_year')
    if (
        'model_year' in fields
        and _has_siel_format_value(model_year)
        and not _SIEL_MODEL_YEAR_PATTERN.fullmatch(str(model_year).strip())
    ):
        errors['model_year'] = '20으로 시작하는 4자리 연도가 아닙니다.'

    ref_capacity = row.get('ref_capacity')
    if (
        'ref_capacity' in fields
        and _has_siel_format_value(ref_capacity)
        and not _SIEL_REF_CAPACITY_PATTERN.fullmatch(
            str(ref_capacity).strip()
        )
    ):
        errors['ref_capacity'] = (
            '숫자와 L/Liter/Litre 또는 cubic foot/feet 단위 '
            '용량 형식이 아닙니다.'
        )

    refrigerator_type = row.get('ref_refrigerator_type')
    if (
        'ref_refrigerator_type' in fields
        and _has_siel_format_value(refrigerator_type)
        and str(refrigerator_type).strip().casefold()
        not in _SIEL_FLIPKART_REF_TYPE_VALUES
    ):
        errors['ref_refrigerator_type'] = (
            'CSV에서 확인된 Flipkart 냉장고 타입 표준값이 아닙니다.'
        )

    ldy_capacity = row.get('ldy_capacity')
    if 'ldy_capacity' in fields and _has_siel_format_value(ldy_capacity):
        pattern = (
            _SIEL_AMAZON_LDY_CAPACITY_PATTERN
            if retailer_key == 'amazon'
            else _SIEL_FLIPKART_LDY_CAPACITY_PATTERN
        )
        if not pattern.fullmatch(str(ldy_capacity).strip()):
            errors['ldy_capacity'] = (
                'SIEL 리테일러별 세탁 용량 형식이 아닙니다.'
            )

    return errors


def _fetch_siel_format_rows(
        cursor, start_date, end_date, source, retailer_value):
    """Fetch each KST day's latest MAIN-anchored SIEL batch."""
    canonical_table = source['table_name']
    date_column = source['date_column']
    source_key = source['source_key']
    format_fields = _get_siel_format_fields(source_key, retailer_value)
    select_columns = list(dict.fromkeys((
        'id', 'batch_id', 'country', 'product', 'account_name', 'page_type',
        'item', 'sku', 'retailer_sku_name', *format_fields,
        date_column, 'product_url',
    )))
    local_date = (
        f"(source.{date_column} AT TIME ZONE "
        f"'{SIEL_BUSINESS_TIMEZONE}')::date"
    )
    cursor.execute(f"""
        WITH latest_batches AS (
            SELECT DISTINCT ON ({local_date})
                   {local_date} AS source_date,
                   source.batch_id,
                   source.id
            FROM {canonical_table} source
            WHERE source.{date_column} >= (
                    %s::date::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                  )
              AND source.{date_column} < (
                    (%s::date + 1)::timestamp AT TIME ZONE
                    '{SIEL_BUSINESS_TIMEZONE}'
                  )
              AND LOWER(BTRIM(CAST(source.account_name AS TEXT))) =
                  LOWER(BTRIM(CAST(%s AS TEXT)))
              AND LOWER(BTRIM(CAST(source.page_type AS TEXT))) = 'main'
              AND {get_tv_validation_condition('source')}
            ORDER BY {local_date}, source.id DESC
        )
        SELECT {', '.join('source.' + column for column in select_columns)}
        FROM {canonical_table} source
        JOIN latest_batches latest
          ON {local_date} = latest.source_date
         AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE source.{date_column} >= (
                %s::date::timestamp AT TIME ZONE
                '{SIEL_BUSINESS_TIMEZONE}'
              )
          AND source.{date_column} < (
                (%s::date + 1)::timestamp AT TIME ZONE
                '{SIEL_BUSINESS_TIMEZONE}'
              )
          AND {get_tv_validation_condition('source')}
        ORDER BY source.item, {local_date}, source.id
    """, (
        str(start_date), str(end_date), retailer_value,
        str(start_date), str(end_date),
    ))
    return [
        dict(zip(select_columns, row))
        for row in cursor.fetchall()
    ]


def _serialize_siel_format_value(key, value):
    if key == 'crawl_datetime' and isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(SIEL_BUSINESS_TIMEZONE))
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value) if value is not None and key != 'id' else value


def _format_siel_record(row, source_key, retailer):
    record = {
        key: _serialize_siel_format_value(key, value)
        for key, value in row.items()
    }
    error_map = evaluate_siel_format_row(row, source_key, retailer)
    record['error_fields'] = list(error_map)
    record['error_details'] = {
        field: {'rule': 'SIEL 형식 검증', 'reason': reason}
        for field, reason in error_map.items()
    }
    return record


def _load_siel_format_normal_reviews(
        cursor, canonical_table, inspection_date, retailer_value):
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s
          AND correction_type = 'format_check' AND status = 'normal'
          AND LOWER(retailer) = LOWER(%s)
    """, (canonical_table, str(inspection_date), retailer_value))
    reviews = {}
    for row in cursor.fetchall():
        reviews[f'{row[0]}_{row[1]}'] = {
            'memo': row[2],
            'created_id': row[3],
            'created_at': (
                row[4].strftime('%Y-%m-%d %H:%M:%S')
                if hasattr(row[4], 'strftime') else str(row[4] or '') or None
            ),
            'reason': row[5],
        }
    return reviews


def _get_siel_format_detail(cursor, target_date, table, retailer, days):
    source_key = _siel_format_source_key(table)
    source = SIEL_SOURCE_CONFIG.get(source_key)
    retailer_value = (
        _resolve_siel_format_retailer(source, retailer) if source else None
    )
    if not source or not retailer_value or not resolve_monitoring_date:
        return {
            'date': str(target_date), 'table': table, 'retailer': retailer,
            'column_names': [], 'editable_cols': [], 'actual_table': '',
            'normal_reviews': {}, 'results': [], 'field_counts': {},
            'total_format_count': 0,
        }

    date_mapping = resolve_monitoring_date(
        target_date, 'SIEL', source['source_key']
    )
    inspection_date = date_mapping['inspection_date']
    source_date = date.fromisoformat(date_mapping['source_date'])
    target_rows = _fetch_siel_format_rows(
        cursor, source_date, source_date, source, retailer_value
    )
    normal_reviews = _load_siel_format_normal_reviews(
        cursor, source['table_name'], inspection_date, retailer_value
    )

    target_records = []
    for row in target_rows:
        record = _format_siel_record(row, source_key, retailer_value)
        record['error_fields'] = [
            field for field in record['error_fields']
            if f"{record['id']}_{field}" not in normal_reviews
        ]
        if record['error_fields']:
            target_records.append(record)

    history_days = min(max(int(days or 1), 1), 30)
    results = target_records
    if history_days > 1 and target_records:
        error_items = {
            str(record.get('item') or '').strip().casefold()
            for record in target_records
            if str(record.get('item') or '').strip()
        }
        history_rows = _fetch_siel_format_rows(
            cursor,
            source_date - timedelta(days=history_days - 1),
            source_date,
            source,
            retailer_value,
        )
        results = [
            _format_siel_record(row, source_key, retailer_value)
            for row in history_rows
            if str(row.get('item') or '').strip().casefold() in error_items
        ]

    field_counts = {}
    for record in target_records:
        for field in record['error_fields']:
            field_counts[field] = field_counts.get(field, 0) + 1

    format_fields = _get_siel_format_fields(source_key, retailer_value)
    date_column = source['date_column']
    column_names = list(dict.fromkeys((
        'id', date_column, 'item', 'account_name', 'country', 'page_type',
        'sku', 'retailer_sku_name', *format_fields, 'product_url',
    )))
    return {
        'date': inspection_date,
        'inspection_date': inspection_date,
        'source_date': source_date.isoformat(),
        'editable_date': source_date.isoformat(),
        'offset_days': date_mapping['offset_days'],
        'table': table,
        'retailer': retailer_value,
        'column_names': column_names,
        'select_cols': column_names,
        'editable_cols': [],
        'actual_table': source['table_name'],
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': field_counts,
        'total_format_count': sum(field_counts.values()),
        'supports_day_history': True,
        'history_days': history_days,
        'date_column': date_column,
        'latest_batch_only': history_days == 1,
        'business_timezone': SIEL_BUSINESS_TIMEZONE,
    }


def _append_siel_format_stats(cursor, target_date, validation):
    if not resolve_monitoring_date or not SIEL_SOURCE_CONFIG:
        return 0
    savepoint = 'layer2_siel_format_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    total_issues = 0
    try:
        for source_key, source in SIEL_SOURCE_CONFIG.items():
            date_mapping = resolve_monitoring_date(
                target_date, 'SIEL', source['source_key']
            )
            source_date = date.fromisoformat(date_mapping['source_date'])
            retailer_rows = []
            table_checked = 0
            table_issues = 0
            for retailer_value in source.get('retailers', ()):
                rows = _fetch_siel_format_rows(
                    cursor, source_date, source_date, source, retailer_value
                )
                normal_reviews = _load_siel_format_normal_reviews(
                    cursor, source['table_name'],
                    date_mapping['inspection_date'], retailer_value,
                )
                issue_count = 0
                for row in rows:
                    for field in evaluate_siel_format_row(
                            row, source_key, retailer_value):
                        if f"{row['id']}_{field}" not in normal_reviews:
                            issue_count += 1
                retailer_rows.append({
                    'retailer': retailer_value,
                    'total': len(rows),
                    'issue_count': issue_count,
                    'status': get_status(issue_count),
                })
                table_checked += len(rows)
                table_issues += issue_count

            validation['tables'].append({
                'table': SIEL_FORMAT_SECTION_BY_SOURCE[source_key],
                'table_name': f"SIEL {source['category']}",
                'total_checked': table_checked,
                'total_issues': table_issues,
                'status': get_status(table_issues),
                'retailers': retailer_rows,
                'inspection_date': date_mapping['inspection_date'],
                'source_date': date_mapping['source_date'],
                'offset_days': date_mapping['offset_days'],
            })
            total_issues += table_issues
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        print(f'[WARN] layer2_siel_format_stats: {exc}')
        return 0
    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    return total_issues


# ── thin wrappers ──────────────────────────────────────────

def validate_tv_field(field_name, value, account_name='Amazon'):
    """TV Retail 필드별 형식 검증. 오류 시 메시지 반환, 정상이면 None"""
    return validate_field('tv_retail_com', field_name, value, account_name, product_line='TV')


def validate_hhp_field(field_name, value, account_name='Amazon'):
    """HHP Retail 필드별 형식 검증. 오류 시 메시지 반환, 정상이면 None"""
    return validate_field('hhp_retail_com', field_name, value, account_name, product_line='HHP')


# ── 형식 오류 상세 조회 ───────────────────────────────────

def get_format_detail(cursor, target_date, table, retailer, days):
    """
    형식 오류 상세 조회.
    Returns dict: {date, table, retailer, column_names, editable_cols, actual_table, normal_reviews, results}
    """
    if _sea_format_product_key(table):
        return _get_sea_format_detail(
            cursor, target_date, table, retailer, days
        )
    if _siel_format_source_key(table):
        return _get_siel_format_detail(
            cursor, target_date, table, retailer, days
        )
    if _tse_format_product_line(table):
        return _get_tse_format_detail(
            cursor, target_date, table, retailer, days
        )

    results = []
    select_cols = []
    column_names = []
    next_date = target_date + timedelta(days=1)
    if table == 'hhp_retail':
        return {
            'date': str(target_date),
            'table': table,
            'retailer': retailer,
            'column_names': [],
            'editable_cols': [],
            'actual_table': '',
            'normal_reviews': {},
            'results': []
        }

    # TV Retail 형식 오류 상세 조회 - SQL 조건으로 오류 행 직접 필터링
    if table == 'tv_retail':
        select_cols = ['id', 'item', 'crawl_datetime', 'product_url']
        all_fields = [
            'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
            'final_sku_price', 'original_sku_price',
            'count_of_reviews', 'star_rating', 'count_of_star_ratings',
            'detailed_review_content',
            'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
            'sku_popularity', 'retailer_membership_discounts',
            'rank_1', 'rank_2', 'summarized_review_content',
            'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
            'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
        ]
        column_names = ['id', 'crawl_datetime'] + all_fields

        # 형식 규칙 → SQL WHERE 조건 변환
        error_where = build_format_error_sql('tv_retail_com', 'TV', retailer)

        query = f"""
            SELECT
                id, crawl_datetime, account_name, {', '.join(all_fields)}
            FROM tv_retail_com
            WHERE crawl_datetime::timestamp >= %s AND crawl_datetime::timestamp < %s
              AND {get_tv_validation_condition()}
        """
        params = [str(target_date), str(next_date)]
        if retailer:
            query += " AND account_name = %s"
            params.append(retailer)
        query += f" AND ({error_where})"
        query += " ORDER BY account_name, crawl_datetime"

        cursor.execute(query, params)
        for row in cursor.fetchall():
            record_id = row[0]
            crawl_dt = row[1]
            account_name = row[2]
            values = list(row[3:])

            record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
            for field, value in zip(all_fields, values):
                record[field] = str(value) if value is not None else None

            # 오류 행 내 개별 필드 오류 식별 (Python 검증, 소수 행만 대상)
            error_fields = []
            error_details = {}
            for field, value in zip(all_fields, values):
                error = validate_tv_field(field, value, account_name)
                if error:
                    error_fields.append(field)
                    error_details[field] = {
                        'rule': error.split(':', 1)[0] if ':' in error else error,
                        'reason': error.split(':', 1)[1].strip() if ':' in error else error
                    }

            if error_fields:
                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # HHP Retail 형식 오류 상세 조회 - SQL 조건으로 오류 행 직접 필터링
    elif table == 'hhp_retail':
        select_cols = ['id', 'item', 'crawl_datetime', 'product_url']
        cursor.execute("SELECT DISTINCT item FROM hhp_item_mst")
        hhp_valid_items = set(row[0] for row in cursor.fetchall())

        hhp_fields = [
            'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
            'final_sku_price', 'original_sku_price',
            'count_of_reviews', 'star_rating', 'count_of_star_ratings',
            'detailed_review_content', 'trade_in', 'sku_status',
            'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
            'sku_popularity', 'retailer_membership_discounts',
            'rank_1', 'rank_2', 'summarized_review_content',
            'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
            'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
        ]
        column_names = ['id', 'crawl_datetime'] + hhp_fields

        # 형식 규칙 → SQL WHERE 조건 변환 + item 참조 무결성 체크
        error_where = build_format_error_sql('hhp_retail_com', 'HHP', retailer)
        item_check = "item IS NOT NULL AND TRIM(item::text) != '' AND item NOT IN (SELECT DISTINCT item FROM hhp_item_mst)"
        full_error_where = f"({error_where}) OR ({item_check})"

        query = f"""
            SELECT
                id, crawl_strdatetime, account_name, {', '.join(hhp_fields)}
            FROM hhp_retail_com
            WHERE crawl_strdatetime::timestamp >= %s AND crawl_strdatetime::timestamp < %s
        """
        params = [str(target_date), str(next_date)]
        if retailer:
            query += " AND account_name = %s"
            params.append(retailer)
        query += f" AND ({full_error_where})"
        query += " ORDER BY account_name, crawl_strdatetime"

        cursor.execute(query, params)
        for row in cursor.fetchall():
            record_id = row[0]
            crawl_dt = row[1]
            account_name = row[2]
            values = list(row[3:])

            record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
            for field, value in zip(hhp_fields, values):
                record[field] = str(value) if value is not None else None

            # 오류 행 내 개별 필드 오류 식별 (Python 검증, 소수 행만 대상)
            error_fields = []
            error_details = {}
            for field, value in zip(hhp_fields, values):
                error = validate_hhp_field(field, value, account_name)
                if error:
                    error_fields.append(field)
                    error_details[field] = {
                        'rule': error.split(':', 1)[0] if ':' in error else error,
                        'reason': error.split(':', 1)[1].strip() if ':' in error else error
                    }

            item = values[0]  # hhp_fields[0] = 'item'
            if item and item not in hhp_valid_items:
                error_fields.append('item')
                error_details['item'] = {
                    'rule': '참조 무결성',
                    'reason': '마스터 테이블에 등록되지 않은 item'
                }

            if error_fields:
                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # YouTube 형식 오류 상세 조회 — 규칙 테이블 기반
    elif table == 'youtube_logs' or (table == 'youtube' and retailer == 'Logs'):
        db_table = 'youtube_collection_logs'
        account_name = 'Logs'
        date_col = 'started_at'
        all_fields = ['keyword', 'status', 'videos_collected', 'comments_collected', 'started_at']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'id, ' + ', '.join(all_fields + case_cols) if case_cols else 'id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    elif table == 'youtube_videos' or (table == 'youtube' and retailer == 'Videos'):
        db_table = 'youtube_videos'
        account_name = 'Videos'
        date_col = 'created_at'
        all_fields = ['video_id', 'keyword', 'channel_custom_url', 'category',
                      'engagement_rate', 'product_sentiment_score', 'published_at', 'created_at',
                      'channel_subscriber_count', 'channel_video_count', 'view_count', 'like_count', 'comment_count']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = ', '.join(all_fields + case_cols) if case_cols else ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                values = list(row[:len(all_fields)])
                err_flags = list(row[len(all_fields):])

                record = {'id': values[0]}  # video_id as id
                for field, value in zip(all_fields, values):
                    if field in ('engagement_rate', 'product_sentiment_score'):
                        record[field] = float(value) if value is not None else None
                    elif field in ('published_at', 'created_at'):
                        record[field] = str(value)[:19] if value else None
                    else:
                        record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    elif table == 'youtube_comments' or (table == 'youtube' and retailer == 'Comments'):
        db_table = 'youtube_comments'
        account_name = 'Comments'
        date_col = 'created_at'
        all_fields = ['video_id', 'comment_type', 'parent_comment_id', 'like_count', 'reply_count', 'published_at', 'created_at']
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'comment_id, ' + ', '.join(all_fields + case_cols) if case_cols else 'comment_id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY comment_id DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    if field in ('published_at', 'created_at'):
                        record[field] = str(value)[:19] if value else None
                    else:
                        record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # Market 형식 오류 상세 조회 — 규칙 테이블 기반
    elif table == 'market' and retailer in ('Trend', 'Comp Product', 'Comp Event', 'Forecast'):
        market_config = {
            'Trend': ('market_trend', 'crawl_at_local_time', ['keyword', 'total_article_number', 'calendar_week', 'crawl_at_local_time']),
            'Comp Product': ('market_comp_product', 'created_at', ['samsung_series_name', 'comp_brand', 'calender_week', 'category', 'created_at']),
            'Comp Event': ('market_comp_event', 'created_at', ['comp_brand', 'comp_sku_name', 'calender_week', 'category', 'created_at']),
            'Forecast': ('openai_forecast_results', 'crawled_at', ['product_name', 'event', 'metric_type', 'event_offset', 'event_value', 'week', 'crawled_at']),
        }
        db_table, date_col, all_fields = market_config[retailer]
        if db_table in DISABLED_SOURCE_TABLES:
            return {
                'date': str(target_date),
                'table': table,
                'retailer': retailer,
                'column_names': [],
                'editable_cols': [],
                'actual_table': '',
                'normal_reviews': {},
                'results': [],
                'field_counts': {},
                'total_format_count': 0,
            }
        account_name = retailer
        column_names = ['id'] + all_fields

        error_where = build_format_error_sql(db_table, 'ALL', account_name)
        field_checks = build_per_field_error_sql(db_table, 'ALL', account_name)

        if error_where != 'FALSE':
            case_cols = [f"CASE WHEN {fc['cond']} THEN 1 ELSE 0 END" for fc in field_checks]
            select_parts = 'id, ' + ', '.join(all_fields + case_cols) if case_cols else 'id, ' + ', '.join(all_fields)

            cursor.execute(f"""
                SELECT {select_parts}
                FROM {db_table}
                WHERE DATE({date_col}) = %s AND ({error_where})
                ORDER BY {date_col} DESC
            """, (target_date,))
            for row in cursor.fetchall():
                record = {'id': row[0]}
                values = list(row[1:len(all_fields)+1])
                err_flags = list(row[len(all_fields)+1:])

                for field, value in zip(all_fields, values):
                    record[field] = str(value) if value is not None else None

                error_fields = []
                error_details = {}
                for i, fc in enumerate(field_checks):
                    if i < len(err_flags) and err_flags[i] == 1:
                        error_fields.append(fc['field'])
                        error_details[fc['field']] = {
                            'rule': fc['field'],
                            'reason': fc['error'] or f"{fc['field']} 형식 오류"
                        }

                record['error_fields'] = error_fields
                record['error_details'] = error_details
                results.append(record)

    # retail + days > 1: 오류 item으로 N일치 확장 재조회
    if days > 1 and table in ('tv_retail', 'hhp_retail') and results:
        error_items = list(set(r['item'] for r in results if r.get('item')))
        if error_items:
            start_date = target_date - timedelta(days=days - 1)
            placeholders = ', '.join(['%s'] * len(error_items))
            results = []

            if table == 'tv_retail':
                query = f"""
                    SELECT
                        id, crawl_datetime, account_name, item, page_type, product_url,
                        main_rank, bsr_rank, final_sku_price, original_sku_price,
                        count_of_reviews, star_rating, count_of_star_ratings,
                        detailed_review_content,
                        number_of_units_purchased_past_month, available_quantity_for_purchase,
                        sku_popularity, retailer_membership_discounts,
                        rank_1, rank_2, summarized_review_content,
                        savings, offer, retailer_sku_name_similar, recommendation_intent,
                        number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
                    FROM tv_retail_com
                    WHERE crawl_datetime::timestamp >= %s AND crawl_datetime::timestamp < %s
                      AND {get_tv_validation_condition()}
                      AND account_name = %s AND item IN ({placeholders})
                    ORDER BY item, crawl_datetime
                """
                expand_params = [str(start_date), str(next_date), retailer] + error_items
                cursor.execute(query, expand_params)
                rows = cursor.fetchall()
                all_fields = [
                    'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
                    'final_sku_price', 'original_sku_price',
                    'count_of_reviews', 'star_rating', 'count_of_star_ratings',
                    'detailed_review_content',
                    'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
                    'sku_popularity', 'retailer_membership_discounts',
                    'rank_1', 'rank_2', 'summarized_review_content',
                    'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
                    'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
                ]
                for row in rows:
                    record_id = row[0]
                    crawl_dt = row[1]
                    account_name = row[2]
                    values = list(row[3:])

                    record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
                    for field, value in zip(all_fields, values):
                        record[field] = str(value) if value is not None else None

                    error_fields = []
                    error_details = {}
                    for field, value in zip(all_fields, values):
                        error = validate_tv_field(field, value, account_name)
                        if error:
                            error_fields.append(field)
                            error_details[field] = {
                                'rule': error.split(':', 1)[0] if ':' in error else error,
                                'reason': error.split(':', 1)[1].strip() if ':' in error else error
                            }
                    record['error_fields'] = error_fields
                    record['error_details'] = error_details
                    results.append(record)

            elif table == 'hhp_retail':
                query = f"""
                    SELECT
                        id, crawl_strdatetime, account_name, item, page_type, product_url,
                        main_rank, bsr_rank, trend_rank, final_sku_price, original_sku_price,
                        count_of_reviews, star_rating, count_of_star_ratings,
                        detailed_review_content, trade_in, sku_status,
                        number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
                        sku_popularity, retailer_membership_discounts,
                        rank_1, rank_2, summarized_review_content,
                        savings, offer, retailer_sku_name_similar, recommendation_intent,
                        number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
                    FROM hhp_retail_com
                    WHERE crawl_strdatetime::timestamp >= %s AND crawl_strdatetime::timestamp < %s
                      AND account_name = %s AND item IN ({placeholders})
                    ORDER BY item, crawl_strdatetime
                """
                expand_params = [str(start_date), str(next_date), retailer] + error_items
                cursor.execute(query, expand_params)
                rows = cursor.fetchall()
                hhp_fields = [
                    'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
                    'final_sku_price', 'original_sku_price',
                    'count_of_reviews', 'star_rating', 'count_of_star_ratings',
                    'detailed_review_content', 'trade_in', 'sku_status',
                    'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
                    'sku_popularity', 'retailer_membership_discounts',
                    'rank_1', 'rank_2', 'summarized_review_content',
                    'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
                    'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
                ]
                for row in rows:
                    record_id = row[0]
                    crawl_dt = row[1]
                    account_name = row[2]
                    values = list(row[3:])

                    record = {'id': record_id, 'crawl_datetime': str(crawl_dt) if crawl_dt else None}
                    for field, value in zip(hhp_fields, values):
                        record[field] = str(value) if value is not None else None

                    error_fields = []
                    error_details = {}
                    for field, value in zip(hhp_fields, values):
                        error = validate_hhp_field(field, value, account_name)
                        if error:
                            error_fields.append(field)
                            error_details[field] = {
                                'rule': error.split(':', 1)[0] if ':' in error else error,
                                'reason': error.split(':', 1)[1].strip() if ':' in error else error
                            }
                    record['error_fields'] = error_fields
                    record['error_details'] = error_details
                    results.append(record)

    # 수정 가능 컬럼 + actual_table 설정
    editable_cols = []
    actual_table = ''
    if table in ('tv_retail', 'hhp_retail') and retailer:
        product_line = 'tv' if table == 'tv_retail' else 'hhp'
        actual_table = 'tv_retail_com' if table == 'tv_retail' else 'hhp_retail_com'
        editable_cols = get_editable_columns(product_line, retailer)
    elif table in ('youtube_logs',) or (table == 'youtube' and retailer == 'Logs'):
        actual_table = 'youtube_collection_logs'
    elif table in ('youtube_videos',) or (table == 'youtube' and retailer == 'Videos'):
        actual_table = 'youtube_videos'
    elif table in ('youtube_comments',) or (table == 'youtube' and retailer == 'Comments'):
        actual_table = 'youtube_comments'
    elif table == 'market' and retailer:
        market_table_map = {
            'Trend': 'market_trend',
            'Comp Product': 'market_comp_product',
            'Comp Event': 'market_comp_event',
            'Forecast': 'openai_forecast_results',
        }
        actual_table = market_table_map.get(retailer, '')
        if actual_table in DISABLED_SOURCE_TABLES:
            actual_table = ''

    # 형식 검증 정상 처리 건 조회
    normal_reviews = {}
    if actual_table:
        cursor.execute("""
            SELECT record_id, column_name, memo, created_id, created_at, reason
            FROM monitoring_corrections
            WHERE table_name = %s AND crawl_date = %s
              AND correction_type = 'format_check' AND status = 'normal'
        """, (actual_table, str(target_date)))
        for nr_row in cursor.fetchall():
            normal_reviews[f"{nr_row[0]}_{nr_row[1]}"] = {
                'memo': nr_row[2],
                'created_id': nr_row[3],
                'created_at': nr_row[4].strftime('%Y-%m-%d %H:%M:%S') if nr_row[4] else None,
                'reason': nr_row[5]
            }

    # 정상 처리된 필드는 error_fields에서 제외 (null_detail의 normal_set 패턴)
    if normal_reviews:
        normal_set = set(normal_reviews.keys())
        for record in results:
            if 'error_fields' in record:
                record_id = record.get('id')
                record['error_fields'] = [
                    f for f in record['error_fields']
                    if f"{record_id}_{f}" not in normal_set
                ]

    # 필드별 건수 집계 (프론트에서 재계산하지 않도록 백엔드에서 계산)
    field_counts = {}
    total_format_count = 0
    for record in results:
        for field in record.get('error_fields', []):
            field_counts[field] = field_counts.get(field, 0) + 1
            total_format_count += 1

    return {
        'date': str(target_date),
        'table': table,
        'retailer': retailer,
        'column_names': column_names,
        'editable_cols': editable_cols,
        'actual_table': actual_table,
        'normal_reviews': normal_reviews,
        'results': results,
        'field_counts': field_counts,
        'total_format_count': total_format_count,
    }


# ── 형식 검증 규칙 조회 ──────────────────────────────────

def _get_description_for_type(rule_type, rule_value, allowed):
    """규칙 타입별 설명 생성"""
    if rule_type == 'regex':
        if rule_value == '^[A-Za-z0-9]+$':
            return '알파벳+숫자만 허용'
        elif '\\$' in rule_value:
            return '$금액 형식'
        elif '\\d' in rule_value:
            return '숫자 형식'
        elif 'http' in rule_value:
            return 'http:// 또는 https:// 시작'
        else:
            return '정규식 패턴'
    return '형식 검증'


def _get_tse_static_format_rules(product_line, retailer):
    retailer_key = str(retailer or '').strip().casefold()
    if retailer_key == 'lazada':
        return [
            dict(TSE_LAZADA_FORMAT_RULES[field])
            for field in get_tse_format_fields(product_line, retailer)
            if field in TSE_LAZADA_FORMAT_RULES
        ]
    if retailer_key == 'powerbuy':
        return [
            dict(rule) for rule in TSE_FORMAT_RULES
            if rule['field'] != 'savings'
        ]
    if retailer_key != 'lotuss':
        return [dict(rule) for rule in TSE_FORMAT_RULES]
    return [
        dict(TSE_LOTUSS_FORMAT_RULES[field])
        for field in get_tse_format_fields(product_line, retailer)
        if field in TSE_LOTUSS_FORMAT_RULES
    ]


def _get_siel_static_format_rules(source_key, retailer):
    fields = _get_siel_format_fields(source_key, retailer)
    rules = [
        dict(SIEL_FORMAT_RULE_DETAILS[field])
        for field in fields
        if field in SIEL_FORMAT_RULE_DETAILS
    ]
    retailer_key = str(retailer or '').strip().casefold()
    source = SIEL_SOURCE_CONFIG.get(source_key, {})
    retailer_value = _resolve_siel_format_retailer(source, retailer)
    for rule in rules:
        if rule['field'] == 'account_name' and retailer_value:
            rule['pattern'] = retailer_value
        elif rule['field'] == 'product':
            rule['pattern'] = source.get('category', '')
        elif rule['field'] == 'product_url':
            rule['pattern'] = (
                'https://www.amazon.in/dp/{ASIN}'
                if retailer_key == 'amazon' else
                'https://www.flipkart.com/{상품명}/p/{상품키}'
            )
        elif rule['field'] == 'star_rating':
            rule['pattern'] = (
                '4.3 / No customer reviews'
                if retailer_key == 'amazon' else '4.3'
            )
        elif retailer_key == 'amazon':
            if rule['field'] == 'final_sku_price':
                rule['description'] = '인도 루피 금액 또는 Amazon 가격 상태'
                rule['pattern'] = (
                    '₹10,999 / Currently unavailable. / '
                    'No featured offers available'
                )
    return rules


def get_format_rules(cursor, table_name, retailer):
    """
    형식검증 규칙 조회.
    Returns dict: {rules: [...]}
    """
    if table_name in TSE_SOURCE_CONFIG:
        return {
            'rules': _get_tse_static_format_rules(table_name, retailer)
        }
    if table_name in SIEL_SOURCE_CONFIG:
        return {
            'rules': _get_siel_static_format_rules(table_name, retailer)
        }

    tbl_rules = dx_table('monitoring_format_rules')
    tbl_templates = dx_table('monitoring_format_templates')

    cursor.execute(f"""
        SELECT r.column_name, t.check_type, t.pattern,
               r.rule_value, r.extra_allowed,
               r.error_message
        FROM {tbl_rules} r
        LEFT JOIN {tbl_templates} t ON r.template_id = t.id
        WHERE r.table_name = %s AND r.account_name = %s
          AND r.is_active = TRUE AND r.is_del = FALSE
          AND (t.id IS NULL OR t.is_active = TRUE)
        ORDER BY r.column_name
    """, (table_name, retailer))

    cols = [desc[0] for desc in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

    result = []
    for row in rows:
        check_type = row.get('check_type') or ''
        pattern = row.get('pattern') or ''
        rule_value = row.get('rule_value') or ''
        extra_allowed = row.get('extra_allowed') or ''
        error_message = row.get('error_message') or ''

        patterns = []
        description = ''

        # 메인 검증 규칙 (template 기반)
        if check_type:
            if check_type in ('regex', 'regex_clean'):
                effective_pattern = pattern or rule_value
                patterns.append(effective_pattern)
                description = error_message or _get_description_for_type(
                    check_type, effective_pattern, []
                )
            elif check_type == 'range':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} ~ {parts[1]}')
                    description = error_message or f'{parts[0]}~{parts[1]} 범위 정수'
            elif check_type == 'range_float':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} ~ {parts[1]}')
                    description = error_message or f'{parts[0]}~{parts[1]} 범위'
            elif check_type == 'enum':
                allowed_list = [v.strip() for v in rule_value.split('|') if v.strip()] if rule_value else []
                patterns.append(' | '.join(allowed_list))
                description = error_message or '허용값만'
            elif check_type == 'starts_with':
                patterns.append(f'"{rule_value}..."')
                description = error_message or f'{rule_value}로 시작'
            elif check_type == 'separator_count':
                parts = rule_value.split('~')
                if len(parts) == 2:
                    patterns.append(f'{parts[0]} 구분자 {parts[1]}개')
                    description = error_message or f'{parts[0]} 구분자 {parts[1]}개 필요'
            elif check_type == 'fk_check':
                patterns.append(f'참조: {rule_value}')
                description = error_message or 'FK 참조 검증'
            elif check_type == 'min':
                patterns.append(f'>= {rule_value}')
                description = error_message or f'{rule_value} 이상'

        # extra_allowed 표시
        if extra_allowed:
            allowed_list = [v.strip() for v in extra_allowed.split('|') if v.strip()]
            for val in allowed_list:
                patterns.append(f'"{val}"')

        if patterns:
            result.append({
                'field': row['column_name'],
                'description': description or '형식 검증',
                'pattern': '\n'.join(patterns)
            })

    # 필드명 알파벳순 정렬
    result.sort(key=lambda x: x['field'])

    return {'rules': result}


# ── 대시보드용 헬퍼 / 통계 ─────────────────────────────────

def get_tv_format_errors(cursor, table_name, date_field, target_date, retailer):
    """TV 형식 오류 데이터 조회 - validate_tv_field 기반"""
    errors = []
    all_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]
    cursor.execute(f"""
        SELECT
            id, item, {date_field}, product_url,
            page_type, main_rank, bsr_rank,
            final_sku_price, original_sku_price,
            count_of_reviews, star_rating, count_of_star_ratings,
            detailed_review_content,
            number_of_units_purchased_past_month, available_quantity_for_purchase,
            sku_popularity, retailer_membership_discounts,
            rank_1, rank_2, summarized_review_content,
            savings, offer, retailer_sku_name_similar, recommendation_intent,
            number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
        FROM {table_name}
        WHERE DATE({date_field}::timestamp) = %s
          AND account_name = %s
          AND {get_tv_validation_condition()}
        ORDER BY id
    """, (target_date, retailer))
    for row in cursor.fetchall():
        record_id = row[0]
        item = row[1]
        crawl_dt = row[2]
        product_url = row[3]
        values = [item] + list(row[4:])
        row_errors = []
        for field, value in zip(all_fields, values):
            error = validate_tv_field(field, value, retailer)
            if error:
                row_errors.append(field)
        if row_errors:
            errors.append({
                'id': record_id,
                'item': item,
                'error_field': ', '.join(row_errors),
                'error_value': ', '.join(row_errors),
                'collected_at': str(crawl_dt) if crawl_dt else None
            })
    return errors


def get_hhp_format_errors(cursor, table_name, date_field, target_date, retailer):
    """HHP 형식 오류 데이터 조회 - validate_hhp_field 기반"""
    errors = []
    hhp_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content', 'trade_in', 'sku_status',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]
    cursor.execute(f"""
        SELECT
            id, item, {date_field}, product_url,
            page_type, main_rank, bsr_rank, trend_rank,
            final_sku_price, original_sku_price,
            count_of_reviews, star_rating, count_of_star_ratings,
            detailed_review_content, trade_in, sku_status,
            number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
            sku_popularity, retailer_membership_discounts,
            rank_1, rank_2, summarized_review_content,
            savings, offer, retailer_sku_name_similar, recommendation_intent,
            number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
        FROM {table_name}
        WHERE DATE({date_field}::timestamp) = %s
          AND account_name = %s
        ORDER BY id
    """, (target_date, retailer))
    for row in cursor.fetchall():
        record_id = row[0]
        item = row[1]
        crawl_dt = row[2]
        product_url = row[3]
        values = [item] + list(row[4:])
        row_errors = []
        for field, value in zip(hhp_fields, values):
            error = validate_hhp_field(field, value, retailer)
            if error:
                row_errors.append(field)
        if row_errors:
            errors.append({
                'id': record_id,
                'item': item,
                'error_field': ', '.join(row_errors),
                'error_value': ', '.join(row_errors),
                'collected_at': str(crawl_dt) if crawl_dt else None
            })
    return errors


def get_format_stats(cursor, target_date):
    """형식 검증 통계 — 대시보드용"""

    total_format_issues = 0
    format_validation = {
        'type': 'format',
        'type_name': '형식 검증',
        'type_name_en': 'Format Validation',
        'description': '데이터 형식 및 패턴 검증',
        'icon': '📋',
        'tables': []
    }

    # tv_item_mst에서 유효한 item 목록 조회
    cursor.execute("SELECT DISTINCT item FROM tv_item_mst")
    tv_valid_items = set(row[0] for row in cursor.fetchall())

    # TV Retail 형식 검증 - 청크 단위 전수검사
    tv_format_errors = []
    tv_format_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    tv_format_total_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    tv_format_rows_count = 0

    all_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]

    CHUNK_SIZE = 5000
    tv_offset = 0
    while True:
        cursor.execute(f"""
            SELECT
                account_name, id, item, page_type, product_url,
                main_rank, bsr_rank, final_sku_price, original_sku_price,
                count_of_reviews, star_rating, count_of_star_ratings,
                detailed_review_content,
                number_of_units_purchased_past_month, available_quantity_for_purchase,
                sku_popularity, retailer_membership_discounts,
                rank_1, rank_2, summarized_review_content,
                savings, offer, retailer_sku_name_similar, recommendation_intent,
                number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
            FROM tv_retail_com
            WHERE DATE(crawl_datetime::timestamp) = %s
              AND {get_tv_validation_condition()}
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (target_date, CHUNK_SIZE, tv_offset))

        chunk = cursor.fetchall()
        if not chunk:
            break
        tv_format_rows_count += len(chunk)

        for row in chunk:
            account_name = row[0] or 'Unknown'
            item_value = row[2]
            errors = []

            if account_name in tv_format_total_by_retailer:
                tv_format_total_by_retailer[account_name] += 1
            else:
                tv_format_total_by_retailer[account_name] = 1

            values = list(row[2:])

            for field, value in zip(all_fields, values):
                error = validate_tv_field(field, value, account_name)
                if error:
                    errors.append({'field': field, 'value': str(value)[:30] if value else '', 'error': error})

            if item_value and item_value not in tv_valid_items:
                errors.append({
                    'field': 'item (참조 무결성)',
                    'value': str(item_value)[:30],
                    'error': '마스터 테이블에 등록되지 않은 item'
                })

            if errors:
                if len(tv_format_errors) < 30:
                    tv_format_errors.append({
                        'id': row[1],
                        'account_name': account_name,
                        'item': row[2],
                        'errors': errors[:5]
                    })
                if account_name in tv_format_by_retailer:
                    tv_format_by_retailer[account_name] += len(errors)
                else:
                    tv_format_by_retailer[account_name] = len(errors)

        tv_offset += CHUNK_SIZE

    tv_format_retailers = []
    tv_format_issue_total = 0
    for retailer, count in tv_format_by_retailer.items():
        tv_format_retailers.append({
            'retailer': retailer,
            'total': tv_format_total_by_retailer.get(retailer, 0),
            'issue_count': count,
            'status': get_status(count)
        })
        tv_format_issue_total += count

    format_validation['tables'].append({
        'table': 'tv_retail',
        'table_name': 'TV Retail',
        'total_checked': tv_format_rows_count,
        'total_issues': tv_format_issue_total,
        'status': get_status(tv_format_issue_total),
        'retailers': tv_format_retailers,
        'sample_errors': tv_format_errors
    })
    total_format_issues += tv_format_issue_total

    # hhp_item_mst
    hhp_valid_items = set()

    # HHP Retail - 청크 단위 전수검사
    hhp_format_errors = []
    hhp_format_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    hhp_format_total_by_retailer = {'Amazon': 0, 'Bestbuy': 0, 'Walmart': 0}
    hhp_format_rows_count = 0

    hhp_fields = [
        'item', 'page_type', 'product_url', 'main_rank', 'bsr_rank', 'trend_rank',
        'final_sku_price', 'original_sku_price',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'detailed_review_content', 'trade_in', 'sku_status',
        'number_of_units_purchased_past_month', 'available_quantity_for_purchase', 'delivery_availability',
        'sku_popularity', 'retailer_membership_discounts',
        'rank_1', 'rank_2', 'summarized_review_content',
        'savings', 'offer', 'retailer_sku_name_similar', 'recommendation_intent',
        'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts', 'discount_type'
    ]

    hhp_offset = 0
    while False:
        cursor.execute("""
            SELECT
                account_name, id, item, page_type, product_url,
                main_rank, bsr_rank, trend_rank, final_sku_price, original_sku_price,
                count_of_reviews, star_rating, count_of_star_ratings,
                detailed_review_content, trade_in, sku_status,
                number_of_units_purchased_past_month, available_quantity_for_purchase, delivery_availability,
                sku_popularity, retailer_membership_discounts,
                rank_1, rank_2, summarized_review_content,
                savings, offer, retailer_sku_name_similar, recommendation_intent,
                number_of_ppl_purchased_yesterday, number_of_ppl_added_to_carts, discount_type
            FROM hhp_retail_com
            WHERE DATE(crawl_strdatetime::timestamp) = %s
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (target_date, CHUNK_SIZE, hhp_offset))

        chunk = cursor.fetchall()
        if not chunk:
            break
        hhp_format_rows_count += len(chunk)

        for row in chunk:
            account_name = row[0] or 'Unknown'
            item_value = row[2]
            errors = []

            if account_name in hhp_format_total_by_retailer:
                hhp_format_total_by_retailer[account_name] += 1
            else:
                hhp_format_total_by_retailer[account_name] = 1

            values = list(row[2:])

            for field, value in zip(hhp_fields, values):
                error = validate_hhp_field(field, value, account_name)
                if error:
                    errors.append({'field': field, 'value': str(value)[:30] if value else '', 'error': error})

            if item_value and item_value not in hhp_valid_items:
                errors.append({
                    'field': 'item (참조 무결성)',
                    'value': str(item_value)[:30],
                    'error': '마스터 테이블에 등록되지 않은 item'
                })

            if errors:
                if len(hhp_format_errors) < 30:
                    hhp_format_errors.append({
                        'id': row[1],
                        'account_name': account_name,
                        'item': row[2],
                        'errors': errors[:5]
                    })
                if account_name in hhp_format_by_retailer:
                    hhp_format_by_retailer[account_name] += len(errors)
                else:
                    hhp_format_by_retailer[account_name] = len(errors)

        hhp_offset += CHUNK_SIZE

    hhp_format_retailers = []
    hhp_format_issue_total = 0
    for retailer, count in hhp_format_by_retailer.items():
        hhp_format_retailers.append({
            'retailer': retailer,
            'total': hhp_format_total_by_retailer.get(retailer, 0),
            'issue_count': count,
            'status': get_status(count)
        })
        hhp_format_issue_total += count

    format_validation['tables'].append({
        'table': 'hhp_retail',
        'table_name': 'HHP Retail',
        'total_checked': hhp_format_rows_count,
        'total_issues': hhp_format_issue_total,
        'status': get_status(hhp_format_issue_total),
        'retailers': hhp_format_retailers,
        'sample_errors': hhp_format_errors
    })
    total_format_issues += hhp_format_issue_total
    format_validation['tables'] = [t for t in format_validation['tables'] if t.get('table') != 'hhp_retail']
    total_format_issues -= hhp_format_issue_total

    # Market 형식 검증
    try:
        configured_market_tables = [
            ('market_trend', 'Trend', 'crawl_at_local_time'),
            ('market_comp_product', 'Comp Product', 'created_at'),
            ('market_comp_event', 'Comp Event', 'created_at'),
            ('openai_forecast_results', 'Forecast', 'crawled_at'),
        ]
        # 수집 재개 시 공통 비활성화 목록에서 테이블을 제거하면 자동 복구된다.
        market_tables = [
            item for item in configured_market_tables
            if item[0] not in DISABLED_SOURCE_TABLES
        ]
        market_total_format_issues = 0
        market_total_format_checked = 0
        market_format_retailers = []

        for mkt_table, mkt_retailer, mkt_date_col in market_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {mkt_table} WHERE DATE({mkt_date_col}) = %s", (target_date,))
            mkt_total = cursor.fetchone()[0] or 0

            error_where = build_format_error_sql(mkt_table, 'ALL', mkt_retailer)
            if error_where != 'FALSE':
                cursor.execute(f"SELECT COUNT(*) FROM {mkt_table} WHERE DATE({mkt_date_col}) = %s AND ({error_where})", (target_date,))
                mkt_issues = cursor.fetchone()[0] or 0
            else:
                mkt_issues = 0

            market_total_format_checked += mkt_total
            market_total_format_issues += mkt_issues
            market_format_retailers.append({
                'retailer': mkt_retailer,
                'total': mkt_total,
                'issue_count': mkt_issues,
                'status': get_status(mkt_issues),
            })

        if market_format_retailers:
            format_validation['tables'].append({
                'table': 'market',
                'table_name': 'Market',
                'total_checked': market_total_format_checked,
                'total_issues': market_total_format_issues,
                'status': get_status(market_total_format_issues),
                'retailers': market_format_retailers
            })
            total_format_issues += market_total_format_issues
    except Exception as e:
        print(f'[WARN] layer_stats market_format: {e}')

    total_format_issues += _append_sea_format_stats(
        cursor, target_date, format_validation
    )

    total_format_issues += _append_siel_format_stats(
        cursor, target_date, format_validation
    )

    total_format_issues += _append_tse_format_stats(
        cursor, target_date, format_validation
    )

    format_validation['total_issues'] = total_format_issues
    format_validation['status'] = get_status(total_format_issues)

    return format_validation, total_format_issues
