from django.urls import path
from apps.dx.dx_layer1 import views as layer1_views
from . import dashboard_api as api
from apps.dx.dx_layer1.common.retail_batches_api import batch_details

urlpatterns = [
    path('', layer1_views.dashboard, name='dashboard'),
    path('api/stats/', api.layer_stats, name='api_stats'),
    path('api/retail-batches/', batch_details, name='api_retail_batches'),
    path('api/collection-status/', api.collection_status, name='api_collection_status'),
]
