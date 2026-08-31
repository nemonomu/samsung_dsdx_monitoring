const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const dashboardSource = fs.readFileSync(
    path.join(root, 'apps', 'dx', 'dx_layer1', 'static', 'dx_layer1', 'js', 'dashboard.js'),
    'utf8'
);

function response(data) {
    return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(data)
    });
}

async function flushPromises() {
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
}

function fakeElement(tagName) {
    return {
        tagName,
        textContent: '',
        children: [],
        style: { cssText: '' },
        appendChild(child) {
            this.children.push(child);
            return child;
        }
    };
}

function elementText(element) {
    return [element.textContent]
        .concat((element.children || []).map(elementText))
        .join(' ');
}

async function testIntegratedBackupPromptAndPost() {
    const button = { disabled: false, textContent: '백업 실행' };
    const confirmMessage = fakeElement('div');
    const requests = [];
    const confirms = [];
    const confirmOptions = [];
    const toasts = [];
    const getResult = {
        success: true,
        tv_count: 1,
        sea_ref_count: 5,
        sea_ldy_count: 6,
        tse_tv_count: 2,
        tse_ref_count: 3,
        tse_ldy_count: 4,
        total_count: 21,
        inspection_date: '2026-08-11',
        source_dates: {
            sea_tv: '2026-08-10',
            sea_ref: '2026-08-10',
            sea_ldy: '2026-08-10',
            tse_tv: '2026-08-11',
            tse_ref: '2026-08-11',
            tse_ldy: '2026-08-11'
        }
    };
    const postResult = {
        success: true,
        message: '백업 완료',
        tv_count: 1,
        sea_ref_count: 5,
        sea_ldy_count: 6,
        tse_tv_count: 2,
        tse_ref_count: 3,
        tse_ldy_count: 4
    };
    const context = {
        console,
        L1: { initLayer1Page: () => {} },
        document: {
            getElementById: id => id === 'btn-backup'
                ? button : id === 'confirmMsg' ? confirmMessage : null,
            createElement: fakeElement
        },
        getSelectedDate: () => '2026-08-11',
        getCsrfToken: () => 'test-csrf',
        showConfirm: (message, type, options) => {
            confirms.push(message);
            confirmOptions.push({ type, options });
            return Promise.resolve(true);
        },
        showToast: (message, type) => toasts.push({ message, type }),
        fetch: (url, options) => {
            requests.push({ url, options });
            return requests.length === 1 ? response(getResult) : response(postResult);
        },
        setImmediate
    };
    vm.createContext(context);
    vm.runInContext(dashboardSource, context);

    context.runBackup();
    await flushPromises();

    assert.strictEqual(requests.length, 2);
    assert.strictEqual(requests[0].url, '/dx/layer1/retail/api/backup/?date=2026-08-11');
    assert.strictEqual(requests[1].options.method, 'POST');
    assert.ok(confirms[0].includes('백업 대상 확인'));
    assert.ok(confirms[0].includes('검수일  2026-08-11'));
    assert.ok(confirms[0].includes('SEA · D-1 데이터 · 2026-08-10'));
    assert.ok(confirms[0].includes('TV 1건  ·  REF 5건  ·  LDY 6건'));
    assert.ok(confirms[0].includes('TSE · D 데이터 · 2026-08-11'));
    assert.ok(confirms[0].includes('TV 2건  ·  REF 3건  ·  LDY 4건'));
    assert.ok(confirms[0].includes('총 21건'));
    const renderedText = elementText(confirmMessage);
    assert.ok(renderedText.includes('백업 대상 확인'));
    assert.ok(renderedText.includes('검수일'));
    assert.ok(renderedText.includes('2026-08-11'));
    assert.ok(renderedText.includes('SEA'));
    assert.ok(renderedText.includes('D-1'));
    assert.ok(renderedText.includes('TSE'));
    assert.ok(renderedText.includes('총 백업 대상'));
    assert.ok(renderedText.includes('21건'));
    assert.strictEqual(confirmOptions.length, 1);
    assert.strictEqual(confirmOptions[0].type, 'info');
    assert.strictEqual(confirmOptions[0].options.okText, '백업 실행');
    assert.strictEqual(confirmOptions[0].options.cancelText, '취소');
    assert.deepStrictEqual(toasts, [{ message: '백업 완료', type: 'success' }]);
    assert.strictEqual(button.disabled, false);
    assert.strictEqual(button.textContent, '백업 실행');
}

(async () => {
    await testIntegratedBackupPromptAndPost();
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
