const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let selectedDate = '2026-09-15';
let location = new URL('http://example.test/dx/layer2/null/?date=2026-09-15&focus=SEA%20TV');
const requests = [];
const rendered = [];
const elements = new Map();
const sandbox = {
    console, URL, URLSearchParams, setTimeout,
    window: { LAYER2: { section: 'null_validation' }, get location() { return location; }, scrollTo() {} },
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
    recordRender: data => rendered.push(data)
};
vm.createContext(sandbox);
for (const file of ['layer2-common.js', 'dashboard.js']) {
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/' + file, 'utf8'), sandbox);
}
vm.runInContext('renderLayer2Stats = function(data) { dxData = data; recordRender(data); };', sandbox);
function complete(request, table = 'tv_retail') {
    const data = {
        date: request.url.searchParams.get('date'), scoped_table: table,
        validation_types: [{ type: 'null', tables: [{ table, table_name: table }] }]
    };
    request.resolve({ ok: true, json: async () => data });
    return data;
}

(async function() {
    for (const section of ['null_validation', 'format_validation', 'anomaly_validation']) {
        sandbox.window.LAYER2.section = section;
        const pending = sandbox.fetchDXStats('SEA REF');
        const request = requests.at(-1);
        assert.strictEqual(request.url.searchParams.get('section'), section);
        assert.strictEqual(request.url.searchParams.get('table'), 'SEA REF');
        complete(request, 'sea_ref_retail');
        await pending;
    }

    sandbox.window.LAYER2.section = 'null_validation';
    rendered.length = 0;
    const old = sandbox.fetchDXStats('SEA TV');
    const oldRequest = requests.at(-1);
    const latest = sandbox.fetchDXStats('SEG TV');
    complete(requests.at(-1), 'seg_tv_retail');
    await latest;
    complete(oldRequest);
    await old;
    assert.deepStrictEqual(rendered.map(data => data.scoped_table), ['seg_tv_retail']);

    const previousDate = sandbox.fetchDXStats('SEG TV');
    const previousRequest = requests.at(-1);
    selectedDate = '2026-09-16';
    const currentDate = sandbox.fetchDXStats('SEG TV');
    complete(requests.at(-1), 'seg_tv_retail');
    await currentDate;
    complete(previousRequest, 'seg_tv_retail');
    await previousDate;
    assert.strictEqual(rendered.at(-1).date, selectedDate);

    const before = requests.length;
    vm.runInContext('ViewStack.stack = [{loadOverview: true}]; ViewStack.pop();', sandbox);
    assert.strictEqual(requests.length, before + 1);
    assert.strictEqual(requests.at(-1).url.searchParams.has('table'), false);
    assert.strictEqual(location.searchParams.has('focus'), false);
    complete(requests.at(-1));

    console.log('Layer2 scoped loading and stale-response tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
