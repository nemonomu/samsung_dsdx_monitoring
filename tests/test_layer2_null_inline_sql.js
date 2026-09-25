const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js', 'utf8');
const cases = [
    ['tv_retail', 'SEA', 'public.tv_retail_com', 'crawl_datetime', 'Bestbuy'],
    ['sea_ref_retail', 'SEA', 'public.ref_retail_com', 'crawl_strdatetime', 'Bestbuy'],
    ['seda_tv_retail', 'SEDA', 'dx_seda.tv_retail_com', 'crawl_strdatetime', 'CasasBahia'],
    ['siel_tv_retail', 'SIEL', 'dx_siel.tv_retail_com', 'crawl_datetime', 'Amazon'],
    ['seg_tv_retail', 'SEG', 'dx_seg.tv_retail_com', 'crawl_datetime', 'OTTO'],
    ['sem_tv_retail', 'SEM', 'dx_sem.tv_retail_com', 'crawl_datetime', 'HomeDepot'],
    ['tse_tv_retail', 'TSE', 'dx_tse.tv_retail_com', 'crawl_datetime', 'Homepro'],
];

function setup(tableParam, country, table, dateColumn, retailer) {
    let html = '';
    const sandbox = {
        console,
        renderCountryFlagLabel: value => value,
        getDetailBody: () => ({innerHTML: ''}),
        getSelectedDate: () => '2026-09-22',
        isInlineMode: () => true,
        buildDetailContainerHtml: options => options.itemQueryHtml,
        renderDetailWithTable() {},
        ViewStack: {push(value) { html = value; }},
    };
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    vm.runInContext(`modalState.tableParam = ${JSON.stringify(tableParam)};
        modalState.tableName = ${JSON.stringify(country + ' TV')};
        modalState.retailer = ${JSON.stringify(country === 'SEDA' ? 'Casas Bahia' : retailer)};
        modalState.days = 3;`, sandbox);
    const data = {
        date: '2026-09-22', source_date: '2026-09-21',
        results: [{id: 7, item: "SKU'1 <x>", ref_capacity: null}],
        actual_table: table, date_column: dateColumn, query_retailer: retailer,
        supports_day_history: true, history_days: 3,
        display_config: {ref_capacity: {select_columns: ['id', 'item', 'ref_capacity']}},
        query_config: {ref_capacity: ['id', 'item', 'ref_capacity']},
    };
    sandbox.renderNullFieldDetailView('ref_capacity', data, true);
    return {sandbox, data, html};
}

for (const entry of cases) {
    const [tableParam, country, table, dateColumn, retailer] = entry;
    const {sandbox, data, html} = setup(...entry);
    const query = sandbox._buildNullRetailDisplayQuery(
        'ref_capacity', data, data.results, data.date, 3, retailer,
        country === 'TSE'
    );
    assert(query.includes(`FROM ${table}`), country);
    assert(query.includes(`${dateColumn} >= '2026-09-19'`), country);
    assert(query.includes(`${dateColumn} < '2026-09-22'`), country);
    assert(/item IN \(\s*'SKU''1 <x>'/.test(query), country);
    assert(query.includes("account_name = '" + retailer + "'"), country);
    assert(html.includes('class="null-detail-query-row"'), country);
    assert(html.includes('3일치 Item 조회 SQL'), country);
    assert(html.includes('onclick="copyToClipboard(this.parentElement.nextElementSibling)"'), country);
    assert(html.includes('FROM ' + table), country);
    assert(html.includes('&lt;x&gt;') && !html.includes('<x>'), country);
    assert.strictEqual((html.match(/class="query-box"/g) || []).length, 1, country);
    if (country === 'SEDA') assert(!query.includes("account_name = 'Casas Bahia'"));
    if (country === 'TSE') assert(query.includes("country = 'TSE'"));
}

for (const [entry, displayName, dbName] of [
    [cases[2], 'Casas Bahia', 'CasasBahia'],
    [cases[4], 'OTTO', 'OTTO'],
    [cases[6], 'Homepro', 'Homepro'],
]) {
    const {sandbox, data} = setup(...entry);
    data.query_retailer = displayName === 'Casas Bahia' ? displayName : displayName.toLowerCase();
    data.results[0].account_name = dbName;
    const query = sandbox._buildNullRetailDisplayQuery(
        'ref_capacity', data, data.results, data.date, 3, displayName,
        entry[1] === 'TSE'
    );
    assert(query.includes(`account_name = '${dbName}'`), entry[1]);
    assert(!query.includes(`account_name = '${data.query_retailer}'`), entry[1]);
}

const sedaWithoutAccount = setup(...cases[2]);
sedaWithoutAccount.data.query_retailer = 'Casas Bahia';
assert(sedaWithoutAccount.sandbox._buildNullRetailDisplayQuery(
    'ref_capacity', sedaWithoutAccount.data, sedaWithoutAccount.data.results,
    sedaWithoutAccount.data.date, 3, 'Casas Bahia', false
).includes("account_name = 'CasasBahia'"));

const tseWithoutAccount = setup(...cases[6]);
tseWithoutAccount.data.query_retailer = 'homepro';
tseWithoutAccount.data.retailer = 'Homepro';
assert(tseWithoutAccount.sandbox._buildNullRetailDisplayQuery(
    'ref_capacity', tseWithoutAccount.data, tseWithoutAccount.data.results,
    tseWithoutAccount.data.date, 3, 'Homepro', true
).includes("account_name = 'Homepro'"));

const {sandbox, data} = setup(...cases[1]);
data.results = [{id: 9, item: null, ref_capacity: null}];
data.batch_id = "b'2";
const idQuery = sandbox._buildNullRetailDisplayQuery(
    'ref_capacity', data, data.results, data.date, 1, 'Bestbuy', false
);
assert(idQuery.includes('id IN (9)'));
assert(idQuery.includes("batch_id = 'b''2'"));
assert(!idQuery.includes('item IN'));

console.log('Layer2 NULL detail SQL appears beside the item list for every retail country.');
