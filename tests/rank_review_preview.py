"""Local UI fixture using real rank review APIs and an isolated in-memory DB.

Run: python tests/rank_review_preview.py
Open http://127.0.0.1:8769/ . No source or production databases are accessed.
"""
import mimetypes
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from django.conf import settings
settings.configure(
    INSTALLED_APPS=['apps.dx.dx_layer1'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True, TIME_ZONE='Asia/Seoul', DEBUG=True, BASE_DIR=ROOT,
    SECRET_KEY='local-rank-review-fixture-only', ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=['127.0.0.1'], STATIC_URL='/static/',
    MIDDLEWARE=[__name__+'.FixtureUser', 'django.middleware.csrf.CsrfViewMiddleware'],
    TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True}],
)
import django
django.setup()
from django.core.cache import cache
from django.core.handlers.wsgi import WSGIHandler
from django.db import connection
from django.http import HttpResponse, Http404
from django.template import engines
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from apps.dx.dx_layer1.models import RetailRankReview, RetailRankReviewImage
from apps.dx.dx_layer1.rank_monitoring import api, snapshots, reviews
from tests.rank_monitoring_fixtures import DAY, samples


class FixtureUser:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        request.user = SimpleNamespace(is_authenticated=True, get_username=lambda: 'ui-reviewer')
        return self.get_response(request)


@ensure_csrf_cookie
def page(request):
    source = (ROOT/'apps/dx/dx_layer1/templates/dx_layer1_rank_monitoring.html').read_text(encoding='utf-8')
    source = re.sub(r"{% extends .*?%}|{% block page_title %}.*?{% endblock %}|{% block \w+ %}|{% endblock %}", '', source)
    shell = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>상품 확인 통합 검증</title><style>:root{--text-primary:#334155;--text-secondary:#64748b;--border-color:#dce4ef}*{box-sizing:border-box}body{font-family:Arial,"Malgun Gothic",sans-serif;margin:24px;background:#f8fafc}</style><body>'
    return HttpResponse(shell+engines['django'].from_string(source).render(
        {'rank_config': {'country':'SEA','mode':'all','date':str(DAY),
                         'catalog':[{'product':'TV','retailers':['Amazon']}], 'results':reviews.RESULTS}}, request)+'</body></html>')


def static(request, name):
    root = ROOT/'apps/dx/dx_layer1/static'
    target = (root/name).resolve()
    if not target.is_relative_to(root) or not target.is_file(): raise Http404
    return HttpResponse(target.read_bytes(), content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')


urlpatterns = [path('', page), path('static/<path:name>', static),
    path('dx/layer1/rank/api/data/', api.data), path('dx/layer1/rank/api/detail/', api.detail),
    path('dx/layer1/rank/api/review/', api.save_review), path('dx/layer1/rank/api/export/', api.export),
    path('dx/layer1/rank/api/review/images/<int:image_id>/', api.review_image)]

if __name__ == '__main__':
    with connection.schema_editor() as editor:
        editor.create_model(RetailRankReview)
        editor.create_model(RetailRankReviewImage)
    scope = {'country':'SEA','product':'TV','retailer':'Amazon','date':str(DAY)}
    with patch.object(snapshots,'load_snapshots',return_value={'rows':samples(),'basis':'UI fixture','sku_from_master':True}):
        snapshot = snapshots.build(scope, 'fixture-generation')
    cache.set('snapshot:'+snapshot['id'], snapshot, 7200)
    with patch.object(snapshots,'backend',return_value=(ROOT,cache)), \
         patch.object(snapshots,'monitoring_cache_generation',return_value='fixture-generation'), \
         patch.object(snapshots,'latest',return_value=(snapshot,{'state':'fresh','age_seconds':0})):
        with make_server('127.0.0.1',8769,WSGIHandler()) as server:
            print('Local: http://127.0.0.1:8769/ (isolated in-memory review DB)', flush=True)
            server.serve_forever()
