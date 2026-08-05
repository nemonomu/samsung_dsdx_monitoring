"""
Layer 1 공통 context — 상수 및 사이드바 헬퍼
"""

from apps.common.dx_schedules import load_collection_schedules
from apps.common.monitoring_exclusions import DISABLED_CHECK_TYPES

LAYER_CONTEXT = {
    'number': 1,
    'name': '기본 통계 검수',
    'name_en': 'Foundational Integrity Check',
    'color': '#1a365d',
}

# check_type → 섹션 페이지 표시명 (기본값, DB에 check_name이 없을 때 사용)
SECTION_TITLES = {
    'dashboard': '대시보드',
    'retail': 'Retail',
    'sentiment': 'Retail 감성분석',
    'youtube': 'YouTube',
    'market_trend': 'Market Trend',
    'market_demand': 'Market 수요증감율',
    'market_competitor': 'Market Competitor',
    'market_competitor_event': 'Market Competitor Event',
    'market_promotion': 'Market Promotion',
    'macro_capital_stock': '자본 스톡(실질, PPP)',
    'macro_net_interest': '민간부문 순 이자수입',
    'macro_potential_gdp': '잠재적 산출량',
    'macro_gdp_ppp_nominal': '명목 GDP(PPP) 1인당',
    'macro_gdp_ppp_real': '실질 GDP(PPP) 1인당',
    'macro_disposable_income_real': '가처분소득(실질, PPP)',
    'macro_cpi': '소비자 물가 지수',
    'macro_disposable_income_nominal': '가처분소득(명목, LCU)',
    'macro_household_debt': '가계부문 금융부채',
    'macro_rpi': '소매 가격 지수',
}


def _build_sidebar_groups(section):
    """스케줄 DB에서 동적으로 사이드바 그룹 생성"""
    schedules = load_collection_schedules()

    daily_sections = []
    period_sections = []
    seen = set()

    for s in schedules:
        ct = s['check_type']
        if ct in DISABLED_CHECK_TYPES:
            continue
        if ct in seen:
            continue
        seen.add(ct)
        title = SECTION_TITLES.get(ct, ct)
        if s['schedule_type'] == 'daily':
            daily_sections.append({'name': title, 'active': section == ct})
        else:
            period_sections.append({'name': title, 'active': section == ct})

    daily_keys = [ct for ct in seen if ct in [s['check_type'] for s in schedules if s['schedule_type'] == 'daily']]
    period_keys = [ct for ct in seen if ct not in daily_keys]

    groups = []
    if daily_sections:
        groups.append({
            'key': 'daily',
            'icon': '📦',
            'label': '데일리 검증',
            'expanded': section in daily_keys,
            'active': section in daily_keys,
            'items': daily_sections,
        })
    if period_sections:
        groups.append({
            'key': 'period',
            'icon': '📅',
            'label': '분석대상일별 검증',
            'expanded': section in period_keys,
            'active': section in period_keys,
            'items': period_sections,
        })
    return groups


def build_context(section, request):
    return {
        'layer': LAYER_CONTEXT,
        'section': section,
        'section_title': SECTION_TITLES.get(section, ''),
        'section_titles': SECTION_TITLES,
        'target_date': request.GET.get('date', ''),
        'sidebar_title': 'Layer 1 검증',
        'sidebar_base_url': '/dx/layer1/',
        'sidebar_groups': _build_sidebar_groups(section),
    }
