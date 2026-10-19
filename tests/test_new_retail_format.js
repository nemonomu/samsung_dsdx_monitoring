const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let html = '', options;
const context = {
    console, document: {getElementById: () => null},
    getSelectedDate: () => '2026-10-19', getDetailBody: () => ({innerHTML: ''}),
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

for (const [table, actual, retailer, sourceDate, collectedAt] of [
    ['seib_tv_retail', 'dx_seib.dx_seib_tv_retail_com', 'MediaMarkt',
        '2026-10-19', '2026-10-19T01:09:37+09:00'],
    ['sem_ldy_dryer_retail', 'dx_sem.dx_sem_ldy_dryer_retail_com', 'HomeDepot',
        '2026-10-19', '2026-10-19T01:00:46+00:00'],
]) {
    const fixture = {
        date: '2026-10-19', source_date: sourceDate, date_column: 'crawl_datetime',
        actual_table: actual, retailer, batch_id: 'b1', editable_cols: ['final_sku_price'],
        column_names: ['id', 'crawl_datetime', 'item', 'final_sku_price', 'product_url'],
        results: [{id: 7, item: '123', account_name: retailer, batch_id: 'b1',
            final_sku_price: 'bad', crawl_datetime: collectedAt,
            _source_date: sourceDate, error_fields: ['final_sku_price']}],
    };
    context.fixture = fixture;
    context.table = table;
    context.retailer = retailer;
    vm.runInContext(`modalState.tableParam = table; modalState.tableName = table;
        modalState.retailer = retailer; modalState.days = 1;
        modalState.formatFieldsData = fixture;`, context);
    context.showFormatFieldDetail('final_sku_price');
    assert(html.includes(`FROM ${actual}`));
    assert(html.includes('batch_id = &#039;b1&#039;'));
    assert(html.includes(retailer));
    assert.strictEqual(options.editableDate, sourceDate);
}
console.log('SEIB and SEM dryer format detail queries passed.');
