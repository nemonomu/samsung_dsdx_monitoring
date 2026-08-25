from django.urls import path
from .dashboard import views as dashboard_views, api as dashboard_api
from .check_log import views as cl_views, api as cl_api
from .corrections import views as corr_views, api as corr_api
from .report import views as report_views, api as report_api
from .tools import views as tools_views
from .collection_status import views as cs_views, api as cs_api
from .collection_issues import api as ci_api
from .unified_inspection import views as ui_views, api as ui_api

app_name = 'layer4'

urlpatterns = [
    # 페이지
    path('', dashboard_views.dashboard, name='dashboard'),
    path('check-log/', cl_views.check_log, name='check_log'),
    path('check-log/detail/', cl_views.check_log_detail, name='check_log_detail'),
    path('corrections/', corr_views.corrections, name='corrections'),
    path('report/', report_views.report, name='report'),
    path('tools/', tools_views.tools, name='tools'),
    path('collection-status/', cs_views.collection_status, name='collection_status'),
    path('collection-status/detail/', cs_views.collection_status_detail, name='collection_status_detail'),
    path('unified-inspection/', ui_views.unified_inspection, name='unified_inspection'),

    # API — 통합 검수 (현재 Step: 날짜 매핑만, DB 조회 없음)
    path('api/unified-inspection/date-mapping/', ui_api.date_mapping, name='api_unified_inspection_date_mapping'),

    # API — 수집 현황
    path('api/collection-status/', cs_api.collection_status_data, name='api_collection_status'),
    path('api/collection-status/email-report-data/', cs_api.email_report_data, name='api_email_report_data'),
    path('api/collection-status/null-detail/', cs_api.collection_null_detail, name='api_collection_null_detail'),
    path('api/collection-status/send-email/', cs_api.send_email_report, name='api_send_email'),
    path('api/collection-status/email-check/', cs_api.email_sent_check, name='api_email_check'),
    path('api/collection-status/email-recipients/', cs_api.email_recipients, name='api_email_recipients'),

    # API — 대시보드
    path('api/dashboard-stats/', dashboard_api.dashboard_stats, name='api_dashboard_stats'),

    # API — 검수기록
    path('api/corrections/', corr_api.corrections_list, name='api_corrections'),
    path('api/corrections/cancel/', corr_api.corrections_cancel, name='api_corrections_cancel'),
    path('api/corrections/history/', corr_api.corrections_history, name='api_corrections_history'),
    path('api/corrections/bulk-history/', corr_api.corrections_bulk_history, name='api_corrections_bulk_history'),
    path('api/review-reasons/', corr_api.review_reasons, name='api_review_reasons'),

    # API — 보고서
    path('api/report/', report_api.report_data, name='api_report'),

    # API — 마감기록 (status는 Layer 1 common 참조)
    path('api/check/status/', cl_api.check_status, name='api_check_status'),
    path('api/check/log/', cl_api.check_log_list, name='api_check_log_list'),
    path('api/check/memo/', cl_api.check_memo_update, name='api_check_memo_update'),

    # API — 수집 이슈
    path('api/collection-issues/', ci_api.collection_issues_list, name='api_collection_issues'),
    path('api/collection-issues/save/', ci_api.collection_issue_save, name='api_collection_issue_save'),
    path('api/collection-issues/delete/', ci_api.collection_issue_delete, name='api_collection_issue_delete'),
    path('api/collection-issues/resolve/', ci_api.collection_issue_resolve, name='api_collection_issue_resolve'),
]
