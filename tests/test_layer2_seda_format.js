const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const body = {innerHTML: ''};
let options, html;
const context = {
    console, document: {getElementById: () => null},
    getSelectedDate: () => '2026-09-21', getDetailBody: () => body,
    isInlineMode: () => true, renderCountryFlagLabel: text => text,
    ViewStack: {push: value => { html = value; }},
    buildDetailContainerHtml: options => options.itemQueryHtml,
    renderDetailWithTable: value => { options = value; },
};
vm.createContext(context);
for (const name of ['null_validation', 'format_validation']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer2/static/dx_layer2/js/${name}.js`, 'utf8'), context);
}
const groups = [
    ['star_rating', 'count_of_star_ratings', 'count_of_reviews'],
    ['original_sku_price', 'final_sku_price', 'savings'],
];
for (const product of ['tv', 'ref', 'ldy']) {
    for (const group of groups) {
        for (const field of group.filter(key => key !== 'savings')) {
            const data = {
                date: '2026-09-21', source_date: '2026-09-20', editable_date: '2026-09-20',
                date_column: 'crawl_strdatetime', actual_table: `dx_seda.dx_seda_${product}_retail_com`,
                column_names: ['id', 'item', 'retailer_sku_name', 'crawl_strdatetime', ...groups.flat()],
                editable_cols: groups.flat().filter(key => key !== 'savings'),
                field_display_columns: {[field]: group},
                field_queries: {[field]: `SELECT ${group.join(', ')} WHERE item = '<script>';`},
                results: [
                    {id: 1, item: 'item', crawl_strdatetime: '2026-09-19', error_fields: []},
                    {id: 2, item: 'item', crawl_strdatetime: '2026-09-20', error_fields: [field]},
                    {id: 3, item: null, crawl_strdatetime: '2026-09-20', error_fields: [field]},
                ],
            };
            context.data = data;
            vm.runInContext(`modalState = {tableParam:'seda_${product}_retail',tableName:'SEDA ${product}', retailer:'Casas Bahia', days:3,formatFieldsData:data}`, context);
            context.showFormatFieldDetail(field);
            const keys = options.config.map(col => col.key);
            for (const key of group) assert(keys.includes(key), key);
            assert.strictEqual(options.data.length, 3, 'history and findings without item are retained');
            assert.strictEqual(options.editableDate, '2026-09-20');
            assert.strictEqual(options.crawlDate, '2026-09-21');
            assert(!options.editableCols.includes('savings'));
            assert(html.includes('&lt;script&gt;'));
            assert(!html.includes('<script>'));
            assert.strictEqual(context.getDefaultFormatHistoryDays(`seda_${product}_retail`), 3);
        }
    }
}
console.log('SEDA format grouped columns, history, editable day and escaped SQL passed.');
