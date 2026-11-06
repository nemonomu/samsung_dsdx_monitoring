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
    return { pending, first, requests: requests.slice(first) };
}
function complete(request, issueOverride) {
    request.done = true;
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
async function finish(load, failSection) {
    let finished = false;
    load.pending.then(() => { finished = true; });
    for (let turn = 0; turn < 20 && !finished; turn++) {
        for (const request of requests.slice(load.first).filter(request => !request.done)) {
            if (request.url.searchParams.get('section') === failSection && !request.url.searchParams.has('table')) {
                request.done = true;
                request.resolve({ ok: false, status: 500 });
            } else complete(request);
        }
        await flush();
    }
    assert(finished, 'all requested work must settle');
    await load.pending;
}
(async function() {
    for (const section of Object.keys(typeBySection)) {
        sandbox.window.LAYER2.section = section;
        for (const country of countries) {
            cold();
            const focus = country + '_ref_retail';
            const load = start(focus);
            assert.strictEqual(load.requests.length, 1, 'only the selected table starts immediately');
            const detail = load.requests[0];
            assert.strictEqual(detail.url.searchParams.get('section'), section);
            assert.strictEqual(detail.url.searchParams.get('table'), focus);
            const beforeRender = rendered.length;
            complete(detail);
            await flush();
            assert.strictEqual(rendered.at(-1).scoped_table, focus);
            assert.strictEqual(badges.size, 0, 'scoped data must not become global totals');
            for (let i = 0; i < 3; i++) {
                const pending = requests.slice(load.first).filter(request => !request.done);
                assert.strictEqual(pending.length, 1, 'global sections run sequentially after detail');
                assert(!pending[0].url.searchParams.has('table'));
                complete(pending[0]);
                await flush();
            }
            await finish(load);
            assertGlobalBadges();
            assert.strictEqual(rendered.length, beforeRender + 1, 'sidebar never replaces detail');
        }
    }
    sandbox.window.LAYER2.section = 'null_validation';
    const fresh = start('sea_ref_retail');
    await finish(fresh);
    assert.strictEqual(requests.length - fresh.first, 1, 'fresh sidebar avoids all global reads');
    const beforeClick = requests.length;
    sandbox.showTableDetailByName('sea_ref_retail');
    assert.strictEqual(requests.length, beforeClick, 'loaded country needs no new request');

    // Obsolete details cannot launch sidebar sweeps or overwrite the new date.
    for (const changeDate of [false, true]) {
        cold();
        const old = start('sea_ref_retail');
        if (changeDate) selectedDate = '2026-09-19';
        sandbox.invalidateLayer2SidebarStats(selectedDate);
        const latest = start('seg_ref_retail');
        await finish(latest);
        const before = requests.length;
        complete(old.requests[0], 99);
        await old.pending;
        assert.strictEqual(requests.length, before);
        assertGlobalBadges();
        assert.strictEqual(rendered.at(-1).scoped_table, 'seg_ref_retail');
        assert.strictEqual(rendered.at(-1).date, selectedDate);
    }
    cold();
    const failed = start('sea_ref_retail');
    await finish(failed, 'format_validation');
    assert.strictEqual(rendered.at(-1).scoped_table, 'sea_ref_retail');
    assert(!badges.has('format_validation'), 'errors must not invent zero counts');
    assert.strictEqual(errors.length, 1);
    const retry = start('sea_ref_retail');
    await finish(retry);
    assert.strictEqual(requests.length - retry.first, 2, 'retry only failed sidebar section');
    assertGlobalBadges();

    sandbox.window.LAYER2.section = 'dashboard';
    const dashboard = start();
    assert.strictEqual(dashboard.requests.length, 3);
    await finish(dashboard);
    assertGlobalBadges();
    assert.strictEqual(rendered.at(-1).summary.total_issues, 101);
    sandbox.window.LAYER2.section = 'null_validation';
    vm.runInContext('layer2SidebarSnapshot = null; layer2SidebarDate = null;', sandbox);
    badges.clear();
    const fromDashboard = start('sea_ref_retail');
    assertGlobalBadges();
    await finish(fromDashboard);
    assert.strictEqual(requests.length - fromDashboard.first, 1);

    now += 31000;
    const refresh = start('sea_ref_retail');
    assertGlobalBadges(); // Keep old badges visible during refresh.
    complete(refresh.requests[0]);
    await flush();
    const globalPending = requests.at(-1);
    const switching = start('seda_ref_retail');
    complete(switching.requests[0]);
    await flush();
    assert.strictEqual(requests.filter(request => !request.done).length, 1, 'reuse the running global read');
    complete(globalPending);
    await finish(switching);
    await refresh.pending;
    assertGlobalBadges();

    sandbox.invalidateLayer2SidebarStats(selectedDate);
    const afterSave = start('sea_ref_retail');
    await finish(afterSave);
    assert.strictEqual(requests.length - afterSave.first, 4, 'save invalidates all sections');
    selectedDate = '2026-09-20';
    const nextDate = start('sea_ref_retail');
    assert.strictEqual(badges.size, 0, 'never display another date counts');
    await finish(nextDate);
    assertGlobalBadges();

    cold();
    sandbox.window.sessionStorage = { getItem() { throw Error('disabled'); }, setItem() { throw Error('disabled'); } };
    await finish(start('sea_ref_retail'));
    const memoryOnly = start('seda_ref_retail');
    await finish(memoryOnly);
    assert.strictEqual(requests.length - memoryOnly.first, 1);
    for (const file of fs.readdirSync('apps/dx/dx_layer2/templates')) {
        const source = fs.readFileSync('apps/dx/dx_layer2/templates/' + file, 'utf8');
        if (source.includes('dx_layer2/js/dashboard.js')) assert(source.includes("dashboard.js' %}?v=20261106-query-performance"), file);
    }
    console.log('Layer2: detail priority, sequential sidebar, cache, races, save invalidation and date isolation passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
