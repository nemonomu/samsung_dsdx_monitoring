const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const dashboardSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js',
    'utf8'
);
const nullSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js',
    'utf8'
);
const layer2CommonSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js',
    'utf8'
);

function testDashboardDisplayOrderAndCanonicalCode() {
    const sandbox = { console };
    vm.createContext(sandbox);
    vm.runInContext(dashboardSource, sandbox);

    const data = {
        validation_types: [{
            type: 'null',
            tables: [
                { table: 'youtube', table_name: 'YouTube' },
                { table: 'tse_ref_retail', table_name: 'TSE REF' },
                { table: 'tv_retail', table_name: 'TV Retail' },
                { table: 'tse_ldy_retail', table_name: 'TSE LDY' },
                { table: 'tse_tv_retail', table_name: 'TSE TV' }
            ]
        }]
    };

    sandbox.prepareLayer2DisplayData(data);
    assert.deepStrictEqual(
        data.validation_types[0].tables.map(table => table.table),
        [
            'tv_retail',
            'tse_tv_retail',
            'tse_ref_retail',
            'tse_ldy_retail',
            'youtube'
        ]
    );
    assert.strictEqual(
        data.validation_types[0].tables[0].table_name,
        'SEA Retail'
    );

    const tseHtml = sandbox.renderDXTableDetail(
        { type: 'null' },
        {
            table: 'tse_tv_retail',
            table_name: 'TSE TV',
            retailers: [{
                retailer: 'Homepro',
                total: 300,
                total_null_count: 1,
                status: 'CRITICAL',
                fields_detail: { sku: 1 }
            }]
        }
    );
    assert.ok(tseHtml.includes("this.dataset.fields, 'tse_tv_retail'"));
}

async function testNullDetailUsesEncodedCanonicalParamsAndShowsErrors() {
    let requestedUrl = '';
    let nextResponse = null;
    const body = { innerHTML: '' };
    const sandbox = {
        console: { error() {} },
        URLSearchParams,
        fetch(url) {
            requestedUrl = url;
            return Promise.resolve(nextResponse);
        },
        getDetailBody() { return body; },
        getSelectedDate() { return '2026-08-11'; }
    };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    vm.runInContext(`
        modalState.tableParam = 'tse_tv_retail';
        modalState.retailer = 'Homepro & Branch';
        modalState.days = 1;
        modalState.nullFieldsData = { date: '2026-08-11' };
        globalThis.renderedDetail = null;
        renderNullFieldDetailView = function(fieldName, data, pushStack) {
            globalThis.renderedDetail = { fieldName, data, pushStack };
        };
    `, sandbox);

    nextResponse = {
        ok: true,
        status: 200,
        json() { return Promise.resolve({ results: [{ id: 7 }] }); }
    };
    await sandbox.showNullFieldDetail('sku');

    const parsed = new URL(requestedUrl, 'http://example.test');
    assert.strictEqual(parsed.pathname, '/dx/layer2/api/null-detail/');
    assert.strictEqual(parsed.searchParams.get('table'), 'tse_tv_retail');
    assert.strictEqual(parsed.searchParams.get('retailer'), 'Homepro & Branch');
    assert.strictEqual(parsed.searchParams.get('date'), '2026-08-11');
    assert.strictEqual(parsed.searchParams.get('column'), 'sku');
    assert.deepStrictEqual(
        JSON.parse(JSON.stringify(sandbox.renderedDetail.data.results)),
        [{ id: 7 }]
    );

    vm.runInContext('globalThis.renderedDetail = null;', sandbox);
    nextResponse = {
        ok: false,
        status: 500,
        json() { return Promise.resolve({ error: 'query failed' }); }
    };
    await sandbox.showNullFieldDetail('sku');

    assert.strictEqual(sandbox.renderedDetail, null);
    assert.ok(body.innerHTML.includes('상세 조회 실패'));
}

function makeTseDetailData() {
    return {
        results: [{
            id: 7,
            item: "TV'1 <script>",
            crawl_datetime: '2026-08-10T09:00:00+09:00',
            sku: null,
            product_url: 'https://example.test/tv-1'
        }],
        display_config: {
            sku: {
                select_columns: [
                    'id', 'crawl_datetime', 'item', 'sku', 'product_url'
                ]
            }
        },
        query_config: {
            sku: [
                'id', 'batch_id', 'crawl_datetime', 'item', 'sku',
                'product_url'
            ]
        },
        select_cols: [
            'id', 'batch_id', 'crawl_datetime', 'item', 'sku',
            'product_url'
        ],
        actual_table: 'dx_tse.dx_tse_tv_retail_com',
        query_retailer: "Home'pro",
        query_include_unassigned: true,
        supports_day_history: true,
        history_days: 3,
        date: '2026-08-10',
        date_column: 'crawl_datetime'
    };
}

