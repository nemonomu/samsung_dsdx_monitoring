"""Exercise the real review JS and API against an isolated in-memory review DB."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
# Playwright's synchronous callbacks run inside its loop; this DB is test-only.
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
from django.conf import settings
settings.configure(INSTALLED_APPS=['apps.dx.dx_layer2'],
                   DATABASES={'default': {'ENGINE':'django.db.backends.sqlite3',
                       'NAME':'file:format-review-browser?mode=memory&cache=shared', 'OPTIONS':{'uri':True}}},
                   USE_TZ=True, TIME_ZONE='Asia/Seoul', SECRET_KEY='format-review-browser', DEBUG=False)
from test_format_review_backend import sample, connection_stub, services, review_api, DAY
from django.core.management import call_command
from django.test import RequestFactory
from playwright.sync_api import sync_playwright, expect

call_command('migrate', 'dx_layer2', verbosity=0)
raw = sample()
js = (ROOT/'apps/dx/dx_layer2/static/dx_layer2/js/format-review.js').read_text(encoding='utf-8')
css = (ROOT/'apps/dx/dx_layer2/static/dx_layer2/css/format-review.css').read_text(encoding='utf-8')
css = (ROOT/'static/css/common.css').read_text(encoding='utf-8') + css
html = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:14px system-ui,sans-serif}'+css+'</style><button data-format-review-table="sea_ref_retail" data-format-review-retailer="Lowes">검토 열기</button><input type="hidden" name="csrfmiddlewaretoken" value="fixture"><script>function getSelectedDate(){return "2026-10-11";}</script><script>'+js+'</script>'


def serve(route):
    req = route.request
    if '/api/format-review/' not in req.url:
        route.fulfill(status=200, content_type='text/html', body=html)
        return
    factory = RequestFactory()
    request = factory.post('/reviews/', data=req.post_data, content_type='application/json') if req.method=='POST' else factory.get('/reviews/', {k:v[0] for k,v in parse_qs(urlsplit(req.url).query).items()})
    request.user=SimpleNamespace(is_authenticated=True,get_username=lambda:'browser-reviewer')
    response=review_api.reviews(request)
    route.fulfill(status=response.status_code,content_type='application/json',body=response.content.decode())


with patch.object(services,'_get_format_detail_raw',side_effect=lambda *a,**k:raw),patch.object(review_api,'dx_connection',connection_stub),patch.object(review_api.timezone,'localdate',return_value=DAY),sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('https://monitoring.test/**',serve)
    page.goto('https://monitoring.test/')
    page.get_by_text('검토 열기',exact=True).click()
    expect(page.locator('.format-review')).to_be_visible()
    def assert_centered():
        box = page.locator('.format-review').bounding_box()
        viewport = page.viewport_size
        assert abs(box['x'] + box['width']/2 - viewport['width']/2) <= 1, box
        assert abs(box['y'] + box['height']/2 - viewport['height']/2) <= 1, box
        assert box['x'] > 0 and box['y'] > 0, box
    assert_centered()
    group=page.locator('.fr-group').filter(has=page.locator('.fr-value',has_text='Pickup Ready by 9am Tomorrow'))
    expect(group).to_have_count(1)
    assert group.locator('.fr-links a').count()==3
    assert group.locator('.fr-links a').first.get_attribute('href')=='https://www.lowes.com/pd/1'
    assert group.locator('.fr-links a').first.get_attribute('rel')=='noopener noreferrer'
    checkbox=group.locator('input[type=checkbox]')
    blank={'x':group.bounding_box()['width']-35,'y':60}
    group.click(position=blank)
    expect(checkbox).to_be_checked()
    expect(group).to_have_class('fr-group selected')
    expect(page.locator('#fr-selected')).to_contain_text('3건 / 1개 값 선택')
    group.click(position=blank)
    expect(checkbox).not_to_be_checked()
    group.locator('label b').click()
    expect(checkbox).to_be_checked()
    group.locator('summary').click()
    expect(group.locator('details')).to_have_attribute('open','')
    expect(checkbox).to_be_checked()
    group.locator('td').first.click()
    expect(checkbox).to_be_checked()
    page.context.route('https://www.lowes.com/**',lambda route:route.fulfill(body='Product fixture'))
    with page.expect_popup() as popup:
        group.locator('.fr-links a').first.click()
    popup.value.close()
    expect(checkbox).to_be_checked()
    group.locator('summary').click()
    checkbox.uncheck()
    expect(group).to_have_class('fr-group')
    group.locator('.fr-value').click()
    expect(checkbox).to_be_checked()
    page.locator('#fr-reason').fill('실제 상품 페이지 확인')
    page.locator('[data-fr="preview"][data-decision="normal"]').click()
    expect(page.locator('#fr-preview')).to_contain_text('3건 / 1개 값')
    # A changed source after preview must be rejected, even though group IDs match.
    raw['results'][0]['product_url']='https://www.lowes.com/pd/changed'
    page.locator('[data-fr="apply"]').click()
    expect(page.locator('#fr-message')).to_contain_text('수집 값 또는 대상이 변경')
    page.locator('[data-fr="preview"][data-decision="normal"]').click()
    page.locator('[data-fr="apply"]').click()
    expect(page.locator('#fr-message')).to_contain_text('처리 결과를 반영')
    page.locator('[data-tab="registered"]').click()
    expect(page.locator('#fr-groups')).to_contain_text('Pickup Ready by 9am Tomorrow')
    page.locator('#fr-reason').fill('잘못 등록하여 취소')
    page.locator('[data-fr="revoke"]').click()
    page.locator('[data-fr="apply"]').click()
    expect(page.locator('#fr-groups')).to_contain_text('등록한 정상 값이 없습니다')
    page.locator('[data-tab="baseline"]').click()
    expect(page.locator('#fr-groups')).to_contain_text('기존 기준 통과')
    baseline=page.locator('.fr-group').filter(has=page.locator('.fr-value',has_text='Pickup Ready Today'))
    baseline.locator('input').check()
    page.locator('#fr-reason').fill('기존 정상 기준의 잘못된 허용 확인')
    page.locator('[data-fr="preview"][data-decision="error"]').click()
    page.locator('[data-fr="apply"]').click()
    page.locator('[data-tab="issues"]').click()
    expect(page.locator('#fr-groups')).to_contain_text('오류 확정')
    assert page.evaluate('FormatReview.safeURL("javascript:alert(1)")')==''
    output=ROOT/'output/format-review-qa'
    output.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(output/'desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert_centered()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(output/'mobile.png'),full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS: real JS/API batch preview/apply, stale source rejection, URL safety, registration revoke, baseline-to-error flow, desktop/mobile.')
