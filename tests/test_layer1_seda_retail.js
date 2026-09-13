const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const context = {
    L1: { renderers: {} },
    window: {},
    esc: value => String(value ?? '').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    getStatusBadge: value => '<status>' + value + '</status>',
    renderCountryFlagLabel: value => value,
};
context.window = context;
vm.runInNewContext(fs.readFileSync(base + 'retail-query.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync(base + 'retail-status.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync(base + 'seda_retail.js', 'utf8'), context);

const html = context.L1.renderers.seda_retail({
    name: 'SEDA Retail',
    check_type: 'seda_retail',
    raw_count: 546,
    inspection_date: '2026-08-11',
    source_date: '2026-08-10',
    collection_window: '검수일 D-1 데이터',
    status: 'OK',
    categories: [{
        category: 'TV', raw_count: 546, main_count: 518, bsr_count: 200,
        expected: 520, status: 'OK', source_date: '2026-08-10',
        retailers: [{
            retailer: 'Casas Bahia', batch_id: '<batch>', raw_count: 308,
            main_count: 300, bsr_count: 100, status: 'OK',
        }],
    }],
}, 2);

assert(html.includes('seda-cat-2-0'));
assert(html.includes('검수일 D-1 데이터'));
assert(html.includes('518/520건'));
assert(html.includes('Casas Bahia'));
assert(html.includes('&lt;batch&gt;'));
assert(!html.includes('<batch>'));
assert(html.includes("L1.retailQuery.open('SEDA-2-0')"));
assert(fs.readFileSync('apps/dx/dx_layer1/templates/dx_layer1_dashboard.html', 'utf8')
    .includes("dx_layer1/js/seda_retail.js' %}?v=2"));
assert(fs.readFileSync('static/js/country-flags.js', 'utf8')
    .includes("if (/^SEDA(?:\\s|$)/.test(text)) return 'br';"));
assert(fs.existsSync('static/img/flags/br.svg'));

console.log('Layer1 SEDA renderer tests passed.');
