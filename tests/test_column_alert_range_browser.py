"""Render the actual alert template and exercise range queries with API fixtures."""
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import django
from django.conf import settings
from django.template import Context, Engine
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'apps/dx/dx_layer1/static/dx_layer1'
settings.configure(SECRET_KEY='test-only', INSTALLED_APPS=[], STATIC_URL='/static/')
django.setup()
base = '''{% block layer1_css %}{% endblock %}
<div id="collection-issues-container" hidden></div>
{% block layer1_content %}{% endblock %}'''
engine = Engine(
    dirs=[str(ROOT / 'apps/dx/dx_layer1/templates')],
    loaders=[('django.template.loaders.locmem.Loader', {'base_layer1.html': base}),
             'django.template.loaders.filesystem.Loader'],
    libraries={'static': 'django.templatetags.static'},
)
catalog = [{'country': 'SEA', 'product': 'TV', 'retailers': ['Amazon', 'Bestbuy']}]
html = engine.get_template('dx_layer1_column_alerts.html').render(Context({'column_catalog': catalog}))
styles = '\n'.join((STATIC / 'css' / name).read_text(encoding='utf-8') for name in [
    'collection-statistics.css', 'column-statistics.css', 'collection-issues.css',
])
document = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><style>
body{{font:14px 'Malgun Gothic',sans-serif;background:#f7f9fc;margin:0;padding:20px}}
*{{box-sizing:border-box}}{styles}</style><body>{html}</body></html>'''
requests, errors = [], []

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))

    def route(request):
        url = request.request.url
        if '/api/' in url:
            assert '/api/column-statistics/' in url, url
            query = parse_qs(urlparse(url).query)
            requests.append(query)
            inspection = query['date'][0]
            source = (date.fromisoformat(inspection) - timedelta(days=1)).isoformat()
            request.fulfill(json={
                'inspection_date': inspection, 'comparison_date': source,
                'comparisons': [{'column': 'sku_status', 'status': 'abnormal',
                                 'history_days': 28, 'baseline': 100, 'current': 20,
                                 'ratio': 20, 'delta': -80}],
            })
        elif '/static/' in url:
            request.fulfill(body='', content_type='text/css')
        else:
            request.fulfill(body=document, content_type='text/html')

    page.route('**/*', route)
    page.goto('http://column-alerts.test/?start_date=2026-09-30&end_date=2026-10-02')
    page.evaluate("window.LAYER1={section:'column_alerts'}; window.setSidebarIssueBadge=()=>{}")
    for script in ['collection-issues.js', 'column-alert-cache.js', 'column-comparison.js', 'column-alerts.js']:
        page.add_script_tag(path=str(STATIC / 'js' / script))
    page.wait_for_function("document.querySelector('#cca-progress').textContent.includes('확인 완료')")
    assert len(requests) == 6
    assert page.locator('#cca-body tr').count() == 6
    assert page.locator('#cca-body tr').first.locator('td').first.inner_text() == '2026-10-02'
    assert 'date=2026-10-02' in page.locator('#cca-body a').first.get_attribute('href')
    assert page.locator('.ci-panel').count() == 0
    assert '미해결' not in page.locator('body').inner_text()
    assert page.locator('#cca-start-date').input_value() == '2026-09-30'
    assert page.locator('#cca-end-date').input_value() == '2026-10-02'
    page.screenshot(path=str(ROOT / 'output/column-alert-range-desktop.png'), full_page=True)

    page.locator('#cca-end-date').fill('2026-09-29')
    page.locator('#cca-filters button').click()
    assert len(requests) == 6, 'invalid range must not request data'
    assert not page.locator('#cca-end-date').evaluate('(el)=>el.checkValidity()')
    page.locator('#cca-end-date').fill('2026-09-30')
    page.locator('#cca-filters button').click()
    page.wait_for_function("document.querySelector('#cca-progress').textContent.includes('확인 완료')")
    assert len(requests) == 8
    assert page.locator('#cca-body tr').count() == 2
    page.locator('#cca-search').fill('nonexistent')
    assert page.locator('#cca-body .ccs-badge').count() == 0
    page.locator('#cca-search').fill('sku_status')
    assert page.locator('#cca-body tr').count() == 2
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(ROOT / 'output/column-alert-range-mobile.png'), full_page=True)
    assert not errors, errors
    browser.close()
print('PASS: range boundaries, source/detail dates, backlog removal, invalid-range recovery, search, desktop and mobile layout.')
