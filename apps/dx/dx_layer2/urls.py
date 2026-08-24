from django.urls import path
from apps.dx.dx_layer2.dashboard import views as dashboard_views, api as dashboard_api
from apps.dx.dx_layer2.null_validation import views as null_views, api as null_api
from apps.dx.dx_layer2.format_validation import views as format_views, api as format_api
from apps.dx.dx_layer2.anomaly_validation import views as anomaly_views, api as anomaly_api
from apps.dx.dx_layer2.data_edit import api as data_edit_api

app_name = 'layer2'

urlpatterns = [
    # 페이지
    path('', dashboard_views.dashboard, name='dashboard'),
    path('null/', null_views.null_validation, name='null_validation'),
    path('format/', format_views.format_validation, name='format_validation'),
    path('anomaly/', anomaly_views.anomaly_validation, name='anomaly_validation'),
    path('review-log/', null_views.null_review_log, name='null_review_log'),
    # APIs — 기존 경로 유지
    path('api/stats/', dashboard_api.layer_stats, name='api_stats'),
    path('api/detail/', dashboard_api.retailer_detail, name='api_detail'),
    path('api/null-detail/', null_api.null_detail, name='api_null_detail'),
    path('api/null-review/', null_api.null_review, name='api_null_review'),
    path('api/null-review-logs/', null_api.null_review_logs, name='api_null_review_logs'),
    path('api/format-detail/', format_api.format_detail, name='api_format_detail'),
    path('api/format-rules/', format_api.format_rules, name='api_format_rules'),
    path('api/anomaly-detail/', anomaly_api.anomaly_detail, name='api_anomaly_detail'),
    path('api/duplicate-cleanup/', anomaly_api.duplicate_cleanup, name='api_duplicate_cleanup'),
    path('api/update-cell/', data_edit_api.update_cell, name='api_update_cell'),
    path('api/review-reasons/', data_edit_api.review_reasons, name='api_review_reasons'),
]
