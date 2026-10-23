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
        'static/css/common.css','static/css/buttons.css','apps/dx/dx_layer4/static/dx_layer4/css/layer4.css',
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
            window.AppModal={create(){},setTitle(){},setBody(){},open(){}};
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
        for path in ['apps/dx/dx_layer4/static/dx_layer4/js/correction-detail.js',
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
        assert page.locator('#correction-inline-detail').is_visible()
        assert page.locator('#audit-query').count()==0
        page.locator('#audit-inline-close').click()
        assert not page.locator('#correction-inline-detail').is_visible()
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
        assert not errors,errors
        browser.close()
        print('PASS: real template, list groups, summary counts, filters, inline detail, column selection, admin SQL')


if __name__=='__main__':
    main()
