const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const context = {L1: {renderers: {}}, esc: value => String(value ?? ''),
    getStatusBadge: value => '<status>' + value + '</status>',
    getSelectedDate: () => '2026-10-30'};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/country-flags.js', 'utf8'), context);
for (const name of ['retail-query', 'retail-status', 'collection-volume', 'tse_retail', 'seib_retail']) {
    vm.runInContext(fs.readFileSync(base + name + '.js', 'utf8'), context);
}
function payload(country, retailer, count, preview = true, date = '2026-10-30') {
    const row = {retailer, raw_count: count, actual: count, main_count: count,
        bsr_count: count, status: count ? 'OK' : preview ? 'PENDING' : 'CRITICAL',
        collection_phase: count || !preview ? 'complete' : 'pending',
        preview_mode: preview, expected: null, status_basis: 'historical_volume',
        collection_window: retailer === 'ECI' ? 'KST 08:00~09:00' : undefined};
    return {checks: [{country, check_type: country.toLowerCase() + '_retail',
        name: country + ' Retail', phase: 'complete', source_date: date,
        status: row.status, categories: [{name: 'LDY_DRYER', source_date: date,
            status: row.status, actual: count, retailers: [row]}]}]};
}
for (const [country, retailer, count] of [['SEG', 'OTTO', 247], ['SEM', 'Liverpool', 58], ['SEIB', 'ECI', 86]]) {
    for (const received of [count, 0]) {
        const data = payload(country, retailer, received);
        // Stale/missing baselines must not override preview or deleted-preview state.
        context.L1.collectionVolume.decorate(data, {policy_version:4, inspection_date:'2026-10-30', snapshots:[]}, '2026-10-30');
        const row = data.checks[0].categories[0].retailers[0];
        assert.equal(row.status, received ? 'OK' : 'PENDING');
        assert.equal(row.volume_alerts.length, 0);
        const badge = context.L1.retailStatus.rowBadge(row);
        assert(badge.includes(received ? '확인용' : '수집 예정'));
        assert(!badge.includes('미수집'));
    }
    const missing = payload(country, retailer, 0, false, '2026-11-01');
    context.L1.collectionVolume.decorate(missing, {policy_version:4, inspection_date:'2026-11-01', snapshots:[]}, '2026-11-01');
    assert.equal(missing.checks[0].categories[0].retailers[0].status, 'CRITICAL');
}
const eci = payload('SEIB', 'ECI', 86);
const html = context.L1.renderers.seib_retail(eci.checks[0], 0);
assert(html.includes('KST 08:00~09:00'));
assert(html.includes('확인용'));
assert(html.includes('ECI'));
const operating = payload('SEIB', 'ECI', 86, false, '2026-11-10');
context.L1.collectionVolume.decorate(operating, {policy_version:4, inspection_date:'2026-11-10', snapshots:[{
    country:'SEIB', available:true, live:true, source_date:'2026-11-10', rows:[{
        product:'LDY_DRYER', retailer:'ECI', slot:'daily', observation_state:'ready',
        bsr_comparison_state:'policy_pending', rules:{main:{baseline:86, days:5, rule:'median_28d', low_percent:30}}
    }]
}]}, '2026-11-10');
const operatingRow = operating.checks[0].categories[0].retailers[0];
assert.equal(operatingRow.status, 'POLICY_PENDING');
assert(context.L1.retailStatus.bsrCell(operatingRow, '86').includes('기준 결정 대기'));
assert.equal(operatingRow.volume_alerts.length, 0);
console.log('November dryers: preview, deletion, post-launch missing, ECI deadline and BSR policy waiting passed.');
