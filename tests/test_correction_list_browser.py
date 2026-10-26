"""Exercise the real corrections template and production list/detail JS, without a DB."""
import json
import re
from copy import deepcopy
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_correction_audit_browser import ROOT, ITEM, ROW, DATA


def main():
    template=(ROOT/'apps/dx/dx_layer4/templates/layer4/corrections.html').read_text(encoding='utf-8')
    content=template.split('{% block layer4_content %}')[1].split('{% endblock %}')[0]
    content=re.sub(r'<script>.*?</script>','',content,flags=re.S)
    style=template.split('{% block layer4_css %}')[1].split('{% endblock %}')[0]
    style=re.sub(r'<link[^>]+>','',style)
    styles='\n'.join((ROOT/path).read_text(encoding='utf-8') for path in [
        'static/css/common.css','static/css/buttons.css','static/css/modal.css','apps/dx/dx_layer4/static/dx_layer4/css/layer4.css',
        'apps/dx/dx_layer4/static/dx_layer4/css/correction-detail.css'])
    records=[]
    for i in range(3):
        row={**ITEM,'id':7+i,'item':'A'+str(i),'record_id':42+i,'category_label':'SEUK TV',
             'country':'SEUK','product':'TV','product_url':ROW['product_url'],'retailer_sku_name':'Sample TV '+str(i),
             'crawl_time':'2026-10-27T01:20:00+09:00','source_available':True,
             'comparison_rows':[dict(id=30+i,source_date='2026-10-25',crawl_time='2026-10-25T01:00:00+09:00',value=None,field_available=True,product_url=ROW['product_url']),
                                dict(id=35+i,source_date='2026-10-26',crawl_time='2026-10-26T01:00:00+09:00',value='£400.00',field_available=True,product_url=ROW['product_url'])]}
        if i==2: row.update(status='normal',old_value=None,new_value=None)
        records.append(row)
    payload=dict(success=True,items=records,page=1,page_size=50,total=3,total_pages=1,status_counts={'corrected':2,'normal':1,'reverted':0},
                 type_counts={'cross_field':3},filter_options={'countries':['SEUK'],'products':['TV'],
                                                           'retailers':['Currys'],'reviewers':['tester']})
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1680,'height':1120})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content('<style>'+styles+'</style>'+style+'<style>:root{--layer-color:#764ba2;--page-color:#764ba2}body{display:block}main{padding:24px}</style><main>'+content+'</main>')
        page.evaluate('''() => {
            window.L4={_sectionHandler:{},_sectionInit:{},escapeHtml:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),TYPE_NAMES:{cross_field:'크로스필드'},STATUS_NAMES:{corrected:'수정',normal:'확인'}};
            window.showToast=(text)=>window.lastToast=text;
            window.CORRECTIONS_IS_ADMIN=false;window.getSelectedDate=()=> '2026-10-27';window.calls=[];
        }''')
        page.evaluate('data=>window.listFixture=data',payload)
        page.evaluate('data=>window.detailFixture=data',DATA)
        page.evaluate('''() => {window.fetch=async url=>{
            window.calls.push(url);const parsed=new URL(url,'https://example.test');
            let data=window.listFixture;
            if(url.includes('/detail/'))data=window.detailFixture;
            else if(url.includes('/query/'))data={success:true,sql:'SELECT 1;'};
            else{data=JSON.parse(JSON.stringify(data));if(parsed.searchParams.get('days')==='1')data.items.forEach(r=>r.comparison_rows=[]);}
            return {ok:true,json:async()=>data};
        };}''')
        for path in ['static/js/modal.js','apps/dx/dx_layer4/static/dx_layer4/js/correction-detail.js',
                     'apps/dx/dx_layer4/static/dx_layer4/js/correction-list.js',
                     'apps/dx/dx_layer4/static/dx_layer4/js/corrections.js']:
            page.add_script_tag(content=(ROOT/path).read_text(encoding='utf-8'))
        page.evaluate("L4._sectionInit.corrections();L4._sectionHandler.corrections();")
        page.wait_for_selector('.audit-group-table')
        assert page.locator('.audit-current-row').count()==3
        assert page.locator('.audit-comparison-row').count()==6
        assert page.locator('[data-col=product][rowspan="3"]').count()==3
        assert page.locator('#corr-total').inner_text()=='3'
        assert page.locator('#corr-corrected').inner_text()=='2'
        assert page.locator('[data-corr-detail]').count()==3
        assert page.locator('.audit-group-table a').count()==9
        assert page.locator('[data-col=category]').nth(1).inner_text().startswith('SEUK TV')
        assert page.locator('#correction-row-count').inner_text().endswith('9행')
        (ROOT/'tmp').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/'tmp/correction_list_production.png'),full_page=True)
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_selector('#audit-source .audit-table')
        modal=page.locator('#modal-corr-detail')
        assert modal.is_visible()
        assert modal.get_attribute('role')=='dialog'
        assert page.locator('#correction-inline-detail').count()==0
        box=modal.locator('.app-modal__content').bounding_box()
        assert abs(box['x']+box['width']/2-840)<2
        assert abs(box['y']+box['height']/2-560)<2
        assert box['height']<=1120*.85+1
        assert page.evaluate('document.body.style.overflow')=='hidden'
        page.screenshot(path=str(ROOT/'tmp/correction_detail_modal.png'),full_page=True)
        assert page.locator('#audit-query').count()==0
        # Keyboard navigation stays inside the dialog.
        page.keyboard.press('Shift+Tab')
        assert modal.evaluate('(node)=>node.contains(document.activeElement)')
        page.keyboard.press('Tab')
        assert modal.locator('.app-modal__close').evaluate('(node)=>node===document.activeElement')
        page.keyboard.press('Escape')
        assert not modal.is_visible()
        assert page.evaluate('document.body.style.overflow')==''
        assert page.locator('[data-corr-detail="0"]').evaluate('(node)=>node===document.activeElement')
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_selector('#audit-source .audit-table')
        modal.locator('.app-modal__close').click()
        assert not modal.is_visible()
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_selector('#audit-source .audit-table')
        modal.click(position={'x':2,'y':2})
        assert not modal.is_visible()
        page.select_option('#correction-compare-days','1')
        page.wait_for_function("document.querySelectorAll('.audit-comparison-row').length===0")
        page.select_option('#corr-country','SEUK')
        page.wait_for_function("window.calls.at(-1).includes('country=SEUK')")
        page.locator('[data-corr-type="null_check"]').click()
        page.wait_for_function("window.calls.at(-1).includes('type=null_check')")
        page.locator('[data-corr-status="normal"]').click()
        page.wait_for_function("window.calls.at(-1).includes('status=normal')")
        page.locator('#correction-columns summary').click()
        page.locator('[data-corr-column="reviewer"]').uncheck()
        assert not page.locator('.audit-group-table [data-col=reviewer]').first.is_visible()
        page.locator('#correction-columns summary').click()
        page.evaluate('window.CORRECTIONS_IS_ADMIN=true')
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_selector('#audit-query')
        page.locator('#audit-query').click()
        page.wait_for_selector('.audit-query-panel')
        # Long audit trails scroll inside the popup while the page stays in place.
        page.keyboard.press('Escape')
        page.evaluate('window.detailFixture.events=Array(80).fill(window.detailFixture.events[0])')
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_function("document.querySelectorAll('.audit-events>div').length===80")
        body=modal.locator('.app-modal__body')
        assert body.evaluate('(node)=>node.scrollHeight>node.clientHeight')
        body.evaluate('(node)=>node.scrollTop=node.scrollHeight')
        assert body.evaluate('(node)=>node.scrollTop')>0
        close_box=modal.locator('.app-modal__close').bounding_box()
        assert 0<=close_box['y']<1120-close_box['height']
        page.keyboard.press('Escape')
        # Saved format decisions use their own evidence API, never legacy
        # correction IDs, raw validation requests, or the legacy cancel endpoint.
        review={**records[0], 'id':-1, 'correction_type':'format_check', 'status':'error',
                'review_source':'format_review','review_event_id':22,'review_target':0,'review_record':0,
                'new_value':'<script>bad()</script>','old_value':None,'reason':'상품 페이지와 대조한 이상 값',
                'comparison_rows':[],'shared_normal':False,'origin_product':'REF'}
        payload.update(items=[review],total=1,type_counts={'format_check':1},
                       status_counts={'corrected':0,'normal':0,'error':1,'reverted':0})
        saved=dict(success=True,review_source='format_review',correction=review,
                   inspection_date='2026-10-27',source_date='2026-10-26',origin_product='REF',
                   field='ref_capacity',value=review['new_value'],reason=review['reason'],shared_normal=False,
                   records=[dict(id=42,item='REF-42',name='Saved refrigerator',collected_at='2026-10-26T23:59:00-04:00',url='javascript:bad()')],
                   checked_urls=['https://example.test/product/42'],captures=[],
                   correction_history=[dict(status='corrected',created_id='editor',created_at='2026-10-27 09:00:00',old_value='192 liters',new_value='192 L',reason='단위 정정')],
                   history=[dict(id=22,action='error',actor='tester',created_at='2026-10-27 10:00:00',product='REF',reason='이상 확인',is_del=False)])
        page.evaluate('data=>window.listFixture=data',payload)
        page.evaluate('data=>window.detailFixture=data',saved)
        page.locator('[data-corr-type="format_check"]').click()
        page.locator('[data-corr-status="error"]').click()
        page.wait_for_function("document.querySelector('#corr-error').textContent==='1'")
        assert page.locator('.audit-current-row [data-col=status]').inner_text()=='이상 확인\n이상 확인 · 미수정'
        assert page.locator('.audit-current-row [data-col=old]').inner_text()=='—'
        assert page.locator('.audit-current-row [data-col=new]').inner_text()==review['new_value']
        page.locator('[data-corr-detail="0"]').click()
        page.wait_for_function("document.querySelector('#audit-source').textContent.includes('Saved refrigerator')")
        assert 'review_event_id=22' in page.evaluate('window.calls.at(-1)')
        assert page.locator('#audit-query').count()==0
        assert page.locator('#audit-source a[href^="javascript:"]').count()==0
        assert '수정·해결 완료가 아닙니다' in page.locator('#audit-source').inner_text()
        assert '단위 정정' in page.locator('#audit-source').inner_text()
        page.screenshot(path=str(ROOT/'tmp/format_review_audit_detail.png'),full_page=True)
        page.keyboard.press('Escape')
        review.update(status='normal',shared_normal=True)
        payload.update(items=[review],status_counts={'corrected':0,'normal':1,'error':0,'reverted':0})
        page.evaluate('data=>window.listFixture=data',payload)
        page.locator('[data-corr-status="normal"]').click()
        page.wait_for_function("document.querySelector('#corr-normal').textContent==='1'")
        assert page.locator('.corr-check').count()==0
        assert not page.locator('#corr-cancel-btn').is_visible()
        assert '정상 공유 승인 · 최초 REF' in page.locator('.audit-current-row').inner_text()
        page.screenshot(path=str(ROOT/'tmp/format_review_audit_list.png'),full_page=True)
        assert not errors,errors
        browser.close()
        print('PASS: real template, groups, counts, filters, centered modal, X/ESC/overlay close, focus, admin SQL')


if __name__=='__main__':
    main()
