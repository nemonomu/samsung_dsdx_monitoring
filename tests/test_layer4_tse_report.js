const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer4', 'static',
        'dx_layer4', 'js', 'report.js'
    ),
    'utf8'
);
const templateSource = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer4', 'templates',
        'layer4', 'report.html'
    ),
    'utf8'
);

function element() {
    return {
        className: '',
        textContent: '',
        innerHTML: '',
        style: {},
        children: [],
        setAttribute(name, value) { this[name] = value; },
        replaceChildren(...children) { this.children = children; },
        appendChild(child) { this.children.push(child); return child; }
    };
}

const reportDetail = element();
const renderedRows = [];
const reportData = {
    success: true,
    date: '2026-08-10',
    collection_status: [],
    collection_issues: [],
    missing_keywords: [],
    excluded_items: [],
    type_summary: {
        null_check: { corrected: 4 },
        duplicate_check: { corrected: 1 },
        format_check: { normal: 1 },
        cross_field: { corrected: 2 }
    },
    grouped_details: {
        null_check: {
            'dx_tse.dx_tse_ldy_retail_com': [
                { retailer: 'Homepro', status: 'corrected', column_name: 'sku', item: 'A' },
                { retailer: 'Homepro', status: 'corrected', column_name: 'sku', item: 'B' },
                { retailer: 'Lazada', status: 'corrected', column_name: 'sku', item: 'B2' },
                { retailer: 'PowerBuy', status: 'corrected', column_name: 'sku', item: 'B3' }
            ],
            'public.ref_retail_com': [
                { retailer: 'Bestbuy', status: 'corrected', column_name: 'sku', item: 'R1' },
                { retailer: 'Lowes', status: 'corrected', column_name: 'sku', item: 'R2' }
            ],
            'dx_siel.dx_siel_ref_retail_com': [
                { retailer: 'Amazon', status: 'normal', column_name: 'sku', item: 'SR1' }
            ],
            'dx_seda.dx_seda_ldy_retail_com': [
                { retailer: 'Magalu', status: 'normal', column_name: 'sku', item: 'SD1' }
            ],
            'dx_seda.dx_seda_tv_retail_com': [
                { retailer: 'Casas Bahia', status: 'corrected', column_name: 'sku', item: 'ST1' }
            ],
            'dx_sem.dx_sem_tv_retail_com': [
                { retailer: 'Liverpool', status: 'corrected', column_name: 'sku', item: 'MT1' }
            ],
            'dx_sem.dx_sem_ref_retail_com': [
                { retailer: 'Liverpool', status: 'corrected', column_name: 'sku', item: 'MR1' }
            ],
            'dx_sem.dx_sem_ldy_retail_com': [
                { retailer: 'Liverpool', status: 'corrected', column_name: 'sku', item: 'ML1' }
            ],
            'dx_seg.dx_seg_ref_retail_com': [
                ...['ref_capacity', 'sku'].flatMap(column_name =>
                    ['R1', 'R2', 'R3', 'R4'].map(item => ({
                        retailer: 'OTTO', status: 'normal', column_name, item
                    }))
                )
            ],
            'dx_seg.dx_seg_ldy_retail_com': [
                { retailer: 'Mediamarkt', status: 'normal', column_name: 'ldy_capacity', item: 'L1' },
                ...['L2', 'L3', 'L4', 'L5', 'L6'].map(item => ({
                    retailer: 'Mediamarkt', status: 'normal', column_name: 'ldy_loading_type', item
                })),
                ...['O1', 'O2', 'O3'].map(item => ({
                    retailer: 'OTTO', status: 'normal', column_name: 'ldy_loading_type', item
                })),
                { retailer: 'OTTO', status: 'normal', column_name: 'sku', item: 'O3' }
            ]
        },
        duplicate_check: {
            'dx_tse.dx_tse_ref_retail_com': [
                { retailer: 'Homepro', status: 'corrected', item: 'C', memo: '확인' }
            ],
            'dx_seg_ref_retail_com': [
                { retailer: 'Mediamarkt', status: 'corrected', item: 'G1', memo: '중복 삭제' }
            ]
        },
        format_check: {
            'dx_tse.dx_tse_tv_retail_com': [
                { retailer: 'Homepro', status: 'normal', column_name: 'savings', item: 'D', reason: '확인' }
            ],
            'dx_seg_tv_retail_com': [
                { retailer: 'Amazon', status: 'corrected', column_name: 'sku', item: 'G2' }
            ]
        },
        cross_field: {
            'dx_tse.dx_tse_tv_retail_com': [
                { retailer: 'Homepro', status: 'corrected', item: 'E', detail_code: 'price', rule_name: '가격 일치' }
            ],
            'public.ldy_retail_com': [
                { retailer: 'Lowes', status: 'corrected', item: 'L1', detail_code: 'price', rule_name: '가격 일치' }
            ],
            'dx_siel.dx_siel_ldy_retail_com': [
                { retailer: 'Flipkart', status: 'normal', item: 'SL1', detail_code: 'price', rule_name: '가격 일치' }
            ],
            'dx_seg.dx_seg_ref_retail_com': [
                { retailer: 'OTTO', status: 'normal', item: 'R1', detail_code: 'price', rule_name: '가격 일치' }
            ]
        }
    }
};

