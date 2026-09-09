const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/seg_retail.js', 'utf8');
const context = {
    L1: { renderers: {} }, window: {},
    esc: value => String(value ?? '').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    getStatusBadge: value => '<status>' + value + '</status>',
    renderCountryFlagLabel: value => value,
};
vm.runInNewContext(source, context);
const render = context.L1.renderers.seg_retail;
const html = render({
    name: 'SEG Retail', raw_count: 318, inspection_date: '2026-09-09',
    source_date: '2026-09-09', collection_window: 'KST 07:00~12:00', status: 'OK',
    categories: [{category: 'REF', raw_count: 318, main_count: 300, bsr_count: 100,
        expected: 300, status: 'OK', retailers: [{
            retailer: 'Mediamarkt', batch_id: '<script>', raw_count: 318,
            main_count: 300, bsr_count: 100, expected: 300, difference: 0, status: 'OK',
            history: [{source_date: '2026-09-08', main_count: 301}],
        }],
    }],
}, 2);
assert(html.includes('seg-cat-2-0'));
assert(html.includes('KST 07:00~12:00'));
assert(html.includes('MAIN 평균'));
assert(html.includes('최대 7개'));
assert(html.includes('소수점 버림'));
assert(html.includes('2026-09-08: 301건'));
assert(html.includes('&lt;script&gt;'));
assert(!html.includes('<script>'));
assert(html.includes('<td class="rt-total">318</td>'));
assert(!html.includes('300.0'));
assert(fs.readFileSync('apps/dx/dx_layer1/templates/dx_layer1_dashboard.html', 'utf8')
    .includes('dx_layer1/js/seg_retail.js'));
console.log('Layer1 SEG renderer tests passed.');
