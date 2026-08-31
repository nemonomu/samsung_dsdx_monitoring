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

async function testIntegratedBackupPromptAndPost() {
    const button = { disabled: false, textContent: '백업 실행' };
    const requests = [];
    const confirms = [];
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
            getElementById: id => id === 'btn-backup' ? button : null
        },
        getSelectedDate: () => '2026-08-11',
        getCsrfToken: () => 'test-csrf',
        showConfirm: message => {
            confirms.push(message);
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
    assert.ok(confirms[0].includes('검수일(inspection_date): 2026-08-11'));
    assert.ok(confirms[0].includes('SEA source_date - TV: 2026-08-10'));
    assert.ok(confirms[0].includes('TSE source_date - TV: 2026-08-11'));
    assert.ok(confirms[0].includes('SEA TV: 1건'));
    assert.ok(confirms[0].includes('SEA REF: 5건'));
    assert.ok(confirms[0].includes('SEA LDY: 6건'));
    assert.ok(confirms[0].includes('TSE TV: 2건'));
    assert.ok(confirms[0].includes('TSE REF: 3건'));
    assert.ok(confirms[0].includes('TSE LDY: 4건'));
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
