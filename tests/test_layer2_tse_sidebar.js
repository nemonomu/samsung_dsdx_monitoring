const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js',
    'utf8'
);
const indexSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/index.js',
    'utf8'
);
const sidebarSource = fs.readFileSync('static/js/sidebar.js', 'utf8');

assert.ok(source.includes('/dx/layer1/retail/api/backup-status/'));
assert.ok(indexSource.includes('/dx/layer1/retail/api/backup-status/'));
for (const label of ['SEA TV:', 'TSE TV:', 'TSE REF:', 'TSE LDY:']) {
    assert.ok(source.includes(label));
    assert.ok(indexSource.includes(label));
}
assert.ok(!indexSource.includes('/dx/layer1/api/backup-status/'));

let openedIndex = null;
const sidebarItems = [
    makeSidebarItem('TV', 'tv_retail'),
    makeSidebarItem('REF', 'sea_ref_retail'),
    makeSidebarItem('LDY', 'sea_ldy_retail'),
    makeSidebarItem('TV', 'tse_tv_retail'),
    makeSidebarItem('REF', 'tse_ref_retail'),
    makeSidebarItem('LDY', 'tse_ldy_retail'),
    makeSidebarItem('YouTube', '')
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
                { table: 'tv_retail', table_name: 'SEA TV' },
                { table: 'sea_ref_retail', table_name: 'SEA REF' },
                { table: 'sea_ldy_retail', table_name: 'SEA LDY' },
                { table: 'tse_tv_retail', table_name: 'TSE TV' },
                { table: 'tse_ref_retail', table_name: 'TSE REF' },
                { table: 'tse_ldy_retail', table_name: 'TSE LDY' },
                { table: 'youtube', table_name: 'YouTube' }
            ]
        }]
    };
`, sandbox);

for (const [label, detailCode, expectedIndex] of [
    ['TSE TV', 'tse_tv_retail', 3],
    ['TSE REF', 'tse_ref_retail', 4],
    ['TSE LDY', 'tse_ldy_retail', 5]
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
sandbox.onSubitemClick('null_validation', 'SEA TV', 'tv_retail');
assert.strictEqual(openedIndex, 0);
assert.strictEqual(sidebarItems[0].classList.active, true);

openedIndex = null;
sandbox.onSubitemClick('null_validation', 'SEA REF', 'sea_ref_retail');
assert.strictEqual(openedIndex, 1);

openedIndex = null;
sandbox.onSubitemClick('null_validation', 'SEA LDY', 'sea_ldy_retail');
assert.strictEqual(openedIndex, 2);

openedIndex = null;
sandbox.onSubitemClick('null_validation', 'YouTube', '');
assert.strictEqual(openedIndex, 6);
assert.strictEqual(sidebarItems[6].classList.active, true);

sandbox.window.LAYER2.section = 'dashboard';
sandbox.window.location.href = 'http://example.test/dx/layer2/';
sandbox.onSubitemClick('null_validation', 'TSE TV', 'tse_tv_retail');
assert.ok(sandbox.window.location.href.includes('/dx/layer2/null/'));
assert.ok(sandbox.window.location.href.includes('focus=TSE%20TV'));
assert.ok(!sandbox.window.location.href.includes('focus=TV&'));

sandbox.window.location.href = 'http://example.test/dx/layer2/';
sandbox.onSubitemClick('null_validation', 'SEA TV', 'tv_retail');
assert.ok(sandbox.window.location.href.includes('focus=SEA%20TV'));
assert.ok(!sandbox.window.location.href.includes('focus=TV&'));

vm.runInContext(sidebarSource, sandbox);

function makeClassList(initial) {
    const values = new Set(initial || []);
    return {
        contains(name) { return values.has(name); },
        remove(name) { values.delete(name); },
        toggle(name, enabled) {
            if (enabled === undefined) enabled = !values.has(name);
            if (enabled) values.add(name); else values.delete(name);
            return enabled;
        }
    };
}

function makeSubgroup(expanded) {
    const title = {
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
    };
    const children = { hidden: !expanded };
    const subgroup = {
        classList: makeClassList(expanded ? ['expanded'] : []),
        parentElement: null,
        querySelector(selector) {
            if (selector === '.sidebar-subgroup-title') return title;
            if (selector === '.sidebar-subgroup-children') return children;
            return null;
        },
    };
    title.closest = selector => selector === '.sidebar-subgroup' ? subgroup : null;
    return { subgroup, title, children };
}

const seaGroup = makeSubgroup(false);
const tseGroup = makeSubgroup(true);
const subgroupList = {
    querySelectorAll() {
        return [seaGroup.subgroup, tseGroup.subgroup].filter(
            item => item.classList.contains('expanded')
        );
    },
};
seaGroup.subgroup.parentElement = subgroupList;
tseGroup.subgroup.parentElement = subgroupList;

sandbox.toggleSidebarSubgroup(seaGroup.title);
assert.strictEqual(seaGroup.subgroup.classList.contains('expanded'), true);
assert.strictEqual(seaGroup.children.hidden, false);
assert.strictEqual(seaGroup.title.attributes['aria-expanded'], 'true');
assert.strictEqual(tseGroup.subgroup.classList.contains('expanded'), false);
assert.strictEqual(tseGroup.children.hidden, true);
assert.strictEqual(tseGroup.title.attributes['aria-expanded'], 'false');

sandbox.toggleSidebarSubgroup(seaGroup.title);
assert.strictEqual(seaGroup.subgroup.classList.contains('expanded'), false);
assert.strictEqual(seaGroup.children.hidden, true);
assert.strictEqual(seaGroup.title.attributes['aria-expanded'], 'false');
