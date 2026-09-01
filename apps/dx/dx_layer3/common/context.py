"""
Layer 3 공통 컨텍스트 빌더 — 사이드바, 레이아웃 등
"""

from apps.dx.dx_layer3.dashboard.services import (
    load_timeseries_rules,
    load_crossfield_rules,
    load_category_rules,
)
from apps.common.tse_retail import TSE_SOURCE_CONFIG


LAYER_CONTEXT = {
    'number': 3,
    'name': '이상치/특수 케이스 검수',
    'name_en': 'Outlier & Anomaly Detection',
    'color': '#d97706',
}

SECTION_TITLES = {
    'dashboard': '대시보드',
    'time_series': '시계열 이상치',
    'cross_field': '크로스 필드 검증',
    'category_spec': '카테고리별 특성',
    'field_missing': '필드 누락',
}


def _get_sidebar_items():
    """사이드바 하위항목 — 규칙 정의에서 이름 목록 추출 (데이터 조회 없음)"""
    sidebar = {}

    ts_rules = load_timeseries_rules()
    sidebar['time_series'] = []
    seen_ts = set()
    for r in ts_rules:
        name = r['detail_name']
        if name not in seen_ts:
            seen_ts.add(name)
            sidebar['time_series'].append({'name': name, 'detail_code': r['detail_code']})

    crossfield_rules = load_crossfield_rules()
    sea_sections = {
        'tv_retail': {
            'name': 'SEA Retail', 'label': 'TV', 'detail_code': 'tv',
        },
        'sea_ref_retail': {
            'name': 'SEA REF', 'label': 'REF', 'detail_code': 'sea_ref',
        },
        'sea_ldy_retail': {
            'name': 'SEA LDY', 'label': 'LDY', 'detail_code': 'sea_ldy',
        },
    }
    tse_section_codes = {
        source['section_code'] for source in TSE_SOURCE_CONFIG.values()
    }
    crossfield_items = []
    seen_crossfield_sections = set()
    sea_item_index = None
    for rule in crossfield_rules:
        section_code = str(rule.get('section_code') or '').strip()
        section_name = str(rule.get('section_name') or '').strip()
        if section_code in sea_sections:
            if sea_item_index is None:
                sea_item_index = len(crossfield_items)
            continue
        if not section_name or section_code in tse_section_codes:
            continue

        identity = section_code or section_name
        if identity in seen_crossfield_sections:
            continue
        seen_crossfield_sections.add(identity)

        crossfield_items.append(section_name)

    active_sections = {
        str(rule.get('section_code') or '').strip()
        for rule in crossfield_rules
    }
    sea_children = [
        dict(child)
        for section_code, child in sea_sections.items()
        if section_code in active_sections
    ]
    if sea_children:
        if sea_item_index is None:
            sea_item_index = len(crossfield_items)
        crossfield_items.insert(sea_item_index, {
            'name': 'SEA Retail',
            'children': sea_children,
        })

    active_tse_sections = active_sections
    tse_children = []
    for detail_code, source in TSE_SOURCE_CONFIG.items():
        if source['section_code'] not in active_tse_sections:
            continue
        tse_children.append({
            'name': source['display_name'],
            'label': source['category'],
            'detail_code': detail_code,
        })
    if tse_children:
        tse_item = {
            'name': 'TSE Retail',
            'children': tse_children,
        }
        insert_at = (
            sea_item_index + 1
            if sea_item_index is not None
            else len(crossfield_items)
        )
        crossfield_items.insert(insert_at, tse_item)

    sidebar['cross_field'] = crossfield_items

    sidebar['category_spec'] = list(dict.fromkeys(
        r['section_name'] for r in load_category_rules() if r.get('section_name')
    ))

    sidebar['field_missing'] = ['TV']

    return sidebar


def _build_sidebar_groups(section, focus='', detail_code=''):
    sidebar = _get_sidebar_items()

    crossfield_items = []
    for item in sidebar['cross_field']:
        if not isinstance(item, dict):
            crossfield_items.append({'name': item, 'active': False})
            continue

        if not item.get('children'):
            item_detail_code = item.get('detail_code', '')
            crossfield_items.append({
                'name': item['name'],
                'detail_code': item_detail_code,
                'active': (
                    section == 'cross_field'
                    and (
                        focus == item['name']
                        or (item_detail_code and detail_code == item_detail_code)
                    )
                ),
            })
            continue

        children = []
        for child in item.get('children', []):
            child_item = dict(child)
            child_item['active'] = (
                section == 'cross_field'
                and (
                    focus == child['name']
                    or detail_code == child['detail_code']
                )
            )
            children.append(child_item)
        crossfield_items.append({
            'name': item['name'],
            'active': any(child['active'] for child in children),
            'children': children,
        })
    return [
        {'key': 'time_series', 'icon': '📈', 'label': '시계열 이상치',
         'expanded': section == 'time_series', 'active': section == 'time_series',
         'items': [{'name': n['name'], 'detail_code': n['detail_code'], 'active': False} for n in sidebar['time_series']]},
        {'key': 'cross_field', 'icon': '🔗', 'label': '크로스 필드 검증',
         'expanded': section == 'cross_field', 'active': section == 'cross_field',
         'items': crossfield_items},
        {'key': 'category_spec', 'icon': '📋', 'label': '카테고리별 특성',
         'expanded': section == 'category_spec', 'active': section == 'category_spec',
         'items': [{'name': n, 'active': False} for n in sidebar['category_spec']]},
        {'key': 'field_missing', 'icon': '🔍', 'label': '필드 누락',
         'expanded': section == 'field_missing', 'active': section == 'field_missing',
         'items': [{'name': n, 'active': False} for n in sidebar['field_missing']]},
    ]


def build_context(section, request):
    focus = request.GET.get('focus', '')
    detail_code = request.GET.get('detail_code', '')
    return {
        'layer': LAYER_CONTEXT,
        'section': section,
        'section_title': SECTION_TITLES.get(section, ''),
        'target_date': request.GET.get('date', ''),
        'sidebar_items': _get_sidebar_items(),
        'sidebar_title': 'Layer 3 검증',
        'sidebar_base_url': '/dx/layer3/',
        'sidebar_groups': _build_sidebar_groups(section, focus, detail_code),
    }
