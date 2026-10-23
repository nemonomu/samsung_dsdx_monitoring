const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer2/static/dx_layer2/js/';
let html, options;
const context = {
    console, URL, window: {}, document: {addEventListener() {}},
    renderCountryFlagLabel: String,
    getDetailBody: () => ({innerHTML: ''}), getSelectedDate: () => '2026-10-23',
    isInlineMode: () => true, buildDetailContainerHtml: data => data.itemQueryHtml,
    renderDetailWithTable: data => {options=data;},
    ViewStack: {push: value => {html=value;}},
};
vm.createContext(context);
for (const file of ['layer2-common.js','dashboard.js','null_validation.js','format_validation.js','format-review.js']) {
    vm.runInContext(fs.readFileSync(base+file,'utf8'),context);
}
context.FormatReview = context.window.FormatReview;
context.captureHtml = value => {html=value;};
vm.runInContext('ViewStack.push = captureHtml;',context);
Object.assign(context, {
    getDetailBody: () => ({innerHTML: ''}), isInlineMode: () => true,
    buildDetailContainerHtml: data => data.itemQueryHtml,
    renderDetailWithTable: data => {options=data;},
});
const products=['tv','ref','ldy','ldy_dryer'];
for (const kind of ['format','anomaly']) {
    const groups=context.buildLayer2NullGroups(products.map(product=>({
        table:'seuk_'+product+'_retail',table_name:'SEUK '+product.toUpperCase(),
        total_records:10,total_issues:1,status:'CRITICAL',retailers:[],
    })),kind);
    assert.equal(groups.length,1);
    assert.equal(groups[0].name,'SEUK Retail');
    assert.equal(groups[0].total_issues,4);
}
for (const product of products) {
    const code='seuk_'+product+'_retail';
    assert(context.FormatReview.supports(code));
    assert(context.isReadOnlyDuplicateTable(code));
    const config=context.getColumnConfig('duplicate',code);
    assert(config.group.some(c=>c.key==='item'));
    assert(!context.getAllColumns(config).some(c=>c.key==='page_type'));
    assert.equal(context.getDefaultFormatHistoryDays(code),3);
    const data={date:'2026-10-23',source_date:'2026-10-23',
        actual_table:'dx_seuk.dx_seuk_'+product+'_retail_com',date_column:'crawl_datetime',
        active_from:'2026-10-23',editable_cols:['savings'],
        column_names:['id','item','crawl_datetime','savings','product_url'],
        results:[{id:42,item:"item'1",savings:'20%',error_fields:['savings'],
            crawl_datetime:'2026-10-23T23:59:00-04:00'},
            {id:43,item:null,savings:'30%',error_fields:['savings'],
             crawl_datetime:'2026-10-23T23:59:00-04:00'}],
    };
    context.testData=data;
    vm.runInContext(`modalState.tableParam=${JSON.stringify(code)}; modalState.tableName='SEUK'; modalState.retailer='Currys'; modalState.days=3; modalState.formatFieldsData=testData;`,context);
    context.showFormatFieldDetail('savings');
    assert.equal(options.editableDate,'2026-10-23');
    assert.deepEqual(Array.from(options.editableCols),['savings']);
    assert.equal(options.data.length,2);
    assert(html.includes('3일치 조회 SQL'));
    assert(html.includes('값별 일괄 검토'));
    assert(html.includes('2026-10-23'));
    assert(!html.includes('AT TIME ZONE'));
}
console.log('SEUK format/duplicate: groups, four products, review controls, scoped edits and original-date SQL passed.');
