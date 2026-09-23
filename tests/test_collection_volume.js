const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {L1: {}, AbortController, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-volume.js', 'utf8'), context);
context.esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
context.getSelectedDate = () => '2026-09-21';
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
            batch_id: 'b1', complete: true, comparison_state: 'ready', alerts: [{status}]}]}]};
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
    assert.strictEqual(data.checks[0].status, 'OK');
    assert.strictEqual(data.checks[0].categories[0].retailers[0].volume_comparison_state, 'unavailable');
}
const data = fixture();
data.summary = {passed: 1, failed: 0};
data.checks[0].is_target_date = true;
volume.decorate(data, saved(), day);
assert.strictEqual(data.summary.passed, 0);
assert.strictEqual(data.summary.failed, 1);
volume.decorate(data, null, day);
assert.strictEqual(data.summary.passed, 1);
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
assert.strictEqual(sea.checks[0].status, 'OK', 'newer displayed SEA batch must discard the old alert');
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
assert.strictEqual(homeDepotRow.status, 'UNASSESSED', 'missing comparison must restore the base status');
homeDepotSaved.snapshots[0].rows[0].alerts = [{status: 'VOLUME_LOW'}];
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'VOLUME_LOW');
homeDepotSaved.snapshots[0].rows[0].alerts = [{status: 'VOLUME_HIGH'}];
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'VOLUME_HIGH');
homeDepotSaved.snapshots[0].rows[0].alerts = [];
homeDepotSaved.snapshots[0].rows[0].batch_id = 'old';
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'UNASSESSED', 'old batch must not produce a normal result');
homeDepotSaved.snapshots[0].rows[0].batch_id = 'b1';
homeDepotRow.count = 0;
homeDepotSaved.snapshots[0].rows[0].total = 0;
volume.decorate(homeDepot, homeDepotSaved, day);
assert.strictEqual(homeDepotRow.status, 'UNASSESSED', 'zero collected rows must not be called normal');
assert.strictEqual(data.checks[0].status, 'OK');
assert.strictEqual(data.checks[0].categories[0].retailers[0].status, 'OK');
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
console.log('Collection volume: threshold states, precedence, snapshot matching and stale-response tests passed.');

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
