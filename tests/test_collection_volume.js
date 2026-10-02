const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {L1: {}, AbortController, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-volume.js', 'utf8'), context);
context.esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
context.getStatusBadge = value => '<status>' + value + '</status>';
context.getSelectedDate = () => day;
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/retail-status.js', 'utf8'), context);
const volume = context.L1.collectionVolume;
const day = '2026-10-02';
const types = {SEA:'retail', SEDA:'seda_retail', SIEL:'siel_retail', SEG:'seg_retail', SEM:'sem_retail', TSE:'tse_retail'};
const median = (baseline=300, extra={}) => ({baseline, days:7, rule:'median_28d', low_percent:30, high_percent:30, review_percent:null, ...extra});
const fixed = () => ({baseline:100, days:0, rule:'fixed_100', low_percent:30, high_percent:null, review_percent:null});
function fixture(country='SIEL', product='TV', base='OK') {
    const source = ['SEA','SEDA'].includes(country) ? '2026-10-01' : day;
    const row = {retailer:country==='SIEL'?'Flipkart':'Retailer', main_count:200, bsr_count:100,
        actual:276, raw_count:276, batch_id:'original', status:base};
    const cat = {name:product, source_date:source, inspection_date:day, status:base, retailers:[row]};
    const check = {check_type:types[country], phase:'complete', source_date:source, inspection_date:day,
        status:base, is_target_date:true, categories:[cat]};
    const data = {summary:{}, checks:[check]};
    const saved = {product, retailer:row.retailer, slot:'daily', main:200, bsr:100, total:276,
        batch_id:'original', complete:true, observation_state:'ready', observation_prior_days:5,
        comparison_state:'ready', rules:{main:median(), bsr:fixed()},
        alerts:[{metric:'total', status:'VOLUME_LOW', actual:276, baseline:500}]};
    const payload = {inspection_date:day, policy_version:3,
        snapshots:[{country, source_date:source, available:true, rows:[saved]}]};
    return {row, cat, check, data, saved, payload};
}
function apply(f) {volume.decorate(f.data, f.payload, day, f.summaries); return f.row.status;}

// The median survives a recollection or deletion; only CURRENT ranks determine the verdict.
for (const country of Object.keys(types)) for (const product of ['TV','REF','LDY']) {
    const f = fixture(country, product);
    assert.equal(apply(f), 'VOLUME_LOW');
    f.saved.batch_id = 'deleted-recollection'; f.saved.main = 300; f.saved.total = 333;
    f.saved.alerts = [];
    assert.equal(apply(f), 'VOLUME_LOW', country+' must recompute after deletion');
    assert.equal(f.row.volume_alerts[0].actual, 200);
    assert.equal(f.cat.status, 'VOLUME_LOW'); assert.equal(f.check.status, 'VOLUME_LOW');
    assert.equal(f.data.summary.failed, 1);
    f.row.main_count = 300; f.row.batch_id = 'successful-retry';
    f.saved.alerts = [{metric:'main', status:'VOLUME_LOW'}];
    assert.equal(apply(f), 'OK', country+' must clear a shortage only when live ranks recover');
    assert.equal(f.data.summary.passed, 1);
    f.row.raw_count = 9999; f.row.actual = 9999;
    assert.equal(apply(f), 'OK', 'total is informational');
    for (const base of ['CRITICAL','WARNING','REVIEW','UNASSESSED']) {
        const old = fixture(country, product, base); old.row.main_count = 300;
        assert.equal(apply(old), 'OK', 'legacy count/average criteria must not override MAIN and BSR');
    }
}
// Boundary comparisons are evaluated before display rounding.
for (const [count, status] of [[1400,'VOLUME_LOW'],[1401,'OK'],[1699,'OK'],[1900,'OK'],[2599,'OK'],[2600,'VOLUME_HIGH']]) {
    const f=fixture(); f.saved.rules.main=median(2000); f.row.main_count=count;
    assert.equal(apply(f),status);
}
const screenshot=fixture(); screenshot.row.main_count=247;
assert.equal(apply(screenshot),'OK','247 vs median 300 is only 17.7% down under the new 30% policy');
screenshot.saved.rules.main=median(400);
assert.equal(apply(screenshot),'VOLUME_LOW');

// Wrong date, stale/missing history, and older API versions must never imply normal.
for (const mutate of [f=>f.payload=null, f=>f.payload.policy_version=2,
    f=>f.payload.inspection_date='2026-10-01', f=>f.payload.snapshots[0].available=false,
    f=>f.payload.snapshots[0].source_date='2026-09-30', f=>f.saved.retailer='Other',
    f=>f.saved.product='LDY', f=>f.saved.slot='different', f=>f.saved.rules={},
    f=>f.saved.rules.main.days=4, f=>f.saved.rules.main.baseline=0,
    f=>delete f.saved.rules.main.days, f=>f.check.inspection_date='2026-10-01']) {
    const f=fixture(); f.row.main_count=300; mutate(f);
    assert.equal(apply(f),'VERIFYING'); assert.equal(f.check.status,'VERIFYING');
    assert.equal(f.data.summary.passed,0); assert.equal(f.data.summary.total_completed,0);
}
const unavailable=fixture();
assert.equal(apply(unavailable),'VOLUME_LOW');unavailable.payload=null;
assert.equal(apply(unavailable),'VERIFYING','a failed second response must not turn an existing warning into OK');

// Fixed BSR and variable BSR keep their own policy after a batch change.
for (const bsr of [0,99,100,101]) {
    const f=fixture(); f.row.main_count=300; f.row.bsr_count=bsr; f.row.batch_id='retry';
    assert.equal(apply(f),bsr<100?'VOLUME_LOW':'OK');
    if(bsr<100) assert(context.L1.retailStatus.bsrCell(f.row,String(bsr)).includes('cs-bsr-low'));
}
for (const [threshold, review] of [[20,15],[30,null]]) {
    for (const bsr of [0,56,57,64,68,69,100]) {
        const f=fixture(); f.row.main_count=300; f.row.bsr_count=bsr;
        f.saved.rules.bsr=median(80,{low_percent:threshold,review_percent:review,high_percent:null});
        f.saved.batch_id='old';
        const expected=(80-bsr)*100>=80*threshold?'VOLUME_LOW':review && (80-bsr)*100>=80*review?'VOLUME_REVIEW':'OK';
        assert.equal(apply(f),expected);
    }
}
const incompleteBasis=fixture(); delete incompleteBasis.saved.rules.main;
incompleteBasis.row.bsr_count=99;
assert.equal(apply(incompleteBasis),'VOLUME_LOW','known BSR shortage remains visible even without MAIN history');
const oldBsr=fixture();oldBsr.row.main_count=300;oldBsr.saved.rules.bsr=median(80,{days:4,high_percent:null});
assert.equal(apply(oldBsr),'VERIFYING');

// Source failures, collection windows, missing MAIN and observation remain explicit.
const error=fixture('SIEL','TV','ERROR');assert.equal(apply(error),'ERROR');
for(const phase of ['pending','collecting']) {
    const f=fixture();f.check.phase=phase;
    assert.equal(apply(f),phase==='pending'?'PENDING':'COLLECTING');
    assert.equal(f.row.volume_alerts.length,0);assert.equal(f.data.summary.passed,0);
}
const zero=fixture();zero.row.main_count=zero.row.bsr_count=zero.row.actual=zero.row.raw_count=0;
zero.payload=null;assert.equal(apply(zero),'CRITICAL');
assert(context.L1.retailStatus.rowBadge(zero.row).includes('\uBBF8\uC218\uC9D1'));
const mainMissing=fixture();mainMissing.row.main_count=0;assert.equal(apply(mainMissing),'CRITICAL');
const observing=fixture();observing.saved.observation_state='observing';observing.saved.observation_prior_days=4;
assert.equal(apply(observing),'VERIFYING');assert.equal(observing.row.observation_days,5);
assert.equal(observing.row.volume_alerts.length,0);
assert(context.L1.retailStatus.rowBadge(observing.row).includes('(5/5'));

// SEA's separately fetched display counts, including batch identity, take precedence.
const sea=fixture('SEA','REF');sea.row.main_count=300;
sea.cat.time_slots=[{name:'AM',status:'OK',retailers:[sea.row]}]; delete sea.cat.retailers;sea.saved.slot='AM';
sea.summaries={ref:{date:day,source_date:sea.cat.source_date,summary:[{retailer:sea.row.retailer,batch_id:'new',
    rows:[{time_slot:'AM',main:200,bsr:100,total:276}]}]}};
assert.equal(apply(sea),'VOLUME_LOW');assert.equal(volume.metrics(sea.row,'SEA').main,200);assert.equal(sea.row._volumeBatchId,'new');
sea.summaries.ref.summary[0].rows[0].main=300;
assert.equal(apply(sea),'OK');
sea.summaries.ref.date='2026-09-30';assert.equal(apply(sea),'VERIFYING');

// An incomplete sibling cannot hide a verified failure or make a parent normal.
const siblings=fixture(); siblings.row.main_count=300;
siblings.cat.retailers.push({...siblings.row,retailer:'Other',collection_phase:'collecting'});
apply(siblings);assert.equal(siblings.check.status,'COLLECTING');
siblings.row.main_count=200;apply(siblings);assert.equal(siblings.check.status,'VOLUME_LOW');

assert.equal(volume.metrics({actual:300,raw_count:315},'SEM').total,300);
assert.equal(volume.metrics({actual:300,raw_count:315},'SEG').total,315);
assert.equal(volume.metrics({bsr_applicable:false,actual:300,raw_count:315}).total,300);
console.log('Collection volume: six-country live recalculation, thresholds, pending, BSR, SEA and parent status checks passed.');

// A stalled volume API must never delay the existing page; old dates cannot repaint it.
async function verifyIndependentLoading() {
    const requests = [], rendered = [];
    let selectedDate = day;
    function pending(kind) {
        return new Promise(resolve => requests.push({kind, resolve}));
    }
    const page = {
        console, getSelectedDate: () => selectedDate, loadDdayCollection() {},
        loadCheckStatus: () => pending('status'), loadSeaRetailSummaries: () => pending('summary'),
        fetch: () => pending('stats'), esc: String,
        document: {getElementById: () => ({innerHTML: ''})},
        L1: {initLayer1Page() {}, collectionVolume: {
            load: () => pending('volume'), decorate(data, payload) {data.volume = payload;},
        }}, recordRender: data => rendered.push({...data}),
    };
    vm.createContext(page);
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js', 'utf8'), page);
    vm.runInContext('renderLayer1Stats = recordRender;', page);
    const first = page.loadStats();
    requests.find(r => r.kind === 'stats').resolve({ok: true, json: async () => ({date: day})});
    requests.find(r => r.kind === 'status').resolve({});
    requests.find(r => r.kind === 'summary').resolve({});
    await first;
    assert.strictEqual(rendered.at(-1).date, day);
    assert.strictEqual(rendered.at(-1).volume, null);
    selectedDate = '2026-09-22';
    page.loadStats();
    const before = rendered.length;
    requests[0].resolve({old: true});
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(rendered.length, before, 'late volume response must not repaint another date');
    console.log('Collection volume: nonblocking requests and late-date response checks passed.');
}
verifyIndependentLoading().catch(error => {console.error(error); process.exitCode = 1;});
