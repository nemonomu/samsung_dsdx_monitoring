"""
DX 데이터 관리
- 아이템 마스터 관리 (is_product 분류)
- 변경 이력 조회
"""

from django.shortcuts import render, redirect


def index(request):
    """데이터 관리 인덱스 → 아이템 마스터로 리다이렉트"""
    return redirect('dx_data:item_master')


def item_master(request):
    """아이템 마스터 관리 페이지"""
    context = {}
    return render(request, 'dx_data/item_master.html', context)


def redirect_data(request):
    """Amazon redirect 데이터 읽기 전용 조회 페이지"""
    return render(request, 'dx_data/redirect_data.html', {})



def history(request):
    """변경 이력 페이지"""
    context = {
        'extra_filters': [
            {
                'id': 'filterField',
                'options': [
                    {'value': '', 'label': '변경 필드 (전체)'},
                    {'value': 'is_product', 'label': '제품여부'},
                    {'value': 'is_checked', 'label': '확인완료'},
                ],
            },
            {
                'id': 'filterAccount',
                'options': [
                    {'value': '', 'label': '리테일러 (전체)'},
                    {'value': 'Amazon', 'label': 'Amazon'},
                    {'value': 'Bestbuy', 'label': 'Bestbuy'},
                    {'value': 'Walmart', 'label': 'Walmart'},
                ],
            },
        ],
    }
    return render(request, 'dx_data/history.html', context)
