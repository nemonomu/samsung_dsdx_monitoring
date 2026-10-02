const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const volumeSource = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-volume.js', 'utf8');
const dashboardSource = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js', 'utf8');
const day = '2026-10-02';
const good = (date = day) => ({inspection_date: date, policy_version: 3, snapshots: [{
    country: 'SIEL', source_date: date, available: true, rows: [{
        product: 'TV', retailer: 'Amazon', slot: 'daily', observation_state: 'ready', rules: {
            main: {rule: 'median_28d', baseline: 300, days: 7, low_percent: 30, high_percent: 30},
            bsr: {rule: 'fixed_100', baseline: 100, days: 0},
        },
    }],
}]});
const response = result => ({ok: true, json: async () => result});
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(fetch) {
    let now = 0, nextId = 0;
    const timers = new Map();
    const context = {L1: {initLayer1Page() {}}, AbortController, fetch, console,
        setTimeout(callback, delay) {const id = ++nextId; timers.set(id, {callback, at: now + delay}); return id;},
        clearTimeout(id) {timers.delete(id);},
    };
    vm.createContext(context);
    vm.runInContext(volumeSource, context);
    return {context, async tick(ms) {
        now += ms;
        for (const [id, timer] of [...timers]) if (timer.at <= now) {timers.delete(id); timer.callback();}
        await flush();
    }};
}

(async () => {
    // A response after the old 3-second limit succeeds without a manual reload.
    let resolveSlow, slowSignal;
    const slow = setup((_url, options) => {
        slowSignal = options.signal;
        return new Promise(resolve => {resolveSlow = resolve;});
    });
    const delayed = slow.context.L1.collectionVolume.load(day);
    await slow.tick(3500);
    assert.equal(slowSignal.aborted, false);
    resolveSlow(response(good()));
    assert.equal((await delayed).inspection_date, day);

    // A timeout is retried with a new signal and cannot leave a stale unknown state.
    let attempts = 0;
    const timeout = setup((_url, {signal, cache}) => {
        assert.equal(cache, 'no-store');
        if (++attempts > 1) return Promise.resolve(response(good()));
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('timeout'))));
    });
    const recovered = timeout.context.L1.collectionVolume.load(day);
    await timeout.tick(8000);
    await timeout.tick(500);
    assert.equal((await recovered).snapshots[0].available, true);
    assert.equal(attempts, 2);

    // Real dashboard loading re-renders the recovered verdict automatically.
    const renders = [];
    let volumeRequests = 0;
    const page = setup(async url => {
        if (url.includes('collection-volume')) return ++volumeRequests === 1 ? {ok: false} : response(good());
        return response({date: day, summary: {}, checks: [{check_type: 'siel_retail', phase: 'complete',
            status: 'OK', inspection_date: day, is_target_date: true, categories: [{name: 'TV', source_date: day,
                status: 'OK', retailers: [{retailer: 'Amazon', status: 'OK', main_count: 300, bsr_count: 100, actual: 345}]}]}]});
    });
    Object.assign(page.context, {getSelectedDate: () => day, loadDdayCollection() {},
        loadCheckStatus: async () => ({}), loadSeaRetailSummaries: async () => ({}), esc: String,
        document: {getElementById: () => ({innerHTML: ''})},
        recordRender(data) {renders.push(data.checks[0].categories[0].retailers[0].status);},
    });
    vm.runInContext(dashboardSource, page.context);
    vm.runInContext('renderLayer1Stats = recordRender;', page.context);
    await page.context.loadStats();
    assert.equal(renders.at(-1), 'VERIFYING');
    await page.tick(500);
    assert.equal(renders.at(-1), 'OK');
    assert.equal(volumeRequests, 2);

    // Repeated failure is bounded and explicitly reported, never normal.
    attempts = 0;
    const failed = setup(async () => {attempts++; throw new Error('unavailable');});
    const failure = failed.context.L1.collectionVolume.load(day);
    await flush(); await failed.tick(500); await failed.tick(1000);
    assert.equal((await failure).load_state, 'error');
    assert.equal(attempts, 3);

    // Changing the date cancels the previous request and its retries.
    const dates = [];
    const changed = setup((url, {signal}) => {
        const date = new URL(url, 'http://test').searchParams.get('date'); dates.push(date);
        if (date !== day) return Promise.resolve(response(good(date)));
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('cancelled'))));
    });
    const old = changed.context.L1.collectionVolume.load(day);
    const fresh = changed.context.L1.collectionVolume.load('2026-10-01');
    assert.equal(await old, null);
    assert.equal((await fresh).inspection_date, '2026-10-01');
    await changed.tick(10000);
    assert.deepEqual(dates, [day, '2026-10-01']);

    // Date/version mismatch is retried, while genuine missing history is kept as unavailable.
    attempts = 0;
    const mismatched = setup(async () => response(++attempts === 1 ? good('2026-09-30') : good()));
    const matched = mismatched.context.L1.collectionVolume.load(day);
    await flush(); await mismatched.tick(500);
    assert.equal((await matched).inspection_date, day);
    const missing = setup(async () => response({...good(), snapshots: []}));
    assert.equal((await missing.context.L1.collectionVolume.load(day)).snapshots.length, 0);
    console.log('Collection volume loading: slow responses, timeout retry, dashboard recovery, failures and date cancellation passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
