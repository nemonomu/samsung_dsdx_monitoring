const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const indexSource = fs.readFileSync(
    'apps/ds/ds_layer4/static/ds_layer4/js/index.js', 'utf8'
);
const screenshotSource = fs.readFileSync(
    'apps/ds/ds_layer4/static/ds_layer4/js/screenshot.js', 'utf8'
);
const reportSource = fs.readFileSync(
    'apps/ds/ds_layer4/static/ds_layer4/js/report.js', 'utf8'
);
const screenshotCss = fs.readFileSync(
    'apps/ds/ds_layer4/static/ds_layer4/css/index.css', 'utf8'
);
const layer4Template = fs.readFileSync(
    'apps/ds/ds_layer4/templates/ds_layer4/index.html', 'utf8'
);

assert.ok(screenshotCss.includes(
    'grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);'
));
assert.ok(screenshotCss.includes('min-width: 220px;'));
assert.ok(screenshotCss.includes('z-index: 10010 !important;'));
assert.ok(!screenshotSource.includes('변경사항을 버릴까요?'));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/css/index.css' %}?v=20260903-4"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/screenshot.js' %}?v=20260903-4"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/index.js' %}?v=20260904-1"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/report.js' %}?v=20260904-1"
));

function fakeClassList() {
    const values = new Set();
    return {
        add(value) { values.add(value); },
        remove(value) { values.delete(value); },
        contains(value) { return values.has(value); },
        toggle(value, force) {
            if (force) values.add(value);
            else values.delete(value);
        }
    };
}

function fakeElement() {
    return {
        value: '',
        hidden: false,
        disabled: false,
        textContent: '',
        innerHTML: '',
        title: '',
        dataset: {},
        style: {},
        classList: fakeClassList(),
        children: [],
        focus() { this.focused = true; },
        addEventListener() {},
        appendChild(child) { this.children.push(child); },
        querySelectorAll() { return []; }
    };
}

const elements = {
    'app-data': Object.assign(fakeElement(), { dataset: { userId: 'tester' } }),
    reportViewToggle: fakeElement(),
    screenshotCauseEditor: fakeElement(),
    screenshotCauseSelect: fakeElement(),
    screenshotCustomCause: fakeElement(),
    screenshotCauseSaveBtn: fakeElement(),
    screenshotCauseReadonly: fakeElement(),
    screenshotDeleteBtn: fakeElement(),
    totalRetailers: fakeElement(),
    totalAnomalies: fakeElement(),
    screenshotStatus: fakeElement(),
    filledCause: fakeElement(),
    reportCount: fakeElement(),
    reportOutputOverlay: fakeElement()
};
const requests = [];

class FilterBar {
    render() { return this; }
}

const sandbox = {
    console,
    FilterBar,
    document: {
        getElementById(id) { return elements[id] || null; },
        createElement() { return fakeElement(); },
        addEventListener() {},
        cookie: ''
    },
    esc(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },
    fetch: async (url, options) => {
        requests.push({ url, options });
        return { json: async () => ({ success: true }) };
    },
    getCsrfToken() { return 'csrf'; },
    showToast() {},
    showConfirm: async () => true,
    renderReportTable() {},
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval
};

vm.createContext(sandbox);
vm.runInContext(indexSource, sandbox);
vm.runInContext(reportSource, sandbox);
vm.runInContext(screenshotSource, sandbox);

function setReportData(cause) {
    vm.runInContext(`
        reportData = {
            anomalies: [{
                id: 101,
                retailer: 'Danawa',
                screenshot_id: 501,
                cause: ${JSON.stringify(cause)}
            }],
            daily_reports: [],
            total_anomalies: 1,
            filled_cause: ${cause ? 1 : 0},
            captured_screenshots: 1
        };
        causeOptions = { Danawa: ['상품페이지 내 항목 부재', '크롤러 오류'] };
        isClosed = false;
        currentScreenshotAnomalyId = 101;
    `, sandbox);
}

assert.strictEqual(sandbox.normalizeReportCause('crawler_null_capture'), '');

setReportData('상품페이지 내 항목 부재');
sandbox.renderScreenshotCauseEditor(101);
assert.strictEqual(elements.screenshotCauseSelect.value, '상품페이지 내 항목 부재');
assert.strictEqual(elements.screenshotCustomCause.hidden, true);
assert.strictEqual(elements.screenshotCauseSaveBtn.disabled, true);

elements.screenshotCauseSelect.value = '크롤러 오류';
sandbox.handleScreenshotCauseChange();
assert.strictEqual(elements.screenshotCauseSaveBtn.disabled, false);
elements.screenshotCauseSelect.value = '상품페이지 내 항목 부재';
sandbox.handleScreenshotCauseChange();
assert.strictEqual(elements.screenshotCauseSaveBtn.disabled, false);

setReportData('직접 확인한 신규 원인');
sandbox.renderScreenshotCauseEditor(101);
assert.strictEqual(elements.screenshotCauseSelect.value, '__custom__');
assert.strictEqual(elements.screenshotCustomCause.value, '직접 확인한 신규 원인');
assert.strictEqual(elements.screenshotCustomCause.hidden, false);
assert.ok(sandbox.getCauseOptionsHtml('Danawa', '직접 확인한 신규 원인').includes(
    '>직접 확인한 신규 원인</option>'
));
assert.ok(!sandbox.getCauseOptionsHtml('Danawa', '직접 확인한 신규 원인').includes('기타:'));
assert.strictEqual(
    sandbox.getCheckedStatusMemo(
        { dataset: { causeSummary: '직판 아님(2건)' } },
        { dataset: { original: '일시품절(6건)' } }
    ),
    '직판 아님(2건)'
);
assert.strictEqual(
    sandbox.getCheckedStatusMemo(
        { dataset: { causeSummary: '' } },
        { dataset: { original: '직접 작성 메모' } }
    ),
    '직접 작성 메모'
);

setReportData('crawler_null_capture');
sandbox.renderScreenshotCauseEditor(101);
assert.strictEqual(elements.screenshotCauseSelect.value, '');

elements.screenshotCauseSelect.value = '__custom__';
elements.screenshotCustomCause.value = '재고 상황에 따른 판매자 변경';
sandbox.handleScreenshotCauseChange();
assert.strictEqual(elements.screenshotCauseSaveBtn.disabled, false);

(async () => {
    await sandbox.saveScreenshotCause();

    assert.strictEqual(requests.length, 1);
    assert.strictEqual(requests[0].url, '/ds/layer4/api/update/');
    const payload = JSON.parse(requests[0].options.body);
    assert.deepStrictEqual(payload, {
        anomaly_id: 101,
        cause: '재고 상황에 따른 판매자 변경',
        user_id: 'tester'
    });
    assert.strictEqual(
        vm.runInContext('reportData.anomalies[0].cause', sandbox),
        '재고 상황에 따른 판매자 변경'
    );

    vm.runInContext('isClosed = true', sandbox);
    sandbox.renderScreenshotCauseEditor(101);
    assert.strictEqual(elements.screenshotCauseSelect.hidden, true);
    assert.strictEqual(elements.screenshotCauseSaveBtn.hidden, true);
    assert.strictEqual(
        elements.screenshotCauseReadonly.textContent,
        '재고 상황에 따른 판매자 변경'
    );
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
