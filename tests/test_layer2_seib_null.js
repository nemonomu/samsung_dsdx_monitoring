const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer2/static/dx_layer2/js/';
let html, options;
const context = {
    console, renderCountryFlagLabel: String,
    renderNullFieldsDetail: fields => Object.keys(fields).join(','),
    getDetailBody: () => ({innerHTML: ''}), getSelectedDate: () => '2026-10-18',
    isInlineMode: () => true, buildDetailContainerHtml: data => data.itemQueryHtml,
    renderDetailWithTable: data => {options=data;},
    ViewStack: {push: value => {html=value;}},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(base+'dashboard.js','utf8'),context);
vm.runInContext(fs.readFileSync(base+'null_validation.js','utf8'),context);
const products=['tv','ref','ldy','ldy_dryer'];
const groups=context.buildLayer2NullGroups(products.map(product=>({
    table:'seib_'+product+'_retail',table_name:'SEIB '+product.toUpperCase(),
    total_records:74,total_issues:8,status:'CRITICAL',retailers:[],
})),'null');
assert.equal(groups.length,1);
assert.equal(groups[0].name,'SEIB Retail');
assert.equal(groups[0].total_records,296);
for(const product of products){
    const code='seib_'+product+'_retail';
    vm.runInContext(`modalState.tableParam=${JSON.stringify(code)}; modalState.retailer='MediaMarkt';`,context);
    const field=product==='tv'?'screen_size':product==='ref'?'ref_capacity':'capacity';
    const data={date:'2026-10-18',inspection_date:'2026-10-18',source_date:'2026-10-18',
        actual_table:'dx_seib.dx_seib_'+product+'_retail_com',date_column:'crawl_datetime',
        supports_day_history:true,history_days:3,editable_cols:[field],
        results:[{id:42,item:"sku'1",[field]:null,crawl_datetime:'2026-10-18T23:59:00-04:00'}],
        display_config:{[field]:{select_columns:['id','item',field,'crawl_datetime']}},
    };
    context.renderNullFieldDetailView(field,data,true);
    assert.equal(context.getDefaultNullHistoryDays(code),3);
    assert.equal(options.crawlDate,'2026-10-18');
    assert.equal(options.editableDate,'2026-10-18');
    assert(!options.editableCols.includes('loading_type'));
    assert(html.includes('3일치 Item 조회 SQL'));
    const sql=context._buildNullRetailDisplayQuery(field,data,data.results,data.date,3,'MediaMarkt',false);
    assert(sql.includes("LEFT(BTRIM(CAST(crawl_datetime AS TEXT)), 10) >= '2026-10-18'"));
    assert(sql.includes("< '2026-10-19'"));
    assert(sql.includes("'sku''1'"));
    assert(!sql.includes('AT TIME ZONE'));
}
console.log('SEIB NULL: four-product grouping, same-day edits, bounded history and raw-date SQL passed.');
