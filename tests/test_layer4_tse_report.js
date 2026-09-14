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

const sandbox = {
    console,
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
        return Promise.resolve({ json: () => Promise.resolve(reportData) });
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
    const crossSummary = renderedRows.find(row => row.includes('크로스필드 검증'));
    assert(crossSummary.includes('SEG OTTO REF 확인 1건'));
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
    assert(templateSource.includes("dx_layer4/js/report.js' %}?v=9"));
    console.log('Layer 4 retail report label tests passed');
});
