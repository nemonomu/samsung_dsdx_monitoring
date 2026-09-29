const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {L1: {}, AbortController, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-volume.js', 'utf8'), context);
context.esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
context.getSelectedDate = () => '2026-09-21';
context.getStatusBadge = value => '<status>' + value + '</status>';
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/retail-status.js', 'utf8'), context);
const volume = context.L1.collectionVolume;
const day = '2026-09-21';
function fixture(base = 'OK') {
    const row = {retailer: 'Lowes', main_count: 210, bsr_count: 100, count: 210, batch_id: 'b1', status: base};
    return {checks: [{check_type: 'sem_retail', phase: 'complete', status: base,
        categories: [{name: 'REF', source_date: day, status: base, retailers: [row]}]}]};
}
function saved(status = 'VOLUME_LOW') {
    return {inspection_date: day, snapshots: [{country: 'SEM', source_date: day, available: true,
        rows: [{product: 'REF', retailer: 'Lowes', slot: 'daily', main: 210, bsr: 100, total: 210,
            batch_id: 'b1', complete: true, observation_state: 'ready', comparison_state: 'ready', alerts: [{status}]}]}]};
}
for (const status of ['VOLUME_LOW', 'VOLUME_HIGH']) {
    const data = volume.decorate(fixture(), saved(status), day);
    assert.strictEqual(data.checks[0].status, status);
    assert.strictEqual(data.checks[0].categories[0].status, status);
    assert.strictEqual(data.checks[0].categories[0].retailers[0].status, status);
}
const semBannerData = volume.decorate(fixture(), saved(), day);
assert(context.L1.retailStatus.render(semBannerData.checks[0], 1, 'sem_retail')
    .includes('Lowes</a> REF 건수 부족'));
const mainReviewPayload = saved('VOLUME_REVIEW');
mainReviewPayload.snapshots[0].rows[0].alerts[0] = {
    metric: 'main', status: 'VOLUME_REVIEW', reason: 'MAIN 중앙값 대비 감소 / 확인 필요',
};
const mainReviewData = volume.decorate(fixture(), mainReviewPayload, day);
assert.strictEqual(mainReviewData.checks[0].status, 'VOLUME_REVIEW');
const mainReviewBanner = context.L1.retailStatus.render(mainReviewData.checks[0], 1, 'sem_retail');
assert(mainReviewBanner.includes('retail-missing-item volume-review'));
assert(mainReviewBanner.includes('MAIN 중앙값 대비 감소 / 확인 필요'));
assert(!mainReviewBanner.includes('건수 증가'));
for (const status of ['CRITICAL', 'WARNING', 'PENDING', 'COLLECTING']) {
    assert.strictEqual(volume.decorate(fixture(status), saved('VOLUME_HIGH'), day).checks[0].status, status);
}
for (const modify of [
    p => p.inspection_date = '2026-09-20',
    p => p.snapshots[0].available = false,
    p => p.snapshots[0].rows[0].batch_id = 'old',
    p => p.snapshots[0].rows[0].total = 209,
    p => p.snapshots[0].rows[0].complete = false,
    p => p.snapshots[0].source_date = '2026-09-20',
]) {
    const payload = saved(); modify(payload);
    const data = volume.decorate(fixture(), payload, day);
    assert.strictEqual(data.checks[0].status, 'VERIFYING');
    assert.strictEqual(data.checks[0].categories[0].retailers[0].volume_comparison_state, 'unavailable');
}
const data = fixture();
data.summary = {passed: 1, failed: 0};
data.checks[0].is_target_date = true;
volume.decorate(data, saved(), day);
assert.strictEqual(data.summary.passed, 0);
assert.strictEqual(data.summary.failed, 1);
volume.decorate(data, null, day);
assert.strictEqual(data.summary.passed, 0);
assert.strictEqual(data.summary.failed, 0);
assert.strictEqual(volume.metrics({bsr_applicable: false, actual: 300, raw_count: 315}).total, 300);
assert.strictEqual(volume.metrics({actual: 300, raw_count: 315}, 'SEM').total, 300);
const sea = fixture(), seaSaved = saved();
sea.checks[0].check_type = 'retail';
seaSaved.snapshots[0].country = 'SEA';
const summary = {ref: {summary: [{retailer: 'Lowes', batch_id: 'new', rows: [
    {time_slot: 'daily', main: 210, bsr: 100, total: 210},
]}]}};
volume.decorate(sea, seaSaved, day, summary);
assert.strictEqual(sea.checks[0].status, 'VERIFYING', 'newer displayed SEA batch must wait for its own verification');
summary.ref.summary[0].batch_id = 'b1';
volume.decorate(sea, seaSaved, day, summary);
assert.strictEqual(sea.checks[0].status, 'VOLUME_LOW');
let banner = context.L1.retailStatus.render(sea.checks[0], 0, 'retail');
assert(banner.includes('Lowes</a> REF 건수 부족'));
assert(banner.includes('category=REF&amp;retailer=Lowes'));
assert(!banner.includes('REF 미수집'));
sea.checks[0].categories[0].retailers[0].batch_count = 2;
banner = context.L1.retailStatus.render(sea.checks[0], 0, 'retail');
assert(banner.includes('REF 배치 2개 이상'));
assert(banner.includes('REF 건수 부족'));
seaSaved.snapshots[0].rows[0].alerts = [{status: 'VOLUME_HIGH'}];
volume.decorate(sea, seaSaved, day, summary);
banner = context.L1.retailStatus.render(sea.checks[0], 0, 'retail');
assert(banner.includes('retail-missing-item volume-review'));
assert(banner.includes('Lowes</a> REF 건수 증가'));
volume.decorate(sea, null, day);
assert(!context.L1.retailStatus.render(sea.checks[0], 0, 'retail').includes('건수 증가'));
const homeDepot = fixture('UNASSESSED'), homeDepotSaved = saved('VOLUME_LOW');
homeDepot.checks[0].check_type = 'retail';
homeDepot.checks[0].categories[0].retailers[0].retailer = 'HomeDepot';
homeDepotSaved.snapshots[0].country = 'SEA';
homeDepotSaved.snapshots[0].rows[0].retailer = 'HomeDepot';
const homeDepotRow = homeDepot.checks[0].categories[0].retailers[0];
homeDepotSaved.snapshots[0].rows[0].alerts = [];
homeDepotSaved.snapshots[0].rows[0].comparison_state = 'insufficient';
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'UNASSESSED');
homeDepotSaved.snapshots[0].rows[0].comparison_state = 'ready';
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'OK');
volume.decorate(homeDepot, null, day);
assert.strictEqual(homeDepotRow.status, 'VERIFYING', 'missing comparison must wait for verification');
homeDepotSaved.snapshots[0].rows[0].alerts = [{status: 'VOLUME_LOW'}];
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'VOLUME_LOW');
homeDepotSaved.snapshots[0].rows[0].alerts = [{status: 'VOLUME_HIGH'}];
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'VOLUME_HIGH');
homeDepotSaved.snapshots[0].rows[0].alerts = [];
homeDepotSaved.snapshots[0].rows[0].batch_id = 'old';
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'VERIFYING', 'old batch must not produce a normal result');
homeDepotSaved.snapshots[0].rows[0].batch_id = 'b1';
homeDepotRow.count = 0;
homeDepotSaved.snapshots[0].rows[0].total = 0;
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'UNASSESSED', 'zero collected rows must not be called normal');
assert.strictEqual(data.checks[0].status, 'VERIFYING');
assert.strictEqual(data.checks[0].categories[0].retailers[0].status, 'VERIFYING');
assert.strictEqual(volume.merge('OK', [{status: 'VOLUME_HIGH'}, {status: 'VOLUME_LOW'}]), 'VOLUME_LOW');
const bsrPayload = saved();
bsrPayload.snapshots[0].rows[0].bsr = 99;
bsrPayload.snapshots[0].rows[0].comparison_state = 'insufficient';
bsrPayload.snapshots[0].rows[0].alerts = [{metric: 'bsr', status: 'VOLUME_LOW', baseline: 100,
    actual: 99, reason: 'BSR 기준 100개 / 수집 99개 / 1개 부족'}];
