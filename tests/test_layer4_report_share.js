const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname,
    '../apps/dx/dx_layer4/static/dx_layer4/js/report.js'), 'utf8');

function setup({clipboard = 'success', fallback = true, saveFails = false, shareFails = false} = {}) {
    const elements = {};
    for (const id of ['saveReportBtn', 'report-detail', 'reportSharePanel',
        'reportShareMessage', 'reportShareUrl', 'reportShareRetry']) {
        elements[id] = {disabled: false, hidden: true, value: '', textContent: '',
            innerHTML: '<p>Saved report</p>', focus() {}, select() {}, setSelectionRange() {}};
    }
    const calls = [], copies = [], toasts = [];
    const state = {saveFails, shareFails};
    const context = {
        window: {location: {origin: 'http://example.test'}},
        document: {
            getElementById: id => elements[id],
            execCommand(command) {
                assert.equal(command, 'copy');
                if (fallback) copies.push(elements.reportShareUrl.value);
                return fallback;
            }
        },
        navigator: clipboard === 'missing' ? {} : {clipboard: {async writeText(text) {
            if (clipboard === 'reject') throw new Error('denied');
            copies.push(text);
        }}},
        L4: {_sectionHandler: {}},
        getSelectedDate: () => '2026-10-20',
        getCsrfToken: () => 'csrf',
        showToast: (text, type) => toasts.push({text, type}),
        fetch: async (url, options) => {
            const body = JSON.parse(options.body);
            calls.push({url, body});
            assert.equal(options.headers['X-CSRFToken'], 'csrf');
            if (url.endsWith('/create/')) {
                return {ok: !state.saveFails, json: async () => state.saveFails
                    ? {success: false, error: 'Save failed'}
                    : {success: true, document_id: 'saved-document'}};
            }
            assert.equal(url, '/api/dx/documents/share-token/');
            return {ok: !state.shareFails, json: async () => state.shareFails
                ? {success: false, error: 'Share failed'}
                : {success: true, token: 'signed:token/+'}};
        }
    };
    vm.runInNewContext(source, context);
    return {context, elements, calls, copies, toasts, state};
}

(async () => {
    const expected = 'http://example.test/dx-share/signed%3Atoken%2F%2B/';
    for (const clipboard of ['success', 'missing', 'reject']) {
        const t = setup({clipboard});
        await t.context.window.saveReportToDocument();
        assert.equal(t.calls.length, 2);
        assert.equal(t.calls[0].body.crawl_date, '2026-10-20');
        assert.equal(t.calls[1].body.document_id, 'saved-document');
        assert.equal(t.calls[1].body.category_id, t.calls[0].body.category_id);
        assert.equal(t.calls[1].body.memo, '2026-10-20 보고서 공유');
        assert.equal(t.copies[0], expected);
        assert.equal(t.elements.reportSharePanel.hidden, false);
        assert.equal(t.elements.saveReportBtn.disabled, false);
        await t.context.window.retryReportShare();
        assert.equal(t.calls.length, 2, 'copy retry must reuse the same token');
        assert.equal(t.copies.length, 2);
    }
    const denied = setup({clipboard: 'reject', fallback: false});
    await denied.context.window.saveReportToDocument();
    assert.equal(denied.copies.length, 0);
    assert.equal(denied.elements.reportShareUrl.value, expected);
    assert(denied.toasts.every(t => t.type !== 'success'));
    assert(denied.elements.reportShareMessage.textContent.includes('자동 복사가 차단'));

    const failedSave = setup({saveFails: true});
    await failedSave.context.window.saveReportToDocument();
    assert.equal(failedSave.calls.length, 1, 'failed save must never create a share');
    assert.equal(failedSave.elements.reportSharePanel.hidden, true);

    const failedShare = setup({shareFails: true});
    await failedShare.context.window.saveReportToDocument();
    assert(failedShare.elements.reportShareMessage.textContent.includes('보고서 저장 완료'));
    failedShare.state.shareFails = false;
    await failedShare.context.window.retryReportShare();
    assert.equal(failedShare.calls.filter(c => c.url.endsWith('/create/')).length, 1);
    assert.equal(failedShare.copies[0], expected);

    const concurrent = setup();
    await Promise.all([concurrent.context.window.saveReportToDocument(),
        concurrent.context.window.saveReportToDocument()]);
    assert.equal(concurrent.calls.length, 2, 'double click must save and share only once');
    console.log('PASS: saved document sharing, memo/date, clipboard and HTTP fallback, manual copy, retry, failure separation and double clicks.');
})().catch(error => { console.error(error); process.exitCode = 1; });
