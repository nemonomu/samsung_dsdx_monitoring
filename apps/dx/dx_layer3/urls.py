from django.urls import path
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from .dashboard import views as dashboard_views, api as dashboard_api
from .time_series import views as ts_views, api as ts_api
from .cross_field import views as cf_views, api as cf_api
from .category_spec import views as cs_views, api as cs_api
from .field_missing import views as fm_views, api as fm_api
from .data_edit import api as edit_api

app_name = 'layer3'

urlpatterns = [
    # 페이지
    path('', dashboard_views.dashboard, name='dashboard'),
    path('time-series/', ts_views.time_series, name='time_series'),
    path('cross-field/', cf_views.cross_field, name='cross_field'),
    path('category-spec/', cs_views.category_spec, name='category_spec'),
    path('field-missing/', fm_views.field_missing, name='field_missing'),

    # API — 대시보드
    path('api/stats/', dashboard_api.layer_stats, name='api_stats'),

    # API — 시계열
    path('api/time-series-detail/', ts_api.time_series_detail, name='api_time_series_detail'),
    path('api/duplicate-detail/', ts_api.duplicate_detail, name='api_duplicate_detail'),
    path('api/review-change-detail/', ts_api.review_change_detail, name='api_review_change_detail'),
    path('api/price-anomalies/', ts_api.price_anomalies, name='api_price_anomalies'),
    path('api/price-changes/', ts_api.price_changes, name='api_price_changes'),

    # API — 크로스 필드
    path('api/cross-field-detail/', cf_api.cross_field_detail, name='api_cross_field_detail'),
    path('api/tse-crossfield-summary/', cf_api.tse_crossfield_summary, name='api_tse_crossfield_summary'),
    path('api/sentiment-cross-detail/', cf_api.sentiment_cross_detail, name='api_sentiment_cross_detail'),
    path('api/crossfield-rules/', cf_api.crossfield_rules, name='api_crossfield_rules'),

    # API — 카테고리별 특성
    path('api/category-spec-detail/', cs_api.category_spec_detail, name='api_category_spec_detail'),
    path('api/category-rules/', cs_api.category_rules, name='api_category_rules'),

    # API — 필드 누락
    path('api/field-missing/', fm_api.field_missing_detection, name='api_field_missing'),
    path('api/field-missing-detail-all/', fm_api.field_missing_detail_all, name='api_field_missing_detail_all'),
    path('api/field-missing-detail-problem/', fm_api.field_missing_detail_problem, name='api_field_missing_detail_problem'),
    path('api/field-missing-detail-by-field/', fm_api.field_missing_detail_by_field, name='api_field_missing_detail_by_field'),

    # API — 셀 수정 / 정상 처리
    path('api/update-cell/', edit_api.update_cell, name='api_update_cell'),
    path('api/review/', edit_api.review, name='api_review'),
    path('api/review-reasons/', edit_api.review_reasons, name='api_review_reasons'),
]

if 'market_comp_product' not in DISABLED_SOURCE_TABLES:
    urlpatterns.append(path(
        'api/comp-product-cross-detail/',
        cf_api.comp_product_cross_detail,
        name='api_comp_product_cross_detail',
    ))
