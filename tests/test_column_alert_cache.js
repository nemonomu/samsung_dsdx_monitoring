const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/column-alert-cache.js', 'utf8');
const storage = new Map();
let now = 100000;
class TestDate extends Date { static now() { return now; } }
function page(username = 'reviewer', blockedStorage = false) {
    const requests = [];
    const sandbox = {
        LAYER1: {username}, Date: TestDate, structuredClone, URLSearchParams,
        sessionStorage: {
            getItem(key) { if (blockedStorage) throw Error('blocked'); return storage.get(key); },
            setItem(key, value) { if (blockedStorage) throw Error('blocked'); storage.set(key, value); },
        },
        fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve})),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    return {cache: sandbox.ColumnAlertCache, requests};
}
const date = '2026-09-23';
const jobs = Array.from({length:37}, (_, i) => ({country:'SEA', product:'TV', retailer:'Retailer'+i}));
const result = {comparison_date:date, comparisons:[{column:'sku', status:'abnormal', current:0,
    baseline:100, ratio:0, delta:-100, history_days:28}], daily:[{raw:'not for storage'}]};
const reply = (req, ok = true) => req.resolve({ok, json:async () => structuredClone(result)});
(async () => {
    const first = page();
    const cold = jobs.map(job => first.cache.load(job, date));
    assert.equal(first.requests.length, 37);
    first.requests.forEach(req => reply(req));
    await Promise.all(cold);
    const nextPage = page();
    const cached = await Promise.all(jobs.map(job => nextPage.cache.load(job, date)));
    assert.equal(nextPage.requests.length, 0, 'same-tab navigation skips all 37 recent requests');
    assert.equal(cached[0].comparisons[0].current, 0);
    assert(![...storage.values()].join('').includes('not for storage'), 'only comparison counts are persisted');
    cached[0].comparisons[0].current = 999;
    assert.equal((await nextPage.cache.load(jobs[0], date)).comparisons[0].current, 0);

    const manual = nextPage.cache.load(jobs[0], date, {force:true});
    assert.equal(nextPage.requests.length, 1, 'explicit query bypasses recent data');
    reply(nextPage.requests[0], false);
    await assert.rejects(manual);
    const afterFailure = page();
    const retry = afterFailure.cache.load(jobs[0], date);
    assert.equal(afterFailure.requests.length, 1, 'failed refresh cannot reuse the old success');
    reply(afterFailure.requests[0]); await retry;

    for (const [job, day, username] of [[jobs[0], '2026-09-22', 'reviewer'],
        [{...jobs[0], product:'REF'}, date, 'reviewer'], [jobs[0], date, 'someone-else']]) {
        const scoped = page(username), request = scoped.cache.load(job, day);
        assert.equal(scoped.requests.length, 1, 'cache is scoped to date, product, retailer and user');
        reply(scoped.requests[0]); await request;
    }
    now += 60000;
    const expired = page(), refresh = expired.cache.load(jobs[1], date);
    assert.equal(expired.requests.length, 1, 'expired counts are fetched again');
    reply(expired.requests[0]); await refresh;

    const aborted = page(), controller = new AbortController();
    const abandoned = aborted.cache.load(jobs[2], date, {signal:controller.signal, force:true});
    controller.abort(); reply(aborted.requests[0]); await abandoned;
    const revisit = page(), reload = revisit.cache.load(jobs[2], date);
    assert.equal(revisit.requests.length, 1, 'cancelled responses are never stored');
    reply(revisit.requests[0]); await reload;

    const blocked = page('reviewer', true), fallback = blocked.cache.load(jobs[3], date);
    reply(blocked.requests[0]); await fallback;
    await blocked.cache.load(jobs[3], date);
    assert.equal(blocked.requests.length, 1, 'storage denial falls back to in-page reuse');
    console.log('Column alert cache: 37 → 0 repeat requests, refresh, TTL, isolation, failures, cancellation and storage denial passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
