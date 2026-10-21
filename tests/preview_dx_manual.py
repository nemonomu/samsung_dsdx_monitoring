"""Run an isolated local manual UI with a disposable DB; never uses production data."""
from pathlib import Path
from datetime import date, timedelta
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_dx_manual as test_config
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth import get_user_model, login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import include, path
from unittest.mock import patch
from django.db import connections
from apps.dx.dx_document.models import PostgresManualRevision, PostgresManualImage
from apps.dx.dx_layer1.column_statistics.links import links as column_links

root = Path(__file__).resolve().parents[1]
settings.DATABASES['default']['NAME'] = str(root / 'tmp/manual-preview.sqlite3')
settings.DATABASES['dx']['NAME'] = str(root / 'tmp/manual-preview-dx.sqlite3')
settings.STATICFILES_DIRS = [str(root / 'static')]
settings.DEBUG = True
settings.ROOT_URLCONF = __name__
call_command('migrate', verbosity=0)
with connections['dx'].schema_editor() as editor:
    existing = connections['dx'].introspection.table_names()
    for model in (PostgresManualRevision, PostgresManualImage):
        if model._meta.db_table not in existing:
            editor.create_model(model)
user, _ = get_user_model().objects.get_or_create(username='manual-preview', defaults={'is_staff': True})


def entry(request):
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('/dx/documents/')


preview_catalog = [dict(country='SEA', product=p, retailers=['Costco']) for p in ('TV', 'REF')]


def alert_preview(request):
    return render(request, 'dx_layer1_column_alerts.html', {
        'section': 'column_alerts', 'section_title': '컬럼 수집 이상',
        'layer': dict(name='Layer 1 검증', color='#243c65', number=1),
        'column_catalog': preview_catalog, 'column_alert_catalog': preview_catalog,
    })


def alert_counts(request):
    day = request.GET.get('date', '2026-10-21')
    fields = ['original_sku_price', 'savings', 'missing_guide_example'] if request.GET.get('product') == 'TV' else ['ref_capacity']
    return JsonResponse(dict(inspection_date=day, comparison_date=str(date.fromisoformat(day) - timedelta(days=1)),
        comparisons=[dict(column=field, status='abnormal', current=0, baseline=100, history_days=28, ratio=0, delta=-100) for field in fields]))


urlpatterns = [
    path('', entry),
    path('dx/layer1/column-alerts/', alert_preview),
    path('dx/layer1/api/column-alert-links/', column_links),
    path('dx/layer1/api/column-statistics/', alert_counts),
    path('', include('apps.dx.dx_document.urls')),
    path('accounts/', include(([
        path('admin/', lambda request: HttpResponse('Local preview'), name='admin_dashboard'),
        path('logout/', lambda request: HttpResponse('Local preview'), name='logout'),
        path('login/', entry, name='login'),
    ], 'accounts'))),
]

categories = [
    {'category_id': 'preview-report', 'category_name': '검수 보고서', 'category_type': 1},
    {'category_id': 'preview-manual', 'category_name': 'DX 검수 매뉴얼', 'category_type': 1},
    {'category_id': 'preview-issue', 'category_name': '이슈보고서', 'category_type': 1},
]
if __name__ == '__main__':
    with patch('apps.dx.dx_document.views.get_categories_list', return_value=categories), \
         patch('apps.dx.dx_document.document.document_services.get_categories_list', return_value=categories), \
         patch('apps.dx.dx_document.document.document_api.get_documents_list', return_value={'success': True, 'documents': [], 'total': 0}):
        call_command('runserver', '127.0.0.1:8769', use_reloader=False)
