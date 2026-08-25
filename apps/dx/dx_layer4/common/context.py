"""
Layer 4 공통 컨텍스트 빌더 — 사이드바, 레이아웃 등
"""

LAYER_CONTEXT = {
    'number': 4,
    'name': '검수 확인',
    'name_en': 'Review & Report',
    'color': '#764ba2',
}

SECTION_TITLES = {
    'dashboard': '대시보드',
    'check_log': '마감기록',
    'corrections': '검수기록',
    'report': '보고서',
    'collection_status': '수집 현황',
    'unified_inspection': '통합 검수',
    'tools': '도구',
}


def _build_sidebar_groups(section, focus=''):
    return [
        {
            'key': 'unified_inspection',
            'icon': '🗓️',
            'label': '통합 검수',
            'href': '/dx/layer4/unified-inspection/',
            'ignore_target_date': True,
            'active': section == 'unified_inspection',
        },
        {
            'key': 'check_log',
            'icon': '✅',
            'label': '마감기록',
            'expanded': section == 'check_log',
            'active': section == 'check_log',
            'items': [
                {'name': '전체 현황', 'active': section == 'check_log'},
            ],
        },
        {
            'key': 'corrections',
            'icon': '📝',
            'label': '검수기록',
            'expanded': section == 'corrections',
            'active': section == 'corrections',
            'items': [
                {'name': 'NULL 검수', 'active': section == 'corrections' and focus == 'NULL 검수'},
                {'name': '형식 검수', 'active': section == 'corrections' and focus == '형식 검수'},
                {'name': '중복 검수', 'active': section == 'corrections' and focus == '중복 검수'},
                {'name': '크로스필드 검수', 'active': section == 'corrections' and focus == '크로스필드 검수'},
                {'name': '누락필드 검수', 'active': section == 'corrections' and focus == '누락필드 검수'},
            ],
        },
        {
            'key': 'report',
            'icon': '📋',
            'label': '보고서',
            'expanded': section == 'report',
            'active': section == 'report',
            'items': [
                {'name': '일일 보고서', 'active': section == 'report'},
            ],
        },
        {
            'key': 'collection_status',
            'icon': '📊',
            'label': '수집 현황',
            'expanded': section == 'collection_status',
            'active': section == 'collection_status',
            'items': [
                {'name': '일일 수집 현황', 'active': section == 'collection_status' and focus == '일일 수집 현황'},
                {'name': '항목별 NULL 현황', 'active': section == 'collection_status' and focus == '항목별 NULL 현황'},
                {'name': '이메일 보고', 'active': section == 'collection_status' and focus == '이메일 보고'},
            ],
        },
        {
            'key': 'tools',
            'icon': '🛠',
            'label': '도구',
            'expanded': section == 'tools',
            'active': section == 'tools',
            'items': [
                {'name': '리뷰 변환', 'active': section == 'tools' and focus == '리뷰 변환'},
                {'name': 'HTML 파서', 'active': section == 'tools' and focus == 'HTML 파서'},
            ],
        },
    ]


def build_context(section, request):
    focus = request.GET.get('focus', '')
    is_admin = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    return {
        'layer': LAYER_CONTEXT,
        'section': section,
        'section_title': SECTION_TITLES.get(section, ''),
        'target_date': request.GET.get('date', ''),
        'focus': focus,
        'sidebar_title': 'Layer 4 검수',
        'sidebar_base_url': '/dx/layer4/',
        'sidebar_groups': _build_sidebar_groups(section, focus),
        'is_admin': is_admin,
    }
