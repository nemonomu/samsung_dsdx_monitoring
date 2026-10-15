const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const root = 'apps/dx/dx_layer2/static/dx_layer2/js/';
const body = {innerHTML: ''};
const elements = new Map();
let clipboard = '';
let fallbackText = '';
let tableOptions;
let pagerOptions;
let pageRequest;
const escape = value => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[ch]));
const context = vm.createContext({
    console, esc: escape,
    window: {isSecureContext: true},
    navigator: {clipboard: {writeText: async text => { clipboard = text; }}},
    setTimeout: () => 0,
    document: {
        getElementById: id => {
            if (!elements.has(id)) elements.set(id, {innerHTML: ''});
            return elements.get(id);
        },
        querySelector: () => null, querySelectorAll: () => [],
        createElement: () => ({style: {}, focus() {}, select() { fallbackText = this.value; }}),
        body: {appendChild() {}, removeChild() {}},
        execCommand: action => { assert.strictEqual(action, 'copy'); return true; }
    },
    getDetailBody: () => body,
    getColumnConfig: () => ({group: [{key: 'item'}], detail: [{key: 'id'}]}),
    getAllColumns: config => config.group.concat(config.detail),
    renderDetailWithTable: options => { tableOptions = options; },
    detailViewState: {}, isInlineMode: () => false,
    isTseDuplicateTable: table => table.startsWith('tse_'),
    flattenRecords: (_type, groups) => groups.flatMap(group => group.records),
    getCellHtml: (row, col) => '<td>' + escape(row[col.key] || '') + '</td>',
    CommonTable: function() { this.render = () => {}; this.renderBody = (rows, render) => rows.forEach(render); },
    FilterBar: function() { this.render = () => this; },
    Pagination: function(_target, options) { pagerOptions = options; this.render = () => {}; }
});
vm.runInContext(fs.readFileSync(root + 'null_validation.js', 'utf8'), context);
context.openDetailModal = (...args) => { pageRequest = args; };
vm.runInContext(fs.readFileSync(root + 'anomaly_validation.js', 'utf8'), context);
// Use the production container to verify placement for both rendering paths.
vm.runInContext(fs.readFileSync(root + 'layer2-common.js', 'utf8')
    .match(/function buildDetailContainerHtml\(options\) \{[\s\S]*?\n\}/)[0], context);

function payload(ids, readonly = false) {
    return {query: `SELECT *\nFROM public.ref_retail_com\nWHERE id IN (${ids.join(', ')});`,
        query_record_count: ids.length, readonly,
        results: {duplicates: [{item: 'same', records: ids.map(id => ({id}))}]}};
}

async function main() {
    const first = payload([10, 11]);
    vm.runInContext('modalState.totalPages = 1;', context);
    context.renderDetailTable('duplicate', first, 'sea_ref_retail');
    assert(body.innerHTML.includes('중복 데이터 조회 SQL (2건)'));
    assert(body.innerHTML.indexOf('query-content') < body.innerHTML.indexOf('detail-table-area'));
    assert(body.innerHTML.includes('copyToClipboard(this.parentElement.nextElementSibling)'));
    assert.strictEqual(tableOptions.type, 'duplicate');
    assert.strictEqual(tableOptions.data[0].records[0].id, 10);

    const dryer = {...payload([20, 21], true), retailer: 'HomeDepot',
        query: 'SELECT * FROM public.ldy_dryer_retail WHERE id IN (20, 21);',
        readonly_message: '건조기 중복 검증은 확인 전용이며 자동 삭제하지 않습니다.',
        select_cols: {group: ['duplicate_type', 'item'], record: ['id', 'sku', 'crawl_datetime', 'product_url']}};
    context.renderDetailTable('duplicate', dryer, 'sea_ldy_dryer_retail');
    assert(body.innerHTML.includes('public.ldy_dryer_retail'));
    assert(tableOptions.config.detail.some(col => col.key === 'crawl_datetime'));
    assert(!tableOptions.config.group.some(col => col.key === 'page_type'));

    vm.runInContext("modalState.totalPages = 3; modalState.totalGroups = 5; modalState.currentPage = 2; modalState.tableName = 'TSE REF'; modalState.retailer = 'Homepro'; modalState.count = 5;", context);
    const second = payload([20, 21], true);
    context.renderDetailTable('duplicate', second, 'tse_ref_retail');
    assert(body.innerHTML.includes('20, 21'));
    assert(!body.innerHTML.includes('10, 11'));
    assert(elements.get('detail-action-bar').innerHTML.includes('확인 전용'));
    assert(body.innerHTML.includes('복사'));
    pagerOptions.onPageChange(3);
    assert.deepStrictEqual(pageRequest, ['duplicate', 'TSE REF', 'Homepro', 5, 3]);
    pagerOptions.onPageChange(4);
    assert.strictEqual(pageRequest[4], 3);

    const hostile = context.buildDuplicateQueryHtml({query: '</pre><script>bad()</script>', query_record_count: 1});
    assert(!hostile.includes('<script>'));
    assert(hostile.includes('&lt;script&gt;'));
    assert.strictEqual(context.buildDuplicateQueryHtml({}), '');
    context.renderDetailTable('duplicate', {query: '', results: {duplicates: []}}, 'sea_ref_retail');
    assert(body.innerHTML.includes('데이터가 없습니다'));
    assert(!body.innerHTML.includes('query-content'));

    const button = {textContent: '복사', style: {}};
    const pre = {textContent: second.query, previousElementSibling: {querySelector: () => button}};
    context.copyToClipboard(pre);
    await Promise.resolve();
    assert.strictEqual(clipboard, second.query);
    assert.strictEqual(button.textContent, '복사됨!');
    context.window.isSecureContext = false;
    context.copyToClipboard(pre);
    assert.strictEqual(fallbackText, second.query);
    console.log('Duplicate SQL: client/server pages, read-only, empty, escaping, HTTPS/HTTP copy passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
