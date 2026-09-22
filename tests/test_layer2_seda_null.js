const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const read = name => fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/' + name, 'utf8');
const dashboard = read('dashboard.js');
const nullSource = read('null_validation.js');
const context = {
    console,
    renderCountryFlagLabel: value => String(value),
    renderNullFieldsDetail: fields => Object.keys(fields || {}).join(','),
};
vm.createContext(context);
vm.runInContext(dashboard, context);
const tables = ['tv', 'ref', 'ldy'].map(product => ({
    table: `seda_${product}_retail`, table_name: `SEDA ${product.toUpperCase()}`,
    total_records: 10, total_issues: 0, status: 'OK',
    inspection_date: '2026-09-14', source_date: '2026-09-13', offset_days: -1,
    retailers: [{retailer: 'Casas Bahia', total: 10, total_null_count: 0,
        fields_detail: {count_of_reviews: 0}, status: 'OK'}],
}));
const grouped = context.buildLayer2NullGroups(tables, 'null');
assert.strictEqual(grouped.length, 1);
assert.strictEqual(grouped[0].name, 'SEDA Retail');
assert.strictEqual(grouped[0].total_records, 30);
const retailHtml = context.renderDXTableDetail({type: 'null'}, tables[0]);
assert(retailHtml.includes('Casas Bahia'));
assert(retailHtml.includes('검수일 2026-09-14'));
assert(retailHtml.includes('데이터일 2026-09-13'));
assert(retailHtml.includes("this.dataset.fields, 'seda_tv_retail'"));

let html, tableOptions;
const body = {innerHTML: ''};
Object.assign(context, {
    getDetailBody: () => body,
    getSelectedDate: () => '2026-09-14',
    isInlineMode: () => true,
    buildDetailContainerHtml: options => options.itemQueryHtml,
    renderDetailWithTable: options => { tableOptions = options; },
    ViewStack: {push(value) { html = value; }, getContainer: () => body},
});
vm.runInContext(nullSource, context);
vm.runInContext("modalState.tableParam = 'seda_ldy_retail'; modalState.tableName = 'SEDA LDY'; modalState.retailer = 'Casas Bahia';", context);
const data = {
    date: '2026-09-14', inspection_date: '2026-09-14', source_date: '2026-09-13',
    date_column: 'crawl_strdatetime', offset_days: -1,
    actual_table: 'dx_seda.dx_seda_ldy_retail_com', query_retailer: 'Casas Bahia',
    results: [
        {id: 1, item: '001', ldy_color: 'White', crawl_strdatetime: '2026-09-12 20:00:00', null_fields: []},
        {id: 2, item: '001', ldy_color: null, crawl_strdatetime: '2026-09-13 20:00:00', null_fields: ['ldy_color']},
    ],
    supports_day_history: true, history_days: 3,
    editable_cols: ['ldy_color'],
    display_config: {ldy_color: {select_columns: ['id', 'item', 'ldy_color', 'crawl_strdatetime']}},
    query_config: {ldy_color: ['id', 'item', 'ldy_color', 'crawl_strdatetime']},
};
context.renderNullFieldDetailView('ldy_color', data, true);
assert(html.includes('검수일 2026-09-14'));
assert(html.includes('데이터일 2026-09-13'));
assert.strictEqual(context.getDefaultNullHistoryDays('seda_ldy_retail'), 3);
assert.strictEqual(tableOptions.crawlDate, '2026-09-14');
assert.strictEqual(tableOptions.editableDate, '2026-09-13');
assert.deepStrictEqual(tableOptions.editableCols, ['ldy_color']);

context.isInlineMode = () => false;
context.renderNullFieldDetailView('ldy_color', data, false);
assert(body.innerHTML.includes("crawl_strdatetime >= '2026-09-11'"));
assert(body.innerHTML.includes("account_name = 'CasasBahia'"));
assert(body.innerHTML.includes("crawl_strdatetime < '2026-09-14'"));
assert(!body.innerHTML.includes('latest_batches'));
assert(body.innerHTML.includes('id="detail-days"'));
console.log('SEDA NULL grouping, D-1 detail, alias SQL, and edit date tests passed.');
