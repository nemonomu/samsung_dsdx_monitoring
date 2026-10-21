"""Run an isolated local manual UI with a disposable DB; never uses production data."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_dx_manual as test_config
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth import get_user_model, login
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import include, path
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
settings.DATABASES['default']['NAME'] = str(root / 'tmp/manual-preview.sqlite3')
settings.STATICFILES_DIRS = [str(root / 'static')]
settings.DEBUG = True
settings.ROOT_URLCONF = __name__
call_command('migrate', verbosity=0)
user, _ = get_user_model().objects.get_or_create(username='manual-preview', defaults={'is_staff': True})


def entry(request):
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('/dx/documents/')


urlpatterns = [
    path('', entry),
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
