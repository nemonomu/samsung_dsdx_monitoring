const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let day = '2026-10-17';
const context = { getSelectedDate: () => day, esc: String, RawDataView: function () {},
    getStatusBadge: value => value, L1: { initLayer1Page() {}, renderers: {} } };
vm.createContext(context);
for (const name of ['retail', 'retail-status', 'collection-volume']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer1/static/dx_layer1/js/${name}.js`, 'utf8'), context);
}
const rows = () => context.buildSeaRetailFallbackCategories().find(c => c.name === 'LDY_DRYER').time_slots[0].retailers;
assert(!rows().some(r => r.retailer === 'Lowes'));
day = '2026-10-18';
assert(rows().some(r => r.retailer === 'Lowes'));
day = '2026-10-19';
const row = {retailer: 'Lowes', status: 'OK', count: 217, main_count: 213, bsr_count: 89,
    collection_phase: 'complete', batch_count: 2,
    batch_context: {check_type: 'retail', product_line: 'ldy_dryer', source_date: '2026-10-18', retailer: 'Lowes'}};
const check = {check_type: 'retail', is_target_date: true, source_date: '2026-10-18', phase: 'complete',
    categories: [{name: 'LDY_DRYER', time_slots: [{name: '일일', retailers: [row]}]}]};
context.L1.collectionVolume.decorate({checks: [check], summary: {}}, {
    policy_version: 4, inspection_date: day, snapshots: [{country: 'SEA', available: true, source_date: '2026-10-18',
        rows: [{product: 'LDY_DRYER', retailer: 'Lowes', slot: '일일', observation_state: 'observing', observation_prior_days: 1, rules: {}}]}]
}, day);
assert.strictEqual(row.status, 'VERIFYING');
assert.strictEqual(row.volume_comparison_state, 'observing');
assert(!row.volume_alerts.length, '89 BSR must not trigger the fixed 100 rule');
const badge = context.L1.retailStatus.rowBadge(row);
assert(badge.includes('관찰 중 (2/5일)'));
assert(badge.includes('배치 2개'));
assert(context.L1.retailStatus.rowBadge({status: 'CRITICAL', count: 0}).includes('미수집'));
console.log('Lowes dryer launch, observation, missing collection and multiple batch badges passed.');
