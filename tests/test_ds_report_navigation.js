const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function element() {
    return {
        value: '', innerHTML: '', textContent: '', hidden: false,
        style: {}, dataset: {}, children: [], attributes: {},
        classList: {add() {}, remove() {}},
        setAttribute(key, value) { this.attributes[key] = value; },
        appendChild(child) { this.children.push(child); },
        addEventListener(name, fn) { this[name] = fn; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}
const ids = ['app-data', 'reportViewToggle', 'targetDate', 'reportContent', 'reportActions',
    'reportDetailNav', 'reportDetailRetailer', 'reportTableArea', 'fileTabSection',
    'totalRetailers', 'totalAnomalies', 'screenshotStatus', 'filledCause', 'reportCount',
    'closeBtn', 'closeBtnText', 'cancelCloseBtn', 'saveFileInfoBtn', 'saveFileInfoBtnText',
    'closedBanner', 'closedBannerText', 'reportOutputOverlay'];
const elements = Object.fromEntries(ids.map(id => [id, element()]));
elements['app-data'].dataset.userId = 'tester';
elements.targetDate.value = '2026-09-28';
elements.reportViewToggle.querySelectorAll = () => elements.reportViewToggle.children;
let selected = [];
const anomalyTable = {querySelectorAll: () => selected};
elements.reportContent.querySelector = selector =>
    selector === '.anomaly-table' && elements.reportContent.innerHTML.includes('class="anomaly-table"')
        ? anomalyTable : null;
const data = {
    success: true, is_closed: false, total_retailers: 3, total_anomalies: 2,
    daily_reports: [
        {id: 1, retailer: 'Amazon_JP', anomaly_total: 1, total_count: 82, memo: 'JP memo'},
        {id: 2, retailer: 'Danawa', anomaly_total: 1, total_count: 81, memo: 'DW memo'},
        {id: 3, retailer: 'CentreCom', anomaly_total: 0, total_count: 32, memo: 'OK'},
    ],
    anomalies: [
        {id: 101, retailer: 'Amazon_JP', retailersku: 'JP-SKU', cause: 'Existing cause'},
        {id: 202, retailer: 'Danawa', retailersku: 'DW-SKU', cause: null},
    ],
    cause_options: {Amazon_JP: ['Existing cause', 'New cause']},
};
const requests = [];
function response(url) {
    return {json: async () => ({...data, anomalies: url.includes('view=detail') ? data.anomalies : []})};
}
let fileLoads = 0;
const sandbox = {
    console: {error() {}},
    FilterBar: class {render() { return this; }},
    document: {
        getElementById: id => elements[id] || null,
        createElement: () => element(), addEventListener() {},
        querySelector: () => anomalyTable, querySelectorAll: () => [],
    },
    AppButton: {iconHtml: () => '', html: (label, action) => `<button onclick="${action}">${label}</button>`},
    esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    renderCaptureButton: () => 'capture', enableColumnResize() {},
    validateQueryDate: () => true, setPersistedDate() {}, checkRunningCaptures() {},
    loadFileTab: async () => { fileLoads++; }, showToast() {}, getCsrfToken: () => 'test',
    fetch: async (url, options) => { requests.push({url, options}); return response(url); },
};
vm.createContext(sandbox);
for (const file of ['index.js', 'report.js']) {
    vm.runInContext(fs.readFileSync('apps/ds/ds_layer4/static/ds_layer4/js/' + file, 'utf8'), sandbox);
}
const state = expression => vm.runInContext(expression, sandbox);

(async () => {
    assert.deepStrictEqual(elements.reportViewToggle.children.map(b => b.textContent), ['상세/현황', '파일']);
    await sandbox.loadReportList();
    assert(requests.at(-1).url.endsWith('view=status'));
    assert(elements.reportContent.innerHTML.includes('openReportRetailerDetail(1)'));
    assert(elements.reportContent.innerHTML.includes('saveStatusMemos') === false);
    assert(elements.reportActions.innerHTML.includes('saveStatusMemos'));
    assert(elements.reportDetailNav.hidden);

    await sandbox.openReportRetailerDetail(1);
    assert(requests.at(-1).url.endsWith('view=detail'));
    assert(!requests.at(-1).url.includes('retailer=')); // Summary and report output keep the whole day.
    assert.equal(elements.reportDetailRetailer.textContent, 'Amazon_JP');
    assert.equal(elements.reportDetailNav.hidden, false);
    assert(elements.reportContent.innerHTML.includes('JP-SKU'));
    assert(!elements.reportContent.innerHTML.includes('DW-SKU'));
    assert(elements.reportContent.innerHTML.includes("saveCheckedAnomalies('Amazon_JP')"));
    assert.equal(elements.reportViewToggle.children[0].attributes['aria-pressed'], 'true');
    assert.equal(elements.totalRetailers.textContent, 3);

    selected = [{id: 'anomalyCheck_101', checked: true}];
    elements.cause_101 = {...element(), value: 'New cause'};
    await sandbox.saveCheckedAnomalies('Amazon_JP');
    await new Promise(resolve => setImmediate(resolve));
    const save = requests.find(r => r.options?.method === 'POST');
    assert.deepStrictEqual(JSON.parse(save.options.body).updates, [{anomaly_id: 101, cause: 'New cause'}]);
    assert.equal(state('currentReportRetailer'), 'Amazon_JP');
    assert(elements.reportContent.innerHTML.includes('JP-SKU'));
    selected = [];

    await sandbox.setReportView('status');
    assert(elements.reportContent.innerHTML.includes('statusTable'));
    assert(elements.reportContent.innerHTML.includes('Danawa'));
    assert(elements.reportDetailNav.hidden);
    await sandbox.openReportRetailerDetail(3);
    assert(elements.reportContent.innerHTML.includes('저장된 이상치가 없습니다'));
    assert(!elements.reportDetailNav.hidden);

    await sandbox.openReportRetailerDetail(2);
    data.is_closed = true;
    await sandbox.loadReportList();
    assert(elements.reportContent.innerHTML.includes('DW-SKU'));
    assert(!elements.reportContent.innerHTML.includes('anomalyCheck_'));
    assert(!elements.reportContent.innerHTML.includes('saveCheckedAnomalies'));
    data.is_closed = false;

    elements.targetDate.value = '2026-09-29';
    await sandbox.loadReportList();
    assert.equal(state('currentReportRetailer'), null);
    assert(requests.at(-1).url.endsWith('view=status'));

    // Detail responses arriving after Back or File must not replace the newer screen.
    const pending = [];
    sandbox.fetch = url => new Promise(resolve => pending.push({url, resolve}));
    const detail = sandbox.openReportRetailerDetail(1);
    const back = sandbox.setReportView('status');
    pending[1].resolve(response(pending[1].url));
    await back;
    pending[0].resolve(response(pending[0].url));
    await detail;
    assert(elements.reportContent.innerHTML.includes('statusTable'));
    const oldDetail = sandbox.openReportRetailerDetail(2);
    await sandbox.setReportView('file');
    pending[2].resolve(response(pending[2].url));
    await oldDetail;
    assert.equal(fileLoads, 1);
    assert.equal(elements.reportTableArea.style.display, 'none');
    assert.equal(elements.fileTabSection.style.display, 'block');
    assert.equal(state('currentReportView'), 'file');

    sandbox.fetch = async url => response(url);
    elements.targetDate.value = '2026-09-30';
    await sandbox.loadReportList();
    assert.equal(state('currentReportView'), 'file');
    assert.equal(elements.reportViewToggle.children[1].attributes['aria-pressed'], 'true');

    // A failed detail request still leaves a working way back to the overview.
    sandbox.fetch = async url => response(url);
    await sandbox.setReportView('status');
    sandbox.fetch = async () => { throw new Error('detail unavailable'); };
    await sandbox.openReportRetailerDetail(1);
    assert(elements.reportContent.innerHTML.includes('detail unavailable'));
    assert(!elements.reportDetailNav.hidden);
    sandbox.fetch = async url => response(url);
    await sandbox.setReportView('status');
    assert(elements.reportContent.innerHTML.includes('statusTable'));
    console.log('DS overview/detail navigation, save, date, file, closed state and async race tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
