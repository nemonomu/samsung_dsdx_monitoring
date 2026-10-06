"""Accordion and escaping checks against real renderer/CSS, without a database."""
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.dx.dx_layer1.event_master.services import COUNTRIES, build_check
from playwright.sync_api import sync_playwright, expect


def main():
    base = ROOT / 'apps/dx/dx_layer1/static/dx_layer1'
    css = '\n'.join(p.read_text(encoding='utf-8') for p in [
        ROOT / 'static/css/common.css', ROOT / 'static/css/table.css',
        base / 'css/layer1.css', base / 'css/event-master.css'])
    groups = [(name, code, 20, '2026-10-05') for code, name in COUNTRIES.items()]
    check = build_check('2026-10-06', groups + [('NEW ZELAND', 'NZ', 1, '2026-10-06')], datetime(2026, 10, 6))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1100, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content('<meta charset="utf-8"><style>' + css + '</style><div id="fixture"></div>')
        page.add_script_tag(path=str(ROOT / 'static/js/security.js'))
        page.add_script_tag(content='var L1 = {renderers:{}};')
        page.add_script_tag(path=str(base / 'js/event-master.js'))
        page.evaluate('(check) => {window.check=check; document.getElementById("fixture").innerHTML=L1.renderers.event_master(check)}', check)
        outer = page.locator('details.event-master')
        expect(outer).not_to_have_attribute('open', '')
        expect(page.locator('.event-master-status')).to_contain_text('57 / 57')
        outer.locator(':scope > summary').click()
        expect(page.get_by_text('국가명 오류:', exact=False)).to_be_visible()
        normal = page.locator('details.event-master-normal')
        expect(normal).not_to_have_attribute('open', '')
        normal.locator(':scope > summary').click()
        expect(normal.locator('tbody tr')).to_have_count(56)
        page.evaluate('document.getElementById("fixture").innerHTML=L1.renderers.event_master(window.check)')
        expect(page.locator('details.event-master')).to_have_attribute('open', '')
        expect(page.locator('details.event-master-normal')).to_have_attribute('open', '')
        normal.locator(':scope > summary').click()
        out = ROOT / 'output/event-master-qa'
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(out / 'mobile.png'), full_page=True)
        check['inspection_date'] = '2026-09-15'
        check['unexpected'] = [{'country':'<img src=x onerror=alert(1)>','country_code':'??',
            'status':'REVIEW','issues':['<script>bad</script>'],'issue_count':1,'execution_date':'2026-09-07'}]
        page.evaluate('(check) => document.getElementById("fixture").innerHTML=L1.renderers.event_master(check)', check)
        expect(page.locator('details.event-master')).not_to_have_attribute('open', '')
        expect(page.locator('#fixture img, #fixture script')).to_have_count(0)
        scheduled = build_check('2026-10-07', [], datetime(2026, 10, 7))
        page.evaluate('(check) => document.getElementById("fixture").innerHTML=L1.renderers.event_master(check)', scheduled)
        page.locator('details.event-master > summary').click()
        expect(page.locator('.event-master-note')).to_contain_text('2026-11-02 적재 예정')
        expect(page.locator('#fixture')).not_to_contain_text('미수집')
        assert not errors, errors
        browser.close()
    print('Event Master: accordion, repaint, date change, escaping and mobile layout passed.')


if __name__ == '__main__':
    main()
