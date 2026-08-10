const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js',
    'utf8'
);

let openedIndex = null;
const sidebarItems = [
    makeSidebarItem('TV Retail', ''),
    makeSidebarItem('TV', 'tse_tv_retail'),
    makeSidebarItem('REF', 'tse_ref_retail'),
    makeSidebarItem('LDY', 'tse_ldy_retail')
];

function makeSidebarItem(label, detailCode) {
    return {
        textContent: label,
        dataset: { detailCode },
        classList: {
            active: false,
            toggle(_name, enabled) { this.active = enabled; }
        }
    };
}

const sandbox = {
    console,
    URL,
    URLSearchParams,
    window: {
        LAYER2: { section: 'null_validation' },
        location: { href: 'http://example.test/dx/layer2/null/' },
        scrollTo() {}
    },
    document: {
        addEventListener() {},
        querySelectorAll(selector) {
            return selector === '.sidebar-subitem' ? sidebarItems : [];
        }
    },
    history: { replaceState() {} },
    getSelectedDate() { return '2026-08-10'; },
    showTableDetail(index) { openedIndex = index; },
    ViewStack: {
        depth() { return 0; },
        pop() {},
        _updateBackBtn() {}
    },
    setTimeout() {}
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);
vm.runInContext(`
    dxData = {
        validation_types: [{
            tables: [
                { table: 'tv_retail', table_name: 'TV Retail' },
                { table: 'youtube', table_name: 'YouTube' },
                { table: 'tse_tv_retail', table_name: 'TSE TV' },
                { table: 'tse_ref_retail', table_name: 'TSE REF' },
                { table: 'tse_ldy_retail', table_name: 'TSE LDY' }
            ]
        }]
    };
`, sandbox);

for (const [label, detailCode, expectedIndex] of [
    ['TSE TV', 'tse_tv_retail', 2],
    ['TSE REF', 'tse_ref_retail', 3],
    ['TSE LDY', 'tse_ldy_retail', 4]
]) {
    openedIndex = null;
    sandbox.onSubitemClick('null_validation', label, detailCode);
    assert.strictEqual(openedIndex, expectedIndex);
    assert.strictEqual(
        sidebarItems.find(item => item.dataset.detailCode === detailCode).classList.active,
        true
    );
    assert.strictEqual(sidebarItems[0].classList.active, false);
}

openedIndex = null;
sandbox.onSubitemClick('null_validation', 'TV Retail', '');
assert.strictEqual(openedIndex, 0);
assert.strictEqual(sidebarItems[0].classList.active, true);

sandbox.window.LAYER2.section = 'dashboard';
sandbox.window.location.href = 'http://example.test/dx/layer2/';
sandbox.onSubitemClick('null_validation', 'TSE TV', 'tse_tv_retail');
assert.ok(sandbox.window.location.href.includes('/dx/layer2/null/'));
assert.ok(sandbox.window.location.href.includes('focus=TSE%20TV'));
assert.ok(!sandbox.window.location.href.includes('focus=TV&'));
