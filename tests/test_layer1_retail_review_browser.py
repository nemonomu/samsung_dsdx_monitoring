"""Headless review interaction test with synthetic API responses, no production DB."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'apps/dx/dx_layer1/static/dx_layer1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default=None)
    args = parser.parse_args()
    css = '\n'.join(path.read_text(encoding='utf-8') for path in [
        ROOT / 'static/css/common.css', ROOT / 'static/css/table.css',
        BASE / 'css/layer1.css', BASE / 'css/collection-statistics.css', BASE / 'css/retail-review.css',
    ])
    scripts = [ROOT / 'static/js/security.js'] + [BASE / ('js/' + name + '.js') for name in [
        'layer1-common', 'collection-volume', 'retail-status', 'retail-review', 'tse_retail', 'sem_retail',
    ]]
    js = '\n'.join(path.read_text(encoding='utf-8') for path in scripts)
    fixture = r'''
        let selectedDate = '2026-09-30';
        getSelectedDate = () => selectedDate;
        renderCountryFlagLabel = esc;
        L1.retailQuery = {button: () => ''};
        currentStatsData = {checks: [{name:'TSE Retail',check_type:'tse_retail',status:'VOLUME_REVIEW', actual:264,
            categories:[{name:'LDY',status:'VOLUME_REVIEW',expected:300,actual:264,source_date:selectedDate,
                retailers:[{retailer:'Homepro',status:'VOLUME_REVIEW',_volumeBaseStatus:'OK',actual:264,
                    main_count:264,bsr_count:100,batch_count:1,batch_id:'h20260930_090003',
                    volume_alerts:[{metric:'main',status:'VOLUME_REVIEW',baseline:300,actual:264,percent:-12,
                    reason:'MAIN 과거 중앙값 300개 / 수집 264개 / 5~15% 감소 / 확인 필요'}]}]}]},
            {name:'SEM Retail',check_type:'sem_retail',status:'REVIEW',actual:160,
            categories:[{name:'REF',status:'REVIEW',expected:220,actual:160,source_date:selectedDate,
                retailers:[{retailer:'Coppel',status:'REVIEW',main_count:160,bsr_count:100,actual:160,
                expected_precise:220,history_day_count:4,allowed_deviation:50,batch_count:1,
                batch_id:'c20260930_023943',observation_state:'observing',observation_days:4}]}]}]};
        renderLayer1Stats = function(data) {
            L1.retailReview.decorate(data, selectedDate);
            document.getElementById('app').innerHTML = data.checks.map((check,i) => L1.renderers[check.check_type](check,i)).join('');
            document.querySelectorAll('.time-slots-container,.sentiment-two-column').forEach(el => el.classList.add('show'));
        };
        async function refresh() {await L1.retailReview.load(selectedDate); renderLayer1Stats(currentStatsData);}
        refresh();
    '''
    html = '<!doctype html><html lang="ko"><meta charset="utf-8"><style>' + css + (
        'body{padding:28px;background:#f6f8fc;font-family:Arial,"Malgun Gothic",sans-serif}'
        '</style><div id="app"></div><script>' + js + '\n' + fixture + '</script></html>')
    records, errors, posts = [], [], []
    fail = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        page = browser.new_page(viewport={'width': 1450, 'height': 920})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            nonlocal records
            if '/api/retail-reviews/' not in route.request.url:
                return route.fulfill(content_type='text/html', body=html)
            if route.request.method == 'GET':
                day = parse_qs(urlsplit(route.request.url).query)['date'][0]
                return route.fulfill(json={'date':day, 'reviews':[r for r in records if r['context']['date']==day],
                    'previous_reviews':[r for r in records if r['context']['date']<day and r['active']]})
            request = route.request.post_data_json
            posts.append(request)
            if fail:
                return route.fulfill(status=500, json={'error': '저장 실패 테스트'})
            old = next((r for r in records if r['context'] == request['context']), None)
            record = {'context': request['context'], 'active': request['action'] == 'confirm',
                      'revision': request['revision'] + 1, 'history': (old['history'] if old else []) + [{
                          'action': request['action'], 'memo': request['memo'], 'username': '검수자',
                          'at': '2026-09-30T03:20:00+00:00',
                      }]}
            records = [r for r in records if r['context'] != record['context']] + [record]
            route.fulfill(json={'review': record})

        page.route('**/*', respond)
        page.goto('http://review.test/')
        buttons = page.locator('.l1-review-badge')
        expect(buttons).to_have_count(2)
        assert buttons.nth(0).evaluate('(el) => getComputedStyle(el).color') == buttons.nth(1).evaluate('(el) => getComputedStyle(el).color')
        buttons.nth(0).hover()
        assert '300개 / 수집 264개' in buttons.nth(0).get_attribute('title')
        assert '평균 220건' in buttons.nth(1).get_attribute('title')
        buttons.nth(0).click()
        expect(page.locator('dialog')).to_be_visible()
        box = page.locator('dialog').bounding_box()
        assert abs(box['x'] + box['width'] / 2 - 725) < 2, 'dialog should be centered'
        expect(page.locator('.l1-review-reasons')).to_contain_text('300개 / 수집 264개')
        page.locator('textarea').fill('원본 사이트 상품 수와 일치')
        output = ROOT / 'output/diagnostics'
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'layer1-review-dialog.png'))
        page.locator('dialog button[data-primary]').click()
        expect(page.locator('dialog')).to_have_count(0)
        expect(buttons.nth(0)).to_have_text('✓ 정상 확인')
        expect(page.locator('.check-item').first.locator('.check-stats')).to_contain_text('✓ 정상 확인')
        expect(page.locator('.check-item').first.locator('.sentiment-category-stats')).to_contain_text('✓ 정상 확인')
        page.screenshot(path=str(output / 'layer1-review-confirmed.png'))
        page.reload()
        expect(buttons.nth(0)).to_have_text('✓ 정상 확인')
        buttons.nth(0).click()
        expect(page.locator('.l1-review-confirmed')).to_contain_text('원본 사이트 상품 수와 일치')
        page.locator('textarea').fill('원본 재확인 필요')
        page.locator('dialog button[data-primary]').click()
        expect(page.locator('dialog')).to_have_count(0)
        expect(buttons.nth(0)).to_have_text('확인 필요')
        assert [event['action'] for event in records[0]['history']] == ['confirm', 'cancel']
        buttons.nth(0).click()
        page.locator('textarea').fill('원본과 일치함')
        fail = True
        page.locator('dialog button[data-primary]').click()
        expect(page.locator('.l1-review-error')).to_contain_text('저장 실패 테스트')
        assert not records[0]['active']
        page.locator('dialog [data-close]').click()
        fail = False
        # Changed data while the modal is open must not save the stale review.
        buttons.nth(0).click()
        page.locator('textarea').fill('변경 이전 검토')
        page.evaluate("currentStatsData.checks[0].categories[0].retailers[0].batch_id='new-batch';renderLayer1Stats(currentStatsData)")
        count = len(posts)
        page.locator('dialog button[data-primary]').click()
        expect(page.locator('.l1-review-error')).to_contain_text('수집 결과가 변경되었습니다')
        assert count == len(posts)
        page.keyboard.press('Escape')
        expect(page.locator('dialog')).to_have_count(0)
        page.evaluate("""() => {
            const check = currentStatsData.checks[1], cat = check.categories[0], row = cat.retailers[0];
            check.status = cat.status = row.status = 'OK';
            check.phase = 'complete';
            L1.collectionVolume.decorate(currentStatsData, {policy_version:4, inspection_date:selectedDate,
                snapshots:[{country:'SEM',available:true,source_date:selectedDate,rows:[{
                    product:'REF',retailer:'Coppel',slot:'daily',observation_state:'ready',
                    rules:{main:{rule:'median_28d',baseline:160,days:5,low_percent:30},
                           bsr:{rule:'median_28d',baseline:100,days:5,low_percent:30}}
                }]}]}, selectedDate);
            renderLayer1Stats(currentStatsData);
        }""")
        group = page.locator('.check-item').nth(1)
        expect(group.locator('.check-stats .status-badge')).to_have_text('정상')
        expect(group.locator('.sentiment-category-stats .status-badge')).to_have_text('정상')
        expect(group.locator('.rt-status')).to_contain_text('정상')
        expect(group.locator('.l1-review-badge')).to_have_count(0)
        assert '정상 확인' not in group.inner_text()
        assert '검증 대기' not in group.inner_text()
        assert '수집중' not in group.inner_text()
        # Real SEA renderer: new dryer BSR99 -> confirm -> next day99 -> pending.
        page.add_script_tag(content='RawDataView=function(){};L1.initLayer1Page=()=>{};' + (BASE/'js/retail.js').read_text(encoding='utf-8'))
        page.evaluate('''() => {
            addCheckBadges=()=>{};
            expandSectionContent=()=>document.querySelectorAll('.time-slots-container,.sentiment-two-column').forEach(e=>e.classList.add('show'));
            window.showCostco=async(day,observation='observing',bsr=99)=>{
                selectedDate=day;
                const source=day==='2026-10-13'?'2026-10-12':'2026-10-13';
                const row={retailer:'Costco',status:'OK',count:300,main_count:300,bsr_count:bsr,batch_count:1,
                    batch_id:'c'+day,items:[{name:'Main Rank',count:300},{name:'BSR Rank',count:bsr}]};
                currentStatsData={checks:[{name:'SEA Retail',check_type:'retail',phase:'complete',status:'OK',
                    categories:[{name:'LDY_DRYER',total:300,source_date:source,time_slots:[{name:'일일',retailers:[row]}]}]}]};
                await L1.retailReview.load(day);
                L1.collectionVolume.decorate(currentStatsData,{policy_version:4,inspection_date:day,snapshots:[{
                    country:'SEA',source_date:source,available:true,rows:[{product:'LDY_DRYER',retailer:'Costco',slot:'일일',
                        observation_state:observation,observation_prior_days:3,
                        rules:{main:{rule:'median_28d',baseline:300,days:5,low_percent:30}}}]}]},day);
                document.getElementById('app').innerHTML='<div id="section-content"></div>';
                renderSeaRetailSection(currentStatsData);
            };
        }''')
        page.evaluate("showCostco('2026-10-13')")
        expect(page.locator('.l1-review-badge')).to_have_text('확인 필요')
        page.locator('.l1-review-count').click()
        expect(page.locator('dialog')).to_contain_text('BSR 99건')
        page.locator('textarea').fill('실제 사이트 BSR 99건과 일치')
        page.locator('dialog [data-primary]').click()
        expect(page.locator('.l1-review-badge')).to_have_text('✓ 정상 확인')
        page.evaluate("showCostco('2026-10-13')")
        expect(page.locator('.l1-review-badge')).to_have_text('✓ 정상 확인')
        page.evaluate("showCostco('2026-10-14','ready')")
        expect(page.locator('.l1-review-badge')).to_have_text('확인 필요')
        page.locator('.l1-review-count').click()
        page.locator('.l1-previous-review summary').click()
        expect(page.locator('.l1-previous-review')).to_contain_text('실제 사이트 BSR 99건과 일치')
        expect(page.locator('.l1-previous-review')).to_contain_text('2026-10-13')
        page.screenshot(path=str(output/'layer1-costco-next-day-review.png'))
        page.locator('textarea').fill('이번 배치는 원본과 불일치')
        page.locator('dialog [data-reject]').click()
        expect(page.locator('.l1-review-badge')).to_have_text('이상 확정')
        page.locator('.l1-review-badge').click()
        page.locator('textarea').fill('다시 확인 필요')
        page.locator('dialog [data-primary]').click()
        expect(page.locator('.l1-review-badge')).to_have_text('확인 필요')
        assert not errors, errors
        browser.close()
    print('Browser: unified colors, reasons, confirm/reload/cancel, failure and stale modal passed.')


if __name__ == '__main__':
    main()
