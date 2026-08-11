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
        null_check: { corrected: 2 },
        duplicate_check: { corrected: 1 },
        format_check: { normal: 1 },
        cross_field: { corrected: 1 }
    },
    grouped_details: {
        null_check: {
            'dx_tse.dx_tse_ldy_retail_com': [
                { retailer: 'Homepro', status: 'corrected', column_name: 'sku', item: 'A' },
                { retailer: 'Homepro', status: 'corrected', column_name: 'sku', item: 'B' }
            ]
        },
        duplicate_check: {
            'dx_tse.dx_tse_ref_retail_com': [
                { retailer: 'Homepro', status: 'corrected', item: 'C', memo: '확인' }
            ]
        },
        format_check: {
            'dx_tse.dx_tse_tv_retail_com': [
                { retailer: 'Homepro', status: 'normal', column_name: 'savings', item: 'D', reason: '확인' }
            ]
        },
        cross_field: {
            'dx_tse.dx_tse_tv_retail_com': [
                { retailer: 'Homepro', status: 'corrected', item: 'E', detail_code: 'price', rule_name: '가격 일치' }
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
    assert(html.includes('HOMEPRO TV'));
    assert(html.includes('HOMEPRO REF'));
    assert(html.includes('HOMEPRO LDY'));
    assert(!html.includes('dx_tse.dx_tse_tv_retail_com'));
    assert(!html.includes('dx_tse.dx_tse_ref_retail_com'));
    assert(!html.includes('dx_tse.dx_tse_ldy_retail_com'));
    console.log('Layer 4 TSE report label tests passed');
});
