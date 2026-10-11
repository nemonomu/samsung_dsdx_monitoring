const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const root = 'apps/dx/dx_layer2/static/dx_layer2/js';
let html = '';
let options;
const context = vm.createContext({
    console,
    renderCountryFlagLabel: value => String(value),
    getDetailBody: () => ({innerHTML: ''}),
    getSelectedDate: () => '2026-10-11',
    isInlineMode: () => true,
    buildDetailContainerHtml: data => data.itemQueryHtml,
    renderDetailWithTable: data => { options = data; },
    ViewStack: {push: value => { html = value; }, getContainer: () => null},
});
vm.runInContext(fs.readFileSync(`${root}/dashboard.js`, 'utf8'), context);
vm.runInContext(fs.readFileSync(`${root}/null_validation.js`, 'utf8'), context);
const tables = [
    {table: 'sea_ldy_dryer_retail', table_name: 'SEA LDY_DRYER', total_records: 300, total_issues: 1},
    {table: 'sea_ldy_retail', table_name: 'SEA LDY', total_records: 100, total_issues: 0},
];
const data = {validation_types: [{tables}]};
context.prepareLayer2DisplayData(data);
assert.deepStrictEqual(data.validation_types[0].tables.map(t => t.table), ['sea_ldy_retail', 'sea_ldy_dryer_retail']);
const groups = context.buildLayer2NullGroups(tables);
assert.strictEqual(groups[0].name, 'SEA Retail');
assert.strictEqual(groups[0].total_records, 400);
assert.strictEqual(context.getDefaultNullHistoryDays('sea_ldy_dryer_retail'), 3);
vm.runInContext(`modalState.tableParam = 'sea_ldy_dryer_retail';
    modalState.tableName = 'SEA LDY_DRYER'; modalState.retailer = 'Costco'; modalState.days = 3;`, context);
const detail = {
    results: [{id: 42, item: '123', account_name: 'Costco', capacity: null,
               crawl_datetime: '2026-10-10 13:00:00', _source_date: '2026-10-10', null_fields: ['capacity']}],
    display_config: {capacity: {select_columns: ['id', 'item', 'capacity', 'crawl_datetime']}},
    query_config: {capacity: ['id', 'item', 'capacity', 'crawl_datetime']},
    actual_table: 'public.ldy_dryer_retail', date_column: 'crawl_datetime',
    date: '2026-10-11', inspection_date: '2026-10-11', source_date: '2026-10-10',
    offset_days: -1, source_key: 'sea_ldy_dryer', batch_id: 'c_batch',
    supports_day_history: true, history_days: 3,
    editable_cols: ['capacity'], normal_reviews: {},
};
context.renderNullFieldDetailView('capacity', detail, true);
assert(html.includes('public.ldy_dryer_retail'));
assert(html.includes('Asia/Seoul'));
assert(html.includes('2026-10-09'));
assert(html.includes('copyToClipboard'));
assert(!html.includes('page_type'));
assert(!html.includes('crawl_strdatetime'));
assert(options, 'Detail table should render');
const sql = context._buildNullRetailDisplayQuery('capacity', detail, detail.results, detail.date, 1, 'Costco', false);
assert(sql.includes("batch_id = 'c_batch'"));
assert(sql.includes("account_name = 'Costco'"));
console.log('Costco dryer Layer 2 grouping, detail and SQL checks passed');