function testTseCanonicalSqlEscapesLiteralsAndHtml() {
    const sandbox = { console };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    const data = makeTseDetailData();
    const query = sandbox._buildTseNullQuery(
        'sku', data, data.results, data.query_config.sku,
        data.date, data.history_days
    );
    const html = sandbox._buildTseNullQueryHtml(
        'sku', data, data.results, data.query_config.sku,
        data.date, data.history_days
    );

    assert.ok(query.includes('FROM dx_tse.dx_tse_tv_retail_com AS source'));
    assert.ok(query.includes('WITH latest_batches AS'));
    assert.ok(query.includes("'2026-08-08'"));
    assert.ok(query.includes("LOWER('Home''pro')"));
    assert.ok(query.includes("source.item IN ('TV''1 <script>')"));
    assert.ok(query.includes("source.country = 'TSE'"));
    assert.ok(query.includes('source.batch_id IS NOT DISTINCT FROM latest.batch_id'));
    assert.ok(!html.includes('<script>'));
    assert.ok(html.includes('&lt;script&gt;'));
    assert.ok(html.includes('3일치 최신 배치 조회 SQL'));

    const singleDayQuery = sandbox._buildTseNullQuery(
        'sku', data, data.results, data.query_config.sku,
        data.date, 1
    );
    assert.ok(singleDayQuery.includes('WITH latest_batch AS'));
    assert.ok(!singleDayQuery.includes('WITH latest_batches AS'));
    assert.ok(singleDayQuery.includes("source.country = 'TSE'"));
    assert.ok(singleDayQuery.includes('source.sku IS NULL'));
    assert.ok(singleDayQuery.includes("source.item IN ('TV''1 <script>')"));
}

function testTseItemNullUsesLatestBatchHistoryQuery() {
    const sandbox = { console };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    const data = makeTseDetailData();
    data.results = [{
        id: 8,
        item: null,
        crawl_datetime: '2026-08-10T09:00:00+09:00',
        product_url: 'https://example.test/missing-item'
    }];
    data.query_config.item = [
        'id', 'batch_id', 'crawl_datetime', 'item', 'product_url'
    ];

    const query = sandbox._buildTseNullQuery(
        'item', data, data.results, data.query_config.item,
        data.date, data.history_days
    );

    assert.ok(query.includes('WITH latest_batches AS'));
    assert.ok(query.includes('source.item IS NULL'));
    assert.ok(query.includes("source.country = 'TSE'"));
    assert.ok(!query.includes('WHERE source.id IN'));

    const mixedData = makeTseDetailData();
    mixedData.results.push({
        id: 8,
        item: null,
        crawl_datetime: '2026-08-10T09:01:00+09:00',
        sku: null,
        product_url: 'https://example.test/missing-item'
    });
    const singleDayQuery = sandbox._buildTseNullQuery(
        'sku', mixedData, mixedData.results, mixedData.query_config.sku,
        mixedData.date, 1
    );
    assert.ok(singleDayQuery.includes("source.item IN ('TV''1 <script>')"));
    assert.ok(singleDayQuery.includes('source.id IN (8)'));
}

function renderTseDetail(inlineMode) {
    let renderedWrapper = '';
    let tableOptions = null;
    const body = { innerHTML: '' };
    const sandbox = {
        console,
        getDetailBody() { return body; },
        getSelectedDate() { return '2026-08-10'; },
        isInlineMode() { return inlineMode; },
        buildDetailContainerHtml(options) { return options.itemQueryHtml; },
        renderDetailWithTable(options) { tableOptions = options; },
        ViewStack: {
            push(html) { renderedWrapper = html; },
            getContainer() { return body; }
        }
    };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    vm.runInContext(`
        modalState.tableParam = 'tse_tv_retail';
        modalState.tableName = 'TSE TV';
        modalState.retailer = 'Homepro';
        modalState.days = 3;
    `, sandbox);

    sandbox.renderNullFieldDetailView('sku', makeTseDetailData(), true);
    return {
        html: inlineMode ? renderedWrapper : body.innerHTML,
        tableOptions
    };
}

function testTseSqlAndDaysRenderInInlineAndDashboardViews() {
    const inline = renderTseDetail(true);
    const dashboard = renderTseDetail(false);

    assert.ok(inline.html.includes('id="detail-days"'));
    assert.ok(inline.html.includes('dx_tse.dx_tse_tv_retail_com'));
    assert.ok(inline.html.includes('3일치 최신 배치 조회 SQL'));
    assert.ok(dashboard.html.includes('id="detail-days"'));
    assert.ok(dashboard.html.includes('dx_tse.dx_tse_tv_retail_com'));
    assert.ok(dashboard.html.includes('3일치 최신 배치 조회 SQL'));
    assert.deepStrictEqual(
        JSON.parse(JSON.stringify(inline.tableOptions.config.map(col => col.key))),
        ['id', 'crawl_datetime', 'item', 'sku', 'product_url']
    );
    assert.deepStrictEqual(
        JSON.parse(JSON.stringify(inline.tableOptions.selectCols)),
        [
            'id', 'batch_id', 'crawl_datetime', 'item', 'sku',
            'product_url'
        ]
    );
    assert.strictEqual(
        dashboard.tableOptions.enableModalColumnSelector,
        true
    );
    assert.ok(layer2CommonSource.includes(
        'isInlineMode() || enableModalColumnSelector'
    ));
}

async function main() {
    testDashboardDisplayOrderAndCanonicalCode();
    await testNullDetailUsesEncodedCanonicalParamsAndShowsErrors();
    testTseCanonicalSqlEscapesLiteralsAndHtml();
    testTseItemNullUsesLatestBatchHistoryQuery();
    testTseSqlAndDaysRenderInInlineAndDashboardViews();
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
