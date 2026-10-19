const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const context = {
    L1: {renderers: {}},
    esc: value => String(value ?? ''),
    getStatusBadge: value => '<status>' + value + '</status>',
    getSelectedDate: () => '2026-10-19',
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/country-flags.js','utf8'),context);
for (const name of ['retail-query','retail-status','collection-volume','tse_retail','seib_retail']) {
    vm.runInContext(fs.readFileSync(base+name+'.js','utf8'),context);
}
function check(day, count) {
    return {check_type:'seib_retail',country:'SEIB',name:'SEIB Retail',phase:'complete',
        source_date:day,status:count?'OK':'CRITICAL',collection_window:'KST 01:00~04:00',
        categories:['TV','REF','LDY','LDY_DRYER'].map(name => ({name,source_date:day,
            actual:count,expected:null,status:count?'OK':'CRITICAL',retailers:[{
                retailer:'MediaMarkt',actual:count,main_count:count,bsr_count:count?59:0,
                status:count?'OK':'CRITICAL',collection_phase:'complete',expected:null,
                status_basis:'historical_volume',batch_count:count?2:0,
            }]}))};
}
const decorate=context.L1.collectionVolume.decorate;
const missing={checks:[check('2026-10-19',0)]};
decorate(missing,{policy_version:4,inspection_date:'2026-10-19',snapshots:[]},'2026-10-19');
assert.equal(missing.checks[0].status,'CRITICAL');
let html=context.L1.renderers.seib_retail(missing.checks[0],0);
assert(html.includes('/static/img/flags/es.svg'));
assert(html.includes('KST 01:00~04:00'));
assert.equal((html.match(/미수집<\/span>/g)||[]).length,8); // summary + retailer rows
assert(html.includes('seib-cat-0-3'));
assert(html.includes('SEIB-0-3'));
const collected={checks:[check('2026-10-18',74)]};
decorate(collected,{policy_version:4,inspection_date:'2026-10-18',snapshots:[{
    country:'SEIB',available:true,source_date:'2026-10-18',rows:
        ['TV','REF','LDY','LDY_DRYER'].map(product=>({product,retailer:'MediaMarkt',slot:'daily',
            observation_state:'observing',observation_prior_days:0,rules:{}}))
}]},'2026-10-18');
assert.equal(collected.checks[0].status,'VERIFYING');
html=context.L1.renderers.seib_retail(collected.checks[0],1);
assert(html.includes('신규 · 관찰 중 (1/5일)'));
assert(!html.includes('74/0건'));
assert(!html.includes('BSR 수량 부족'));
const query=context.L1.retailQuery.buildQuery('SEIB','LDY_DRYER','MediaMarkt','m1','2026-10-18');
assert(query.includes('dx_seib.dx_seib_ldy_dryer_retail_com'));
assert(query.includes("LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10) = '2026-10-18'"));
console.log('SEIB: Spain flag, four missing products, observation, batches and same-day SQL passed.');