// The same retailer/item in SEA and SEM must remain separate in every section.
for (const type of ['null_check', 'format_check', 'duplicate_check', 'cross_field']) {
    for (const product of ['ref', 'ldy']) {
        for (const table of [`public.${product}_retail_com`, `dx_sem.dx_sem_${product}_retail_com`]) {
            const rows = reportData.grouped_details[type][table] || [];
            rows.push({ retailer: 'HomeDepot', status: 'corrected', item: 'HD1',
                column_name: 'sku', detail_code: 'price', rule_name: '가격 일치', memo: '중복 삭제' });
            reportData.grouped_details[type][table] = rows;
        }
    }
}

reportData.grouped_details.format_check['public.ref_retail_com'] = [
    ...(reportData.grouped_details.format_check['public.ref_retail_com'] || []),
    {retailer:'Lowes',status:'error',column_name:'pick_up_availability',item:'ERROR-1',reason:'HTML 수집 오류'}
];
reportData.grouped_details.null_check['dx_seuk.dx_seuk_tv_retail_com'] = [
    {retailer: 'Amazon', status: 'normal', column_name: 'star_rating', item: 'UK1'}
];
reportData.grouped_details.cross_field['dx_seuk.dx_seuk_tv_retail_com'] = [
    {retailer: 'Argos', status: 'corrected', column_name: 'savings', item: 'UK2'}
];

const sandbox = {
    console,
    AbortController,
    document: {
        getElementById(id) { return id === 'report-detail' ? reportDetail : element(); },
        createElement() { return element(); }
    },
    L4: {
        _sectionHandler: {},
        TYPE_NAMES: {
            null_check: 'NULL 검증',
            duplicate_check: '중복 검증',
            format_check: '형식 검증',
            cross_field: '크로스필드 검증',
            field_missing: '누락필드 검증'
        },
        CHECK_SECTION_NAMES: {},
        escapeHtml(value) { return String(value == null ? '' : value); }
    },
    CommonTable: function() {
        this.render = function() {};
        this.renderBody = function(data, renderRow) {
            data.forEach((item, index) => renderedRows.push(renderRow(item, index)));
        };
    },
    getSelectedDate() { return '2026-08-10'; },
    fetch() {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(reportData) });
    },
    showToast() {},
    getCsrfToken() { return 'token'; }
};
sandbox.window = sandbox;

vm.createContext(sandbox);
vm.runInContext(source, sandbox);
sandbox.L4._sectionHandler.report();

