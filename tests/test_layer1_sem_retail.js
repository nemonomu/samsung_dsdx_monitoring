const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const base = path.join(__dirname, '../apps/dx/dx_layer1/static/dx_layer1/js');
const context = {
    document: {},
    localStorage: {},
    renderCountryFlagLabel: value => String(value),
    esc: value => String(value ?? ''),
};
context.window = context;
for (const name of ['layer1-common', 'retail-query', 'retail-status', 'tse_retail', 'sem_retail']) {
    vm.runInNewContext(fs.readFileSync(path.join(base, name + '.js'), 'utf8'), context);
}
context.filterBar = { getDate: () => '2026-09-13' };

for (const [status, count, expectedLabel, expectedClass] of [
    ['OK', 300, '정상', 'ok'],
    ['REVIEW', 314, '확인필요', 'warning'],
    ['CRITICAL', 0, '심각', 'critical'],
]) {
    const retailer = {
        retailer: 'Liverpool', batch_id: 'liv20260913_000003',
        main_count: count, bsr_count: count ? 100 : 0,
        actual: count, raw_count: count, expected: 264,
        status, status_basis: 'previous_main_average',
    };
    const html = context.L1.renderers.sem_retail({
        name: 'SEM Retail', check_type: 'sem_retail', actual: count, status,
        categories: [{
            name: 'REF', actual: count, expected: 264, status,
            inspection_date: '2026-09-13', retailers: [retailer],
        }],
    }, 0);
    const badge = '<span class="status-badge ' + expectedClass +
        '"><span class="status-dot"></span>' + expectedLabel + '</span>';
    assert.strictEqual(html.split(badge).length - 1, 3, status + ' at check/category/retailer');
    assert(html.includes(count + '/264건'));
    assert.strictEqual(html.includes('REF 미수집'), status === 'CRITICAL');
    if (status === 'REVIEW') assert(!html.includes('심각'));
}

assert.strictEqual(context.getStatusClass('REVIEW'), 'warning');
assert.strictEqual(context.getRetailerStatusClass('REVIEW'), 'warning');
assert(context.getStatusBadge('WARNING').includes('주의'));
assert(context.getStatusBadge('CRITICAL').includes('심각'));

const multiRetailerHtml = context.L1.renderers.sem_retail({
    name: 'SEM Retail', check_type: 'sem_retail', actual: 600, status: 'OK',
    categories: [{
        name: 'REF', actual: 600, expected: 528, status: 'OK',
        inspection_date: '2026-09-13',
        retailers: [
            {
                retailer: 'Liverpool', batch_id: 'liv-ref', main_count: 300,
                bsr_count: 100, actual: 300, raw_count: 300,
                expected: 264, status: 'OK',
                status_basis: 'previous_main_average',
            },
            {
                retailer: 'HomeDepot', batch_id: 'hd-ref', main_count: 300,
                bsr_count: 100, actual: 300, raw_count: 300,
                expected: 264, status: 'OK',
                status_basis: 'previous_main_average',
            },
        ],
    }],
}, 1);
assert(multiRetailerHtml.includes('Liverpool'));
assert(multiRetailerHtml.includes('HomeDepot'));
assert(multiRetailerHtml.includes('600/528건'));
console.log('Layer1 SEM review status rendering tests passed.');
