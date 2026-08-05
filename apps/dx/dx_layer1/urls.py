from django.urls import path, include
from django.shortcuts import redirect
from apps.dx.dx_layer1.common import api as check_api
from apps.common.monitoring_exclusions import DISABLED_CHECK_TYPES

app_name = 'layer1'

urlpatterns = [
    path('', include('apps.dx.dx_layer1.dashboard.urls')),
    path('retail/', include('apps.dx.dx_layer1.retail.urls')),
    path('sentiment/', include('apps.dx.dx_layer1.sentiment.urls')),
    path('youtube/', include('apps.dx.dx_layer1.youtube.urls')),
    path('macro/', include('apps.dx.dx_layer1.macro.urls')),
    path('check-log/', lambda request: redirect('/dx/layer4/check-log/', permanent=True)),

    # 검수 확인/완료 API
    path('api/check/status/', check_api.check_status, name='api_check_status'),
    path('api/check/save/', check_api.check_save, name='api_check_save'),
    path('api/check/delete/', check_api.check_delete, name='api_check_delete'),
]

# 수집이 재개되면 공통 비활성화 목록에서 항목을 제거하면 URL도 복구된다.
_OPTIONAL_MARKET_ROUTES = (
    ('market_trend', 'market-trend/', 'apps.dx.dx_layer1.market_trend.urls'),
    ('market_demand', 'market-demand/', 'apps.dx.dx_layer1.market_demand.urls'),
    ('market_competitor', 'market-competitor/', 'apps.dx.dx_layer1.market_competitor.urls'),
    ('market_competitor_event', 'market-competitor-event/', 'apps.dx.dx_layer1.market_competitor_event.urls'),
    ('market_promotion', 'market-promotion/', 'apps.dx.dx_layer1.market_promotion.urls'),
)
for check_type, route, urlconf in _OPTIONAL_MARKET_ROUTES:
    if check_type not in DISABLED_CHECK_TYPES:
        urlpatterns.append(path(route, include(urlconf)))
