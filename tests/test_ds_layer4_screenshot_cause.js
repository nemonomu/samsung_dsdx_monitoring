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

assert.match(screenshotCss, /\.screenshot-modal-header\s*\{\s*display: flex;\s*flex-wrap: wrap;/);
assert.ok(screenshotCss.includes('min-width: 220px;'));
assert.ok(screenshotCss.includes('z-index: 10010 !important;'));
assert.ok(!screenshotSource.includes('변경사항을 버릴까요?'));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/css/index.css' %}?v=20260923-5"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/screenshot.js' %}?v=20260923-4"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/index.js' %}?v=20260923-1"
));
assert.ok(layer4Template.includes(
    "{% static 'ds_layer4/js/report.js' %}?v=20260923-5"
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
        querySelector() { return null; },
        querySelectorAll() { return []; }
    };
}

const elements = {
    'app-data': Object.assign(fakeElement(), { dataset: { userId: 'tester' } }),
    reportViewToggle: fakeElement(),
    reportContent: fakeElement(),
    reportActions: fakeElement(),
    screenshotCauseEditor: fakeElement(),
    screenshotCauseSelect: fakeElement(),
    screenshotCustomCause: fakeElement(),
    screenshotCauseSaveBtn: fakeElement(),
    screenshotCauseReadonly: fakeElement(),
    screenshotDeleteBtn: fakeElement(),
    screenshotPrice: fakeElement(),
    screenshotSoldBy: fakeElement(),
    screenshotModal: fakeElement(),
    screenshotTitle: fakeElement(),
    screenshotBody: fakeElement(),
    screenshotPrev: fakeElement(),
    screenshotNext: fakeElement(),
    screenshotCounter: fakeElement(),
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
    AppButton: { iconHtml() { return ''; }, html() { return ''; } },
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
    safeUrl(value) { return value; },
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

// 미선택 행을 먼저 표시하되 같은 그룹의 순서와 원본 데이터는 보존한다.
const mixedAnomalies = Object.freeze([
    { id: 1, cause: '상품페이지 없음' },
    { id: 2, cause: null },
    { id: 3, cause: '직접 확인한 신규 원인' },
    { id: 4, cause: '' },
    { id: 5, cause: '   ' },
    { id: 6, cause: ' CRAWLER_NULL_CAPTURE ' },
    { id: 7 }
].map(a => ({ ...a, retailer: 'Currys' })));
const mixedData = {
    daily_reports: [{ retailer: 'Currys', anomaly_total: 7 }],
    anomalies: mixedAnomalies
};
vm.runInContext("currentReportView = 'detail'; isClosed = false;", sandbox);
sandbox.renderReportTable(mixedData);
const initialHtml = elements.reportContent.innerHTML;
assert.ok(initialHtml.includes('원인 미선택 5건'));
assert.ok(initialHtml.includes('data-anomaly-ids="2,4,5,6,7,1,3"'));
assert.deepStrictEqual(
    [...initialHtml.matchAll(/id="cause_(\d+)"/g)].map(match => Number(match[1])),
    [2, 4, 5, 6, 7, 1, 3]
);
assert.strictEqual((initialHtml.match(/class="missing-cause-row"/g) || []).length, 5);
assert.deepStrictEqual(mixedAnomalies.map(a => a.id), [1, 2, 3, 4, 5, 6, 7]);
assert.ok(initialHtml.includes('>직접 확인한 신규 원인</option>'));
assert.ok(initialHtml.includes('원인 적용 이력'));
assert.ok(!initialHtml.includes('id="memo_'));
const historyHtml = sandbox.renderCauseHistory({
    id: 7, cause: '현재 원인', cause_history: { status: 'automatic', source: {
        crawl_date: '2026-09-22', retailersku: 'old-sku', title: '<과거 제목>',
        retailprice: 0, ships_from: null, sold_by: '과거 판매자', cause: '이전 원인', screenshot_id: 900
    } }
});
assert.ok(historyHtml.includes('과거 원인 자동 적용'));
assert.ok(historyHtml.includes('&lt;과거 제목&gt;'));
assert.ok(historyHtml.includes('<dt>가격</dt><dd>0</dd>'));
assert.ok(historyHtml.includes('과거 판매자'));
assert.ok(historyHtml.includes('showCauseHistoryScreenshot(7)'));
assert.ok(!historyHtml.includes('현재 원인'));
assert.ok(sandbox.renderCauseHistory({ cause_history: { status: 'legacy_match', source: {} } })
    .includes('자동 적용 여부 미기록'));

// 일괄 선택 중에는 화면 재정렬이나 저장 데이터 변경이 없어야 한다.
elements.cause_2 = fakeElement();
sandbox.document.querySelectorAll = () => [{ id: 'anomalyCheck_2' }];
sandbox.applyBulkCause({ value: '상품페이지 없음' }, 'Currys');
assert.strictEqual(elements.cause_2.value, '상품페이지 없음');
assert.strictEqual(elements.reportContent.innerHTML, initialHtml);
assert.strictEqual(mixedAnomalies[1].cause, null);
sandbox.document.querySelectorAll = () => [];

// 저장한 원인으로 다시 렌더링할 때 순서와 미선택 건수를 갱신한다.
mixedAnomalies[1].cause = '상품페이지 없음';
sandbox.renderReportTable(mixedData);
assert.ok(elements.reportContent.innerHTML.includes('원인 미선택 4건'));
assert.ok(elements.reportContent.innerHTML.includes('data-anomaly-ids="4,5,6,7,1,2,3"'));
vm.runInContext('isClosed = true', sandbox);
const closedHtml = sandbox.renderAnomalyItems(mixedAnomalies, 'Currys');
assert.ok(closedHtml.includes('data-anomaly-ids="4,5,6,7,1,2,3"'));
assert.ok(!closedHtml.includes('id="anomalyCheck_'));
assert.ok(!sandbox.renderAnomalyItems([mixedAnomalies[0]], 'Currys').includes('missing-cause-row'));
sandbox.renderReportTable({ daily_reports: mixedData.daily_reports, anomalies: [mixedAnomalies[0]] });
assert.ok(!elements.reportContent.innerHTML.includes('missing-cause-badge'));

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

    // 상품별 수집값 표시 및 이동 중 늦게 도착하는 이미지 응답 검증.
    vm.runInContext(`
        isClosed = false;
        reportData.anomalies = [
            { id: 101, retailer: 'Amazon_GB', screenshot_id: 501, retailprice: '399.99', sold_by: 'TechAzonia®' },
            { id: 102, retailer: 'Amazon_GB', screenshot_id: 502, retailprice: null, sold_by: '  ' },
            { id: 103, retailer: 'Amazon_GB', screenshot_id: 503, retailprice: 0, sold_by: '<판매자 & 이름>' }
        ];
    `, sandbox);
    const pending = new Map();
    sandbox.fetch = url => new Promise(resolve => pending.set(url, resolve));
    function completeImage(fileId) {
        pending.get(`/ds/layer4/api/screenshot/?file_id=${fileId}`)({
            json: async () => ({ success: true, file_name: `${fileId}.png`, url: `/image/${fileId}.png` })
        });
    }
    const firstImage = sandbox.showScreenshot(501, 101);
    assert.strictEqual(elements.screenshotPrice.textContent, '399.99');
    assert.strictEqual(elements.screenshotSoldBy.textContent, 'TechAzonia®');
    assert.strictEqual(elements.screenshotPrice.classList.contains('missing-value'), false);
    const nextImage = sandbox.navigateScreenshot(1);
    assert.strictEqual(elements.screenshotPrice.textContent, 'NULL');
    assert.strictEqual(elements.screenshotSoldBy.textContent, 'NULL');
    assert.strictEqual(elements.screenshotPrice.classList.contains('missing-value'), true);
    assert.strictEqual(elements.screenshotSoldBy.classList.contains('missing-value'), true);
    completeImage(502);
    await nextImage;
    completeImage(501);
    await firstImage;
    assert.strictEqual(elements.screenshotTitle.textContent, '502.png');
    assert.ok(elements.screenshotBody.innerHTML.includes('/image/502.png'));
    assert.strictEqual(elements.screenshotPrice.textContent, 'NULL');

    const thirdImage = sandbox.navigateScreenshot(1);
    completeImage(503);
    await thirdImage;
    assert.strictEqual(elements.screenshotPrice.textContent, '0');
    assert.strictEqual(elements.screenshotPrice.classList.contains('missing-value'), false);
    assert.strictEqual(elements.screenshotSoldBy.textContent, '<판매자 & 이름>');
    assert.strictEqual(elements.screenshotSoldBy.innerHTML, '');
    const previousImage = sandbox.navigateScreenshot(-1);
    completeImage(502);
    await previousImage;
    assert.strictEqual(elements.screenshotTitle.textContent, '502.png');
    assert.strictEqual(elements.screenshotPrice.textContent, 'NULL');
    sandbox.renderScreenshotProductInfo(999);
    assert.strictEqual(elements.screenshotSoldBy.textContent, 'NULL');

    vm.runInContext(`reportData.anomalies[1].cause_history = { status: 'automatic', source: {
        id: 88, crawl_date: '2026-09-22', screenshot_id: 900, retailprice: '299.00',
        sold_by: '과거 판매자', cause: '과거 원인'
    }};`, sandbox);
    const historicalImage = sandbox.showCauseHistoryScreenshot(102);
    completeImage(900);
    await historicalImage;
    assert.strictEqual(elements.screenshotPrice.textContent, '299.00');
    assert.strictEqual(elements.screenshotSoldBy.textContent, '과거 판매자');
    assert.strictEqual(elements.screenshotCauseReadonly.textContent, '과거 원인');
    assert.strictEqual(elements.screenshotCauseSaveBtn.hidden, true);
    assert.strictEqual(elements.screenshotDeleteBtn.style.display, 'none');
    assert.strictEqual(elements.screenshotNext.style.display, 'none');
    assert.ok(elements.screenshotTitle.textContent.includes('과거 캡처 · 2026-09-22'));
    assert.strictEqual(vm.runInContext('currentScreenshotAnomalyId', sandbox), null);
    await sandbox.saveScreenshotCause(); // 과거 기록에서는 수정 불가.
    const currentImage = sandbox.showScreenshot(501, 101);
    completeImage(501);
    await currentImage;
    assert.strictEqual(elements.screenshotPrice.textContent, '399.99');
    assert.strictEqual(elements.screenshotCauseSaveBtn.hidden, false);

    // 메모 입력란 없이 원인만 저장하며 기존 메모를 지우는 payload를 보내지 않는다.
    const checkbox = { id: 'anomalyCheck_101', checked: true };
    sandbox.document.querySelector = () => ({ querySelectorAll: () => [checkbox] });
    sandbox.document.querySelectorAll = () => [];
    elements.cause_101 = Object.assign(fakeElement(), { value: '새 원인' });
    sandbox.loadReportList = () => {};
    let causePayload;
    sandbox.fetch = async (url, options) => {
        causePayload = JSON.parse(options.body);
        return { json: async () => ({ success: true }) };
    };
    await sandbox.saveCheckedAnomalies('Amazon_GB');
    assert.deepStrictEqual(causePayload.updates, [{ anomaly_id: 101, cause: '새 원인' }]);
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
