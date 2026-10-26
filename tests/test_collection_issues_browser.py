"""Production component browser checks with deterministic API fixtures."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'apps/dx/dx_layer1/static/dx_layer1'
OUT=ROOT/'output/diagnostics/collection-issues'
OUT.mkdir(parents=True,exist_ok=True)

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content("""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
    body{font:14px 'Malgun Gothic',sans-serif;color:#20314a;background:#f6f9fc;margin:0}header{padding:24px;background:white;border-bottom:1px solid #dfe7f0;font-size:20px;font-weight:bold}main{margin:30px auto;max-width:1180px;padding:0 20px}.hero{background:#20385e;color:white;padding:32px;border-radius:12px;margin-bottom:24px}.hero h1{font-size:26px;margin:0}.datebar,.stats{background:white;border:1px solid #dfe7f0;border-radius:10px;padding:22px;margin-bottom:22px}button,input{font:inherit}input{padding:8px;border:1px solid #dfe7f0;border-radius:5px}
    </style></head><body><header>◇ Trusted Data · Layer 1</header><main><div class="hero"><h1>기본 통계 검수</h1><p>DX 데이터 품질 모니터링</p></div><div id="filter-bar-container" class="datebar">조회 날짜 <input type="date" value="2026-10-20"></div><div id="collection-issues-container" hidden></div><div id="stats-grid" class="stats">총 검증 항목　6　　　 정상　6　　　 실패　0</div></main></body></html>""")
    page.add_style_tag(path=str(STATIC/'css/collection-issues.css'))
    page.evaluate("""()=>{
        window.LAYER1={section:'dashboard'};window.getCsrfToken=()=>'test-csrf';
        window.calls=[];window.failed=false;
        window.issue={id:1,country:'SEA',product:'REF',retailer:'Costco',source_date:'2026-10-14',column:'',severity:'uncollected',status:'open',baseline:null,observed_count:0,current_count:0,revision:0,first_detected_at:'2026-10-15T00:00:00Z',last_checked_at:'2026-10-20T00:00:00Z',history:[{action:'detected',username:'',reason:'',created_at:'2026-10-15T00:00:00Z'}]};
        window.sqls={count:"SELECT COUNT(*) FROM public.ref_retail_com WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-10-14';",rows:"SELECT * FROM public.ref_retail_com WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-10-14';",batches:"SELECT batch_id, COUNT(*) FROM public.ref_retail_com WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-10-14' GROUP BY batch_id;"};
        window.fetch=async(url,options={})=>{
            calls.push({url,options});let value={},ok=true;
            if(url.includes('/action/')){
                const input=JSON.parse(options.body);issue.revision++;
                issue.history.push({action:input.action,username:'reviewer',reason:input.reason,created_at:'2026-10-20T01:00:00Z'});
                if(input.action==='except')issue.status='excepted';
                value={issue:structuredClone(issue)};
            }else if(url.includes('/sql/'))value={queries:sqls};
            else if(url.includes('/1/'))value={issue:structuredClone(issue),queries:sqls};
            else {
                if(failed){ok=false;value={error:'조회 실패'};}
                else {
                    const params=new URLSearchParams(url.split('?')[1]),state=params.get('status');
                    const columnIssue={...structuredClone(issue),id:2,column:'inventory_status',severity:'abnormal',status:'open',baseline:38,observed_count:0};
                    const extra=window.extraIssues||[];
                    value={start_date:'2026-10-01',target_count:1,scans:window.pending?[]:[{scanned_through:'2026-10-18',last_checked_at:'2026-10-20T00:00:00Z',error:false,pending:false}],issues:[issue,columnIssue,...extra].filter(row=>state===row.status).map(row=>structuredClone(row))};
                }
            }
            return {ok,json:async()=>value};
        };
    }""")
    page.add_script_tag(path=str(STATIC/'js/collection-issues.js'))
    page.evaluate("CollectionIssues.load({date:'2026-10-20'})")
    page.wait_for_selector('[data-ci-detail]')
    assert page.evaluate("new URLSearchParams(calls.at(-1).url.split('?')[1]).get('inspection_date')") == '2026-10-20'
    assert page.locator('.ci-head h3').inner_text() == '과거 미해결 · 미수집·수집 이상 1건'
    assert page.locator('#ci-status').count() == 0
    assert 'inventory_status' not in page.locator('.ci-panel').inner_text()
    assert page.evaluate("""()=>{
        let a=document.querySelector('#filter-bar-container').getBoundingClientRect(),b=document.querySelector('.ci-panel').getBoundingClientRect(),c=document.querySelector('#stats-grid').getBoundingClientRect();return a.bottom<=b.top&&b.bottom<=c.top;
    }""")
    page.screenshot(path=str(OUT/'backlog-desktop.png'))
    page.evaluate("CollectionIssues.load({date:'2026-10-19'})")
    page.wait_for_selector('[data-ci-sql]')
    assert page.evaluate("new URLSearchParams(calls.at(-1).url.split('?')[1]).get('inspection_date')") == '2026-10-19'
    assert '2026-10-14' in page.locator('.ci-panel').inner_text()
    page.locator('[data-ci-sql]').click()
    page.wait_for_selector('#ci-sql-text')
    for kind in ['count','rows','batches']:
        page.locator(f'[data-ci-kind="{kind}"]').click()
        assert "'2026-10-14'" in page.locator('#ci-sql-text').input_value()
    page.locator('[data-ci-copy]').click()
    assert '복사' in page.locator('#ci-message').inner_text()
    page.screenshot(path=str(OUT/'source-sql.png'))
    page.locator('[data-ci-close]').click()
    page.locator('[data-ci-detail]').click()
    page.locator('[data-ci-action="except"]').click()
    assert '사유' in page.locator('#ci-message').inner_text()
    page.locator('#ci-reason').fill('<script>bad()</script> 원본 확인')
    page.locator('[data-ci-action="acknowledge"]').click()
    page.wait_for_function('issue.revision===1')
    assert page.evaluate('issue.status')=='open'
    assert page.locator('dialog script').count()==0
    assert '담당자 확인' in page.locator('dialog').inner_text()
    page.locator('#ci-reason').fill('등록된 비수집일')
    page.locator('[data-ci-action="except"]').click()
    page.wait_for_function("issue.status==='excepted'")
    page.locator('[data-ci-close]').click()
    page.wait_for_function("document.querySelector('.ci-head h3').textContent.includes('0건')")
    assert page.locator('#ci-status').count() == 0
    assert '예외 처리' not in page.locator('.ci-panel').inner_text()
    page.evaluate("""()=>{
        issue.status='open';
        window.extraIssues=[
            {...issue,id:3,kind:'volume',column:'__main:daily',label:'MAIN 수집량 부족',baseline:293,current_count:131},
            {...issue,id:4,kind:'batches',column:'__batches',label:'배치 ID 2개',batch_ids:['b1','b2']},
            {...issue,id:5,status:'resolved',kind:'volume',column:'__bsr:daily',label:'BSR 수집량 부족'}
        ];
        CollectionIssues.load({date:'2026-10-20'},true);
    }""")
    page.wait_for_selector('[data-ci-detail="4"]')
    assert page.locator('.ci-panel tbody tr').count() == 1
    assert page.locator('[data-ci-detail]').count() == 3
    assert 'b1 · b2' in page.locator('.ci-panel').inner_text()
    assert 'BSR 수집량 부족' not in page.locator('.ci-panel').inner_text()
    assert '1건' in page.locator('.ci-head h3').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'backlog-mobile.png'))
    page.evaluate("pending=true; issue.status='excepted'; extraIssues=[]; CollectionIssues.load({date:'2026-10-20'},true)")
    page.wait_for_function("document.querySelector('.ci-head h3').textContent.includes('점검 중')")
    assert '0건으로 확정하지 않습니다' in page.locator('.ci-panel').inner_text()
    page.evaluate("failed=true; CollectionIssues.load({date:'2026-10-20'},true)")
    page.wait_for_selector('[role="alert"]')
    assert '미해결 없음으로 처리하지 않습니다' in page.locator('[role="alert"]').inner_text()
    # Alert pages use inspection ranges, with no backlog request or panel.
    page.evaluate("""()=>{
        failed=false;issue.status='open';LAYER1.section='column_alerts';
        calls.length=0;
        document.querySelector('#collection-issues-container').outerHTML='<div id="collection-issues-container" hidden></div>';
        document.querySelectorAll('dialog').forEach(dialog=>dialog.remove());
    }""")
    page.add_script_tag(path=str(STATIC/'js/collection-issues.js'))
    page.evaluate("CollectionIssues.load({date:'2026-10-20'})")
    assert page.evaluate('calls.length') == 0
    assert page.locator('.ci-panel').count() == 0
    # SQL for a selected source date still works without the backlog panel.
    page.evaluate("CollectionIssues.sql({country:'SEA',product:'REF',retailer:'Costco',source_date:'2026-10-14'})")
    page.wait_for_selector('#ci-sql-text')
    assert "'2026-10-14'" in page.locator('#ci-sql-text').input_value()
    assert not errors,errors
    browser.close()
print('PASS: production backlog placement, unchanged original date, SQL tabs/copy, acknowledgement persistence, mandatory exception reason, history, XSS escaping, mobile and query failure.')
