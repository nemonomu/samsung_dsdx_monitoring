from django.urls import path
from apps.dx.dx_layer1 import views as layer1_views
from . import dashboard_api as api

urlpatterns = [
    path('', layer1_views.dashboard, name='dashboard'),
    path('api/stats/', api.layer_stats, name='api_stats'),
    path('api/collection-status/', api.collection_status, name='api_collection_status'),
]