setImmediate(() => {
    const html = renderedRows.join('\n');
    assert(html.includes('SEA LOWES REF 오류 확정 1건'));
    assert(html.includes('pick_up_availability 오류 확정: HTML 수집 오류'));
    for (const type of ['NULL 검증', '형식 검증', '중복 검증', '크로스필드 검증']) {
        const summary = renderedRows.find(row => row.includes(type));
        for (const product of ['REF', 'LDY']) {
            assert(summary.includes(`SEA HOMEDEPOT ${product} 수정 1건`), type + product);
            assert(summary.includes(`SEM HomeDepot ${product} 수정 1건`), type + product);
        }
    }
    assert(html.includes('TSE HOMEPRO TV'));
    assert(html.includes('TSE HOMEPRO REF'));
    assert(html.includes('TSE HOMEPRO LDY'));
    assert(!html.includes('TSE LAZADA LDY'));
    assert(!html.includes('TSE POWERBUY LDY'));
    assert(html.includes('SEA BESTBUY REF'));
    assert(html.includes('SEA LOWES REF'));
    assert(html.includes('SEA LOWES LDY'));
    assert(html.includes('SIEL AMAZON REF'));
    assert(html.includes('SIEL FLIPKART LDY'));
    assert(html.includes('SEDA MAGALU LDY'));
    assert(html.includes('SEDA CASAS BAHIA TV'));
    assert(html.includes('SEM Liverpool TV'));
    assert(html.includes('SEM Liverpool REF'));
    assert(html.includes('SEM Liverpool LDY'));
    const nullSummary = renderedRows.find(row => row.includes('NULL 검증'));
    assert(nullSummary.includes('SEG OTTO REF 확인 8건'));
    assert(nullSummary.includes('SEG MEDIAMARKT LDY 확인 6건'));
    assert(nullSummary.includes('SEG OTTO LDY 확인 4건'));
    assert(nullSummary.includes('SEDA MAGALU LDY 확인 1건'));
    assert(nullSummary.includes('SEDA CASAS BAHIA TV 수정 1건'));
    assert(nullSummary.includes('SEUK Amazon TV 확인 1건'));
    const crossSummary = renderedRows.find(row => row.includes('크로스필드 검증'));
    assert(crossSummary.includes('SEG OTTO REF 확인 1건'));
    assert(crossSummary.includes('SEUK Argos TV 수정 1건'));
    assert(renderedRows.find(row => row.includes('형식 검증')).includes('SEG AMAZON TV 수정 1건'));
    assert(renderedRows.find(row => row.includes('중복 검증')).includes('SEG MEDIAMARKT REF 수정 1건'));
    const detailRows = renderedRows.filter(row => !row.includes('확인 8건') && !row.includes('확인 1건'));
    for (const label of ['SEG OTTO REF', 'SEG MEDIAMARKT LDY', 'SEG OTTO LDY', 'SEG AMAZON TV', 'SEG MEDIAMARKT REF']) {
        assert(detailRows.some(row => row.includes('>' + label + '</td>')), label);
    }
    assert(!html.includes('dx_seg'));
    assert(!html.includes('dx_tse.dx_tse_tv_retail_com'));
    assert(!html.includes('dx_tse.dx_tse_ref_retail_com'));
    assert(!html.includes('dx_tse.dx_tse_ldy_retail_com'));
    assert(!html.includes('public.ref_retail_com'));
    assert(!html.includes('public.ldy_retail_com'));
    assert(!html.includes('dx_siel.dx_siel_ref_retail_com'));
    assert(!html.includes('dx_siel.dx_siel_ldy_retail_com'));
    assert(!html.includes('dx_seda.dx_seda_ldy_retail_com'));
    assert(!html.includes('dx_seda.dx_seda_tv_retail_com'));
    assert(!html.includes('dx_sem.dx_sem_tv_retail_com'));
    assert(!html.includes('dx_sem.dx_sem_ref_retail_com'));
    assert(!html.includes('dx_sem.dx_sem_ldy_retail_com'));
    assert(!html.includes('>Retail 수정'));
    assert(!html.includes('dx_seuk.dx_seuk_tv_retail_com'));
    assert(/dx_layer4\/js\/report\.js' %\}\?v=\d{8}-[a-z-]+/.test(templateSource));
    console.log('Layer 4 retail report label tests passed');
});

async function testReportLoadFailureAndDateChange() {
    const view = element();
    const requests = [];
    let date = '2026-11-23';
    const context = {
        ...sandbox,
        document: {getElementById: () => view, createElement: element},
        L4: {...sandbox.L4, _sectionHandler: {}},
        getSelectedDate: () => date,
        fetch: (url, {signal}) => new Promise(resolve => requests.push({url, signal, resolve}))
    };
    context.window = context;
    vm.runInNewContext(source, context);
    const load = context.L4._sectionHandler.report;

    const initial = load();
    assert.equal(view.children[0].role, 'status');
    assert(view.children[0].children[0].textContent.includes('조회 중'));
    await load();
    assert.equal(requests.length, 1);
    requests[0].resolve({ok: false, status: 504, json: async () => { throw new SyntaxError(); }});
    await initial;
    assert.equal(view.children[0].role, 'alert');
    assert(view.children[0].children[0].textContent.includes('HTTP 504'));

    const retry = view.children[0].children[1].onclick();
    date = '2026-11-24';
    const nextDay = load();
    assert(requests[1].signal.aborted);
    requests[1].resolve({ok: true, json: async () => reportData});
    await retry;
    assert(view.children[0].children[0].textContent.includes('2026-11-24'));
    requests[2].resolve({ok: true, json: async () => ({success: true, date})});
    await nextDay;
    assert(view.innerHTML.includes('해당 날짜에 검수 기록이 없습니다.'));

    const refresh = load();
    assert(requests[3].url.endsWith('&refresh=1'));
    requests[3].resolve({ok: true, json: async () => ({success: true, date})});
    await refresh;
    console.log('Layer 4 report loading, retry, and request ordering tests passed');
}

testReportLoadFailureAndDateChange().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
