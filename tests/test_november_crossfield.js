const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const {execFileSync} = require('child_process');

const fixtures = JSON.parse(execFileSync('python', ['-B', '-c', `
import json
from unittest.mock import patch
from tests.test_november_crossfield import uk, ib, row, RetailerCursor, DAY
fixtures=[]
for module, key, retailer in [(uk,'seuk_'+p,'AO') for p in ('ref','ldy','ldy_dryer')]+[(ib,'seib_ldy_dryer','ECI')]:
    record=row(retailer, final_sku_price='120', original_sku_price='100', savings='20')
    with patch.object(module,'exclude_page_absent_records',side_effect=lambda c,d,r,**kw:(r,[])):
        summary=getattr(module,'get_'+key[:4]+'_cross_field_summary')(RetailerCursor(module,key,[record]),DAY,key)
        detail=getattr(module,'get_'+key[:4]+'_cross_field_rule_detail')(RetailerCursor(module,key,[record]),DAY,key,203,3)
    fixtures.append(dict(retailer=retailer,summary=summary,detail=detail))
print(json.dumps(fixtures,default=str))
`], {encoding:'utf8'}));

(async () => {
    for (const fixture of fixtures) {
        const container = {innerHTML:''};
        const context = {
            console, document:{addEventListener(){},querySelector:()=>container},
            esc:value=>String(value == null ? '' : value), escJs:String,
            getSelectedDate:()=> '2026-10-30',
            fetchAPI:async ()=>fixture.detail,
        };
        context.window=context;
        vm.createContext(context);
        for (const file of ['static/js/retail-review-columns.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/common.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js']) {
            vm.runInContext(fs.readFileSync(file,'utf8'),context);
        }
        vm.runInContext('ViewStack.push = html => { window.savedHtml = html; };',context);
        context.isCrossFieldInline=()=>true;
        const country=fixture.summary.product_line.slice(0,4);
        context.renderCrossfieldSummaryContent(country,'',fixture.summary);
        assert(container.innerHTML.includes(fixture.retailer));
        const actions=[...container.innerHTML.matchAll(/onclick="(loadCrossfieldRuleDetail[^\"]+)"/g)];
        const action=actions.find(match=>match[1].includes("'203'"));
        assert(action, fixture.summary.product_line);
        await vm.runInContext(action[1],context);
        context.renderProductUrl=value=>String(value||'');
        context.FilterBar=function(){this.render=()=>this;};
        context._cfRebuildTable=()=>{};
        context.setTimeout=()=>{};
        context.showRetailerDetail(fixture.retailer);
        const state=context._cfDetailState;
        assert.strictEqual(state.allData.filter(row=>row._rowRole==='target').length,1);
        assert(state.allData.every(row=>row.account_name===fixture.retailer));
        for (const field of ['final_sku_price','original_sku_price']) {
            assert(state.visibleKeys.includes(field));
            assert(state.editableCols.has(field));
        }
        assert.strictEqual(state.visibleKeys.includes('savings'), fixture.retailer==='AO');
        assert.strictEqual(state.editableCols.has('savings'), fixture.retailer==='AO');
        assert(context._cfUsesEqualReviewCounts(fixture.summary.product_line,fixture.retailer));
    }
    console.log('November cross-field UI: AO three products and ECI routing, retailer isolation and savings visibility passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
