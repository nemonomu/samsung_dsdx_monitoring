"""Headless UI contract test using synthetic history; no app settings or DB."""
import json
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.dx.dx_layer2.null_validation import review_history as history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default=None)
    args = parser.parse_args()
    template = (ROOT / 'apps/dx/dx_layer2/templates/layer2_null_review_log.html').read_text(encoding='utf-8')
    script = (ROOT / 'apps/dx/dx_layer2/static/dx_layer2/js/null_review_log.js').read_text(encoding='utf-8')
    css = re.search(r'<style>(.*?)</style>', template, re.S).group(1)
    body = re.search(r'{% block layer2_content %}(.*?){% endblock %}', template, re.S).group(1)
    html = ('<!doctype html><html lang="ko"><meta charset="utf-8"><style>'
            ':root{--border-color:#dbe3ef;--text-primary:#19283f;--text-secondary:#64748b;'
            '--layer-color:#269d94;--bg-primary:#f5f8fc}*{box-sizing:border-box}'
            'body{font:14px Arial,"Malgun Gothic",sans-serif;background:#f6f8fc;padding:20px}'
            + css + '</style>' + body + '<script>' + script + '</script></html>')
    today = datetime.now(history.KOREA).date().isoformat()
    records = [dict(id=f'manual:{i}', record_id=i, applied_date=today,
                    country='SEG' if i % 2 else 'SEA', product_line='REF',
                    retailer='OTTO', item=f'ITEM-{i}', sku=f'SKU-{i:04}',
                    retailer_sku_name='샘플 냉장고 330L', product_url='https://example.com/product',
                    collected_at='2026-09-22 10:30', column_name='sku',
                    reason='상품페이지 내 항목 부재', created_id='reviewer',
                    original_created_at='2026-09-23T10:00:00+09:00',
                    memo='현재 페이지 확인.\n해당 항목 표기 없음.' if i % 3 == 0 else '',
                    auto_applied=False, application_type='수동확인') for i in range(1, 122)]
    records[0].update(memo='<img src=x onerror=alert(1)>', product_url='javascript:alert(1)')
    requests = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        page = browser.new_page(viewport={'width': 1550, 'height': 960})
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            if '/api/null-review-logs/' not in route.request.url:
                return route.fulfill(content_type='text/html', body=html)
            params = {key: values[0] for key, values in parse_qs(urlsplit(route.request.url).query).items()}
            requests.append(params)
            options = history.parse_filters(params)
            scoped = [row for row in records if (not options['start'] or row['applied_date'] >= str(options['start']))
                      and (not options['end'] or row['applied_date'] <= str(options['end']))]
            route.fulfill(content_type='application/json', body=json.dumps(history.paginate(scoped, options)))
        page.route('**/*', respond)
        page.goto('http://history.test/')
        page.wait_for_selector('tbody tr')
        assert requests[-1]['period'] == 'today'
        assert page.locator('tbody tr').count() == 50
        assert page.locator('#review-log-calendar').is_hidden()
        page.get_by_role('button', name='2', exact=True).click()
        page.wait_for_function("document.querySelector('tbody td')?.textContent === '51'")
        assert requests[-1]['page'] == '2'
        page.get_by_role('searchbox').fill('SKU-0121')
        page.get_by_role('button', name='조회', exact=True).click()
        page.wait_for_function("document.querySelectorAll('tbody tr').length === 1")
        assert 'SKU-0121' in page.locator('tbody').inner_text()
        assert requests[-1]['page'] == '1'
        page.get_by_role('searchbox').fill('')
        page.get_by_role('checkbox', name='메모 있는 건만').check()
        page.wait_for_function("document.querySelectorAll('tbody tr').length === 41")
        assert page.locator('tbody img').count() == 0
        assert page.locator('tbody a[href^="javascript:"]').count() == 0
        assert '<img src=x onerror=alert(1)>' in page.locator('tbody').inner_text()
        assert page.locator('.review-log-memo').first.evaluate('(el) => getComputedStyle(el).fontWeight') == '750'
        page.get_by_role('button', name='달력', exact=True).click()
        assert page.locator('#review-log-calendar').is_visible()
        page.locator('#review-log-start').fill('2026-09-12')
        page.locator('#review-log-end').fill('2026-09-23')
        page.get_by_role('button', name='조회', exact=True).click()
        page.wait_for_function("document.querySelector('#review-log-body').getAttribute('aria-busy') === 'false'")
        assert requests[-1]['start_date'] == '2026-09-12'
        assert requests[-1]['end_date'] == '2026-09-23'
        page.locator('#review-log-start').fill('2026-09-24')
        before = len(requests)
        page.get_by_role('button', name='조회', exact=True).click()
        assert '늦을 수 없습니다' in page.locator('#review-log-feedback').inner_text()
        assert len(requests) == before
        page.get_by_role('button', name='전체', exact=True).click()
        page.wait_for_function("document.querySelector('#review-log-body').getAttribute('aria-busy') === 'false'")
        assert requests[-1]['period'] == 'all'
        assert 'start_date' not in requests[-1]
        page.get_by_role('checkbox', name='메모 있는 건만').uncheck()
        page.wait_for_function("document.querySelectorAll('tbody tr').length === 50")
        output = ROOT / 'output/diagnostics'
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'null-history-table.png'))
        page.get_by_role('checkbox', name='메모 있는 건만').check()
        page.wait_for_function("document.querySelectorAll('tbody tr').length === 41")
        page.locator('.review-log-scroll').evaluate('(el) => el.scrollLeft = el.scrollWidth')
        page.screenshot(path=str(output / 'null-history-memos.png'))
        assert not errors, errors
        browser.close()
    print('History browser checks passed: today/calendar/all, 50-row pagination, global SKU search, memo filter, XSS escaping, original evidence.')


if __name__ == '__main__':
    main()
