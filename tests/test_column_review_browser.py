"""Real templates and review API, isolated in-memory DB, synthetic clipboard image."""
import base64
import copy
import io
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import test_column_review_backend as fixture
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import Client
from django.template import Engine, Context
from playwright.sync_api import sync_playwright, expect
from apps.dx.dx_layer1.column_statistics import reviews as api
from apps.dx.dx_layer1.models import ColumnNormalReview, ColumnReviewImage

settings.ROOT_URLCONF = fixture.__name__
settings.DEBUG = False
settings.DATABASES['default']['NAME'] = 'file:column-review-' + uuid4().hex + '?mode=memory&cache=shared'
settings.DATABASES['default']['OPTIONS'] = {'uri':True}
call_command('migrate', verbosity=0)
client = Client()
client.force_login(get_user_model().objects.create_user(username='browser-reviewer', is_staff=True))
STATIC = ROOT / 'apps/dx/dx_layer1/static/dx_layer1'
base = '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:14px sans-serif;background:#f7f9fc;padding:20px}*{box-sizing:border-box}</style>
<link rel="stylesheet" href="/static/dx_layer1/css/collection-statistics.css">
{% block layer1_css %}{% endblock %}</head><body>{% block layer1_content %}{% endblock %}
<script>window.LAYER1={username:'browser-reviewer'};window.setSidebarIssueBadge=()=>{};</script>
<script src="/static/dx_layer1/js/column-alert-cache.js"></script>
{% block layer1_js %}{% endblock %}</body></html>'''
engine = Engine(dirs=[str(ROOT/'apps/dx/dx_layer1/templates')],
    loaders=[('django.template.loaders.locmem.Loader', {'base_layer1.html':base}), 'django.template.loaders.filesystem.Loader'],
    libraries={'static':'django.templatetags.static'})
html = engine.get_template('dx_layer1_column_alerts.html').render(Context(dict(
    column_catalog=[dict(country='SEA', product='TV', retailers=['Amazon'])], csrf_token='test-token')))
failed_save = False
errors = []


def inspect(target):
    return ({**fixture.CONTEXT, 'column':target['column']}, {**fixture.ROW, 'column':target['column']})


def route_request(route):
    path = urlparse(route.request.url).path
    if path.startswith('/static/dx_layer1/'):
        file = STATIC / path.removeprefix('/static/dx_layer1/')
        route.fulfill(path=str(file), content_type='text/javascript' if file.suffix=='.js' else 'text/css')
    elif path == '/dx/layer1/api/column-statistics/':
        data = dict(country='SEA', product='TV', retailer='Amazon', inspection_date=fixture.TARGET['inspection_date'],
            comparison_date=fixture.TARGET['source_date'], daily=[dict(date=fixture.TARGET['source_date'],total=300,raw_total=300)],
            comparisons=[copy.deepcopy(fixture.ROW), {**fixture.ROW,'column':'sku'}])
        route.fulfill(json=api.attach_reviews(data))
    elif path.startswith(fixture.PREFIX):
        target_url = path + ('?' + urlparse(route.request.url).query if route.request.method=='GET' else '')
        if route.request.method == 'POST':
            if failed_save:
                route.fulfill(status=503,json={'error':'테스트 저장 실패: 다시 시도하세요.'})
                return
            response = client.generic('POST', target_url, data=route.request.post_data_buffer,
                content_type=route.request.headers['content-type'])
        else:
            response = client.get(target_url)
        route.fulfill(status=response.status_code, body=response.content, content_type=response['Content-Type'])
    elif path == '/dx/layer1/api/column-alert-links/':
        route.fulfill(json={'links':[], 'guides':{}, 'manual_error':False})
    else:
        route.fulfill(body=html, content_type='text/html; charset=utf-8')


# Requests run serially in Playwright's callback greenlet against this test-only DB.
with patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE':'true'}), patch.object(api,'inspect',side_effect=inspect), sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge',headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.route('**/*',route_request)
    page.goto('http://column-review.test/?date=2026-10-15')
    expect(page.locator('[data-column-review]')).to_have_count(2)
    page.locator('[data-column-review]').first.click()
    dialog = page.locator('.column-review-dialog')
    expect(dialog.locator('textarea')).to_be_visible()
    dialog.get_by_role('button',name='정상 확인',exact=True).click()
    expect(dialog.locator('[data-error]')).to_contain_text('한 장 이상')
    encoded = base64.b64encode(fixture.image_file().read()).decode()

    def paste():
        dialog.locator('.column-review-paste').focus()
        page.evaluate('''encoded => {
            const bytes=Uint8Array.from(atob(encoded), c=>c.charCodeAt(0));
            const clipboard=new DataTransfer();
            clipboard.items.add(new File([bytes],'clipboard.png',{type:'image/png'}));
            document.activeElement.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));
        }''',encoded)

    paste()
    paste()
    expect(dialog.locator('[data-previews] img')).to_have_count(2)
    dialog.locator('[data-remove]').first.click()
    expect(dialog.locator('[data-previews] img')).to_have_count(1)
    dialog.locator('textarea').fill('실제 페이지 확인: <b>정상</b>')
    failed_save = True
    dialog.get_by_role('button',name='정상 확인',exact=True).click()
    expect(dialog.locator('[data-error]')).to_contain_text('테스트 저장 실패')
    expect(dialog.locator('[data-previews] img')).to_have_count(1)
    expect(dialog.locator('textarea')).to_have_value('실제 페이지 확인: <b>정상</b>')
    failed_save = False
    dialog.get_by_role('button',name='정상 확인',exact=True).click()
    expect(dialog.locator('[data-error]')).to_contain_text('저장했습니다')
    expect(dialog.locator('.column-review-entry img')).to_have_count(1)
    expect(dialog.locator('.column-review-memo')).to_have_text('실제 페이지 확인: <b>정상</b>')
    expect(dialog.locator('.column-review-memo b')).to_have_count(0)
    assert ColumnNormalReview.objects.get().active
    assert ColumnReviewImage.objects.count()==1
    expect(page.locator('#cca-body [data-column-review]')).to_have_count(1)
    dialog.get_by_role('button',name='닫기',exact=True).click()
    page.reload()
    expect(page.locator('[data-status=confirmed]')).to_contain_text('1')
    page.locator('[data-status=confirmed]').click()
    page.locator('#cca-body [data-column-review]').click()
    expect(dialog.locator('.column-review-entry img')).to_have_count(1)
    assert dialog.locator('.column-review-entry img').evaluate('(img)=>img.complete && img.naturalWidth>0')
    output=ROOT/'output'
    output.mkdir(exist_ok=True)
    page.screenshot(path=str(output/'column-review-evidence-desktop.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(output/'column-review-evidence-mobile.png'))
    assert dialog.evaluate('(el)=>el.scrollWidth <= el.clientWidth')
    dialog.locator('textarea').fill('다시 확인 필요')
    dialog.get_by_role('button',name='정상 확인 취소',exact=True).click()
    expect(dialog.locator('[data-error]')).to_contain_text('저장했습니다')
    assert not ColumnNormalReview.objects.get().active
    assert ColumnReviewImage.objects.count()==1
    assert len(ColumnNormalReview.objects.get().history)==2
    assert not errors, errors
    browser.close()
print('PASS: paste, preview/remove, failed save retry, actual API persistence, reload, evidence history, cancel and mobile layout.')
