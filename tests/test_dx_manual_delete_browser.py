"""Real manual assets with intercepted local fixtures; no production DB or network."""
import copy
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import test_dx_manual as config
from django.template.loader import render_to_string
from apps.dx.dx_document.manual_catalog import prepare_data
from playwright.sync_api import sync_playwright, expect

APP = ROOT / 'apps/dx/dx_document'
saved = prepare_data(config.manual.seed_data())
version = 0
target = dict(country='독일', retailer='SEG/expert', category='tv', scope='tv', field='summarized_review_content')


def route_request(route):
    global saved, version
    path = urlparse(route.request.url).path
    if path == '/dx/documents/manual/save/':
        payload = route.request.post_data_json
        assert payload['version'] == version
        saved = copy.deepcopy(payload['data'])
        version += 1
        route.fulfill(json=dict(version=version, created_by='test-editor'))
    elif path == '/':
        html = render_to_string('dx_document/manual_content.html', dict(
            guide_data=prepare_data(saved), guide_meta=dict(version=version, target=target), csrf_token='test-token'))
        route.fulfill(content_type='text/html; charset=utf-8', body=html)
    elif path.startswith('/static/dx_document/'):
        file = APP / 'static/dx_document' / path.removeprefix('/static/dx_document/')
        route.fulfill(path=str(file), content_type='text/javascript' if file.suffix == '.js' else 'text/css')
    elif path.startswith('/dx/documents/manual/images/'):
        route.fulfill(path=str(APP / 'manual_data/images' / path.rstrip('/').split('/')[-1]), content_type='image/png')
    else:
        route.fulfill(status=404)


def field(name):
    return page.locator('#fieldList [data-field="' + name + '"]')


def delete(accept=True):
    page.once('dialog', lambda dialog: dialog.accept() if accept else dialog.dismiss())
    page.locator('#manualDeleteColumn').click()


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport=dict(width=1440, height=1000))
    page.route('**/*', route_request)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://manual.test/')
    expect(field('summarized_review_content')).to_be_visible()
    expect(page.locator('#manualDeleteColumn')).to_be_hidden()
    page.locator('#editModeToggle').click()
    expect(page.locator('#manualDeleteColumn')).to_be_enabled()
    delete(False)
    expect(field('summarized_review_content')).to_be_visible()
    delete()
    expect(field('summarized_review_content')).to_have_count(0)
    page.locator('#undoEdit').click()
    expect(field('summarized_review_content')).to_be_visible()
    delete()
    page.locator('#saveGuide').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    page.reload()
    expect(field('summarized_review_content')).to_have_count(0)
    page.locator('[data-scope="ref"]').click()
    expect(field('summarized_review_content')).to_be_visible()
    page.locator('[data-scope="tv"]').click()
    page.locator('#editModeToggle').click()
    # Re-adding a deleted original keeps its identifier/number and restores it.
    page.locator('#manualAddColumn').click()
    page.locator('#manualColumnName').fill('summarized_review_content')
    page.locator('#manualColumnLabel').fill('리뷰 요약')
    page.locator('#manualStructureForm [type="submit"]').click()
    expect(field('summarized_review_content')).to_be_visible()
    # Common deletion affects this retailer's shared list, not other retailers.
    page.locator('[data-scope="common"]').click()
    field('retailer_sku_name').click()
    delete()
    expect(field('retailer_sku_name')).to_have_count(0)
    page.locator('[data-scope="ref"]').click()
    expect(field('retailer_sku_name')).to_have_count(0)
    page.locator('#undoEdit').click()
    expect(field('retailer_sku_name')).to_be_visible()
    # Last product field can be deleted, then a new one added to the empty scope.
    page.locator('[data-scope="tv"]').click()
    while page.locator('#fieldList [data-field]').count():
        page.locator('#fieldList [data-field]').first.click()
        delete()
    expect(page.locator('#manualDeleteColumn')).to_be_disabled()
    expect(page.locator('#lessonTitle')).to_have_text('등록된 컬럼이 없습니다.')
    page.locator('#manualAddColumn').click()
    page.locator('#manualColumnName').fill('manual_test_column')
    page.locator('#manualColumnLabel').fill('테스트 컬럼')
    page.locator('#manualStructureForm [type="submit"]').click()
    expect(field('manual_test_column')).to_be_visible()
    delete()
    expect(page.locator('#manualDeleteColumn')).to_be_disabled()
    page.locator('#saveGuide').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    page.reload()
    expect(page.locator('#lessonTitle')).to_have_text('등록된 컬럼이 없습니다.')
    assert not errors, errors
    browser.close()
print('PASS: delete/cancel/undo, save/reload, product/common scope, re-add and empty scope.')
