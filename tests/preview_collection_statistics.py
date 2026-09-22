"""Local UI fixture: python tests/preview_collection_statistics.py

Only synthetic counts and an in-memory database; no project settings or source DB.
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from django.conf import settings
settings.configure(
    INSTALLED_APPS=['django.contrib.staticfiles', 'apps.dx.dx_layer1'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'DIRS': [ROOT / 'templates'], 'APP_DIRS': True,
                'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}],
    STATIC_URL='/static/', STATICFILES_DIRS=[ROOT / 'static'],
    ROOT_URLCONF=__name__, ALLOWED_HOSTS=['127.0.0.1', 'localhost'],
    SECRET_KEY='local-synthetic-preview-only', USE_TZ=True, TIME_ZONE='Asia/Seoul', DEBUG=False,
)
import django
django.setup()
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.http import HttpResponse
from django.urls import path, include
from apps.dx.dx_layer1.collection_statistics import api, collector
from apps.dx.dx_layer1.common import context

context.load_collection_schedules = lambda: [
    {'check_type': name, 'schedule_type': 'daily'}
    for name in ['retail', 'seda_retail', 'siel_retail', 'seg_retail', 'sem_retail', 'tse_retail']
]
urlpatterns = [
    path('dx/layer1/collection-statistics/', api.page),
    path('dx/layer1/api/collection-statistics/', api.weekly),
    path('accounts/', include(([path('login/', lambda request: HttpResponse('Preview'), name='login')], 'accounts'))),
]


def fixture(country, inspection):
    rows = []
    for name, usual in [('Amazon', 240), ('Bestbuy', 300), ('Walmart', 310)]:
        count = usual + (inspection.day % 5 - 2) * 3
        if inspection == date(2026, 9, 19):
            count = 150 if name == 'Amazon' else 420 if name == 'Bestbuy' else count
        if inspection == date(2026, 9, 20) and name == 'Walmart':
            count = 0
        rows.append({'retailer': name, 'main_count': count, 'bsr_count': min(count, 100),
                     'raw_count': count, 'status': 'OK' if count else 'CRITICAL',
                     'batch_id': str(inspection)})
    return {'phase': 'complete', 'categories': [{'name': 'TV', 'retailers': rows}]}


if __name__ == '__main__':
    call_command('migrate', verbosity=0)
    end = date(2026, 9, 21)
    collector.refresh_country('SEA', end - timedelta(days=83), end, loader=fixture, today=date(2026, 9, 22))
    print('Synthetic preview: http://127.0.0.1:8766/dx/layer1/collection-statistics/?date=2026-09-21', flush=True)
    with make_server('127.0.0.1', 8766, StaticFilesHandler(get_wsgi_application())) as server:
        server.serve_forever()
