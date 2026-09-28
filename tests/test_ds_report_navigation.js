const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function element() {
    const classes = new Set();
    return {
        value: '', innerHTML: '', textContent: '', hidden: false,
        style: {}, dataset: {}, children: [], attributes: {},
        classList: {
            add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
            contains(name) { return classes.has(name); },
            toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
        },
        setAttribute(key, value) { this.attributes[key] = value; },
        appendChild(child) { this.children.push(child); },
        addEventListener(name, fn) { this[name] = fn; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}
const ids = ['app-data', 'reportViewToggle', 'targetDate', 'reportContent', 'reportActions',
    'reportTableArea', 'fileTabSection',
    'totalRetailers', 'totalAnomalies', 'screenshotStatus', 'filledCause', 'reportCount',
    'closeBtn', 'closeBtnText', 'cancelCloseBtn', 'saveFileInfoBtn', 'saveFileInfoBtnText',
    'closedBanner', 'closedBannerText', 'reportOutputOverlay'];
const elements = Object.fromEntries(ids.map(id => [id, element()]));
elements['app-data'].dataset.userId = 'tester';
elements.targetDate.value = '2026-09-28';
elements.reportViewToggle.querySelectorAll = () => elements.reportViewToggle.children;
let retailerRows = [];
let anomalyTables = {};
let renderedContent = '';
// Model the rendered rows so toggles exercise DOM state, not just generated strings.
Object.defineProperty(elements.reportContent, 'innerHTML', {
    get: () => renderedContent,
    set(html) {
        renderedContent = html;
        retailerRows = [];
        anomalyTables = {};
        for (const id of Object.keys(elements)) {
            if (/^(anomalyDetails|anomalyCheck_|cause_|statusMemo_)/.test(id)) delete elements[id];
        }
        const sections = html.split('<tr class="retailer-row"').slice(1);
        for (const section of sections) {
            const row = element();
            row.dataset.retailer = section.match(/data-retailer="([^"]+)"/)[1];
            const toggle = element();
            toggle.attributes['aria-expanded'] = 'false';
            row.querySelector = selector => selector === '.report-retailer-toggle' ? toggle : null;
            retailerRows.push(row);
            const details = element();
            details.innerHTML = section.slice(section.indexOf('<tr class="anomaly-details"'));
            elements[section.match(/id="(anomalyDetails\d+)"/)[1]] = details;
            const table = element();
            const ids = [...section.matchAll(/id="anomalyCheck_(\d+)"/g)].map(match => match[1]);
            for (const id of ids) elements[`anomalyCheck_${id}`] = {...element(), id: `anomalyCheck_${id}`, checked: false};
            table.querySelectorAll = () => ids.map(id => elements[`anomalyCheck_${id}`]).filter(input => input?.checked);
            if (section.includes('class="anomaly-table"')) anomalyTables[row.dataset.retailer] = table;
            details.querySelector = selector => selector === '.anomaly-table' ? anomalyTables[row.dataset.retailer] || null : null;
            for (const match of section.matchAll(/id="cause_(\d+)"/g)) elements[`cause_${match[1]}`] = element();
            const memo = section.match(/id="(statusMemo_\d+)"[^>]*value="([^"]*)"/);
            if (memo) elements[memo[1]] = {...element(), value: memo[2]};
        }
    },
});
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
    cause_summary: {Amazon_JP: {'Existing cause': 1}},
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
        querySelector: selector => anomalyTables[selector.match(/data-retailer="([^"]+)"/)?.[1]] || null,
        querySelectorAll: selector => selector === '.retailer-row' ? retailerRows : [],
    },
    AppButton: {iconHtml: () => '', html: (label, action) => `<button onclick="${action}">${label}</button>`},
    esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    renderCaptureButton: () => 'capture', enableColumnResize() {},
    validateQueryDate: () => true, setPersistedDate() {}, checkRunningCaptures() {},
    loadFileTab: async () => { fileLoads++; }, showToast() {}, getCsrfToken: () => 'test',
    fetch: async (url, options) => {
        requests.push({url, options});
        if (options?.method === 'POST') {
            for (const update of JSON.parse(options.body).updates || []) {
                data.anomalies.find(row => row.id === update.anomaly_id).cause = update.cause;
            }
        }
        return response(url);
    },
};
vm.createContext(sandbox);
for (const file of ['index.js', 'report.js']) {
    vm.runInContext(fs.readFileSync('apps/ds/ds_layer4/static/ds_layer4/js/' + file, 'utf8'), sandbox);
}
const state = expression => vm.runInContext(expression, sandbox);

