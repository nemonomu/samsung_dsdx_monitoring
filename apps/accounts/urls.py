from django.urls import path
from . import views
from .sessions import session_status

app_name = 'accounts'

urlpatterns = [
    # 인증
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('session-status/', session_status, name='session_status'),

    # 관리자 페이지 - 회원관리
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/user/create/', views.user_create, name='user_create'),
    path('admin/user/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('admin/user/<int:user_id>/delete/', views.user_delete, name='user_delete'),
    path('admin/user/<int:user_id>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),

    # 관리자 페이지 - 수집항목 관리
    path('admin/retail-columns/', views.retail_columns, name='retail_columns'),
    path('admin/retail-columns/create/', views.retail_columns_create, name='retail_columns_create'),
    path('admin/retail-columns/<int:column_id>/update/', views.retail_columns_update, name='retail_columns_update'),
    path('admin/retail-columns/<int:column_id>/delete/', views.retail_columns_delete, name='retail_columns_delete'),
    path('admin/retail-columns/<int:column_id>/toggle/', views.retail_columns_toggle, name='retail_columns_toggle'),

    # 관리자 페이지 - 예외조건 관리
    path('admin/exclude-rules/', views.exclude_rules, name='exclude_rules'),
    path('admin/exclude-rules/create/', views.exclude_rules_create, name='exclude_rules_create'),
    path('admin/exclude-rules/<int:rule_id>/update/', views.exclude_rules_update, name='exclude_rules_update'),
    path('admin/exclude-rules/<int:rule_id>/delete/', views.exclude_rules_delete, name='exclude_rules_delete'),
    path('admin/exclude-rules/<int:rule_id>/toggle/', views.exclude_rules_toggle, name='exclude_rules_toggle'),

    # 관리자 페이지 - NULL 검증 관리
    path('admin/null-checks/', views.null_checks, name='null_checks'),
    path('admin/null-checks/create/', views.null_checks_create, name='null_checks_create'),
    path('admin/null-checks/<int:check_id>/update/', views.null_checks_update, name='null_checks_update'),
    path('admin/null-checks/<int:check_id>/delete/', views.null_checks_delete, name='null_checks_delete'),
    path('admin/null-checks/<int:check_id>/toggle/', views.null_checks_toggle, name='null_checks_toggle'),

    # 관리자 페이지 - 형식 검증 관리
    path('admin/format-rules/', views.format_rules, name='format_rules'),
    path('admin/format-rules/create/', views.format_rules_create, name='format_rules_create'),
    path('admin/format-rules/<int:rule_id>/update/', views.format_rules_update, name='format_rules_update'),
    path('admin/format-rules/<int:rule_id>/delete/', views.format_rules_delete, name='format_rules_delete'),
    path('admin/format-rules/<int:rule_id>/toggle/', views.format_rules_toggle, name='format_rules_toggle'),

    # 형식 검증 - 템플릿
    path('admin/format-templates/new/', views.format_template_edit, name='format_template_new'),
    path('admin/format-templates/<int:tmpl_id>/edit/', views.format_template_edit, name='format_template_edit'),
    path('admin/format-templates/api/list/', views.format_templates_list, name='format_templates_list'),
    path('admin/format-templates/api/save/', views.format_templates_save, name='format_templates_save'),
    path('admin/format-templates/api/<int:tmpl_id>/delete/', views.format_templates_delete, name='format_templates_delete'),
    path('admin/format-templates/api/<int:tmpl_id>/toggle/', views.format_templates_toggle, name='format_templates_toggle'),

    # 형식 검증 - 설정
    path('admin/format-config/new/', views.format_config_edit, name='format_config_new'),
    path('admin/format-config/<int:config_id>/edit/', views.format_config_edit, name='format_config_edit'),
    path('admin/format-config/api/list/', views.format_config_list, name='format_config_list'),
    path('admin/format-config/api/save/', views.format_config_save, name='format_config_save'),
    path('admin/format-config/api/<int:config_id>/delete/', views.format_config_delete, name='format_config_delete'),

    # 관리자 페이지 - DS 스케줄 설정
    path('admin/schedule-settings/', views.schedule_settings, name='schedule_settings'),
    path('admin/schedule-settings/create/', views.schedule_settings_create, name='schedule_settings_create'),
    path('admin/schedule-settings/<int:target_id>/update/', views.schedule_settings_update, name='schedule_settings_update'),
    path('admin/schedule-settings/<int:target_id>/delete/', views.schedule_settings_delete, name='schedule_settings_delete'),
    path('admin/schedule-settings/<int:target_id>/toggle/', views.schedule_settings_toggle, name='schedule_settings_toggle'),

    # 관리자 페이지 - DX 수집 스케줄 설정
    path('admin/dx-schedule-settings/', views.dx_schedule_settings, name='dx_schedule_settings'),
    path('admin/dx-schedule-settings/create/', views.dx_schedule_settings_create, name='dx_schedule_settings_create'),
    path('admin/dx-schedule-settings/<int:schedule_id>/update/', views.dx_schedule_settings_update, name='dx_schedule_settings_update'),
    path('admin/dx-schedule-settings/<int:schedule_id>/delete/', views.dx_schedule_settings_delete, name='dx_schedule_settings_delete'),
    path('admin/dx-schedule-settings/<int:schedule_id>/toggle/', views.dx_schedule_settings_toggle, name='dx_schedule_settings_toggle'),
    path('admin/dx-schedule-settings/new/', views.dx_schedule_settings_form, name='dx_schedule_settings_new'),
    path('admin/dx-schedule-settings/<int:schedule_id>/edit/', views.dx_schedule_settings_form, name='dx_schedule_settings_edit'),

    # 관리자 페이지 - DS 이상치 원인 옵션 관리
    path('admin/anomaly-causes/', views.anomaly_causes, name='anomaly_causes'),
    path('admin/anomaly-causes/create/', views.anomaly_causes_create, name='anomaly_causes_create'),
    path('admin/anomaly-causes/<int:cause_id>/update/', views.anomaly_causes_update, name='anomaly_causes_update'),
    path('admin/anomaly-causes/<int:cause_id>/delete/', views.anomaly_causes_delete, name='anomaly_causes_delete'),
    path('admin/anomaly-causes/<int:cause_id>/toggle/', views.anomaly_causes_toggle, name='anomaly_causes_toggle'),

    # 관리자 페이지 - 문서 카테고리 관리
    path('admin/document-categories/', views.document_categories, name='document_categories'),
    path('admin/document-categories/new/', views.document_category_edit, name='document_category_new'),
    path('admin/document-categories/<str:category_id>/edit/', views.document_category_edit, name='document_category_edit'),
    path('admin/document-categories/create/', views.document_categories_create, name='document_categories_create'),
    path('admin/document-categories/<str:category_id>/update/', views.document_categories_update, name='document_categories_update'),
    path('admin/document-categories/<str:category_id>/delete/', views.document_categories_delete, name='document_categories_delete'),
    path('admin/document-categories/<str:category_id>/toggle/', views.document_categories_toggle, name='document_categories_toggle'),

    # 관리자 페이지 - DX 카테고리 검증 규칙
    path('admin/category-rules/', views.category_rules, name='category_rules'),
    path('admin/category-rules/new/', views.category_rules_edit, name='category_rules_new'),
    path('admin/category-rules/<int:rule_id>/edit/', views.category_rules_edit, name='category_rules_edit'),
    path('admin/category-rules/api/list/', views.category_rules_list_api, name='category_rules_list_api'),
    path('admin/category-rules/api/save/', views.category_rules_save_api, name='category_rules_save_api'),
    path('admin/category-rules/api/delete/', views.category_rules_delete_api, name='category_rules_delete_api'),

    # 관리자 페이지 - 이메일 수신자 관리
    path('admin/email-config/', views.email_config, name='email_config'),
    path('admin/email-config/create/', views.email_config_create, name='email_config_create'),
    path('admin/email-config/<int:config_id>/edit/', views.email_config_form, name='email_config_edit'),
    path('admin/email-config/<int:config_id>/update/', views.email_config_update, name='email_config_update'),
    path('admin/email-config/<int:config_id>/delete/', views.email_config_delete, name='email_config_delete'),
    path('admin/email-config/<int:config_id>/toggle/', views.email_config_toggle, name='email_config_toggle'),
    path('admin/email-config/<str:config_key>/', views.email_config_recipients, name='email_config_recipients'),
    path('admin/email-config/<str:config_key>/new/', views.email_config_form, name='email_config_new'),

    # 관리자 페이지 - DS 문서 카테고리 관리
    path('admin/ds-document-categories/', views.ds_document_categories, name='ds_document_categories'),
    path('admin/ds-document-categories/new/', views.ds_document_category_edit, name='ds_document_category_new'),
    path('admin/ds-document-categories/<str:category_id>/edit/', views.ds_document_category_edit, name='ds_document_category_edit'),
    path('admin/ds-document-categories/create/', views.ds_document_categories_create, name='ds_document_categories_create'),
    path('admin/ds-document-categories/<str:category_id>/update/', views.ds_document_categories_update, name='ds_document_categories_update'),
    path('admin/ds-document-categories/<str:category_id>/delete/', views.ds_document_categories_delete, name='ds_document_categories_delete'),
    path('admin/ds-document-categories/<str:category_id>/toggle/', views.ds_document_categories_toggle, name='ds_document_categories_toggle'),
]
