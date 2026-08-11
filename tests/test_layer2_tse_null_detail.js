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

async function main() {
    testDashboardDisplayOrderAndCanonicalCode();
    await testNullDetailUsesEncodedCanonicalParamsAndShowsErrors();
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
