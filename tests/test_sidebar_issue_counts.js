const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const layer3Path = 'apps/dx/dx_layer3/static/dx_layer3/js/';
const read = path => fs.readFileSync(path, 'utf8');

function target() {
    return {
        badge: null,
        querySelector(selector) {
            return selector.includes('sidebar-issue-badge') ? this.badge : null;
        },
        insertBefore(badge) {
            this.badge = badge;
            badge.remove = () => { this.badge = null; };
        }
    };
}

function group(items) {
    const header = target();
    const entries = items.map(([name, code, parent]) => {
        const item = target();
        item.dataset = { sidebarItemName: name, sidebarDetailCode: code || '' };
        item.classList = { contains: value => !!parent && value === 'sidebar-subgroup' };
        if (parent) {
            item.title = target();
            item.querySelector = () => item.title;
        }
        return item;
    });
    return {
        header, entries,
        querySelector() { return header; },
        querySelectorAll(selector) {
            if (selector === '[data-sidebar-item-name]') return entries;
            return [header, ...entries.map(item => item.title || item)]
                .map(item => item.badge).filter(Boolean);
        }
    };
}

const groups = {
    cross_field: group([
        ['SEA Retail', '', true], ['SEA Retail', 'tv'], ['SEA REF', 'sea_ref'],
        ['SIEL Retail', '', true], ['SIEL TV', 'siel_tv'],
        ['TV Sentiment 논리적 일관성']
    ]),
    time_series: group([['가격 이상', 'tv_price_median']]),
    category_spec: group([['카테고리 규칙']]),
    field_missing: group([['SEA Retail', '', true], ['TV', 'tv'], ['REF', 'sea_ref']])
};
let selectedDate = '2026-09-18';
let search = '?date=2026-09-18&focus=SIEL%20TV&detail_code=siel_tv';
const container = { innerHTML: '' };
const sandbox = {
    console, URLSearchParams,
    window: { LAYER3: { section: 'cross_field' }, location: {
        get search() { return search; }, pathname: '/dx/layer3/cross-field/'
    } },
    history: { replaceState() {} },
    document: {
        addEventListener() {},
        createElement() { return { setAttribute() {} }; },
        querySelector(selector) {
            const match = selector.match(/data-sidebar-group="([^"]+)"/);
            return match ? groups[match[1]] : null;
        },
        querySelectorAll() { return []; },
        getElementById(id) { return id === 'categories-container' ? container : null; }
    },
    getSelectedDate: () => selectedDate
};
vm.createContext(sandbox);
vm.runInContext(read('static/js/sidebar.js'), sandbox);
vm.runInContext(read(layer3Path + 'common.js'), sandbox);
sandbox.checkBackupStatus = () => {};
const check = (name, detail_code, failed, category = '크로스 필드 검증') =>
    ({ name, detail_code, failed, category });
const count = item => item.badge ? Number(item.badge.textContent.replaceAll(',', '')) : 0;
const flush = () => new Promise(resolve => setImmediate(resolve));

