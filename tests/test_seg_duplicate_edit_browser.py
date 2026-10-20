"""Exercise SKU editing and duplicate reload using real UI code and mocked API."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'apps/dx/dx_layer2/static/dx_layer2'
scripts = [ROOT / f'static/js/{name}.js' for name in (
    'security', 'format', 'ui', 'pagination', 'table', 'filter-bar',
)] + [BASE / f'js/{name}.js' for name in (
    'layer2-common', 'null_validation', 'anomaly_validation',
)]
styles = [ROOT / f'static/css/{name}.css' for name in (
    'common', 'table', 'buttons', 'filter-bar',
)] + [BASE / 'css/layer2.css']
fixture = """
function initFilterBar() {}
checkBackupStatus = () => {};
function fetchDXStats() {}
getSelectedDate = () => '2026-10-20';
isInlineMode = () => true;
getDetailBody = () => document.getElementById('app');
getCsrfToken = () => 'fixture';
let refreshed = 0;
let activeFixture;
function loadFixture(data, pages) {
    if (data.actual_table) activeFixture = data;
    modalState.type = 'duplicate';
    modalState.tableName = activeFixture.display_name;
    modalState.tableParam = activeFixture.table;
    modalState.retailer = activeFixture.retailer;
    modalState.count = 2;
    modalState.totalPages = pages;
    modalState.totalGroups = 2;
    modalState.currentPage = 1;
    modalState.days = 3; // Stale NULL history selection must not disable today's edit.
    renderDetailTable('duplicate', data, activeFixture.table);
}
openDetailModal = async function(type, table, retailer, count, page) {
    if (type !== 'duplicate' || table !== activeFixture.display_name || retailer !== activeFixture.retailer || page !== 1)
        throw Error('Incorrect reload scope');
    const response = await fetch('/fixture-detail');
    loadFixture(await response.json(), 1);
    refreshed++;
};
"""
html = ('<!doctype html><meta charset="utf-8"><style>body{padding:24px}'
        + '\n'.join(p.read_text(encoding='utf-8') for p in styles)
        + '</style><div id="app"></div><script>'
        + '\n'.join(p.read_text(encoding='utf-8') for p in scripts)
        + fixture + '</script>')

COUNTRIES = (
    ('SEG REF', 'seg_ref_retail', 'dx_seg.dx_seg_ref_retail_com', 'OTTO', 'crawl_strdatetime', '2026-10-20'),
    ('SEA LDY_DRYER', 'sea_ldy_dryer_retail', 'public.ldy_dryer_retail', 'Lowes', 'crawl_datetime', '2026-10-19'),
    ('SEDA REF', 'seda_ref_retail', 'dx_seda.dx_seda_ref_retail_com', 'Magalu', 'crawl_strdatetime', '2026-10-19'),
    ('SIEL REF', 'siel_ref_retail', 'dx_siel.dx_siel_ref_retail_com', 'Amazon', 'crawl_datetime', '2026-10-20'),
    ('SEM REF', 'sem_ref_retail', 'dx_sem.dx_sem_ref_retail_com', 'HomeDepot', 'crawl_datetime', '2026-10-20'),
    ('TSE REF', 'tse_ref_retail', 'dx_tse.dx_tse_ref_retail_com', 'Homepro', 'crawl_datetime', '2026-10-20'),
    ('SEIB REF', 'seib_ref_retail', 'dx_seib.dx_seib_ref_retail_com', 'MediaMarkt', 'crawl_datetime', '2026-10-20'),
)


def payload(country=COUNTRIES[0]):
    display, section, table, retailer, date_column, source_day = country
    return {
        'display_name': display, 'table': section,
        'date': '2026-10-20', 'source_date': source_day,
        'date_column': date_column, 'editable_date': source_day,
        'actual_table': table, 'retailer': retailer,
        'readonly': False, 'allow_cleanup': False, 'editable_cols': ['sku'],
        'edit_message': 'SKU 셀을 더블클릭해 수정한 뒤 저장하세요.',
        'results': {'duplicates': [{
            'item': 'same', 'page_type': 'MAIN', 'duplicate_type': '상품 매핑 충돌',
            'retailer_sku_name': 'Option A, Option B', 'reason': '동일 item + SKU',
            'dup_count': 2, 'records': [
                {'id': i, 'sku': 'OLD-SKU', 'retailer_sku_name': f'Option {i}',
                 date_column: source_day + 'T21:22:19-04:00'}
                for i in (108558, 108584)
            ],
        }]},
    }

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1450, 'height': 920})
    errors, posted = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    fail = False

    def route(req):
        if req.request.url.endswith('/api/update-cell/'):
            posted.append(req.request.post_data_json)
            req.fulfill(status=400 if fail else 200, content_type='application/json',
                        body=json.dumps({'error': '수정 실패'} if fail else {'success': True}))
        elif req.request.url.endswith('/fixture-detail'):
            req.fulfill(content_type='application/json', body='{"results":{"duplicates":[]}}')
        else:
            req.fulfill(content_type='text/html', body=html)

    page.route('https://monitoring.test/**', route)
    for country, pages in ((country, pages) for country in COUNTRIES for pages in (1, 2)):
        page.goto('https://monitoring.test/')
        page.evaluate('([data, pages]) => loadFixture(data, pages)', [payload(country), pages])
        expect(page.locator('td[data-editable]')).to_have_count(2)
        expect(page.locator('td[data-editable]:not([data-col="sku"])')).to_have_count(0)
        expect(page.locator('.dup-check')).to_have_count(0)
        expect(page.get_by_text('선택 삭제', exact=True)).to_have_count(0)
        cell = page.locator('td[data-row-id="108558"][data-col="sku"]')
        cell.dblclick()
        page.locator('.cell-edit-overlay').fill('CORRECT-SKU')
        page.locator('.cell-edit-overlay').press('Enter')
        expect(cell).to_have_text('CORRECT-SKU')
        page.locator('#btn-save-edits').click()
        page.locator('.memo-dialog-input').fill('옵션 SKU 수정')
        page.locator('.memo-dialog-confirm').click()
        expect(page.locator('#app')).to_contain_text('데이터가 없습니다')
        assert posted[-1] == {
            'table_name': country[2], 'row_id': 108558,
            'column_name': 'sku', 'new_value': 'CORRECT-SKU',
            'crawl_date': '2026-10-20', 'correction_type': 'duplicate', 'memo': '옵션 SKU 수정',
        }
        assert page.evaluate('refreshed') == 1
    # A rejected save keeps the edit available and does not reload away the evidence.
    fail = True
    page.goto('https://monitoring.test/')
    page.evaluate('data => loadFixture(data, 2)', payload())
    cell = page.locator('td[data-row-id="108558"][data-col="sku"]')
    cell.dblclick()
    page.locator('.cell-edit-overlay').fill('RETRY-SKU')
    page.locator('.cell-edit-overlay').press('Enter')
    page.locator('#btn-save-edits').click()
    page.locator('.memo-dialog-confirm').click()
    expect(page.locator('#btn-save-edits')).to_be_enabled()
    expect(cell).to_have_class('cell-pending')
    assert page.evaluate('refreshed') == 0
    fail = False
    page.locator('#btn-save-edits').click()
    page.locator('.memo-dialog-confirm').last.click()
    expect(page.locator('#app')).to_contain_text('데이터가 없습니다')
    assert posted[-1]['new_value'] == 'RETRY-SKU'
    assert page.evaluate('refreshed') == 1
    assert not errors, errors
    browser.close()
print('Seven-country duplicate SKU editing: client/server pagination, D-1, audit payload, reload and failed save passed.')
