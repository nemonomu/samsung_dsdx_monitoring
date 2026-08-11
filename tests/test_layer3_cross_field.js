const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'static',
        'dx_layer3',
        'js',
        'cross-field.js'
    ),
    'utf8'
);
const commonSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'static',
        'dx_layer3',
        'js',
        'common.js'
    ),
    'utf8'
);

assert(commonSource.includes('/dx/layer1/retail/api/backup-status/'));
for (const label of ['SEA TV:', 'TSE TV:', 'TSE REF:', 'TSE LDY:']) {
    assert(commonSource.includes(label));
}

let inlineHtml = '';
const modal = { title: '', body: '', opened: false };
const sandbox = {
    console,
    document: { addEventListener() {} },
    window: { crossfieldRetailerData: null },
    isCrossFieldInline: () => true,
    ViewStack: {
        push(html) { inlineHtml = html; },
    },
    AppModal: {
        setTitle(_name, title) { modal.title = title; },
        setBody(_name, body) { modal.body = body; },
        open() { modal.opened = true; },
    },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

sandbox.showRetailerDetail('Homepro');
assert(inlineHtml.includes('상세 데이터를 찾을 수 없습니다'));
assert(inlineHtml.includes('ViewStack.pop()'));

sandbox.isCrossFieldInline = () => false;
sandbox.window.crossfieldRetailerData = {};
sandbox.showRetailerDetail('Homepro');
assert.strictEqual(modal.title, 'Homepro - 상세 조회');
assert(modal.body.includes('다시 조회해 주세요'));
assert.strictEqual(modal.opened, true);

async function testSeaRetailDisplayKeepsCanonicalTvRoute() {
    let requestedUrl = '';
    const detailModal = { title: '', body: '', opened: false };
    const commonSandbox = {
        console,
        window: { LAYER3: { section: 'dashboard' } },
        document: {
            addEventListener() {},
            querySelector() { return null; },
            getElementById() { return null; },
        },
        getSelectedDate: () => '2026-08-11',
        escJs: value => String(value || ''),
        fetchAPI: async url => {
            requestedUrl = url;
            return {
                date: '2026-08-11',
                product_line: 'tv',
                total_anomalies: 0,
                anomalies: [],
                rule_summary: [],
            };
        },
        AppModal: {
            setTitle(_name, title) { detailModal.title = title; },
            setBody(_name, body) { detailModal.body = body; },
            open() { detailModal.opened = true; },
            getTitle() { return ''; },
        },
    };

    vm.createContext(commonSandbox);
    vm.runInContext(commonSource, commonSandbox);

    assert.strictEqual(
        commonSandbox.getLayer3DisplayName('TV 논리적 일관성', ''),
        'SEA Retail'
    );
    await commonSandbox.showDetail('크로스 필드 검증', 'SEA Retail', 'tv');

    assert.strictEqual(
        requestedUrl,
        '/layer3/api/cross-field-detail/?date=2026-08-11&type=tv'
    );
    assert.strictEqual(detailModal.title, 'SEA Retail (0건)');
    assert(detailModal.body.includes('논리 오류 데이터가 없습니다'));
    assert.strictEqual(detailModal.opened, true);
}

testSeaRetailDisplayKeepsCanonicalTvRoute().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