(async function() {
    sandbox.updateLayer3SidebarIssueBadges({ checks: [
        check('TV 논리적 일관성', 'tv', 1),
        check('SEA REF 논리적 일관성', 'sea_ref', 4),
        check('SIEL TV 논리적 일관성', 'siel_tv', 1),
        check('TV Sentiment↔리뷰 일관성', '', 3),
        check('가격 이상', 'tv_price_median', 2, '시계열 이상치'),
        check('카테고리 규칙', '', 6, '카테고리별 특성')
    ] });
    const cross = groups.cross_field;
    assert.strictEqual(count(cross.header), 9);
    assert.strictEqual(count(cross.entries[0].title), 5);
    assert.strictEqual(count(cross.entries[1]), 1, 'SEA TV must not inherit the regional total');
    assert.strictEqual(count(cross.entries[3].title), 1);
    assert.strictEqual(count(cross.entries[4]), 1);
    assert.strictEqual(count(cross.entries[5]), 3, 'Sentiment label alias');
    assert.strictEqual(count(groups.time_series.header), 2);
    assert.strictEqual(count(groups.category_spec.header), 6);
    sandbox.updateSidebarIssueBadges('category_spec', 7, [
        { name: '카테고리 규칙', detailCode: 'legacy_code', count: 7 }
    ]);
    assert.strictEqual(count(groups.category_spec.entries[0]), 7, 'legacy flat menus retain name matching');
    sandbox.updateLayer3SidebarIssueBadges({ checks: [check('SIEL TV', 'siel_tv', 0)] });
    assert.strictEqual(count(cross.header), 0);
    assert.strictEqual(count(cross.entries[4]), 0);

    const pending = [];
    const details = [];
    sandbox.fetchAPI = url => new Promise(resolve => pending.push({ url, resolve }));
    sandbox.showDetail = (...args) => { details.push(args); container.innerHTML = 'detail'; };
    await sandbox.loadData();
    assert.strictEqual(details.length, 1, 'detail opens without waiting for sidebar stats');
    assert(pending[0].url.includes('section=cross_field'));
    pending[0].resolve({ checks: [check('SIEL TV 논리적 일관성', 'siel_tv', 1)] });
    await flush();
    assert.strictEqual(count(cross.entries[4]), 1, 'direct focus must show the issue');
    assert.strictEqual(count(cross.entries[3].title), 1);
    assert.strictEqual(count(cross.header), 1);
    assert.strictEqual(container.innerHTML, 'detail', 'stats must not replace the detail view');

    await sandbox.loadData();
    selectedDate = '2026-09-19';
    await sandbox.loadData();
    pending[2].resolve({ checks: [check('SIEL TV', 'siel_tv', 2)] });
    await flush();
    pending[1].resolve({ checks: [check('SIEL TV', 'siel_tv', 99)] });
    await flush();
    assert.strictEqual(count(cross.entries[4]), 2, 'old date must not overwrite current counts');

    for (const [section, category, name, code] of [
        ['category_spec', '카테고리별 특성', '카테고리 규칙', ''],
        ['time_series', '시계열 이상치', '가격 이상', 'tv_price_median']
    ]) {
        sandbox.window.LAYER3.section = section;
        sandbox.loadTimeSeriesPage = () => { container.innerHTML = 'detail'; };
        search = '?focus=' + encodeURIComponent(name) + '&detail_code=' + code;
        await sandbox.loadData();
        const request = pending.at(-1);
        assert(request.url.includes('section=' + section));
        request.resolve({ checks: [check(name, code, 3, category)] });
        await flush();
        assert.strictEqual(count(groups[section].entries[0]), 3);
    }

    vm.runInContext(read(layer3Path + 'field-missing.js'), sandbox);
    sandbox.fetchAPI = async () => ({ summary: { total_missing_cases: 1, fields_with_issues: 1 } });
    await sandbox.loadAllRetailersMissing();
    assert.strictEqual(count(groups.field_missing.entries[1]), 3);
    vm.runInContext("currentFieldMissingPL = 'sea_ref'", sandbox);
    await sandbox.loadAllRetailersMissing();
    assert.strictEqual(count(groups.field_missing.entries[2]), 2);
    assert.strictEqual(count(groups.field_missing.entries[0].title), 5);
    selectedDate = '2026-09-20';
    sandbox.fetchAPI = async () => ({ summary: { total_missing_cases: 0 } });
    await sandbox.loadAllRetailersMissing();
    assert.strictEqual(count(groups.field_missing.header), 0, 'new date clears prior product totals');
    assert.strictEqual(count(groups.field_missing.entries[1]), 0);

    let resolveOld;
    sandbox.fetchAPI = () => new Promise(resolve => { resolveOld = resolve; });
    vm.runInContext("currentFieldMissingPL = 'tv'", sandbox);
    const oldLoad = sandbox.loadAllRetailersMissing();
    vm.runInContext("currentFieldMissingPL = 'sea_ref'", sandbox);
    sandbox.fetchAPI = async () => ({ summary: { total_missing_cases: 2 } });
    await sandbox.loadAllRetailersMissing();
    resolveOld({ summary: { total_missing_cases: 99 } });
    await oldLoad;
    assert.strictEqual(count(groups.field_missing.header), 4, 'stale product response ignored');

    for (const file of fs.readdirSync('apps/dx/dx_layer3/templates')) {
        const source = read('apps/dx/dx_layer3/templates/' + file);
        if (source.includes('dx_layer3/js/common.js')) {
            assert(source.includes("common.js' %}?v=20260918-sidebar2"), file);
        }
    }
    console.log('Sidebar counts: focus, hierarchy, aliases, zero reset, dates and stale requests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
