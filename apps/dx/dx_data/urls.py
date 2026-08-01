from django.urls import path
from . import views
from apps.dx.dx_data.item_master import item_master_api
from apps.dx.dx_data.redirect_data import redirect_data_api

app_name = 'dx_data'

urlpatterns = [
    # 페이지
    path('', views.index, name='index'),
    path('item-master/', views.item_master, name='item_master'),
    path('redirect-data/', views.redirect_data, name='redirect_data'),
    path('history/', views.history, name='history'),

    # API
    path('api/item-master/list/', item_master_api.item_master_list, name='api_item_master_list'),
    path('api/item-master/save/', item_master_api.item_master_save, name='api_item_master_save'),
    path('api/item-master/history/', item_master_api.item_master_history, name='api_item_master_history'),
    path('api/redirect-data/list/', redirect_data_api.redirect_data_list, name='api_redirect_data_list'),
]