const bsrData = fixture('WARNING');
bsrData.checks[0].categories[0].retailers[0].bsr_count = 99;
bsrData.summary = {};
bsrData.checks[0].is_target_date = true;
volume.decorate(bsrData, bsrPayload, day);
assert.strictEqual(bsrData.checks[0].status, 'VOLUME_LOW');
assert.strictEqual(bsrData.summary.failed, 1);
const bsrBanner = context.L1.retailStatus.render(bsrData.checks[0], 0, 'seg_retail');
assert(bsrBanner.includes('BSR 기준 100개 / 수집 99개 / 1개 부족'));
assert(!bsrBanner.includes('비교 이력 부족'));
const bsrCell = context.L1.retailStatus.bsrCell(bsrData.checks[0].categories[0].retailers[0], '99');
assert(bsrCell.includes('class="cs-bsr-low"'));
assert(bsrCell.includes('>99<small'));
assert.strictEqual(volume.metrics({bsr_count: 99, bsr_applicable: false}).bsr, 99);
const insufficient = saved();
insufficient.snapshots[0].rows[0].alerts = [];
insufficient.snapshots[0].rows[0].comparison_state = 'insufficient';
const insufficientData = volume.decorate(fixture(), insufficient, day);
assert.strictEqual(insufficientData.checks[0].status, 'OK');
assert.strictEqual(context.L1.retailStatus.render(insufficientData.checks[0], 0, 'seg_retail'), '');

