const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {L1: {}, esc: String, getStatusBadge: String, console};
vm.createContext(context);
for (const name of ['collection-volume', 'retail-review', 'retail-status']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer1/static/dx_layer1/js/${name}.js`, 'utf8'), context);
}
const day = '2026-10-11';
function fixture(phase = 'complete', count = 80, observation = 'ready') {
    const row = {retailer: 'Costco', batch_id: 'c10', count, status: count ? 'OK' : 'CRITICAL',
        collection_phase: phase, items: [{name: 'Main Rank', count}, {name: 'BSR Rank', count: count ? 89 : 0}]};
    const data = {checks: [{check_type: 'retail', inspection_date: day, source_date: '2026-10-10',
        categories: [{name: 'TV', source_date: '2026-10-10', time_slots: [{name: '일일', retailers: [row]}]}]}]};
    const rules = {main: {baseline: 100, days: 5, rule: 'median_28d', low_percent: 30, review_percent: 15, high_percent: 30},
        bsr: {baseline: 89, days: 5, rule: 'median_28d', low_percent: 20, review_percent: 15}};
    const payload = {policy_version: 4, inspection_date: day, snapshots: [{country: 'SEA', source_date: '2026-10-10', available: true,
        rows: [{product: 'TV', retailer: 'Costco', slot: '일일', observation_state: observation,
            observation_prior_days: observation === 'observing' ? 4 : 5, rules}]}]};
    context.L1.collectionVolume.decorate(data, payload, day);
    context.L1.retailReview.decorate(data, day);
    return {row, data};
}
let {row} = fixture();
assert.strictEqual(row.status, 'VOLUME_REVIEW');
assert.strictEqual(row._reviewContext.retailer, 'Costco');
assert.strictEqual(row._reviewContext.batch_id, 'c10');
assert(context.L1.retailReview.badge(row, row.status).includes('확인 필요'));
row = fixture('complete', 80, 'observing').row;
assert.strictEqual(row.observation_days, 5);
assert(context.L1.retailStatus.rowBadge(row).includes('신규 · 관찰 중 (5/5일)'));
assert.strictEqual(row.volume_alerts.length, 0);
row = fixture('collecting', 0).row;
assert.strictEqual(row.status, 'COLLECTING');
assert(!context.L1.retailStatus.rowBadge(row).includes('미수집'));
row = fixture('complete', 0, 'observing').row;
assert.strictEqual(row.status, 'CRITICAL');
assert(context.L1.retailStatus.rowBadge(row).includes('미수집'));
console.log('Costco frontend: observation, median review context and overdue receipt states passed.');
