from django.urls import path
from apps.dx.dx_layer1 import views as layer1_views
from . import dashboard_api as api
from apps.dx.dx_layer1.common.retail_batches_api import batch_details
from apps.dx.dx_layer1.collection_statistics import api as statistics_api

urlpatterns = [
    path('collection-statistics/', statistics_api.page, name='collection_statistics'),
    path('api/collection-statistics/', statistics_api.weekly, name='api_collection_statistics'),
    path('api/collection-volume/', statistics_api.alerts, name='api_collection_volume'),
    path('', layer1_views.dashboard, name='dashboard'),
    path('api/stats/', api.layer_stats, name='api_stats'),
    path('api/retail-batches/', batch_details, name='api_retail_batches'),
    path('api/collection-status/', api.collection_status, name='api_collection_status'),
]
