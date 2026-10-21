from django.urls import path
from . import views, manual
from apps.dx.dx_document.document import document_api

app_name = 'dx_document'

urlpatterns = [
    # Pages
    path('dx/documents/', views.index, name='index'),
    path('dx/documents/new/', views.edit, name='new'),
    path('dx/documents/manual/', manual.page, name='manual'),
    path('dx/documents/manual/content/', manual.content, name='manual_content'),
    path('dx/documents/manual/save/', manual.save, name='manual_save'),
    path('dx/documents/manual/history/', manual.history, name='manual_history'),
    path('dx/documents/manual/upload/', manual.upload, name='manual_upload'),
    path('dx/documents/manual/images/<str:digest>/', manual.image, name='manual_image'),
    path('dx/documents/<str:document_id>/edit/', views.edit, name='edit'),
    path('dx-share/file/<path:token>/<str:file_name>', views.share_file, name='share_file'),
    path('dx-share/<path:token>/', views.share, name='share'),

    # Document API
    path('api/dx/documents/', document_api.documents_list, name='api_list'),
    path('api/dx/documents/detail/', document_api.document_detail, name='api_detail'),
    path('api/dx/documents/create/', document_api.document_create, name='api_create'),
    path('api/dx/documents/<str:document_id>/update/', document_api.document_update, name='api_update'),
    path('api/dx/documents/<str:document_id>/delete/', document_api.document_delete, name='api_delete'),
    path('api/dx/documents/upload/', document_api.upload, name='api_upload'),
    path('api/dx/documents/files/', document_api.document_files, name='api_files'),
    path('api/dx/documents/files/<str:file_id>/delete/', document_api.file_delete, name='api_file_delete'),
    path('api/dx/documents/file/<str:file_name>', document_api.file_proxy, name='api_file'),
    path('api/dx/documents/share-token/', document_api.share_token, name='api_share_token'),
    path('api/dx/documents/share-list/', document_api.share_list, name='api_share_list'),
    path('api/dx/documents/share-revoke/', document_api.share_revoke, name='api_share_revoke'),
]