function fixedFixture(country = 'SEA', product = 'TV', retailer = 'Walmart', bsr = 99) {
    const data = fixture();
    const check = data.checks[0], cat = check.categories[0], row = cat.retailers[0];
    check.check_type = {SEA:'retail', SEG:'seg_retail', SIEL:'siel_retail', SEDA:'seda_retail', SEM:'sem_retail', TSE:'tse_retail'}[country];
    check.inspection_date = day;
    check.is_target_date = true;
    cat.name = product;
    Object.assign(row, {retailer, main_count:299, bsr_count:bsr, count:337});
    data.summary = {passed:1,failed:0};
    return data;
}
const rowOf = data => data.checks[0].categories[0].retailers[0];
function maturePayload(data) {
    const check = data.checks[0], cat = check.categories[0], row = rowOf(data);
    const country = {retail:'SEA', sem_retail:'SEM', seg_retail:'SEG', seda_retail:'SEDA', siel_retail:'SIEL', tse_retail:'TSE'}[check.check_type];
    return {inspection_date: day, snapshots: [{country, source_date: day, available: true, rows: [{
        product: cat.name, retailer: row.retailer, slot: 'daily', ...volume.metrics(row, country),
        batch_id: row.batch_id, complete: true, observation_state: 'ready', observation_prior_days: 5,
        observation_days: 5, comparison_state: 'ready', alerts: [],
    }]}]};
}
for (const [country, product, retailer] of [
    ['SEA', 'REF', 'Lowes'], ['SEA', 'LDY', 'Lowes'], ['SEA', 'TV', 'Amazon'],
    ['SIEL', 'TV', 'Amazon'], ['SIEL', 'REF', 'Amazon'], ['SIEL', 'LDY', 'Amazon'],
    ['SEG', 'TV', 'Amazon'], ['SEG', 'REF', 'Amazon'],
]) {
    const current = fixedFixture(country, product, retailer, 85);
    assert.strictEqual(rowOf(volume.decorate(current, null, day)).status, 'VERIFYING');
    const payload = {inspection_date: day, snapshots: [{country, source_date: day, available: true,
        rows: [{product, retailer, slot: 'daily', main: 299, bsr: 85, total: 337, batch_id: 'b1',
            complete: true, observation_state: 'ready', comparison_state: 'ready', alerts: [{metric: 'bsr', status: 'VOLUME_REVIEW',
                reason: 'BSR 과거 중앙값 100개 / 수집 85개 / 15% 이상 감소 / 확인 필요'}]}]}]};
    volume.decorate(current, payload, day);
    assert.strictEqual(current.checks[0].status, 'VOLUME_REVIEW');
    assert.strictEqual(current.checks[0].categories[0].status, 'VOLUME_REVIEW');
    assert.strictEqual(rowOf(current).status, 'VOLUME_REVIEW');
    assert.strictEqual(current.summary.failed, 0);
    const cell = context.L1.retailStatus.bsrCell(rowOf(current), '85');
    assert(cell.includes('cs-bsr-review') && cell.includes('확인 필요'));
    const banner = context.L1.retailStatus.render(current.checks[0], 0, current.checks[0].check_type);
    assert(banner.includes('retail-missing-item volume-review') && banner.includes('15% 이상 감소'));
    assert(!banner.includes('건수 증가'));
    payload.snapshots[0].rows[0].alerts = [];
    volume.decorate(current, payload, day);
    assert.strictEqual(rowOf(current).status, 'OK');
}
assert.strictEqual(volume.merge('OK', [{status: 'VOLUME_REVIEW'}, {status: 'VOLUME_LOW'}]), 'VOLUME_LOW');
assert.strictEqual(volume.merge('CRITICAL', [{status: 'VOLUME_REVIEW'}]), 'CRITICAL');
// Missing or stale observation evidence must not invent a fixed-target failure.
for (const payload of [null, {inspection_date:day,snapshots:[]},
    {inspection_date:day,snapshots:[{country:'SEA',available:false,rows:[]}]},
    {inspection_date:'2026-09-20',snapshots:[]}, saved()]) {
    const current = volume.decorate(fixedFixture(), payload, day);
    assert.strictEqual(rowOf(current).status, 'VERIFYING');
    assert.strictEqual(rowOf(current).observation_state, 'unknown');
    assert.strictEqual(current.summary.failed, 0);
    assert(context.L1.retailStatus.bsrCell(rowOf(current), '99').includes('관찰 이력 확인 중'));
    assert(!context.L1.retailStatus.bsrCell(rowOf(current), '99').includes('cs-bsr-low'));
}
for (const [country, product, retailer] of [
    ['SEA','REF','Amazon'], ['SEA','LDY','HomeDepot'], ['SEM','REF','Liverpool'],
    ['SEDA','TV','Magalu'], ['SEG','TV','OTTO'], ['SIEL','TV','Flipkart'], ['TSE','TV','Homepro'],
]) {
    const current = fixedFixture(country, product, retailer);
    assert.strictEqual(rowOf(volume.decorate(current, maturePayload(current), day)).status, 'VOLUME_LOW');
    assert(context.L1.retailStatus.bsrCell(rowOf(current), '99').includes('cs-bsr-low'));
}
for (const [country, product, retailer] of [['SEA','TV','Amazon'], ['SEM','REF','HomeDepot'], ['SEM','REF','Coppel'], ['SEM','LDY','Coppel']]) {
    const current = fixedFixture(country, product, retailer);
    assert.strictEqual(rowOf(volume.decorate(current, maturePayload(current), day)).status, 'OK', 'variable targets use the median decision');
}
for (const adjust of [
    d => {rowOf(d).bsr_count = 100;},
    d => {rowOf(d).bsr_count = null;},
    d => {Object.assign(rowOf(d), {main_count:0,bsr_count:0,count:0,status:'CRITICAL'});},
    d => {d.checks[0].phase = 'collecting';},
    d => {rowOf(d).status = 'COLLECTING';},
    d => {rowOf(d).status = 'ERROR';},
    d => {rowOf(d).collection_status = 'COLLECTING';},
    d => {d.checks[0].inspection_date = '2026-09-20';},
]) {
    const current = fixedFixture(); adjust(current); volume.decorate(current, maturePayload(current), day);
    assert(!context.L1.retailStatus.bsrCell(rowOf(current), '99').includes('cs-bsr-low'));
}
const displayedSummary = {tv:{inspection_date:day,source_date:day,summary:[{retailer:'Walmart',rows:[{time_slot:'daily',main:299,bsr:99,total:337,batch_id:'b1'}]}]}};
const updated = fixedFixture('SEA','TV','Walmart',100);
volume.decorate(updated, maturePayload(updated), day, displayedSummary);
assert.strictEqual(rowOf(updated).volume_alerts[0].actual, 99, 'use the counts actually displayed by the current SEA summary');
displayedSummary.tv.summary[0].rows[0].bsr = 100;
volume.decorate(updated, maturePayload(updated), day, displayedSummary);
assert.strictEqual(rowOf(updated).status, 'OK', 'recovered counts remove the previous alert');
displayedSummary.tv.summary[0].rows[0].bsr = 99;
displayedSummary.tv.inspection_date = '2026-09-20';
volume.decorate(updated, maturePayload(updated), day, displayedSummary);
assert.strictEqual(rowOf(updated).status, 'VERIFYING', 'a different date must not supply current BSR values');
assert.strictEqual(rowOf(updated).volume_alerts.length, 0);
console.log('Collection volume: threshold states, precedence, snapshot matching and stale-response tests passed.');

