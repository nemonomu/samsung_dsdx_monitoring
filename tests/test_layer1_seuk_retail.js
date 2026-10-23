const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const context = {L1:{renderers:{}}, esc:value=>String(value??''),
    getStatusBadge:value=>'<status>'+value+'</status>', getSelectedDate:()=> '2026-10-28'};
context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/country-flags.js','utf8'),context);
for(const name of ['retail-query','retail-status','collection-volume','tse_retail','seuk_retail'])
    vm.runInContext(fs.readFileSync(base+name+'.js','utf8'),context);
function check(day,count=309,phase='complete') {
    const status=phase==='pending'?'PENDING':phase==='collecting'?'COLLECTING':count?'OK':'CRITICAL';
    return {check_type:'seuk_retail',country:'SEUK',name:'SEUK Retail',phase,
        source_date:day,status,active_from:'2026-10-23',collection_window:'KST 01:00~04:00',
        categories:['TV','REF','LDY','LDY_DRYER'].map(name=>({name,source_date:day,
            actual:count,expected:null,status,retailers:day<'2026-10-23'?[]:[{
                retailer:'Currys',actual:count,main_count:count?290:0,bsr_count:count?60:0,
                status,collection_phase:phase,expected:null,status_basis:'historical_volume',batch_id:'c1',batch_count:1,
            }]}))};
}
function decorate(day,count,state,phase='complete') {
    const data={checks:[check(day,count,phase)]};
    const rows=['TV','REF','LDY','LDY_DRYER'].map(product=>({product,retailer:'Currys',slot:'daily',
        observation_state:state==='observing'?'observing':'ready',observation_prior_days:state==='observing'?0:5,
        bsr_comparison_state:state,rules:state==='policy_pending'?{main:{baseline:290,days:5,rule:'median_28d',low_percent:30,review_percent:15,high_percent:30}}:{}}));
    context.L1.collectionVolume.decorate(data,{policy_version:4,inspection_date:day,snapshots:[{
        country:'SEUK',source_date:day,available:true,live:true,rows}]},day);
    return data.checks[0];
}
let result=decorate('2026-10-22',0,'observing','pending');
assert.equal(result.status,'PENDING');
assert(result.categories.every(c=>c.status==='PENDING'));
assert(context.L1.renderers.seuk_retail(result,0).includes('운영 시작 전'));
result=decorate('2026-10-23',0,'observing');
assert.equal(result.status,'CRITICAL');
result=decorate('2026-10-23',309,'observing','collecting');
assert.equal(result.status,'COLLECTING');
result=decorate('2026-10-23',309,'observing');
assert.equal(result.status,'OK');
let html=context.L1.renderers.seuk_retail(result,0);
assert(html.includes('/static/img/flags/gb.svg'));
assert(html.includes('KST 01:00~04:00'));
assert(html.includes('신규 · 관찰 중 (1/5일)'));
assert(html.includes('seuk-cat-0-3'));
assert(!html.includes('309/0건'));
result=decorate('2026-10-28',309,'policy_pending');
assert.equal(result.status,'POLICY_PENDING');
assert(result.categories.every(c=>c.retailers.every(r=>!r.volume_alerts.length)));
html=context.L1.renderers.seuk_retail(result,0);
assert(html.includes('기준 결정 대기'));
assert(!html.includes('100개'));
const query=context.L1.retailQuery.buildQuery('SEUK','LDY_DRYER','Currys','c1','2026-10-23');
assert(query.includes('dx_seuk.dx_seuk_ldy_dryer_retail_com'));
assert(query.includes("LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10) = '2026-10-23'"));
assert(!query.includes('AT TIME ZONE'));
console.log('SEUK: launch, collection window, missing, observation, deferred BSR, renderer and exact-day SQL passed.');
