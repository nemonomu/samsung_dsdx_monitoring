"""Exercise shipped manual JS with isolated fixtures; never writes production data."""
import copy
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
fail_save = False
old = copy.deepcopy(next(p for p in saved['photos'] if p['retailer'] == 'SEG/expert' and p['category'] == 'tv'))
column = old['boxes'][0]['fields'][0]
old.update(name='user_photo_100', userEdited=True, customImage=saved['assets'][old['name']])
new = copy.deepcopy(old)
new.update(name='user_photo_200', stage='새 수집 화면')
saved['photos'].extend([old, new])
saved['profiles']['SEG/expert']['routeNotes'] = {'main':'검색 → TV 선택\n이 목록에서 수집', 'bsr':'베스트셀러 목록에서 수집'}
target = dict(country='독일', retailer='SEG/expert', category='tv', scope='common', field=column)
fallback_image = APP / 'manual_data/images' / old['customImage'].rstrip('/').split('/')[-1]


def route_request(route):
    global saved, version
    path = urlparse(route.request.url).path
    if path == '/dx/documents/manual/save/':
        if fail_save:
            route.fulfill(status=500, json={'error':'테스트 저장 실패'})
            return
        payload = route.request.post_data_json
        assert payload['version'] == version
        saved = copy.deepcopy(payload['data'])
        version += 1
        route.fulfill(json=dict(version=version, created_by='test-editor'))
    elif path == '/dx/documents/manual/upload/':
        route.fulfill(json={'url':'/dx/documents/manual/images/' + 'a' * 64 + '/'})
    elif path == '/':
        html = render_to_string('dx_document/manual_content.html', dict(
            guide_data=prepare_data(saved), guide_meta=dict(version=version, target=target), csrf_token='test-token'))
        route.fulfill(content_type='text/html; charset=utf-8', body=html)
    elif path.startswith('/static/dx_document/'):
        file = APP / 'static/dx_document' / path.removeprefix('/static/dx_document/')
        route.fulfill(path=str(file), content_type='text/javascript' if file.suffix == '.js' else 'text/css')
    elif path.startswith('/dx/documents/manual/images/'):
        route.fulfill(path=str(fallback_image), content_type='image/png')
    else:
        route.fulfill(status=404)


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport=dict(width=1440, height=1000))
    page.route('**/*', route_request)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://manual.test/')
    expect(page.locator('#captureSelect option:checked')).to_contain_text('새 수집 화면')
    assert page.locator('#photoPager').bounding_box()['y'] < page.locator('#canvas').bounding_box()['y']
    page.locator('#routeDetails').click()
    expect(page.locator('.manual-route-description').first).to_have_text('검색 → TV 선택\n이 목록에서 수집')
    page.locator('dialog[open] .close').click()
    page.locator('#editModeToggle').click()
    page.locator('#captureSelect').select_option('1')
    expect(page.locator('#manualPrimaryPhoto')).to_be_enabled()
    page.locator('#manualPrimaryPhoto').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    page.reload()
    expect(page.locator('#captureSelect option:checked')).not_to_contain_text('새 수집 화면')
    page.locator('#editModeToggle').click()
    page.locator('#editImage').click()
    expect(page.locator('#replacePhoto')).to_have_text('현재 이미지 교체')
    expect(page.locator('#addPhoto')).to_have_text('별도 캡처 추가')
    selected_name = page.locator('#editPhotoSelect option:checked').inner_text().split(' / ')[-1]
    before_count = len(saved['photos'])
    # File chooser upload exercises replacement, then recreates the required annotation.
    with page.expect_file_chooser() as chooser:
        page.locator('#replacePhoto').click()
    chooser.value.set_files(dict(name='replacement.png', mimeType='image/png', buffer=fallback_image.read_bytes()))
    expect(page.locator('#boxList')).to_contain_text('아직 번호 박스')
    page.locator('#applyImage').click()
    expect(page.locator('#imageError')).to_contain_text('번호 박스')
    box = page.locator('#annotationCanvas').bounding_box()
    page.mouse.move(box['x'] + 20, box['y'] + 20)
    page.mouse.down()
    page.mouse.move(box['x'] + 100, box['y'] + 100)
    page.mouse.up()
    page.locator('#applyImage').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    assert len(saved['photos']) == before_count
    replacement = next(p for p in saved['photos'] if p['name'] == selected_name)
    assert replacement['customImage'].endswith('a' * 64 + '/')
    page.reload()
    expect(page.locator('#canvas image')).to_have_attribute('href', replacement['customImage'])
    page.locator('#editModeToggle').click()
    page.locator('#captureSelect').select_option('1')
    fail_save = True
    page.locator('#manualPrimaryPhoto').click()
    expect(page.locator('#saveFailure')).to_have_text('테스트 저장 실패')
    expect(page.locator('#editStatus')).to_contain_text('저장하지 않은 변경')
    fail_save = False
    page.locator('#saveGuide').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    # Add is distinct from replacement, becomes primary and can be undone.
    page.locator('#editImage').click()
    with page.expect_file_chooser() as chooser:
        page.locator('#addPhoto').click()
    chooser.value.set_files(dict(name='added.png', mimeType='image/png', buffer=fallback_image.read_bytes()))
    expect(page.locator('#boxList')).to_contain_text('아직 번호 박스')
    page.locator('#editPhotoStage').fill('추가 캡처 확인')
    box = page.locator('#annotationCanvas').bounding_box()
    page.mouse.move(box['x'] + 20, box['y'] + 20)
    page.mouse.down()
    page.mouse.move(box['x'] + 100, box['y'] + 100)
    page.mouse.up()
    page.locator('#applyImage').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    assert len(saved['photos']) == before_count + 1
    expect(page.locator('#captureSelect option:checked')).to_contain_text('추가 캡처 확인')
    page.locator('#undoEdit').click()
    page.locator('#saveGuide').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    assert len(saved['photos']) == before_count
    page.reload()
    expect(page.locator('#captureSelect option:checked')).not_to_contain_text('추가 캡처 확인')
    assert not errors, errors
    browser.close()
print('Manual image selection, replacement, reload, route text and save retry passed.')