for (const retailer of ['Coppel', 'FutureRetailer']) {
    const current = fixedFixture('SEM', 'REF', retailer, 60);
    const payload = maturePayload(current), stored = payload.snapshots[0].rows[0];
    Object.assign(stored, {observation_state: 'observing', observation_prior_days: 1, observation_days: 2,
        alerts: [{metric: 'bsr', status: 'VOLUME_LOW', rule: 'fixed_100'}, {metric: 'main', status: 'VOLUME_LOW'}]});
    volume.decorate(current, payload, day);
    assert.strictEqual(rowOf(current).status, 'OK');
    assert.strictEqual(rowOf(current).volume_alerts.length, 0);
    assert(context.L1.retailStatus.rowBadge(rowOf(current)).includes('신규 · 관찰 중 (2/5일)'));
    assert(context.L1.retailStatus.render(current.checks[0], 0, 'sem_retail').includes('신규 · 관찰 중 (2/5일)'));
    stored.observation_prior_days = 4;
    volume.decorate(current, payload, day);
    assert.strictEqual(rowOf(current).observation_days, 5);
    assert.strictEqual(rowOf(current).volume_alerts.length, 0, 'fifth day is still observation');
    for (const status of ['CRITICAL', 'ERROR', 'COLLECTING']) {
        const failed = fixedFixture('SEM', 'REF', retailer, 0);
        Object.assign(rowOf(failed), {status, count: 0, main_count: 0});
        volume.decorate(failed, payload, day);
        assert.strictEqual(rowOf(failed).status, status);
        assert.strictEqual(rowOf(failed).observation_days, 4);
        assert.strictEqual(rowOf(failed).volume_alerts.length, 0);
        const badge = context.L1.retailStatus.rowBadge(rowOf(failed));
        assert(badge.includes('신규 · 관찰 중 (4/5일)'));
        assert(badge.includes(status === 'CRITICAL' ? '미수집' : status));
    }
    Object.assign(stored, {observation_state: 'ready', observation_prior_days: 5,
        alerts: retailer === 'Coppel' ? [] : [{metric: 'bsr', status: 'VOLUME_LOW'}]});
    volume.decorate(current, payload, day);
    assert.strictEqual(rowOf(current).status, retailer === 'Coppel' ? 'OK' : 'VOLUME_LOW');
    assert(!context.L1.retailStatus.rowBadge(rowOf(current)).includes('신규'));
}

