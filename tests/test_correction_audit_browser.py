"""Headless UI fixture for the production read-only audit component; no live DB."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'apps/dx/dx_layer4/static/dx_layer4/js/correction-detail.js').read_text(encoding='utf-8')
CSS=(ROOT/'apps/dx/dx_layer4/static/dx_layer4/css/correction-detail.css').read_text(encoding='utf-8')
ITEM=dict(id=7,table_name='dx_seuk.dx_seuk_tv_retail_com',record_id=42,retailer='Currys',item='A',
          column_name='savings',correction_type='cross_field',old_value='£400.00',new_value='£400.99',
          status='corrected',reason='price',memo='<img src=x onerror=alert(1)>',created_id='tester',
          created_at='2026-10-27 09:00',crawl_date='2026-10-27')
ROW=dict(id=42,batch_id='current',item='A',retailer_sku_name='TV',sku=None,savings='£400.99',
         product_url='https://www.currys.co.uk/products/example.html',_source_date='2026-10-26')
DATA=dict(success=True,country='SEUK',product='TV',source_date='2026-10-26',start_date='2026-10-24',
          field='savings',field_available=True,target=ROW,rows=[dict(ROW,id=41),ROW],
          columns=list(ROW),events=[dict(ITEM)],notice='현재 저장값',truncated=False)


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1400,'height':1000})
        errors=[]
        page.on('pageerror',lambda error: errors.append(str(error)))
        page.set_content('''<style>:root{--text-primary:#183153;--text-secondary:#73839c;--border-color:#dce5f1}body{font:14px Arial;background:#f6f8fc}#modal{background:white;padding:24px;margin:20px auto;max-width:1180px}.corr-detail-table{border-collapse:collapse;width:100%}.corr-detail-table th,.corr-detail-table td{border:1px solid #dce5f1;padding:8px;text-align:left}button{padding:8px;cursor:pointer}</style><div id="modal"></div>''')
        page.add_style_tag(content=CSS)
        page.evaluate('''() => {
            window.L4={escapeHtml:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),TYPE_NAMES:{cross_field:'크로스필드'},STATUS_NAMES:{corrected:'수정'}};
            window.AppModal={setTitle(){},setBody(id,html){document.getElementById('modal').innerHTML=html;},open(){}};
            window.showToast=(text)=>window.lastToast=text;
            window.CORRECTIONS_IS_ADMIN=false;
            window.calls=[];
        }''')
        page.evaluate('data=>{window.fixture=data;}',DATA)
        page.evaluate('item=>{window.item=item;}',ITEM)
        page.evaluate('''() => {window.fetch=async url=>{
            window.calls.push(url);
            const data=url.includes('/query/')?{success:true,record_sql:'SELECT * FROM dx_seuk.dx_seuk_tv_retail_com WHERE id = 42;',history_sql:'SELECT * FROM dx_seuk.dx_seuk_tv_retail_com LIMIT 301;'}:window.fixture;
            return {ok:true,json:async()=>data};
        };}''')
        page.add_script_tag(content=SOURCE)
        page.evaluate('CorrectionAudit.open(window.item)')
        page.wait_for_selector('.audit-table')
        assert page.locator('#audit-query').count()==0
        assert not any('/query/' in url for url in page.evaluate('window.calls'))
        assert page.locator('.audit-table tbody tr').count()==2
        assert page.locator('.audit-null').count()>=1
        assert page.locator('img').count()==0
        assert page.locator('.audit-url a').get_attribute('rel')=='noopener noreferrer'
        assert not page.locator('input:not([type=number]),textarea').count()
        page.evaluate('window.CORRECTIONS_IS_ADMIN=true;CorrectionAudit.open(window.item)')
        page.wait_for_selector('#audit-query')
        page.locator('#audit-query').click()
        page.wait_for_selector('.audit-query-panel pre')
        assert page.locator('.audit-query-panel pre').count()==2
        assert page.locator('.audit-query-panel pre').first.inner_text().startswith('SELECT')
        page.locator('#audit-days').fill('31')
        count=len(page.evaluate('window.calls'))
        page.locator('#audit-reload').click()
        assert len(page.evaluate('window.calls'))==count
        # Missing source: the saved audit values survive, with a visible warning.
        page.evaluate('window.fixture={...window.fixture,target:null,rows:[]};CorrectionAudit.open(window.item)')
        page.wait_for_selector('.audit-warning')
        assert '£400.00' in page.locator('#modal').inner_text()
        assert not page.locator('.audit-url a').count()
        # Unsafe product URL is never rendered as a hyperlink.
        unsafe={**DATA,'target':{**ROW,'product_url':'javascript:alert(1)'},'rows':[]}
        page.evaluate('data=>{window.fixture=data;CorrectionAudit.open(window.item)}',unsafe)
        page.wait_for_selector('.audit-url')
        assert not page.locator('a[href^="javascript:"]').count()
        # A response to an older record must not replace the currently selected record.
        page.evaluate('''() => {
            window.pending=[];window.fetch=url=>new Promise(resolve=>window.pending.push(data=>resolve({ok:true,json:async()=>data})));
            CorrectionAudit.open(window.item);CorrectionAudit.open({...window.item,id:8});
        }''')
        page.evaluate('data=>window.pending[1](data)',DATA)
        page.wait_for_selector('.audit-table')
        page.evaluate('data=>window.pending[0]({...data,product:"STALE"})',DATA)
        page.wait_for_timeout(50)
        assert 'STALE' not in page.locator('#audit-source').inner_text()
        assert not errors,errors
        browser.close()
        print('PASS: common detail, admin-only SQL controls, source URL, nulls, escaping, missing source, stale responses')


if __name__=='__main__':
    main()
