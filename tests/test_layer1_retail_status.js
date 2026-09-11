const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const base = path.join(__dirname, '../apps/dx/dx_layer1/static/dx_layer1/js');
const elements = {};
const context = {
    L1: { renderers: {}, initLayer1Page() {} },
    document: { getElementById: id => elements[id] },
    RawDataView: function() {},
    getSelectedDate: () => '2026-09-11',
    renderCountryFlagLabel: value => value,
    getStatusClass: value => value,
    getStatusBadge: value => '<status>' + value + '</status>',
    esc: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
};
context.window = context;
for (const name of ['retail-status', 'retail-query', 'retail', 'siel_retail', 'seg_retail', 'tse_retail', 'sem_retail']) {
    vm.runInNewContext(fs.readFileSync(path.join(base, name + '.js'), 'utf8'), context);
}
const status = context.L1.retailStatus;
const missing = retailer => ({ retailer, count: 0, status: 'CRITICAL' });
const sea = {
    name: 'SEA Retail', check_type: 'retail', inspection_date: '2026-09-08',
    source_date: '2026-09-07', actual: 0, status: 'CRITICAL',
    categories: [{ name: 'TV', time_slots: [{ name: '일일', retailers: [
        missing('Bestbuy'), missing('Walmart'), { ...missing('Amazon'), status: 'COLLECTING' },
    ] }] }, { name: 'REF', time_slots: [{ name: '일일', retailers: [missing('Bestbuy')] }] }],
};
const summary = status.render(sea, 0, 'retail');
assert(summary.includes('>Bestbuy</a> TV 미수집'));
assert(summary.includes('>Walmart</a> TV 미수집'));
assert(summary.includes('>Bestbuy</a> REF 미수집'));
assert(!summary.includes('Amazon'));
const href = /href="([^"]+)"/.exec(summary)[1].replace(/&amp;/g, '&');
const url = new URL(href, 'http://monitoring.test');
assert.strictEqual(url.pathname, '/dx/layer1/retail/');
assert.strictEqual(url.searchParams.get('category'), 'TV');
assert.strictEqual(url.searchParams.get('retailer'), 'Bestbuy');
assert.strictEqual(url.searchParams.get('period'), '일일');
assert.strictEqual(url.searchParams.get('date'), '2026-09-08');
assert(summary.includes('onclick="event.stopPropagation()"'));

for (const row of [
    { ...missing('Bestbuy'), status: 'PENDING' },
    { ...missing('Bestbuy'), status: 'COLLECTING' },
    { ...missing('Bestbuy'), status: 'OK' },
    { ...missing('Bestbuy'), count: 199 },
    { ...missing('Bestbuy'), count: null },
    { ...missing('Bestbuy'), count: 'unknown' },
    { ...missing('Lotuss'), actual: 0, raw_count: 80 },
    { ...missing('Liverpool'), actual: 0, actual_count: 20 },
]) {
    assert.strictEqual(status.render({ categories: [{ name: 'TV', retailers: [row] }] }, 0, 'retail'), '');
}
assert.strictEqual(status.render({ categories: [] }, 0, 'retail'), '');
assert.strictEqual(status.render(sea, 0, 'youtube'), '');
const duplicate = status.render({ categories: [{ name: 'TV', retailers: [missing('Bestbuy')],
    time_slots: [{ retailers: [missing('BESTBUY')] }] }] }, 0, 'retail');
assert.strictEqual((duplicate.match(/TV 미수집/g) || []).length, 1);
const unsafe = status.render({ categories: [{ category: 'TV', retailers: [missing('<script>"&')] }] }, 0, 'retail');
assert(!unsafe.includes('<script>'));
assert(unsafe.includes('&lt;script&gt;&quot;&amp;'));

const countries = [
    ['retail', 'SEA', 'retail', 'Bestbuy'],
    ['siel_retail', 'SIEL', 'siel', 'Flipkart'],
    ['seg_retail', 'SEG', 'seg', 'Mediamarkt'],
    ['sem_retail', 'SEM', 'sem', 'Liverpool'],
    ['tse_retail', 'TSE', 'tse', 'Homepro'],
];
for (const [type, country, prefix, retailer] of countries) {
    const categories = ['TV', 'REF', 'LDY'].map(product => ({
        name: product, category: product, total: 0, actual: 0, raw_count: 0, status: 'CRITICAL',
        ...(type === 'retail' ? { time_slots: [{ name: '일일', retailers: [missing(retailer)] }] }
            : { retailers: [{ ...missing(retailer), raw_count: 0 }] }),
    }));
    const html = context.L1.renderers[type]({ name: country + ' Retail', check_type: type,
        status: 'CRITICAL', categories, actual: 0, raw_count: 0 }, 4);
    const header = html.slice(0, html.indexOf('<div class="time-slots-container"'));
    assert(header.includes('L1.retailStatus.toggle(this,'));
    assert.strictEqual((header.match(/미수집<\/span>/g) || []).length, 3, country);
    assert(html.includes('id="' + prefix + '-cat-4-2"'));
    if (type !== 'retail') {
        assert(header.includes('href="#' + prefix + '-cat-4-2"'));
        assert(header.includes('event.stopPropagation();L1.retailStatus.open(this, 4)'));
    }
}

function classList() {
    const values = new Set();
    return {
        contains: value => values.has(value),
        add: value => values.add(value),
        remove: value => values.delete(value),
        toggle(value, force = !values.has(value)) {
            if (force) values.add(value); else values.delete(value);
            return force;
        },
    };
}
const tables = [0, 1, 2].map(() => ({ classList: classList() }));
const icons = [0, 1, 2].map(() => ({ classList: classList() }));
const parentIcon = { classList: classList() };
const container = {
    classList: classList(),
    querySelectorAll: selector => selector === '.sentiment-two-column' ? tables : icons,
};
elements['time-slots-4'] = container;
const main = { querySelector: () => parentIcon };
status.toggle(main, 4);
assert(container.classList.contains('show'));
assert(parentIcon.classList.contains('expanded'));
assert(tables.every(table => table.classList.contains('show')));
assert(icons.every(icon => icon.classList.contains('expanded')));
status.toggle(main, 4);
assert(!container.classList.contains('show'));
assert(!parentIcon.classList.contains('expanded'));
tables[1].classList.remove('show');
icons[1].classList.remove('expanded');
status.toggle(main, 4);
assert(tables.every(table => table.classList.contains('show')));
assert(icons.every(icon => icon.classList.contains('expanded')));
status.toggle(main, 4);
status.open({ closest: () => main }, 4);
assert(container.classList.contains('show'));
assert(parentIcon.classList.contains('expanded'));
assert(tables.every(table => table.classList.contains('show')));
assert.doesNotThrow(() => status.toggle(main, 999));

const template = fs.readFileSync(path.join(base, '../../../templates/base_layer1.html'), 'utf8');
assert(template.indexOf('js/retail-status.js') > template.indexOf('js/layer1-common.js'));
assert(template.indexOf('js/retail-status.js') < template.indexOf('{% block layer1_js %}'));
console.log('Layer1 retail missing summaries and country expansion tests passed.');
