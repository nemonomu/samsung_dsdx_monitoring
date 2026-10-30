"""Real UI components with local API fixtures; no external services or writes."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'apps/dx/dx_layer1/static/dx_layer1'
OUT = ROOT / 'output/diagnostics/metric-review'
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.route('http://metric-review.test/**', lambda route: route.fulfill(status=200, body='<html></html>', content_type='text/html'))
    page.goto('http://metric-review.test/?date=2026-10-30')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('''<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body>
        <div id="collection-issues-container"></div>
        <form id="cs-filters"><input id="cs-date" type="date" value="2026-10-30">
        <select id="cs-country"><option value="ALL">ALL</option></select>
        <select id="cs-product"><option value="ALL">ALL</option></select>
        <select id="cs-retailer"><option value="">ALL</option></select>
        <select id="cs-days"><option value="5">5</option></select></form>
        <div id="cs-message"></div><div id="cs-results"><span id="cs-updated"></span><span id="cs-selection"></span>
        <table><thead id="cs-table-head"></thead><tbody id="cs-table-body"></tbody></table></div>
        </body></html>''')
    for name in ('collection-issues','collection-statistics','retail-review'):
        path=STATIC/'css'/f'{name}.css'
        if path.exists(): page.add_style_tag(path=str(path))
    page.evaluate('''() => {
        window.LAYER1={section:'dashboard'}; window.getCsrfToken=()=>'csrf';
        window.normal={main:false,bsr:false}; window.revisions={main:0,bsr:0};
        window.histories={main:[],bsr:[]}; window.writes=[];
        window.target=metric=>({country:'SEA',product:'LDY',retailer:'Costco',slot:'daily',source_date:'2026-10-28',metric});
        window.decision=metric=>normal[metric]?{action:'confirm',memo:'원본 확인 <safe>',username:'tester',at:'2026-10-30T04:00:00Z',metrics:[metric]}:null;
        window.day=()=>({date:'2026-10-28',slot:'daily',batch_id:'b1',state:'complete',main:63,bsr:71,total:74,
            observation_state:'ready',comparison_state:'ready',bsr_comparison_state:'ready',
            baselines:{main:{value:74.5,days:5},bsr:{value:100,days:0,rule:'fixed_100'}},
            alerts:[{metric:'main',status:'VOLUME_REVIEW',reason:'MAIN low'},{metric:'bsr',status:'VOLUME_LOW',reason:'BSR low'}],
            metric_reviews:Object.fromEntries(['main','bsr'].filter(m=>normal[m]).map(m=>[m,decision(m)]))});
        window.issue=metric=>({id:metric==='main'?1:2,...target(metric),column:'__'+metric,kind:'volume',
            label:metric.toUpperCase()+' 수집량 확인',status:normal[metric]?'confirmed':'open',
            baseline:metric==='main'?74.5:100,observed_count:metric==='main'?63:71,current_count:metric==='main'?63:71,
            review_target:target(metric),history:[],revision:0});
        window.fetch=async(url,options={})=>{
            const params=new URLSearchParams(url.split('?')[1]); let value;
            if(url.includes('/volume-review/')) {
                if(options.method==='POST') {
                    const payload=JSON.parse(options.body); writes.push(payload); revisions[payload.metric]++;
                    normal[payload.metric]=payload.action==='confirm';
                    histories[payload.metric].push({action:payload.action,memo:payload.memo,username:'tester',at:'2026-10-30T04:00:00Z'});
                    value={saved:true};
                } else {const m=params.get('metric');value={target:target(m),counts:[63,71,74,1],inspection_date:'2026-10-29',batch_id:'b1',
                    reasons:[m.toUpperCase()+' check'],decision:decision(m),history:histories[m],revision:revisions[m],token:'fixture-token'};}
            } else if(url.includes('/collection-statistics/')) value={weeks:[{start:'2026-10-26',rows:[{country:'SEA',product:'LDY',retailer:'Costco',slot:'daily',daily:[day()]}]}],baseline_dates:{SEA:'2026-10-29'}};
            else if(/collection-issues\\/[12]\\//.test(url)) value={issue:issue(url.includes('/1/')?'main':'bsr'),queries:{}};
            else value={policy_version:1,start_date:'2026-10-01',target_count:0,scans:[],issues:['main','bsr'].map(issue).filter(i=>params.get('status')==='all'||i.status===params.get('status'))};
            return {ok:true,json:async()=>structuredClone(value)};
        };
    }''')
    for name in ('volume-review','collection-issues','collection-statistics'):
        page.add_script_tag(path=str(STATIC/'js'/f'{name}.js'))
    page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded')); document.getElementById('cs-date').value='2026-10-30'; document.getElementById('cs-date').dispatchEvent(new Event('change')); CollectionIssues.load({date:'2026-10-30'})")
    page.wait_for_selector('[data-ci-detail="1"]')
    page.wait_for_selector('.cs-main-high [data-cs-review]')
    assert page.locator('#cs-message').is_hidden()
    # Direct confirmation from the statistics cell; MAIN only.
    page.locator('.cs-main-high [data-cs-review]').click()
    page.locator('.l1-review-dialog textarea').fill('원본 확인 <safe>')
    page.locator('.l1-review-dialog button[type=submit]').click()
    page.wait_for_selector('.cs-main-confirmed')
    assert page.locator('.cs-bsr-low').count() == 1
    assert page.locator('[data-ci-detail="1"]').count() == 0
    assert page.locator('[data-ci-detail="2"]').count() == 1
    assert page.evaluate('writes[0].metric') == 'main'
    # Confirm BSR from the past incident popup; both statistics cells go green.
    page.locator('[data-ci-detail="2"]').click()
    page.locator('[data-ci-normal]').click()
    page.locator('.l1-review-dialog textarea').fill('BSR 원본 정상')
    page.locator('.l1-review-dialog button[type=submit]').click()
    page.wait_for_selector('.cs-bsr-confirmed')
    page.locator('[data-ci-close]').click()
    page.wait_for_function("document.querySelectorAll('[data-ci-detail]').length===0")
    # Completed-list history remains available and cancellation restores MAIN only.
    page.locator('[data-ci-status]').select_option('confirmed')
    page.wait_for_selector('[data-ci-detail="1"]')
    page.locator('[data-ci-detail="1"]').click()
    page.locator('[data-ci-normal]').click()
    assert '<safe>' in page.locator('.l1-review-dialog').inner_text()
    assert page.locator('.l1-review-dialog safe').count() == 0
    page.screenshot(path=str(OUT/'normal-review-history.png'))
    page.locator('.l1-review-dialog textarea').fill('다시 점검')
    page.locator('.l1-review-dialog button[type=submit]').click()
    page.wait_for_selector('.cs-main-high')
    assert page.locator('.cs-bsr-confirmed').count() == 1
    page.locator('[data-ci-close]').click()
    page.locator('[data-ci-status]').select_option('open')
    page.wait_for_selector('[data-ci-detail="1"]')
    assert page.locator('[data-ci-detail="2"]').count() == 0
    assert not errors, errors
    browser.close()
print('PASS: statistics and past incidents share metric confirmation, history, escaping and cancellation.')
