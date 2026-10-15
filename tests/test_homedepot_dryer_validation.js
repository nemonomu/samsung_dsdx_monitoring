const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let html = '', options;
const context = {
    console, document: {getElementById: () => null},
    getSelectedDate: () => '2026-10-16', getDetailBody: () => ({innerHTML: ''}),
    isInlineMode: () => true, renderCountryFlagLabel: String,
    buildDetailContainerHtml: data => data.itemQueryHtml,
    renderDetailWithTable: data => { options = data; },
    ViewStack: {push: value => { html = value; }, getContainer: () => null},
};
context.window = context;
vm.createContext(context);
for (const file of ['null_validation', 'format_validation']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer2/static/dx_layer2/js/${file}.js`, 'utf8'), context);
}
const raw = {date: '2026-10-16', source_date: '2026-10-15', date_column: 'crawl_datetime',
    actual_table: 'public.ldy_dryer_retail', editable_cols: ['capacity'],
    column_names: ['id', 'crawl_datetime', 'item', 'capacity', 'sku', 'product_url'],
    results: [{id: 1, item: '123', account_name: 'HomeDepot', capacity: '7.4 L',
        crawl_datetime: '2026-10-15T23:30:00-04:00', _source_date: '2026-10-15',
        error_fields: ['capacity'], error_details: {capacity: {rule: 'format', reason: 'invalid'}}}]};
context.fixture = raw;
vm.runInContext(`modalState.tableParam = 'sea_ldy_dryer_retail'; modalState.tableName = 'SEA LDY_DRYER';
    modalState.retailer = 'HomeDepot'; modalState.days = 3; modalState.formatFieldsData = fixture;`, context);
context.showFormatFieldDetail('capacity');
assert(html.includes('public.ldy_dryer_retail'));
assert(html.includes('crawl_datetime'));
assert(html.includes('HomeDepot'));
assert(html.includes('copyToClipboard'));
assert(html.includes('fmt-detail-days'));
assert(!html.includes('crawl_strdatetime'));
assert(!html.includes('page_type'));
assert.strictEqual(options.editableDate, '2026-10-15');
assert.strictEqual(options.data.length, 1);
assert.strictEqual(options.dateColumn, 'crawl_datetime');
console.log('HomeDepot dryer format detail, history, edit date and lookup SQL passed.');
