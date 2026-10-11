const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
function read(relativePath) {
    return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

const format = read('apps/dx/dx_layer2/static/dx_layer2/js/format_validation.js');
const common = read('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js');

assert(format.includes('const isSegRetail = /^seg_(tv|ref|ldy|ldy_dryer)_retail$/'));
assert(format.includes('isSeaRetail || isSielRetail || isSegRetail'));
assert(format.includes("tableName: 'dx_seg.dx_seg_tv_retail_com'"));
assert(format.includes("dateColumn: 'crawl_strdatetime'"));
assert(common.includes("'seg_tv_retail': 'seg_tv'"));
assert(common.includes("'seg_ref_retail': 'seg_ref'"));
assert(common.includes("'seg_ldy_retail': 'seg_ldy'"));

console.log('Layer2 SEG format frontend tests passed.');

const vm = require('vm');
for (const [product, field, dateColumn] of [
    ['tv', 'screen_size', 'crawl_strdatetime'],
    ['ref', 'ref_capacity', 'crawl_strdatetime'],
    ['ldy', 'ldy_capacity', 'crawl_strdatetime'],
    ['ldy_dryer', 'capacity', 'crawl_datetime'],
]) {
    let html = '';
    let options;
    const sandbox = {
        console, getDetailBody: () => ({innerHTML: ''}),
        getSelectedDate: () => '2026-10-11', isInlineMode: () => true,
        renderCountryFlagLabel: value => value,
        buildDetailContainerHtml: value => value.itemQueryHtml,
        ViewStack: {push(value) { html = value; }},
        renderDetailWithTable(value) { options = value; },
    };
    vm.createContext(sandbox);
    vm.runInContext(read('apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js'), sandbox);
    vm.runInContext(format, sandbox);
    const table = `dx_seg.dx_seg_${product}_retail${product === 'ldy_dryer' ? '' : '_com'}`;
    const data = {
        date: '2026-10-11', source_date: '2026-10-11', date_column: dateColumn,
        actual_table: table, editable_cols: [field], column_names: ['id', 'item', dateColumn, field],
        results: [{id: 7, item: "I'1", account_name: 'expert', [dateColumn]: '2026-10-11',
                   [field]: 'bad', error_fields: [field]}],
    };
    vm.runInContext(`modalState.tableParam = 'seg_${product}_retail';
        modalState.tableName = 'SEG ${product}'; modalState.retailer = 'Expert';
        modalState.days = 3; modalState.formatFieldsData = ${JSON.stringify(data)};`, sandbox);
    sandbox.showFormatFieldDetail(field);
    assert(html.includes(`FROM ${table}`));
    assert(html.includes(`${dateColumn} &gt;=`));
    assert(html.includes('copyToClipboard'));
    assert(!html.includes('page_type'));
    assert.strictEqual(options.dateColumn, dateColumn);
    assert.strictEqual(options.formatReviewField, field);
    assert.deepStrictEqual(Array.from(options.editableCols), [field]);
}
console.log('Expert format SQL and editable detail tests passed.');