// Receipt during the window cannot be shown as normal, even if an old saved
// result has identical counts. End-of-window verification uses the same batch.
const early = fixedFixture('SEM', 'REF', 'Coppel', 56);
early.checks[0].phase = 'collecting';
const earlyPayload = maturePayload(early);
earlyPayload.snapshots[0].rows[0].alerts = [{metric: 'bsr', status: 'VOLUME_LOW'}];
volume.decorate(early, earlyPayload, day);
assert.strictEqual(rowOf(early).status, 'VERIFYING');
assert.strictEqual(early.checks[0].status, 'VERIFYING');
assert.strictEqual(early.checks[0].categories[0].status, 'VERIFYING');
assert.strictEqual(early.summary.passed, 0);
assert.strictEqual(early.summary.total_completed, 0);
assert.strictEqual(rowOf(early).volume_alerts.length, 0);
early.checks[0].phase = 'complete';
volume.decorate(early, earlyPayload, day);
assert.strictEqual(rowOf(early).status, 'VOLUME_LOW');
assert.strictEqual(early.checks[0].status, 'VOLUME_LOW');
assert.strictEqual(early.summary.failed, 1);
earlyPayload.snapshots[0].rows[0].alerts = [];
volume.decorate(early, earlyPayload, day);
assert.strictEqual(rowOf(early).status, 'OK');
assert.strictEqual(early.summary.passed, 1);
assert.strictEqual(early.summary.total_completed, 1);
assert.strictEqual(early.summary.pass_rate, 100);
rowOf(early).batch_id = 'retry';
volume.decorate(early, earlyPayload, day);
assert.strictEqual(rowOf(early).status, 'VERIFYING', 'a retry waits for its own statistics');

