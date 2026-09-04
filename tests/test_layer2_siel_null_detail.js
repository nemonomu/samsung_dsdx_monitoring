const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const dashboardSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js', 'utf8'
);
const nullSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js', 'utf8'
);
const commonSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js', 'utf8'
);
const nullTemplateSource = fs.readFileSync(
    'apps/dx/dx_layer2/templates/layer2_null_validation.html', 'utf8'
);

const dashboardSandbox = {
    console,
    renderCountryFlagLabel: value => String(value),
    renderNullFieldsDetail(fields) {
        return Object.keys(fields || {}).join(',');
    }
};
vm.createContext(dashboardSandbox);
vm.runInContext(dashboardSource, dashboardSandbox);

const data = {
    validation_types: [{
        type: 'null',
        type_name: 'NULL 검증',
        tables: [
            { table: 'youtube', table_name: 'YouTube', total_records: 0, total_issues: 0, status: 'OK' },
            { table: 'tse_tv_retail', table_name: 'TSE TV', total_records: 3, total_issues: 0, status: 'OK' },
            { table: 'siel_ldy_retail', table_name: 'LDY', total_records: 30, total_issues: 2, status: 'CRITICAL' },
            { table: 'sea_ldy_retail', table_name: 'SEA LDY', total_records: 20, total_issues: 0, status: 'OK' },
            { table: 'siel_tv_retail', table_name: 'TV', total_records: 40, total_issues: 1, status: 'CRITICAL' },
            { table: 'tv_retail', table_name: 'SEA TV', total_records: 10, total_issues: 0, status: 'OK' },
            { table: 'siel_ref_retail', table_name: 'REF', total_records: 50, total_issues: 3, status: 'CRITICAL' }
        ]
    }]
};
dashboardSandbox.prepareLayer2DisplayData(data);
assert.deepStrictEqual(
    data.validation_types[0].tables.map(table => table.table),
    [
        'tv_retail', 'sea_ldy_retail',
        'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail',
        'tse_tv_retail', 'youtube'
    ]
);
assert.strictEqual(data.validation_types[0].tables[2].table_name, 'SIEL TV');
assert.strictEqual(data.validation_types[0].tables[3].table_name, 'SIEL REF');
assert.strictEqual(data.validation_types[0].tables[4].table_name, 'SIEL LDY');

const groups = dashboardSandbox.buildLayer2NullGroups(
    data.validation_types[0].tables, data.validation_types[0]
);
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(groups.map(entry => entry.name || entry.member.table.table_name))),
    ['SEA Retail', 'SIEL Retail', 'TSE Retail', 'YouTube']
);
assert.strictEqual(groups[1].total_records, 120);
assert.strictEqual(groups[1].total_issues, 6);
assert.strictEqual(groups[1].status, 'CRITICAL');

const summaryHtml = dashboardSandbox.renderDXTableDetail(
    { type: 'null' },
    {
        table: 'siel_ref_retail',
        table_name: 'SIEL REF',
        inspection_date: '2026-08-31',
        source_date: '2026-08-31',
        offset_days: 0,
        retailers: [{
            retailer: 'Flipkart',
            total: 300,
            total_null_count: 2,
            status: 'CRITICAL',
            batch_id: 'f_20260831_090000',
            fields_detail: { ref_capacity: 2 }
        }]
    }
);
assert.ok(summaryHtml.includes('검수일 2026-08-31'));
assert.ok(summaryHtml.includes('데이터일 2026-08-31'));
assert.ok(summaryHtml.includes('· D'));
assert.ok(!summaryHtml.includes('batch_id:'));
assert.ok(summaryHtml.includes("this.dataset.fields, 'siel_ref_retail'"));

let detailBody = { innerHTML: '' };
let itemQueryHtml = '';
let tableOptions = null;
const nullSandbox = {
    console,
    getDetailBody() { return detailBody; },
    getSelectedDate() { return '2026-08-31'; },
    isInlineMode() { return false; },
    buildDetailContainerHtml(options) {
        itemQueryHtml = options.itemQueryHtml;
        return options.itemQueryHtml;
    },
    renderDetailWithTable(options) { tableOptions = options; }
};
vm.createContext(nullSandbox);
vm.runInContext(nullSource, nullSandbox);
assert.strictEqual(nullSandbox.getDefaultNullHistoryDays('siel_tv_retail'), 3);
assert.strictEqual(nullSandbox.getDefaultNullHistoryDays('siel_ref_retail'), 3);
assert.strictEqual(nullSandbox.getDefaultNullHistoryDays('siel_ldy_retail'), 3);
assert.strictEqual(nullSandbox.getDefaultFormatHistoryDays('siel_tv_retail'), 3);

vm.runInContext(`
    modalState.tableParam = 'siel_ref_retail';
    modalState.tableName = 'SIEL REF';
    modalState.retailer = 'Flipkart';
    modalState.days = 3;
`, nullSandbox);
nullSandbox.renderNullFieldDetailView('ref_capacity', {
    results: [{
        id: 42,
        item: 'item-1',
        ref_capacity: null,
        crawl_datetime: '2026-08-31 08:50:00',
        product_url: 'https://p/1',
        null_fields: ['ref_capacity']
    }],
    display_config: {
        ref_capacity: {
            select_columns: [
                'crawl_datetime', 'item', 'account_name', 'country', 'sku',
                'retailer_sku_name', 'ref_capacity', 'product_url'
            ]
        }
    },
    query_config: {
        ref_capacity: [
            'id', 'crawl_datetime', 'batch_id', 'account_name', 'page_type',
            'item', 'ref_capacity', 'product_url'
        ]
    },
    actual_table: 'dx_siel.dx_siel_ref_retail_com',
    inspection_date: '2026-08-31',
    source_date: '2026-08-31',
    offset_days: 0,
    batch_id: 'f_20260831_090000',
    supports_day_history: true,
    history_days: 3,
    date: '2026-08-31',
    date_column: 'crawl_datetime'
}, true);
assert.ok(itemQueryHtml.includes('3일치 조회 쿼리 (기준 데이터일 2026-08-31)'));
assert.ok(itemQueryHtml.includes('WITH latest_batches AS'));
assert.ok(itemQueryHtml.includes("AT TIME ZONE 'Asia/Seoul'"));
assert.ok(itemQueryHtml.includes("IN ('main', 'bsr')"));
assert.ok(itemQueryHtml.includes('source.batch_id IS NOT DISTINCT FROM latest.batch_id'));
assert.ok(itemQueryHtml.includes(
    "NOT (source.account_name = 'Amazon' AND source.redirect IS TRUE)"
));
assert.ok(!itemQueryHtml.includes("INTERVAL '2 days'"));
assert.strictEqual(tableOptions.actualTable, 'dx_siel.dx_siel_ref_retail_com');
assert.strictEqual(tableOptions.crawlDate, '2026-08-31');
assert.strictEqual(tableOptions.editableDate, '2026-08-31');
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(tableOptions.editableCols)), []
);

assert.ok(commonSource.includes("detailViewState.type !== 'null'"));
assert.ok(commonSource.includes('requireMemo: requiresMemo'));
assert.ok(commonSource.includes('if (memoRequired && !memo)'));
assert.ok(nullTemplateSource.includes(
    "dx_layer2/js/layer2-common.js' %}?v=20260904-4"
));

console.log('Layer2 SIEL NULL frontend tests passed.');
