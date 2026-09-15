const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js', 'utf8');
const requests = [];
const rendered = [];
let date = '2026-09-15';
function pending(kind, requestDate) {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    requests.push({ kind, date: requestDate, resolve });
    return promise;
}
const sandbox = {
    console, getSelectedDate: () => date,
    loadCheckStatus: day => pending('status', day),
    loadSeaRetailSummaries: day => pending('summary', day),
    fetch: () => pending('stats', date),
    L1: { initLayer1Page() {} },
    document: { getElementById: () => ({ innerHTML: '' }) },
    esc: String,
    recordRender: data => rendered.push(data),
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
vm.runInContext('renderLayer1Stats = recordRender;', sandbox);

async function flush() { await new Promise(done => setImmediate(done)); }
function completeStats(request) {
    request.resolve({ ok: true, json: async () => ({ date: request.date }) });
}

(async function() {
    const first = sandbox.loadStats();
    assert.deepStrictEqual(requests.map(r => r.kind), ['status', 'summary', 'stats']);
    completeStats(requests[2]);
    await flush();
    assert.strictEqual(rendered.at(-1).date, '2026-09-15');
    requests[0].resolve({ date: '2026-09-15' });
    requests[1].resolve({});
    await first;

    const older = sandbox.loadStats();
    const oldRequests = requests.slice(-3);
    date = '2026-09-16';
    const newer = sandbox.loadStats();
    const newRequests = requests.slice(-3);
    newRequests[0].resolve({ date });
    newRequests[1].resolve({});
    completeStats(newRequests[2]);
    await newer;
    oldRequests[0].resolve({ date: '2026-09-15' });
    oldRequests[1].resolve({});
    completeStats(oldRequests[2]);
    await older;
    assert.strictEqual(rendered.at(-1).date, date);
    assert.strictEqual(sandbox.currentCheckStatus.date, date);
    assert.strictEqual(sandbox.currentStatsData.date, date);
    console.log('Layer1 progressive loading and stale-response tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
