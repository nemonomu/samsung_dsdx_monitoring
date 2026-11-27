const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js', 'utf8');
const requests = [];
const rendered = [];
const frames = [];
let date = '2026-09-15';
function pending(kind, requestDate, extra = {}) {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    requests.push({kind, date:requestDate, resolve, ...extra});
    return promise;
}
const sandbox = {
    console, clearTimeout, URLSearchParams, window:{}, getSelectedDate: () => date,
    location:{search:'?date=' + date}, sessionStorage:{getItem:() => '2026-09-01'},
    loadDdayCollection: day => pending('dday', day),
    resetDdayCollection() {},
    loadCheckStatus: day => pending('status', day),
    loadSeaRetailSummaries: day => pending('summary', day),
    resetSeaRetailSummaries() {}, currentRetailSummary:null,
    fetch(url, options) {
        const params = new URL(url, 'http://test').searchParams;
        return pending(params.get('dashboard_scope'), params.get('date'), {refresh:params.get('refresh'), options});
    },
    L1: {initLayer1Page() {},
        collectionVolume:{load:day => pending('volume', day), decorate() {}},
        retailReview:{load:day => pending('review', day)}},
    ColumnAlertSummary:{load:day => pending('columns', day), reset() {}},
    updateConfirmedCount() {},
    addCheckBadges() {},
    requestAnimationFrame: callback => frames.push(callback),
    document: {getElementById: () => ({innerHTML:''})},
    esc:String,
    recordRender: data => rendered.push({...data, checks:[...data.checks], summary:{...data.summary}}),
};
class TestDate extends Date { static now() { return Date.UTC(2026, 8, 16, 10); } }
sandbox.Date = TestDate;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
vm.runInContext('renderLayer1Stats = recordRender;', sandbox);