const newDuringWindow = fixedFixture('SEM', 'LDY', 'Coppel', 60);
newDuringWindow.checks[0].phase = 'collecting';
const newDuringPayload = maturePayload(newDuringWindow);
Object.assign(newDuringPayload.snapshots[0].rows[0], {
    observation_state: 'observing', observation_prior_days: 2, observation_days: 2,
});
volume.decorate(newDuringWindow, newDuringPayload, day);
assert.strictEqual(rowOf(newDuringWindow).observation_days, 2);
assert.strictEqual(rowOf(newDuringWindow).status, 'VERIFYING');
assert(context.L1.retailStatus.rowBadge(rowOf(newDuringWindow)).includes('신규 · 관찰 중 (2/5일)'));

const separate = fixedFixture('SEA', 'REF', 'Lowes', 50);
const separatePayload = maturePayload(separate);
separatePayload.snapshots[0].rows[0].alerts = [{metric: 'bsr', status: 'VOLUME_LOW'}];
rowOf(separate).collection_phase = 'complete';
separate.checks[0].phase = 'collecting';
separate.checks[0].status = 'COLLECTING';
separate.checks[0].categories[0].status = 'COLLECTING';
separate.checks[0].categories[0].retailers.push({retailer: 'Walmart', count: 300, status: 'OK', collection_phase: 'collecting'});
volume.decorate(separate, separatePayload, day);
assert.strictEqual(rowOf(separate).status, 'VOLUME_LOW');
assert.strictEqual(separate.checks[0].status, 'VOLUME_LOW', 'a pending sibling cannot hide a verified shortage');
assert.strictEqual(separate.checks[0].categories[0].retailers[1].status, 'VERIFYING');

// Observation on one slot must not hide missing/error alerts on another slot.
const multiSlot = fixedFixture('SEM', 'REF', 'Coppel', 60);
const multiRow = {...rowOf(multiSlot)};
const multiCat = multiSlot.checks[0].categories[0];
multiCat.retailers = [];
multiCat.time_slots = [
    {name: 'AM', retailers: [multiRow]},
    {name: 'PM', retailers: [{...multiRow, status: 'CRITICAL', main_count: 0, bsr_count: 0, count: 0}]},
    {name: 'night', retailers: [{...multiRow, status: 'ERROR'}]},
];
const multiPayload = {inspection_date: day, snapshots: [{country: 'SEM', source_date: day, available: true,
    rows: multiCat.time_slots.map(slot => ({product: 'REF', retailer: 'Coppel', slot: slot.name,
        observation_state: 'observing', observation_prior_days: 1, observation_days: 2, complete: true}))}]};
volume.decorate(multiSlot, multiPayload, day);
assert(multiCat.time_slots.every(slot => slot.retailers[0].observation_days === 2));
const multiBanner = context.L1.retailStatus.render(multiSlot.checks[0], 0, 'sem_retail');
assert.strictEqual((multiBanner.match(/신규 · 관찰 중/g) || []).length, 1);
assert(multiBanner.includes('미수집'));
assert(multiBanner.includes('오류'));

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
