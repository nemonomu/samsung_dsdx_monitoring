const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function element() {
    const classes = new Set(['hidden']);
    return {
        value: '', innerHTML: '', textContent: '', dataset: {}, style: {}, disabled: false,
        classList: {add: key => classes.add(key), remove: key => classes.delete(key), contains: key => classes.has(key)},
        addEventListener() {}, focus() {}, select() {}, querySelectorAll: () => [],
    };
}

function setup() {
    const ids = ['targetDate', 'closeReportBtn', 'reportOutputContent', 'reportOutputOverlay',
        'reportLinkNotice', 'closedReportLink'];
    const elements = Object.fromEntries(ids.map(id => [id, element()]));
    elements.targetDate.value = '2026-10-01';
    const data = {success: true, is_closed: false, total_retailers: 1,
        daily_reports: [{retailer: 'Retailer', anomaly_total: 1, memo: 'Reviewed', file_size: 20}], anomalies: []};
    const posts = [], notices = [], copies = [];
    let refreshed = 0;
    const sandbox = {
        URL, console, isClosed: false, reportData: null,
        document: {getElementById: id => elements[id], execCommand: () => false},
        window: {location: {origin: 'https://monitor.example'}, isSecureContext: true},
        navigator: {clipboard: {writeText: async text => { copies.push(text); }}},
        showToast: (...args) => notices.push(args), showConfirm: async () => true,
        getCsrfToken: () => 'test', loadReportList: async () => { refreshed++; },
        updateCloseButton: state => { elements.closeReportBtn.disabled = state.is_closed; },
        fetch: async (url, options) => {
            if (options?.method === 'POST') {
                posts.push({url, body: JSON.parse(options.body)});
                return {ok: true, json: async () => ({success: true,
                    document_url: '/ds-share/20260212-0001%3A20261002-0001%3Atest-signature/'})};
            }
            return {ok: true, json: async () => url.includes('report-list') ? structuredClone(data) : {}};
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('apps/ds/ds_layer4/static/ds_layer4/js/report.js', 'utf8'), sandbox);
    sandbox.generateReportContent = () => '<h2>Title</h2><p>Reviewed report</p>';
    return {sandbox, elements, data, posts, notices, copies, refreshed: () => refreshed};
}

async function testCloseFlow() {
    let t = setup();
    await t.sandbox.openReportOutput();
    assert.equal(t.posts.length, 0, 'preview must not close');
    await Promise.all([t.sandbox.closeReport(), t.sandbox.closeReport()]);
    assert.equal(t.posts.length, 1, 'double click must send one request');
    assert.equal(t.posts[0].body.crawl_date, '2026-10-01');
    assert.equal(t.posts[0].body.content, '<p>Reviewed report</p>');
    assert.equal(t.copies[0], 'https://monitor.example/ds-share/20260212-0001%3A20261002-0001%3Atest-signature/');
    assert.equal(t.notices.at(-1)[0], '마감되었습니다. 보고서 공유 링크가 복사되었습니다. (24시간 유효)');
    assert(t.elements.closeReportBtn.disabled);
    assert(!t.elements.reportOutputOverlay.classList.contains('show'));
    assert.equal(t.refreshed(), 1);

    t = setup();
    t.sandbox.navigator.clipboard.writeText = async () => { throw Error('denied'); };
    await t.sandbox.openReportOutput();
    await t.sandbox.closeReport();
    assert(t.sandbox.isClosed, 'clipboard failure must not undo closing');
    assert.equal(t.notices.at(-1)[0], '마감되었습니다. 링크를 복사해주세요.');
    assert(!t.elements.reportLinkNotice.classList.contains('hidden'));
    t.sandbox.document.execCommand = () => true;
    await t.sandbox.copyClosedReportLink();
    assert.equal(t.notices.at(-1)[1], 'success', 'manual retry should work');

    for (const scenario of ['cancel', 'missing memo', 'missing retailer', 'changed date', 'closed']) {
        t = setup();
        if (scenario === 'cancel') t.sandbox.showConfirm = async () => false;
        if (scenario === 'missing memo') t.data.daily_reports[0].memo = '';
        if (scenario === 'missing retailer') t.data.total_retailers = 2;
        if (scenario === 'closed') t.data.is_closed = true;
        await t.sandbox.openReportOutput();
        if (scenario === 'changed date') t.elements.targetDate.value = '2026-10-02';
        await t.sandbox.closeReport();
        assert.equal(t.posts.length, 0, scenario);
        assert.equal(t.copies.length, 0, scenario);
    }

    t = setup();
    await t.sandbox.openReportOutput();
    t.sandbox.fetch = async () => ({json: async () => ({success: false, error: 'Rejected'})});
    await t.sandbox.closeReport();
    assert.equal(t.copies.length, 0);
    assert(!t.sandbox.isClosed);
    assert(!t.elements.closeReportBtn.disabled);
    assert(t.elements.reportOutputOverlay.classList.contains('show'));
}

async function testDocumentLink() {
    const elements = Object.fromEntries(['app-data', 'reportPopupTitle', 'reportDocTitle',
        'reportPopupBody', 'reportPopupOverlay'].map(id => [id, element()]));
    elements['app-data'].dataset.apiDetailUrl = '/api/ds/documents/detail/';
    const body = element();
    elements.reportPopupBody.querySelector = () => body;
    const events = {};
    const requests = [];
    const sandbox = {
        URLSearchParams, window: {location: {search: '?document_id=20261002-0001'}},
        esc: text => text,
        document: {getElementById: id => elements[id], createElement: element,
            addEventListener: (name, fn) => { events[name] = fn; }},
        CommonTable: class {render() { return this; }},
        ButtonBar: class {render() { return this; } toggleBar() {}},
        FilterBar: class {render() { return this; }},
        fetch: async url => { requests.push(url); return {json: async () => ({success: true,
            document: {title: '2026-10-01 DS 검수 보고서', content: '<p>Saved content</p>'}})}; },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('apps/ds/ds_document/static/ds_document/js/index.js', 'utf8'), sandbox);
    events.DOMContentLoaded();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests[0], '/api/ds/documents/detail/?document_id=20261002-0001');
    assert.equal(elements.reportDocTitle.textContent, '2026-10-01 DS 검수 보고서');
    assert.equal(body.innerHTML, '<p>Saved content</p>');
    assert(elements.reportPopupOverlay.classList.contains('active'));
}

(async () => {
    await testCloseFlow();
    await testDocumentLink();
    console.log('DS report close, copy fallback, validation and document deep link tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
