const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let date = '2026-09-23';
const requests = [], nodes = new Map();
const get = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent:'', innerHTML:'', querySelectorAll:() => []});
    return nodes.get(id);
};
const sandbox = {
    console, URLSearchParams,
    window: {LAYER3:{section:'dashboard'}, location:{search:''}},
    document:{addEventListener(){}, getElementById:get},
    getSelectedDate: () => date,
    esc: value => String(value),
    escJs: value => String(value),
    renderCountryFlagLabel: value => String(value),
    fetchAPI: url => new Promise((resolve, reject) => requests.push({url, resolve, reject})),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer3/static/dx_layer3/js/common.js', 'utf8'), sandbox);
sandbox.checkBackupStatus = () => {};
sandbox.loadAllRetailersMissing = () => {};
const complete = req => req.resolve({checks:[], summary:{}});
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    let load = sandbox.loadData();
    assert.equal(requests.length, 2);
    assert(requests.every(req => !req.url.includes('section=time_series')),
        'dashboard does not run time-series queries in background');
    assert(get('categories-container').innerHTML.includes('시계열 검증 조회'));
    requests.forEach(complete); await load;
    assert(get('categories-container').innerHTML.includes('현재 합계에서 제외'));

    let manual = sandbox.loadDashboardTimeSeries();
    assert.equal(requests.length, 3, 'explicit click starts exactly one time-series request');
    assert(requests[2].url.includes('section=time_series'));
    assert(get('categories-container').innerHTML.includes('disabled'));
    await sandbox.loadDashboardTimeSeries();
    assert.equal(requests.length, 3, 'double-click does not duplicate work');
    requests[2].resolve({checks:[{category:'시계열 이상치',name:'가격 이상',checked:10,failed:2,status:'WARNING'}]});
    await manual;
    assert.equal(Number(get('total-checked').textContent), 10);
    assert.equal(Number(get('total-failed').textContent), 2);
    assert(!get('categories-container').innerHTML.includes('시계열 검증 조회'));

    load = sandbox.loadData();
    requests.slice(3).forEach(complete); await load;
    manual = sandbox.loadDashboardTimeSeries();
    const stale = requests.at(-1);
    date = '2026-09-24';
    load = sandbox.loadData();
    requests.slice(-2).forEach(complete); await load;
    stale.resolve({checks:[{category:'시계열 이상치',checked:999,failed:999}]}); await manual;
    assert.equal(Number(get('total-checked').textContent), 0, 'old date cannot overwrite the new dashboard');
    assert(get('categories-container').innerHTML.includes('시계열 검증 조회'));

    manual = sandbox.loadDashboardTimeSeries();
    requests.at(-1).reject(Error('query failed')); await manual;
    assert(get('categories-container').innerHTML.includes('데이터 로딩 실패'));
    assert.equal(Number(get('total-failed').textContent), 0, 'query errors do not invent anomaly counts');
    sandbox.window.LAYER3.section = 'cross_field';
    load = sandbox.loadData(); complete(requests.at(-1)); await load;
    const before = requests.length;
    await sandbox.loadDashboardTimeSeries(); await tick();
    assert.equal(requests.length, before, 'other sections do not run time-series queries');
    console.log('Layer3 lazy time-series: no background query, explicit click, duplicates, dates, failures and other sections passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
