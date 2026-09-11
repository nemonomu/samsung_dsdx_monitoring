const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const nodes = {};
let summary = null;
let body = '';
let copied = '';
let fallbackRemoved = false;
const context = {
    L1: {renderers: {}},
    esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    getSelectedDate: () => '2026-03-01',
    getRetailSummaryData: () => summary,
    getStatusBadge: status => '<status>' + status + '</status>',
    renderCountryFlagLabel: value => value,
    showToast: () => {},
    navigator: {},
    document: {
        getElementById: id => nodes[id],
        createElement: () => ({style: {}, select() {copied = this.value;}, remove() {fallbackRemoved = true;}}),
        execCommand: command => command === 'copy',
    },
    AppModal: {
        create() {}, setTitle() {}, open() {},
        setBody(id, html) {
            body = html;
            nodes['l1-query-retailer'] = {value: '0'};
            nodes['l1-query-date'] = {value: html.match(/id="l1-query-date" value="([^"]*)"/)[1]};
            nodes['l1-query-sql'] = {};
            nodes['l1-query-copy'] = {};
        },
        getBody: () => ({appendChild() {}}),
    },
};
context.window = context;
vm.runInNewContext(fs.readFileSync(base + 'retail-query.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync(base + 'retail-status.js', 'utf8'), context);
const query = context.L1.retailQuery;

// Every country/product routes to its real table and date type.
for (const country of ['SEA', 'SIEL', 'SEG', 'TSE', 'SEM']) {
    for (const product of ['TV', 'REF', 'LDY']) {
        const sql = query.buildQuery(country, product, 'Amazon', 'a_batch', '2026-09-09');
        const prefix = country.toLowerCase();
        const table = country === 'SEA' ? 'public.' + product.toLowerCase() + '_retail_com'
            : `dx_${prefix}.dx_${prefix}_${product.toLowerCase()}_retail_com`;
        const date = country === 'SEG' || (country === 'SEA' && product !== 'TV') ? 'crawl_strdatetime' : 'crawl_datetime';
        assert(sql.startsWith('SELECT *\nFROM ' + table + '\n'));
        assert(sql.includes("AND batch_id = 'a_batch'"));
        assert(sql.endsWith('ORDER BY ' + date + ';'));
        assert(sql.includes(country === 'SIEL'
            ? `AND ${date} >= ('2026-09-09'::date::timestamp AT TIME ZONE 'Asia/Seoul')\n`
            : `AND ${date} >= '2026-09-09'\n`));
        assert(!sql.includes('redirect') && !sql.includes('sku,'));
    }
}
assert(query.buildQuery('SEA', 'TV', "A'B", "b'1, b2, b2", '2026-09-09').includes("IN ('b''1', 'b2')"));
assert(query.buildQuery('SEA', 'TV', "A'B", 'b1', '2026-09-09').includes("= 'a''b'"));
for (const args of [
    ['SEA', 'TV', 'Amazon', '', '2026-09-09'],
    ['SEA', 'TV', 'Amazon', ' , ', '2026-09-09'],
    ['SEA', 'TV', 'Amazon', 'b1', 'bad-date'],
    ['OTHER', 'TV', 'Amazon', 'b1', '2026-09-09'],
]) assert.strictEqual(query.buildQuery(...args), '');

const cat = {name: 'TV', time_slots: [{retailers: [{retailer: 'Amazon', batch_id: 'old-batch'}]}]};
const button = query.button('SEA', cat, 0, 0);
assert(button.includes('event.stopPropagation();'));
query.open('SEA-0-0');
assert(nodes['l1-query-sql'].textContent.includes("AND batch_id = 'old-batch'"));
assert.strictEqual(nodes['l1-query-date'].value, '2026-02-28');
// Resolve async SEA summaries on click; use the source date, not inspection day.
summary = {source_date: '2026-09-09', summary: [
    {retailer: 'Amazon', batch_id: 'fallback', rows: [{batch_id: 'a_20260909_170012'}]},
    {retailer: 'Bestbuy', rows: [{batch_id: 'b1, b2'}]},
    {retailer: 'Walmart', batch_id: ''},
]};
query.open('SEA-0-0');
assert(body.includes('전체 조회 SQL') && body.includes('복사'));
assert.strictEqual(nodes['l1-query-date'].value, '2026-09-09');
assert(nodes['l1-query-sql'].textContent.includes("batch_id = 'a_20260909_170012'"));
nodes['l1-query-retailer'].value = '1';
query.update();
assert(nodes['l1-query-sql'].textContent.includes("batch_id IN ('b1', 'b2')"));
nodes['l1-query-retailer'].value = '2';
query.update();
assert(nodes['l1-query-copy'].disabled);
assert(!nodes['l1-query-sql'].textContent.includes('SELECT'));

// SEM shares the TSE renderer but must use its own source table.
vm.runInNewContext(fs.readFileSync(base + 'tse_retail.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync(base + 'sem_retail.js', 'utf8'), context);
const html = context.L1.renderers.sem_retail({check_type: 'sem_retail', name: 'SEM Retail',
    categories: [{name: 'TV', actual: 300, retailers: [{retailer: 'Liverpool', batch_id: 'liv1'}]}]}, 1);
assert(html.includes("L1.retailQuery.open('SEM-1-0')"));
assert(html.includes('toggleSemCategory'));
assert(/l1-retail-query-button[\s\S]*?<span class="sentiment-category-count">300\/0건<\/span>/.test(html));
query.open('SEM-1-0');
assert(nodes['l1-query-sql'].textContent.includes('FROM dx_sem.dx_sem_tv_retail_com'));
assert.strictEqual(nodes['l1-query-date'].value, '2026-03-01');

(async () => {
    // HTTP production pages need the legacy copy fallback inside the modal.
    await query.copy();
    assert.strictEqual(copied, nodes['l1-query-sql'].textContent);
    assert(fallbackRemoved);
    context.isSecureContext = true;
    context.navigator.clipboard = {writeText: async value => {copied = value;}};
    nodes['l1-query-date'].value = '2026-02-28';
    query.update();
    await query.copy();
    assert.strictEqual(copied, nodes['l1-query-sql'].textContent);
    assert(copied.includes(">= '2026-02-28'"));
    console.log('Layer1 retail query tests passed (15 sources, batch/date selection, SEM routing, copy).');
})().catch(error => {console.error(error); process.exitCode = 1;});
