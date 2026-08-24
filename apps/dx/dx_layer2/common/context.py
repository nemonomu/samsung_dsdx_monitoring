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
    'null_review_log': 'NULL 검수 로그',
}


TSE_RETAIL_SIDEBAR_CHILDREN = (
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

SEA_RETAIL_SIDEBAR_CHILD = {
    'name': 'SEA Retail',
    'label': 'TV',
    'detail_code': 'tv_retail',
}


DISPLAY_NAME_OVERRIDES = {
    'tv_retail': 'SEA Retail',
}


def _get_display_name(category, info):
    return DISPLAY_NAME_OVERRIDES.get(category, info['display_name'])


def _legacy_display_order(category):
    """Keep SEA first and YouTube immediately behind the TSE group."""
    return {
        'tv_retail': 0,
        'youtube': 2,
    }.get(category, 3)



def get_status(issue_count):
    """상태 기준: 0건 = OK, 1건 이상 = CRITICAL"""
    return 'OK' if issue_count == 0 else 'CRITICAL'


def get_sidebar_items():
    """사이드바 하위항목 — 카테고리 목록에서 추출 (데이터 조회 없음)"""
    from apps.dx.dx_layer2.null_validation.services import load_null_check_config
    config = load_null_check_config()
    items = [
        {'key': category, 'name': _get_display_name(category, info)}
        for category, info in sorted(
            config.items(), key=lambda item: _legacy_display_order(item[0])
        )
    ]
    return {'null': items, 'format': items, 'anomaly': items}


def build_sidebar_groups(section, focus=''):
    from apps.dx.dx_layer2.null_validation.services import (
        get_all_categories,
        load_null_check_config,
    )
    config = load_null_check_config()

    def make_items(sec):
        items = []
        for category, info in sorted(
            config.items(), key=lambda item: _legacy_display_order(item[0])
        ):
            display_name = _get_display_name(category, info)
            item_active = (
                section == sec
                and focus in (
                    display_name, info['display_name'], category,
                )
            )
            if category == 'tv_retail':
                sea_child = dict(SEA_RETAIL_SIDEBAR_CHILD)
                sea_child['active'] = item_active
                items.append({
                    'name': 'SEA Retail',
                    'active': item_active,
                    'children': [sea_child],
                })
                continue
            items.append({
                'name': display_name,
                'active': item_active,
            })
        return items

    section_items = {
        'null_validation': make_items('null_validation'),
        'format_validation': make_items('format_validation'),
        'anomaly_validation': make_items('anomaly_validation'),
    }
    section_items['anomaly_validation'].append({
        'name': 'NULL 검수 로그',
        'active': section == 'null_review_log',
        'href': '/dx/layer2/review-log/',
    })
    active_categories = set(get_all_categories())
    for section_name, items in section_items.items():
        tse_children = []
        for child in TSE_RETAIL_SIDEBAR_CHILDREN:
            if child['detail_code'] not in active_categories:
                continue
            child_item = dict(child)
            child_item['active'] = (
                section == section_name
                and focus in (child['name'], child['detail_code'])
            )
            tse_children.append(child_item)

        if not tse_children:
            continue
        tse_parent = {
            'name': 'TSE Retail',
            'active': any(child['active'] for child in tse_children),
            'children': tse_children,
        }
        youtube_index = next(
            (
                index for index, item in enumerate(items)
                if item['name'] == _get_display_name(
                    'youtube', config.get('youtube', {'display_name': 'YouTube'})
                )
            ),
            len(items),
        )
        items.insert(youtube_index, tse_parent)

    return [
        {'key': 'null_validation', 'icon': '🔍', 'label': 'NULL 검증',
         'expanded': section == 'null_validation', 'active': section == 'null_validation', 'items': section_items['null_validation']},
        {'key': 'format_validation', 'icon': '📋', 'label': '형식 검증',
         'expanded': section == 'format_validation', 'active': section == 'format_validation', 'items': section_items['format_validation']},
        {'key': 'anomaly_validation', 'icon': '🔄', 'label': '중복 검증',
         'expanded': section in ('anomaly_validation', 'null_review_log'),
         'active': section in ('anomaly_validation', 'null_review_log'),
         'items': section_items['anomaly_validation']},
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
