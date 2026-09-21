const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const body = {innerHTML: ''};
const actionBar = {innerHTML: ''};
let tableOptions, renderedRows;
const context = {
    console, window: {},
    document: {
        addEventListener() {},
        getElementById: id => id === 'detail-action-bar' ? actionBar : null,
        querySelector: () => null,
    },
    CommonTable: class {
        constructor(selector, options) { tableOptions = options; }
        render() {}
        renderBody(rows, render) { renderedRows = rows.map(render).join(''); }
    },
};
vm.createContext(context);
for (const name of ['layer2-common', 'dashboard', 'null_validation', 'anomaly_validation']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer2/static/dx_layer2/js/${name}.js`, 'utf8'), context);
}
Object.assign(context, {
    getDetailBody: () => body,
    buildDetailContainerHtml: () => '',
    isInlineMode: () => false,
    getCellHtml: (row, col) => `<td>${row[col.key] || row._parent[col.key] || ''}</td>`,
});
for (const product of ['tv', 'ref', 'ldy']) {
    const table = `seda_${product}_retail`;
    assert(context.isReadOnlyDuplicateTable(table));
    const config = context.getColumnConfig('duplicate', table);
    for (const key of ['id', 'sku', 'batch_id', 'crawl_strdatetime']) {
        assert(config.detail.some(col => col.key === key));
    }
    const data = {
        table, table_name: `SEDA ${product.toUpperCase()}`,
        total_records: 4, total_issues: 2, status: 'CRITICAL',
        inspection_date: '2026-09-21', source_date: '2026-09-20', offset_days: -1,
        retailers: [{retailer: 'Casas Bahia', duplicate_groups: 2, status: 'CRITICAL'}],
    };
    const groups = context.buildLayer2NullGroups([data], 'duplicate');
    assert.strictEqual(groups[0].name, 'SEDA Retail');
    const html = context.renderDXTableDetail({type: 'duplicate'}, data);
    assert(html.includes(`openDetailModal('duplicate', 'SEDA ${product.toUpperCase()}', 'Casas Bahia', 2)`));
    assert(html.includes('Page Type + Item'));
}
const data = {
    readonly: true, readonly_message: 'SEDA 중복 검증은 확인 전용입니다.', editable_cols: [],
    results: {duplicates: [{duplicate_type: '상품 매핑 충돌', item: '001', page_type: 'MAIN', records: [
        {id: 1, sku: 'SKU-A', batch_id: 'batch001'}, {id: 2, sku: 'SKU-B', batch_id: 'batch001'},
    ]}]},
};
vm.runInContext('modalState.totalPages = 2; modalState.totalGroups = 2;', context);
context.renderDetailTable('duplicate', data, 'seda_tv_retail');
assert(actionBar.innerHTML.includes('확인 전용'));
assert(!tableOptions.columns.some(col => col.key === '_chk'));
assert(!renderedRows.includes('dup-check'));
assert(renderedRows.includes('rowspan="2"'));
assert(renderedRows.includes('상품 매핑 충돌'));
assert(renderedRows.includes('SKU-A') && renderedRows.includes('SKU-B'));
assert(renderedRows.includes('batch001'));
console.log('SEDA duplicate grouping, routing, columns and read-only rendering passed.');
