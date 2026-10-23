const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const {execFileSync} = require('child_process');

const fixtures = JSON.parse(execFileSync('python', ['-B', '-c', `
import json
from tests.test_seuk_crossfield import fixture, SEUK_SOURCE_CONFIG
print(json.dumps([fixture(product) for product in SEUK_SOURCE_CONFIG]))
`], {encoding:'utf8'}));

(async () => {
    for (const fixture of fixtures) {
        const container = {innerHTML:''};
        const urls = [];
        const context = {
            console, document:{addEventListener(){},querySelector:()=>container},
            esc:value=>String(value == null ? '' : value),escJs:String,
            getSelectedDate:()=> '2026-10-26',
            fetchAPI:async url=>{urls.push(url); return fixture.detail;},
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
        context.renderCrossfieldSummaryContent('SEUK','',fixture.summary);
        for (const rule of fixture.summary.rule_summary) assert(container.innerHTML.includes(rule.detail_name));
        assert.strictEqual(fixture.summary.rule_summary.length,7);
        const actions=[...container.innerHTML.matchAll(/onclick="(loadCrossfieldRuleDetail[^\"]+)"/g)];
        const action=actions.find(match=>match[1].includes("'7'"));
        assert(action);
        await vm.runInContext(action[1],context);
        assert(urls.at(-1).includes('type='+fixture.summary.product_line.toLowerCase()));
        context.renderProductUrl=value=>String(value||'');
        context.FilterBar=function(){this.render=()=>this;};
        context._cfRebuildTable=()=>{};
        context.setTimeout=()=>{};
        context.showRetailerDetail('Currys');
        assert(context.savedHtml.includes('3일치 Item 조회 SQL'));
        assert(context.savedHtml.includes('dx_seuk.dx_seuk_'));
        const state=context._cfDetailState;
        assert.strictEqual(state.allData.filter(row=>row._rowRole==='target').length,1);
        assert.strictEqual(state.allData.filter(row=>row._rowRole==='comparison_history').length,1);
        for (const field of ['final_sku_price','original_sku_price','savings']) {
            assert(state.visibleKeys.includes(field));
            assert(state.editableCols.has(field));
        }
        assert(!state.editableCols.has('sku'));
        assert(context._cfUsesEqualReviewCounts(fixture.summary.product_line,'Currys'));
        context.AppModal={setTitle(){},setBody(){},open(){}};
        await context.showRulesModal(fixture.summary.label+' 논리적 일관성');
        assert(urls.at(-1).includes('type='+fixture.summary.product_line.toLowerCase()));
    }
    console.log('SEUK cross-field: four products, seven rules, GBP edits, history and rule routing passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
