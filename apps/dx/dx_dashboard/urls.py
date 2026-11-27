from django.urls import path
from . import views

app_name = 'dx_dashboard'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/sem-tv-status/', views.sem_tv_status, name='sem_tv_status'),
]
