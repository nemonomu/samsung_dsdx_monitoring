"""
Layer 2 공통 상수 및 컨텍스트
"""


LAYER_CONTEXT = {
    'number': 2,
    'name': '형식/NULL 검수',
    'name_en': 'Formatting & Null Validation',
    'color': '#0d9488',
}

SECTION_TITLES = {
    'dashboard': '대시보드',
    'null_validation': 'NULL 검증',
    'format_validation': '형식 검증',
    'anomaly_validation': '중복 검증',
}


TSE_NULL_SIDEBAR_CHILDREN = (
    {
        'name': 'TSE TV',
        'label': 'TV',
        'detail_code': 'tse_tv_retail',
    },
    {
        'name': 'TSE REF',
        'label': 'REF',
        'detail_code': 'tse_ref_retail',
    },
    {
        'name': 'TSE LDY',
        'label': 'LDY',
        'detail_code': 'tse_ldy_retail',
    },
)



def get_status(issue_count):
    """상태 기준: 0건 = OK, 1건 이상 = CRITICAL"""
    return 'OK' if issue_count == 0 else 'CRITICAL'


def get_sidebar_items():
    """사이드바 하위항목 — 카테고리 목록에서 추출 (데이터 조회 없음)"""
    from apps.dx.dx_layer2.null_validation.services import load_null_check_config
    config = load_null_check_config()
    items = [{'key': c, 'name': info['display_name']} for c, info in config.items()]
    return {'null': items, 'format': items, 'anomaly': items}


def build_sidebar_groups(section, focus=''):
    from apps.dx.dx_layer2.null_validation.services import (
        get_all_categories,
        load_null_check_config,
    )
    config = load_null_check_config()

    def make_items(sec):
        return [{'name': info['display_name'], 'active': section == sec and info['display_name'] == focus} for info in config.values()]

    null_items = make_items('null_validation')
    active_categories = set(get_all_categories())
    tse_children = []
    for child in TSE_NULL_SIDEBAR_CHILDREN:
        if child['detail_code'] not in active_categories:
            continue
        child_item = dict(child)
        child_item['active'] = (
            section == 'null_validation'
            and focus in (child['name'], child['detail_code'])
        )
        tse_children.append(child_item)

    if tse_children:
        null_items.append({
            'name': 'TSE',
            'active': any(child['active'] for child in tse_children),
            'children': tse_children,
        })

    return [
        {'key': 'null_validation', 'icon': '🔍', 'label': 'NULL 검증',
         'expanded': section == 'null_validation', 'active': section == 'null_validation', 'items': null_items},
        {'key': 'format_validation', 'icon': '📋', 'label': '형식 검증',
         'expanded': section == 'format_validation', 'active': section == 'format_validation', 'items': make_items('format_validation')},
        {'key': 'anomaly_validation', 'icon': '🔄', 'label': '중복 검증',
         'expanded': section == 'anomaly_validation', 'active': section == 'anomaly_validation', 'items': make_items('anomaly_validation')},
    ]


def build_context(section, request):
    focus = request.GET.get('focus', '')
    return {
        'layer': LAYER_CONTEXT,
        'section': section,
        'section_title': SECTION_TITLES.get(section, ''),
        'target_date': request.GET.get('date', ''),
        'sidebar_items': get_sidebar_items(),
        'sidebar_title': 'Layer 2 검증',
        'sidebar_base_url': '/dx/layer2/',
        'sidebar_groups': build_sidebar_groups(section, focus),
    }
