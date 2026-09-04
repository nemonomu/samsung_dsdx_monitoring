const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const dashboardSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js', 'utf8'
);
const nullSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js', 'utf8'
);
const layer2CommonSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js', 'utf8'
);

const sandbox = {
    console,
    displayCountryFlagLabel(value) {
        const flags = { SEA: '🇺🇸', SIEL: '🇮🇳', TSE: '🇹🇭' };
        const text = String(value || '');
        return flags[text.split(' ')[0]] ? flags[text.split(' ')[0]] + ' ' + text : text;
    },
    renderNullFieldsDetail(fields) {
        return Object.keys(fields || {}).join(',');
    }
};
vm.createContext(sandbox);
vm.runInContext(dashboardSource, sandbox);

const data = {
    validation_types: [{
        tables: [
            { table: 'youtube', table_name: 'YouTube', total_records: 0, total_issues: 0, status: 'OK' },
            { table: 'tse_ref_retail', table_name: 'TSE REF', total_records: 612, total_issues: 22, status: 'CRITICAL' },
            { table: 'tse_tv_retail', table_name: 'TSE TV', total_records: 993, total_issues: 8, status: 'CRITICAL' },
            { table: 'sea_ldy_retail', table_name: 'LDY', total_records: 468, total_issues: 0, status: 'OK' },
            { table: 'tv_retail', table_name: 'TV Retail', total_records: 316, total_issues: 5, status: 'CRITICAL' },
            { table: 'tse_ldy_retail', table_name: 'TSE LDY', total_records: 583, total_issues: 18, status: 'CRITICAL' },
            { table: 'sea_ref_retail', table_name: 'REF', total_records: 625, total_issues: 57, status: 'CRITICAL' }
        ]
    }]
};
sandbox.prepareLayer2DisplayData(data);
assert.deepStrictEqual(
    data.validation_types[0].tables.map(table => table.table),
    [
        'tv_retail', 'sea_ref_retail', 'sea_ldy_retail',
        'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail', 'youtube'
    ]
);
assert.strictEqual(data.validation_types[0].tables[0].table_name, 'SEA TV');
assert.strictEqual(data.validation_types[0].tables[1].table_name, 'SEA REF');
assert.strictEqual(data.validation_types[0].tables[2].table_name, 'SEA LDY');

const groups = sandbox.buildLayer2NullGroups(data.validation_types[0].tables);
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(groups.map(entry => ({
        type: entry.type,
        name: entry.name || entry.member.table.table_name,
        total_records: entry.total_records,
        total_issues: entry.total_issues,
        status: entry.status
    })))),
    [
        { type: 'group', name: 'SEA Retail', total_records: 1409, total_issues: 62, status: 'CRITICAL' },
        { type: 'group', name: 'TSE Retail', total_records: 2188, total_issues: 48, status: 'CRITICAL' },
        { type: 'table', name: 'YouTube' }
    ]
);

const groupedHtml = sandbox.renderInlineNullGroups(data.validation_types[0]);
assert.ok(groupedHtml.includes('SEA TV/REF/LDY NULL 검증'));
assert.ok(groupedHtml.includes('TSE TV/REF/LDY NULL 검증'));
assert.ok(groupedHtml.includes('SEA TV'));
assert.ok(groupedHtml.includes('SEA REF'));
assert.ok(groupedHtml.includes('SEA LDY'));
assert.ok(groupedHtml.includes('YouTube'));
assert.ok(groupedHtml.includes('🇺🇸 SEA Retail'));
assert.ok(groupedHtml.includes('🇹🇭 TSE Retail'));
assert.ok(groupedHtml.indexOf('SEA Retail') < groupedHtml.indexOf('TSE Retail'));

const html = sandbox.renderDXTableDetail(
    { type: 'null' },
    {
        table: 'sea_ldy_retail',
        table_name: 'SEA LDY',
        inspection_date: '2026-08-31',
        source_date: '2026-08-30',
        offset_days: -1,
        retailers: [{
            retailer: 'Lowes',
            total: 197,
            total_null_count: 1,
            status: 'CRITICAL',
            batch_id: 'l_260830_191936',
            fields_detail: { sku: 1 }
        }]
    }
);
assert.ok(html.includes('검수일 2026-08-31'));
assert.ok(html.includes('데이터일 2026-08-30'));
assert.ok(html.includes('D-1'));
assert.ok(!html.includes('offset_days='));
assert.ok(!html.includes('batch_id:'));
assert.ok(html.includes("this.dataset.fields, 'sea_ldy_retail'"));

assert.ok(nullSource.includes("/^sea_(ref|ldy)_retail$/.test(tableParam)"));
assert.ok(nullSource.includes("IN ('MAIN', 'BSR')"));
assert.ok(nullSource.includes('data.source_date || date'));
assert.ok(nullSource.includes('data.actual_table'));
assert.ok(!nullSource.includes('· batch_id: ${data.batch_id'));

