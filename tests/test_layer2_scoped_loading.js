const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let selectedDate = '2026-09-18';
let location = new URL('http://example.test/dx/layer2/null/?date=2026-09-18&focus=SEA%20REF');
const requests = [], rendered = [], errors = [];
const badges = new Map(), elements = new Map(), storage = new Map();
let now = Date.now();
class TestDate extends Date { static now() { return now; } }
const sandbox = {
    Date: TestDate, console: { ...console, error: (...args) => errors.push(args) }, URL, URLSearchParams, setTimeout,
    window: { sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) }, LAYER2: { section: 'null_validation' }, get location() { return location; }, scrollTo() {} },
    document: {
        addEventListener() {},
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, { innerHTML: '', style: {} });
            return elements.get(id);
        },
        querySelectorAll() { return []; }
    },
    history: { replaceState(_, __, url) { location = new URL(url); } },
    getSelectedDate: () => selectedDate,
    fetch(url) {
        let resolve;
        const promise = new Promise(done => { resolve = done; });
        requests.push({ url: new URL(url, location), resolve });
        return promise;
    },
    updateSidebarIssueBadges: (group, total, items) => badges.set(group, { total, items }),
    clearSidebarIssueBadges: groups => groups.forEach(group => badges.delete(group))
};
vm.createContext(sandbox);
for (const file of ['layer2-common.js', 'dashboard.js']) {
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/' + file, 'utf8'), sandbox);
}
// Exercise the real render entry point, including its sidebar update policy.
sandbox.renderDXSummary = () => {};
sandbox.updateCurrentInfo = () => {};
sandbox.renderDXValidationTypes = data => {
    rendered.push(data);
    elements.get('dx-validation-container').innerHTML = data.scoped_table || 'overview';
};
const typeBySection = { null_validation: 'null', format_validation: 'format', anomaly_validation: 'duplicate' };
const countries = ['sea', 'seda', 'siel', 'seg', 'sem', 'tse'];
const flush = () => new Promise(resolve => setImmediate(resolve));
function cold() {
    storage.clear();
    vm.runInContext('layer2SidebarSnapshot = null; layer2SidebarDate = null; layer2SidebarPending.clear(); layer2SidebarGeneration += 1;', sandbox);
}
function start(table) {
    const first = requests.length;
    const pending = sandbox.fetchDXStats(table);
    return { pending, requests: requests.slice(first) };
}
function complete(request, issueOverride) {
    const type = typeBySection[request.url.searchParams.get('section')];
    const focus = request.url.searchParams.get('table');
    const counts = type === 'null' ? [9, 2, 2, 3, 4, 0]
        : type === 'format' ? [81, 0, 0, 0, 0, 0] : [0, 0, 0, 0, 0, 0];
    const tables = focus ? [{ table: focus, total_issues: issueOverride ?? 9 }]
        : countries.map((country, index) => ({
            table: country + '_ref_retail', total_issues: issueOverride ?? counts[index]
        }));
    const total = tables.reduce((sum, table) => sum + table.total_issues, 0);
    const data = {
        date: request.url.searchParams.get('date'), scoped_table: focus,
        validation_types: [{ type, total_issues: total, tables }],
        summary: { total_issues: total, null_issues: type === 'null' ? total : 0,
            format_issues: type === 'format' ? total : 0,
            duplicate_issues: type === 'duplicate' ? total : 0, overall_status: 'CRITICAL' }
    };
    request.resolve({ ok: true, json: async () => data });
}
function assertGlobalBadges() {
    assert.strictEqual(badges.get('null_validation').total, 20);
    for (const [name, count] of [['SEA', 9], ['SEDA', 2], ['SIEL', 2], ['SEG', 3], ['SEM', 4], ['TSE', 0]]) {
        const items = badges.get('null_validation').items;
        assert.strictEqual(items.find(item => item.name === name + ' Retail').count, count);
        assert.strictEqual(items.find(item => item.detailCode === name.toLowerCase() + '_ref_retail').count, count);
    }
    assert.strictEqual(badges.get('format_validation').total, 81);
    assert.strictEqual(badges.get('anomaly_validation').total, 0);
}
(async function() {
    for (const section of Object.keys(typeBySection)) {
        sandbox.window.LAYER2.section = section;
        for (const [index, country] of countries.entries()) {
            cold();
            const focus = country + '_ref_retail';
            const load = start(focus);
            assert.strictEqual(load.requests.length, 4);
            const [detail, ...sidebar] = load.requests;
            assert.strictEqual(detail.url.searchParams.get('section'), section);
            assert.strictEqual(detail.url.searchParams.get('table'), focus);
            assert(sidebar.every(request => !request.url.searchParams.has('table')));
            const beforeRender = rendered.length;
            if (index % 2 === 0) {
                complete(detail);
                await flush();
                assert.strictEqual(rendered.at(-1).scoped_table, focus, 'detail must not wait for sidebar');
                assert.strictEqual(badges.size, 0, 'scoped response must not supply global counts');
                sidebar.forEach(request => complete(request));
            } else {
                sidebar.forEach(request => complete(request));
                await flush();
                assertGlobalBadges();
                assert.strictEqual(rendered.length, beforeRender, 'sidebar must not replace body');
                complete(detail);
            }
            await load.pending;
            assertGlobalBadges();
            assert.strictEqual(rendered.length, beforeRender + 1);
            assert.strictEqual(elements.get('dx-validation-container').innerHTML, focus);
        }
    }
    sandbox.window.LAYER2.section = 'null_validation';
    cold();
    const cached = start('sea_ref_retail');
    complete(cached.requests[0]);
    await flush();
    const beforeCachedClick = requests.length;
    sandbox.showTableDetailByName('sea_ref_retail');
    assert.strictEqual(requests.length, beforeCachedClick, 'loaded country needs no new request');
    cached.requests.slice(1).forEach(request => complete(request));
    await cached.pending;
    assertGlobalBadges();

    const beforeCountryClick = requests.length;
    sandbox.onSubitemClick('null_validation', 'SEDA REF', 'seda_ref_retail');
    const countryRequests = requests.slice(beforeCountryClick);
    assert.strictEqual(countryRequests.length, 1, 'fresh counts must avoid three full-country queries');
    assert.strictEqual(countryRequests[0].url.searchParams.get('table'), 'seda_ref_retail');
    countryRequests.forEach(request => complete(request));
    await flush();
    assert.strictEqual(rendered.at(-1).scoped_table, 'seda_ref_retail');
    assertGlobalBadges();

    for (const changeDate of [false, true]) {
        cold();
        const old = start('sea_ref_retail');
        if (changeDate) selectedDate = '2026-09-19';
        sandbox.invalidateLayer2SidebarStats(selectedDate);
        const latest = start('seg_ref_retail');
        latest.requests.forEach(request => complete(request));
        await latest.pending;
        old.requests.forEach(request => complete(request, 99));
        await old.pending;
        assertGlobalBadges();
        assert.strictEqual(rendered.at(-1).scoped_table, 'seg_ref_retail');
        assert.strictEqual(rendered.at(-1).date, selectedDate);
    }
    cold();
    const failedSidebar = start('sea_ref_retail');
    const [detail, ...sidebar] = failedSidebar.requests;
    complete(detail);
    sidebar.forEach(request => request.url.searchParams.get('section') === 'format_validation'
        ? request.resolve({ ok: false, status: 500 }) : complete(request));
    await failedSidebar.pending;
    assert.strictEqual(rendered.at(-1).scoped_table, 'sea_ref_retail');
    assert.strictEqual(badges.get('null_validation').total, 20);
    assert(!badges.has('format_validation'), 'failed section must not invent zero counts');
    assert.strictEqual(errors.length, 1);
    const first = requests.length;
    vm.runInContext('ViewStack.stack = [{loadOverview: true}]; ViewStack.pop();', sandbox);
    const overview = requests.slice(first);
    assert.strictEqual(overview.length, 2, 'reuse overview and cached duplicate counts; retry failed format');
    assert(overview.every(request => !request.url.searchParams.has('table')));
    assert.strictEqual(location.searchParams.has('focus'), false);
    overview.forEach(request => complete(request));
    await flush();
    assertGlobalBadges();
    assert.strictEqual(rendered.at(-1).scoped_table, null);
    sandbox.window.LAYER2.section = 'dashboard';
    const dashboard = start();
    assert.strictEqual(dashboard.requests.length, 3);
    dashboard.requests.forEach(request => complete(request));
    await dashboard.pending;
    assertGlobalBadges();
    assert.strictEqual(rendered.at(-1).summary.total_issues, 101);
    // Simulate navigating from the dashboard into a fresh document in the same tab.
    sandbox.window.LAYER2.section = 'null_validation';
    vm.runInContext('layer2SidebarSnapshot = null; layer2SidebarDate = null;', sandbox);
    badges.clear();
    const fromDashboard = start('sea_ref_retail');
    assertGlobalBadges(); // Synchronous: no API response has arrived yet.
    assert.strictEqual(fromDashboard.requests.length, 1, 'only selected product is queried within 30 seconds');
    complete(fromDashboard.requests[0]);
    await fromDashboard.pending;
    assert(!Array.from(storage.values()).join('').includes('retailer_sku_name'));

    now += 31000;
    const refresh = start('sea_ref_retail');
    assertGlobalBadges(); // Stale counts remain visible during background refresh.
    assert.strictEqual(refresh.requests.length, 4);
    const switching = start('seda_ref_retail');
    assert.strictEqual(switching.requests.length, 1, 'reuse three in-flight global queries on rapid navigation');
    refresh.requests.forEach(request => complete(request));
    switching.requests.forEach(request => complete(request));
    await Promise.all([refresh.pending, switching.pending]);
    assertGlobalBadges();

    sandbox.invalidateLayer2SidebarStats(selectedDate);
    const afterSave = start('sea_ref_retail');
    assert.strictEqual(afterSave.requests.length, 4, 'save/search invalidates even a fresh snapshot');
    assertGlobalBadges();
    afterSave.requests.forEach(request => complete(request));
    await afterSave.pending;

    selectedDate = '2026-09-20';
    const nextDate = start('sea_ref_retail');
    assert.strictEqual(badges.size, 0, 'never display another date\'s counts');
    nextDate.requests.forEach(request => complete(request));
    await nextDate.pending;
    assertGlobalBadges();

    cold();
    const sessionStorage = sandbox.window.sessionStorage;
    sandbox.window.sessionStorage = { getItem() { throw Error('disabled'); }, setItem() { throw Error('disabled'); } };
    const noStorage = start('sea_ref_retail');
    noStorage.requests.forEach(request => complete(request));
    await noStorage.pending;
    const memoryOnly = start('seda_ref_retail');
    assertGlobalBadges();
    assert.strictEqual(memoryOnly.requests.length, 1);
    complete(memoryOnly.requests[0]);
    await memoryOnly.pending;
    sandbox.window.sessionStorage = sessionStorage;
    for (const file of fs.readdirSync('apps/dx/dx_layer2/templates')) {
        const source = fs.readFileSync('apps/dx/dx_layer2/templates/' + file, 'utf8');
        if (source.includes('dx_layer2/js/dashboard.js')) {
            assert(source.includes("dashboard.js' %}?v=20260918-sidebar-cache1"), file);
        }
    }
    console.log('Layer2: synchronous dashboard cache restore, 30s reuse, in-flight deduplication, save invalidation, date isolation and all-country navigation passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