(async () => {
    assert.deepStrictEqual(elements.reportViewToggle.children.map(b => b.textContent), ['상세/현황', '파일']);
    await sandbox.loadReportList();
    assert(requests.at(-1).url.endsWith('view=detail'));
    assert(!requests.at(-1).url.includes('retailer=')); // Summary and report output keep the whole day.
    assert(elements.reportContent.innerHTML.includes('<td class="report-retailer-cell" onclick="openReportRetailerDetail(1)"'));
    assert(elements.reportContent.innerHTML.includes('saveStatusMemos') === false);
    assert(elements.reportActions.innerHTML.includes('saveStatusMemos'));
    assert.equal(retailerRows.length, 3);
    assert(retailerRows.every(row => !row.classList.contains('expanded')));
    assert.equal(state('expandedRetailers.size'), 0);
    assert(elements.reportContent.innerHTML.includes('Existing cause(1건)'));
    assert(elements.reportContent.innerHTML.includes('value="JP memo"'));
    assert(elements.reportContent.innerHTML.includes('colspan="7"'));

    const requestCount = requests.length;
    await sandbox.openReportRetailerDetail(1);
    assert.equal(requests.length, requestCount); // Opening a row keeps the existing inputs and list.
    assert.equal(state('currentReportView'), 'status');
    assert.equal(retailerRows.length, 3);
    assert(elements.anomalyDetails0.classList.contains('show'));
    assert(!elements.anomalyDetails1.classList.contains('show'));
    assert(elements.anomalyDetails0.innerHTML.includes('JP-SKU'));
    assert(!elements.anomalyDetails0.innerHTML.includes('DW-SKU'));
    assert(elements.anomalyDetails0.innerHTML.includes("saveCheckedAnomalies('Amazon_JP')"));
    assert.equal(retailerRows[0].querySelector('.report-retailer-toggle').attributes['aria-expanded'], 'true');
    assert.equal(elements.reportViewToggle.children[0].attributes['aria-pressed'], 'true');
    assert.equal(elements.totalRetailers.textContent, 3);

    elements.anomalyCheck_101.checked = true;
    elements.cause_101.value = 'New cause';
    elements.statusMemo_1.value = 'Unsaved memo';
    const firstCauseInput = elements.cause_101;
    await sandbox.openReportRetailerDetail(2);
    assert(elements.anomalyDetails0.classList.contains('show'));
    assert(elements.anomalyDetails1.classList.contains('show'));
    assert(elements.anomalyDetails1.innerHTML.includes('DW-SKU'));
    assert(elements.anomalyDetails1.innerHTML.includes('원인 미선택 1건'));
    await sandbox.openReportRetailerDetail(1);
    assert(!elements.anomalyDetails0.classList.contains('show'));
    assert(elements.anomalyDetails1.classList.contains('show'));
    assert.equal(retailerRows[0].querySelector('.report-retailer-toggle').attributes['aria-expanded'], 'false');
    await sandbox.openReportRetailerDetail(1);
    assert.strictEqual(elements.cause_101, firstCauseInput);
    assert.equal(elements.cause_101.value, 'New cause');
    assert.equal(elements.statusMemo_1.value, 'Unsaved memo');
    assert(elements.anomalyCheck_101.checked);
    assert.equal(requests.length, requestCount);

    await sandbox.saveCheckedAnomalies('Amazon_JP');
    await new Promise(resolve => setImmediate(resolve));
    const save = requests.find(r => r.options?.method === 'POST');
    assert.deepStrictEqual(JSON.parse(save.options.body).updates, [{anomaly_id: 101, cause: 'New cause'}]);
    assert.equal(state('expandedRetailers.size'), 2);
    assert(elements.anomalyDetails0.classList.contains('show'));
    assert(elements.anomalyDetails1.classList.contains('show'));
    assert(elements.anomalyDetails0.innerHTML.includes('selected>New cause'));

    await sandbox.setReportView('status');
    assert(elements.reportContent.innerHTML.includes('statusTable'));
    assert(elements.reportContent.innerHTML.includes('Danawa'));
    await sandbox.openReportRetailerDetail(3);
    assert(elements.anomalyDetails2.innerHTML.includes('저장된 이상치가 없습니다'));
    assert(elements.anomalyDetails2.classList.contains('show'));
    await sandbox.openReportRetailerDetail(999);
    assert.equal(state('expandedRetailers.size'), 3);

    data.is_closed = true;
    await sandbox.loadReportList();
    assert(elements.reportContent.innerHTML.includes('DW-SKU'));
    assert(!elements.reportContent.innerHTML.includes('anomalyCheck_'));
    assert(!elements.reportContent.innerHTML.includes('saveCheckedAnomalies'));
    assert.equal(elements.reportActions.innerHTML, '');
    assert(elements.reportContent.innerHTML.includes('colspan="6"'));
    assert(elements.anomalyDetails1.classList.contains('show'));
    await sandbox.openReportRetailerDetail(2);
    assert(!elements.anomalyDetails1.classList.contains('show'));
    await sandbox.openReportRetailerDetail(2);
    assert(elements.anomalyDetails1.classList.contains('show'));
    data.is_closed = false;

    elements.targetDate.value = '2026-09-29';
    await sandbox.loadReportList();
    assert.equal(state('expandedRetailers.size'), 0);
    assert(retailerRows.every(row => !row.classList.contains('expanded')));
    assert(requests.at(-1).url.endsWith('view=detail'));

    // Old requests must not replace a newer date or the File screen.
    const pending = [];
    sandbox.fetch = url => new Promise(resolve => pending.push({url, resolve}));
    const older = sandbox.loadReportList();
    elements.targetDate.value = '2026-09-30';
    const newer = sandbox.loadReportList();
    pending[1].resolve(response(pending[1].url));
    await newer;
    const latestContent = elements.reportContent.innerHTML;
    pending[0].resolve(response(pending[0].url));
    await older;
    assert.equal(elements.reportContent.innerHTML, latestContent);
    const oldDetail = sandbox.loadReportList();
    await sandbox.setReportView('file');
    pending[2].resolve(response(pending[2].url));
    await oldDetail;
    assert.equal(fileLoads, 1);
    assert.equal(elements.reportTableArea.style.display, 'none');
    assert.equal(elements.fileTabSection.style.display, 'block');
    assert.equal(state('currentReportView'), 'file');

    sandbox.fetch = async url => response(url);
    elements.targetDate.value = '2026-10-01';
    await sandbox.loadReportList();
    assert.equal(state('currentReportView'), 'file');
    assert.equal(elements.reportViewToggle.children[1].attributes['aria-pressed'], 'true');

    // A failed load can be retried without leaving the combined view.
    sandbox.fetch = async url => response(url);
    await sandbox.setReportView('status');
    sandbox.fetch = async () => { throw new Error('detail unavailable'); };
    await sandbox.loadReportList();
    assert(elements.reportContent.innerHTML.includes('detail unavailable'));
    assert.equal(state('currentReportView'), 'status');
    sandbox.fetch = async url => response(url);
    await sandbox.setReportView('status');
    assert(elements.reportContent.innerHTML.includes('statusTable'));
    assert.equal(retailerRows.length, 3);
    console.log('DS inline retailer details, draft preservation, save, date, file, closed state and async race tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