let youtubeDetailHtml = '';
let youtubeTableOptions = null;
const youtubeSandbox = {
    console,
    displayCountryFlagLabel: value => String(value),
    getDetailBody() { return { innerHTML: '' }; },
    getSelectedDate() { return '2026-08-31'; },
    isInlineMode() { return true; },
    buildDetailContainerHtml() { return '<div id="youtube-detail"></div>'; },
    renderDetailWithTable(options) { youtubeTableOptions = options; },
    ViewStack: {
        push(html) { youtubeDetailHtml = html; },
        getContainer() { return null; }
    }
};
vm.createContext(youtubeSandbox);
vm.runInContext(nullSource, youtubeSandbox);
assert.strictEqual(youtubeSandbox.getDefaultNullHistoryDays('tv_retail'), 3);
assert.strictEqual(youtubeSandbox.getDefaultNullHistoryDays('sea_ref_retail'), 3);
assert.strictEqual(youtubeSandbox.getDefaultNullHistoryDays('sea_ldy_retail'), 3);
assert.strictEqual(youtubeSandbox.getDefaultNullHistoryDays('tse_tv_retail'), 3);
assert.strictEqual(youtubeSandbox.getDefaultNullHistoryDays('youtube'), 1);
assert.strictEqual(youtubeSandbox.getDefaultFormatHistoryDays('tv_retail'), 3);
assert.ok(layer2CommonSource.includes('detailViewState.pageSize || 100'));
assert.ok(layer2CommonSource.includes('getPageSize() : 100'));
vm.runInContext(`
    modalState.tableParam = 'youtube';
    modalState.tableName = 'YouTube';
    modalState.retailer = 'Country Runs';
    modalState.days = 1;
`, youtubeSandbox);
youtubeSandbox.renderNullFieldDetailView('batch_id', {
    results: [{ id: 7, batch_id: null, null_fields: ['batch_id'] }],
    display_config: {
        batch_id: { select_columns: ['id', 'batch_id'] }
    },
    query_config: { batch_id: ['id', 'batch_id'] },
    actual_table: 'youtube_country_collection_runs',
    inspection_date: '2026-08-31',
    source_date: '2026-08-30',
    offset_days: -1,
    source_key: 'sea_youtube',
    date: '2026-08-31',
    date_column: 'collection_date'
}, true);
assert.ok(youtubeDetailHtml.includes('검수일 2026-08-31'));
assert.ok(youtubeDetailHtml.includes('데이터일 2026-08-30'));

vm.runInContext(`
    modalState.tableParam = 'sea_ldy_retail';
    modalState.tableName = 'SEA LDY';
    modalState.retailer = 'Lowes';
    modalState.days = 2;
`, youtubeSandbox);
youtubeSandbox.renderNullFieldDetailView('sku', {
    results: [
        {
            id: 41, item: 'item-1', sku: 'OLD-SKU',
            crawl_strdatetime: '2026-08-29 19:04:00'
        },
        {
            id: 42, item: 'item-1', sku: null,
            crawl_strdatetime: '2026-08-30 19:19:36', null_fields: ['sku']
        }
    ],
    display_config: {
        sku: { select_columns: ['id', 'item', 'sku', 'crawl_strdatetime'] }
    },
    query_config: { sku: ['id', 'item', 'sku', 'crawl_strdatetime'] },
    actual_table: 'public.ldy_retail_com',
    inspection_date: '2026-08-31',
    source_date: '2026-08-30',
    supports_day_history: true,
    history_days: 2,
    date: '2026-08-31',
    date_column: 'crawl_strdatetime'
}, true);
assert.ok(youtubeDetailHtml.includes('value="2"'));
assert.ok(youtubeDetailHtml.includes('2일치'));
assert.strictEqual(youtubeTableOptions.crawlDate, '2026-08-31');
assert.strictEqual(youtubeTableOptions.editableDate, '2026-08-30');

function makeReviewCell(rowId, columnName) {
    const classes = new Set();
    return {
        dataset: { rowId: String(rowId), col: columnName },
        isConnected: true,
        classList: {
            add(value) { classes.add(value); },
            remove(value) { classes.delete(value); },
            contains(value) { return classes.has(value); }
        }
    };
}

