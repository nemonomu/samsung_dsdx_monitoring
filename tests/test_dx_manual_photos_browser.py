"""Exercise shipped manual JS with isolated fixtures; never writes production data."""
import copy
from base64 import b64encode
from io import BytesIO
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import test_dx_manual as config
from django.template.loader import render_to_string
from apps.dx.dx_document.manual_catalog import prepare_data
from playwright.sync_api import sync_playwright, expect
from PIL import Image

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


def assert_carousel_layout(page):
    image = page.locator('#canvas > svg').bounding_box()
    previous = page.locator('#prevPhoto').bounding_box()
    following = page.locator('#nextPhoto').bounding_box()
    dots = page.locator('#capturePosition').bounding_box()
    assert previous['x'] + previous['width'] <= image['x'] + 1
    assert following['x'] >= image['x'] + image['width'] - 1
    center = image['y'] + image['height'] / 2
    for arrow in (previous, following):
        assert abs((arrow['y'] + arrow['height'] / 2) - center) < 2
    assert dots['y'] >= image['y'] + image['height'] - 1
    assert abs((dots['x'] + dots['width'] / 2) - (image['x'] + image['width'] / 2)) < 2


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport=dict(width=1440, height=1000))
    page.route('**/*', route_request)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://manual.test/')
    expect(page.locator('#captureDescription')).to_contain_text('새 수집 화면')
    expect(page.locator('#capturePosition')).to_have_text(re.compile(r'^1 / \d+$'))
    expect(page.locator('#prevPhoto')).to_be_disabled()
    expect(page.locator('#photoPager select')).to_have_count(0)
    dots = page.locator('#capturePosition .manual-capture-dot')
    total = int(page.locator('#capturePosition .manual-capture-count').text_content().split(' / ')[1])
    expect(dots).to_have_count(total)
    expect(dots.nth(0)).to_have_class(re.compile(r'\bis-current\b'))
    assert_carousel_layout(page)
    page.set_viewport_size({'width': 560, 'height': 900})
    assert_carousel_layout(page)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    assert page.locator('#photoPager').bounding_box()['y'] < page.locator('#canvas').bounding_box()['y']
    page.locator('#routeDetails').click()
    expect(page.locator('.manual-route-description').first).to_have_text('검색 → TV 선택\n이 목록에서 수집')
    page.locator('dialog[open] .close').click()
    page.locator('#editModeToggle').click()
    page.locator('#nextPhoto').click()
    expect(page.locator('#capturePosition')).to_have_text(re.compile(r'^2 / \d+$'))
    expect(dots.nth(1)).to_have_class(re.compile(r'\bis-current\b'))
    expect(page.locator('#capturePosition .is-current')).to_have_count(1)
    page.locator('#prevPhoto').click()
    expect(page.locator('#captureDescription')).to_contain_text('새 수집 화면')
    page.locator('#nextPhoto').click()
    expect(page.locator('#manualPrimaryPhoto')).to_be_enabled()
    page.locator('#manualPrimaryPhoto').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    page.reload()
    expect(page.locator('#captureDescription')).not_to_contain_text('새 수집 화면')
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
    page.locator('#nextPhoto').click()
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
    expect(page.locator('#captureDescription')).to_contain_text('추가 캡처 확인')
    page.locator('#undoEdit').click()
    page.locator('#saveGuide').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    assert len(saved['photos']) == before_count
    page.reload()
    expect(page.locator('#captureDescription')).not_to_contain_text('추가 캡처 확인')

    representative = page.locator('#captureDescription').inner_text()
    page.locator('#editModeToggle').click()
    page.locator('#editImage').click()
    clipboard_image = BytesIO()
    Image.new('RGB', (40, 24), 'white').save(clipboard_image, format='PNG')
    result = page.locator('#editPhotoNote').evaluate('''(input, base64) => {
        const data = new DataTransfer();
        data.items.add(new File([Uint8Array.from(atob(base64), c => c.charCodeAt(0))], 'capture.png', {type:'image/png'}));
        return input.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }''', b64encode(clipboard_image.getvalue()).decode())
    assert not result
    expect(page.locator('#annotationCanvas image')).to_have_attribute('width', '40')
    expect(page.locator('#editPhotoSelect option:checked')).to_have_text('새 이미지')
    page.locator('#editPhotoStage').fill('붙여넣기 캡처')
    page.locator('#applyImage').click()
    expect(page.locator('#editStatus')).to_contain_text('저장됨')
    assert len(saved['photos']) == before_count + 1
    pasted = next(photo for photo in saved['photos'] if photo['stage'] == '붙여넣기 캡처')
    assert pasted['captureField'] == column and pasted['boxes'] == []
    assert pasted['customImage'].endswith('a' * 64 + '/')
    expect(page.locator('#captureDescription')).to_contain_text('공통 · 붙여넣기 캡처')
    expect(page.locator('#manualPrimaryPhoto')).to_be_enabled()
    page.reload()
    expect(page.locator('#captureDescription')).to_have_text(representative)
    total = int(page.locator('#capturePosition').inner_text().split(' / ')[1])
    for _ in range(total - 1):
        page.locator('#nextPhoto').click()
        if '붙여넣기 캡처' in page.locator('#captureDescription').inner_text():
            break
    expect(page.locator('#captureDescription')).to_contain_text('공통 · 붙여넣기 캡처')
    expect(page.locator('#canvas .view-caption')).to_have_text('등록한 전체 캡처입니다.')
    expect(page.locator('#sceneTabs [data-view="data"]')).to_have_count(0)
    assert not errors, errors
    browser.close()
print('Manual clipboard capture, paging, representative selection, replacement, reload and save retry passed.')