const flush = () => new Promise(done => setImmediate(done));
function complete(request, ok = true) {
    if (request.kind === 'periodic' || request.kind === 'daily') {
        request.resolve({ok, status:503, json:async () => ({
            target_date:request.date, checks:[request.kind],
            summary:{total_checked:1, total_completed:1, passed:1, failed:0,status:'OK'},
        })});
    } else {
        request.resolve(request.kind === 'dday' ? false : {date:request.date});
    }
}
async function paint() {
    assert.equal(frames.length, 1);
    frames.shift()();
    await flush();
}
(async function() {
    const template = fs.readFileSync('apps/dx/dx_layer1/templates/dx_layer1_dashboard.html', 'utf8');
    const prime = template.match(/<script>([\s\S]+?)<\/script>/)[1]
        .replace('{% url "dx_layer1:api_stats" %}', '/dx/layer1/api/stats/');
    vm.runInContext(prime, sandbox);
    const first = sandbox.loadStats();
    assert.deepStrictEqual(requests.map(r => r.kind), ['daily']);
    assert.equal(requests[0].date, date, 'URL date takes priority over stored date');
    assert(!sandbox.window.layer1InitialStats, 'the preload is consumed once');
    complete(requests[0]);
    await flush();
    assert.deepStrictEqual(rendered.at(-1).checks, ['daily']);
    assert.equal(rendered.at(-1)._retailPending, true);
    assert.equal(rendered.at(-1)._periodicPending, true);
    await paint();
    assert.equal(requests.length, 1, 'no widgets start before the first paint opportunity');
    await paint();
    assert.deepStrictEqual(requests.slice(1).map(r => r.kind),
        ['periodic','dday','status','volume','review','summary','columns']);
    requests.slice(1).forEach(request => complete(request));
    await first;
    assert.equal(frames.length, 1, 'supplementary responses coalesce into one repaint');
    await paint();
    assert.deepStrictEqual(rendered.at(-1).checks, ['daily','periodic']);
    assert.equal(rendered.at(-1).summary.total_checked, 2);
    assert.equal(rendered.at(-1)._retailPending, false);

    const older = sandbox.loadStats();
    const old = requests.at(-1);
    date = '2026-09-16';
    const manual = sandbox.loadStats(true);
    const forcedDaily = requests.at(-1);
    assert.equal(forcedDaily.refresh, '1');
    assert.equal(forcedDaily.options.cache, 'no-store');
    complete(old);
    await older;
    complete(forcedDaily);
    await flush();
    await paint();
    await paint();
    const forcedPeriodic = requests.find(request => request.date === date && request.kind === 'periodic');
    assert.equal(forcedPeriodic.refresh, '1');
    assert.equal(forcedPeriodic.options.cache, 'no-store');
    requests.slice(-7).forEach(request => complete(request, request !== forcedPeriodic));
    await manual;
    await paint();
    assert.deepStrictEqual(rendered.at(-1).checks, ['daily']);
    assert.equal(rendered.at(-1).target_date, date);
    assert.equal(rendered.at(-1)._periodicError, 'HTTP 503');
    assert.equal(sandbox.currentCheckStatus.date, date);

    const storage = new Map(), nodes = {};
    sandbox.sessionStorage = {
        getItem: key => storage.get(key),
        setItem: (key, value) => storage.set(key, value),
        removeItem: key => storage.delete(key),
    };
    sandbox.window.LAYER1 = {userId:'7'};
    sandbox.document.getElementById = id => (nodes[id] ||= {});
    const normal = {name:'정상 카드', check_type:'youtube', status:'OK', actual:123,
        display_group:'daily', is_target_date:true, categories:[{sku:'internal detail'}]};
    const seed = () => sandbox.saveDailyPreview({checks:[
        normal, {...normal, name:'오류 카드', status:'ERROR'},
        {...normal, name:'보류 카드', status:'POLICY_PENDING'},
        {...normal, name:'기간 카드', display_group:'periodic'}
    ]}, date, null, false);
    seed();
    const raw = [...storage.values()][0];
    assert.deepStrictEqual(JSON.parse(raw).cards, [{name:normal.name, count:123}]);
    assert(!raw.includes('internal detail'));
    assert.equal(sandbox.takeDailyPreview('2026-09-17', true), '');
    seed();
    sandbox.window.LAYER1.userId = '8';
    assert.equal(sandbox.takeDailyPreview(date, true), '');
    sandbox.window.LAYER1.userId = '7';
    seed();
    const key = [...storage.keys()][0];
    storage.set(key, JSON.stringify({...JSON.parse(raw), confirmedAt:TestDate.now() - 5*60*1000}));
    assert.equal(sandbox.takeDailyPreview(date, true), '');

    seed();
    const reopened = sandbox.loadStats(false, true);
    assert(nodes['daily-checks-list'].innerHTML.includes('data-confirmed-preview'));
    assert(nodes['daily-checks-list'].innerHTML.includes('마지막 정상 확인'));
    assert(nodes['daily-checks-list'].innerHTML.includes('재조회 중'));
    assert.equal(storage.size, 0, 'consumption precedes the fresh read');
    const failedDaily = requests.at(-1);
    const consoleError = sandbox.console.error;
    sandbox.console = {...console, error() {}};
    complete(failedDaily, false);
    await flush();
    await paint();
    await paint();
    requests.slice(-7).forEach(request => complete(request));
    await reopened;
    await paint();
    sandbox.console = {...console, error:consoleError};
    assert.equal(rendered.at(-1)._dailyError, 'HTTP 503');
    assert.equal(storage.size, 0, 'a failed recheck cannot revive consumed normal results');
    seed();
    const manualWithoutPreview = sandbox.loadStats(true, true);
    assert(!nodes['daily-checks-list'].innerHTML.includes('data-confirmed-preview'));
    assert.equal(storage.size, 0, 'manual removes previous verification before reading');
    complete(requests.at(-1));
    await flush();
    await paint();
    await paint();
    requests.slice(-7).forEach(request => complete(request));
    await manualWithoutPreview;
    await paint();
    console.log('Layer1: single daily primer, paint barrier, totals, stale dates, full manual and periodic failure passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
