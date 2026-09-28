const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const base = path.join(__dirname, '../apps/dx/dx_layer1/static/dx_layer1/js');
const context = {
    document: {}, localStorage: {},
    renderCountryFlagLabel: value => String(value),
    esc: value => String(value ?? ''),
};
context.window = context;
for (const name of ['layer1-common', 'retail-query', 'retail-status', 'tse_retail', 'sem_retail']) {
    vm.runInNewContext(fs.readFileSync(path.join(base, name + '.js'), 'utf8'), context);
}
context.filterBar = {getDate: () => '2026-09-28'};

for (const [category, main, raw, bsr, expected] of [
    ['LDY', 85, 94, 94, 83], ['REF', 274, 274, 100, 272],
]) {
    const html = context.L1.renderers.sem_retail({
        name: 'SEM Retail', check_type: 'sem_retail', actual: main, status: 'OK',
        categories: [{
            name: category, actual: main, expected, status: 'OK',
            inspection_date: '2026-09-28',
            retailers: [{
                retailer: 'Coppel', batch_id: 'c20260928_000002',
                main_count: main, bsr_count: bsr, actual: main, raw_count: raw,
                expected, status: 'OK', status_basis: 'previous_main_average',
            }],
        }],
    }, 2);
    assert(html.includes('Coppel'));
    assert(html.includes(`${main}/${expected}건`));
}
console.log('Layer1 SEM Coppel REF/LDY rendering tests passed.');