const commonSandbox = {
    console,
    window: { LAYER2: { section: 'null_validation' } },
    document: {
        addEventListener() {},
        getElementById() { return null; }
    },
    modalState: { days: 1, nullFieldsData: {} },
    esc(value) { return String(value); }
};
vm.createContext(commonSandbox);
vm.runInContext(layer2CommonSource, commonSandbox);
const productUrlColumns = commonSandbox.ensureProductUrlColumn(
    [{ key: 'item', label: 'item' }],
    ['id', 'item', 'product_url']
);
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(productUrlColumns)),
    [
        { key: 'item', label: 'item' },
        { key: 'product_url', label: 'URL', width: 80 }
    ]
);
assert.strictEqual(
    commonSandbox.ensureProductUrlColumn(
        productUrlColumns, ['id', 'item', 'product_url']
    ).filter(column => column.key === 'product_url').length,
    1
);
const normalizedDateColumns = commonSandbox.normalizeRetailSourceDateColumns([
    { key: 'crawl_strdatetime', label: '데이터일', width: 120 },
    { key: 'sku', label: 'sku', width: 120 }
]);
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(normalizedDateColumns)),
    [
        { key: 'crawl_strdatetime', label: 'crawl_strdatetime', width: 190 },
        { key: 'sku', label: 'sku', width: 120 }
    ]
);
const duplicateRetailKeys = vm.runInContext(
    "getAllColumns(DETAIL_COLUMNS.dup_default).map(column => column.key)",
    commonSandbox
);
assert.ok(Array.from(duplicateRetailKeys).includes('product_url'));
vm.runInContext(`
    detailViewState.type = 'null';
    detailViewState.editableCols = new Set();
    detailViewState.crawlDate = '2026-08-31';
    detailViewState.editableDate = '2026-08-30';
    detailViewState.dateColumn = 'crawl_strdatetime';
    modalState.days = 1;
`, commonSandbox);

const reviewCellHtml = commonSandbox.getCellHtml(
    { id: 42, ref_capacity: null, null_fields: ['ref_capacity'] },
    { key: 'ref_capacity' },
    'sea_ref_retail'
);
assert.ok(reviewCellHtml.includes('class="null-value"'));
assert.ok(reviewCellHtml.includes('data-row-id="42"'));
assert.ok(reviewCellHtml.includes('data-col="ref_capacity"'));
assert.ok(!reviewCellHtml.includes('data-editable="true"'));

vm.runInContext('modalState.days = 2;', commonSandbox);
const currentSourceCellHtml = commonSandbox.getCellHtml(
    {
        id: 43,
        sku: null,
        crawl_strdatetime: '2026-08-30 19:19:36',
        null_fields: ['sku']
    },
    { key: 'sku' },
    'sea_ldy_retail'
);
const previousSourceCellHtml = commonSandbox.getCellHtml(
    {
        id: 41,
        sku: 'OLD-SKU',
        crawl_strdatetime: '2026-08-29 19:04:00',
        null_fields: []
    },
    { key: 'sku' },
    'sea_ldy_retail'
);
assert.ok(currentSourceCellHtml.includes('data-row-id="43"'));
assert.ok(!previousSourceCellHtml.includes('data-row-id="41"'));

const currentDateCellHtml = commonSandbox.getCellHtml(
    { id: 43, crawl_strdatetime: '2026-08-30 19:19:36' },
    { key: 'crawl_strdatetime' },
    'sea_ldy_retail'
);
const historyDateCellHtml = commonSandbox.getCellHtml(
    { id: 41, crawl_strdatetime: '2026-08-29 19:04:00' },
    { key: 'crawl_strdatetime' },
    'sea_ldy_retail'
);
assert.ok(currentDateCellHtml.includes('2026-08-30'));
assert.ok(currentDateCellHtml.includes('수정 대상'));
assert.ok(!currentDateCellHtml.includes('19:19:36</span>'));
assert.ok(historyDateCellHtml.includes('2026-08-29'));
assert.ok(historyDateCellHtml.includes('비교 이력'));

const first = makeReviewCell(1, 'ref_capacity');
const second = makeReviewCell(2, 'ref_capacity');
const pending = makeReviewCell(3, 'ref_capacity');
pending.classList.add('cell-pending');
const fourth = makeReviewCell(4, 'ref_capacity');
const otherColumn = makeReviewCell(5, 'sku');
const rangeTable = {
    querySelectorAll() {
        return [first, second, pending, fourth, otherColumn];
    }
};
assert.deepStrictEqual(
    Array.from(commonSandbox._getNullReviewRangeCells(
        rangeTable, first, fourth
    )),
    [first, second, fourth]
);
assert.deepStrictEqual(
    Array.from(commonSandbox._getNullReviewRangeCells(
        rangeTable, first, otherColumn
    )),
    []
);
assert.ok(layer2CommonSource.includes("detailViewState.type === 'null'"));
assert.ok(layer2CommonSource.includes(
    "td.null-value[data-row-id][data-col]"
));
assert.ok(layer2CommonSource.includes('Shift+클릭으로 범위 선택'));
assert.ok(layer2CommonSource.includes('ensureProductUrlColumn'));

console.log('Layer2 SEA NULL frontend tests passed.');
