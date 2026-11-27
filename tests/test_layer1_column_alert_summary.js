const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const read = p => fs.readFileSync(p, 'utf8');
const path = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const tick = () => new Promise(resolve => setImmediate(resolve));
class Element {
    constructor() {
        this.textContent = ''; this.innerHTML = ''; this.children = []; this.attributes = {};
        this.listeners = {}; this.hidden = false; this.value = '';
        const classes = new Set();
        this.classList = {add:v => classes.add(v), remove:v => classes.delete(v), contains:v => classes.has(v)};
    }
    appendChild(child) {this.children.push(child);}
    insertBefore(child) {this.appendChild(child); child.remove = () => {this.children = this.children.filter(c => c !== child);};}
    querySelector(selector) {return selector.includes('sidebar-issue-badge') ? this.children.find(c => c.className === 'sidebar-issue-badge') || null : null;}
    setAttribute(k, v) {this.attributes[k] = v;}
    removeAttribute(k) {delete this.attributes[k]; if (k === 'href') delete this.href;}
    addEventListener(k, fn) {this.listeners[k] = fn;}
    reportValidity() {return true;}
}
function setup(section = 'dashboard') {
    const nodes = new Map();
    for (const id of ['l1-column-alert-catalog','l1-column-alert-link','l1-column-alert-total','l1-column-alert-breakdown','l1-column-alert-history','l1-column-alert-history-detail']) nodes.set(id, new Element());
    nodes.get('l1-column-alert-catalog').textContent = JSON.stringify([{country:'SEA',product:'TV',retailers:['Amazon','Bestbuy','Walmart']}]);
    const menu = new Element(), pending = [], events = {};
    const sandbox = {
        console, URLSearchParams, AbortController, Intl, Date, structuredClone, LAYER1:{section},
        document:{getElementById:id => nodes.get(id) || null, querySelector:() => menu, createElement:() => new Element(),
            addEventListener:(k,fn) => {
                const preceding = events[k];
                events[k] = event => { preceding?.(event); fn(event); };
            }},
        fetch:(url,options) => new Promise(resolve => pending.push({url,options,resolve})),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(read('static/js/sidebar.js'), sandbox);
    vm.runInContext(read(path + 'column-alert-cache.js'), sandbox);
    vm.runInContext(read(path + 'column-alert-summary.js'), sandbox);
    const respond = (req, statuses, ok = true, extra = {}) => req.resolve({ok,json:async () => ({comparisons:statuses.map(status => ({status})), ...extra})});
    return {sandbox,nodes,menu,pending,respond,events,badge:() => menu.querySelector('.sidebar-issue-badge')};
}
function setupStats(search) {
    const stats = setup('column_statistics');
    for (const id of ['filters', 'catalog', 'date', 'country', 'product', 'retailer', 'days', 'message',
        'results', 'detail', 'overview', 'groups', 'overview-filters', 'retailer-detail', 'selection', 'sku-note',
        'status-filters', 'updated']) {
        stats.nodes.set('ccs-' + id, new Element());
    }
    const button = new Element(), body = new Element(), historyChanges = [];
    body.querySelectorAll = () => [];
    const panel = {thead: new Element(), tbody: body, '.ccs-scroll': new Element(), '.ccs-status-filters': new Element()};
    stats.nodes.get('ccs-detail').querySelector = selector => panel[selector];
    stats.nodes.get('ccs-filters').querySelector = () => button;
    stats.nodes.get('ccs-groups').replaceChildren = () => {};
    stats.nodes.get('ccs-catalog').textContent = stats.nodes.get('l1-column-alert-catalog').textContent;
    stats.nodes.get('ccs-days').value = '7';
    Object.assign(stats.sandbox, {
        location:{search}, history:{replaceState: (_state, _title, url) => historyChanges.push(url)},
        Option:class {}, ColumnComparison:{tabs:() => ''}, ColumnStatisticsNotes:{reset() {}, render() {}},
    });
    const fetch = stats.sandbox.fetch;
    stats.sandbox.fetch = (url, options) => {
        const response = fetch(url, options);
        stats.pending.at(-1).resultsHidden = stats.nodes.get('ccs-results').hidden;
        return response;
    };
    for (const id of ['country', 'product', 'retailer']) stats.nodes.get('ccs-' + id).replaceChildren = () => {};
    vm.runInContext(read(path + 'column-statistics.js'), stats.sandbox);
    stats.events.DOMContentLoaded();
    stats.submit = () => stats.nodes.get('ccs-filters').listeners.submit({preventDefault() {}});
    return {...stats, historyChanges};
}
(async () => {
    const s = setup();
    const run = s.sandbox.ColumnAlertSummary.load('2026-09-23');
    assert.equal(s.pending.length, 2);
    assert.equal(s.sandbox.ColumnAlertSummary.load('2026-09-23'), run, 'deduplicate same date');
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '조회 중');
    s.respond(s.pending[0], ['abnormal','review','normal']); await tick();
    assert.equal(s.badge(), null, 'do not publish partial counts');
    s.respond(s.pending[1], ['abnormal','review']); s.respond(s.pending[2], ['review','insufficient']); await run;
    assert.equal(s.badge().textContent, '2');
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '5', 'dashboard includes abnormal and review');
    assert.match(s.nodes.get('l1-column-alert-breakdown').innerHTML, /이상 2/);
    assert.match(s.nodes.get('l1-column-alert-breakdown').innerHTML, /확인 필요 3/);
    assert.equal(s.nodes.get('l1-column-alert-link').href, '/dx/layer1/column-alerts/?date=2026-09-23');
    assert.equal(s.menu.href, s.nodes.get('l1-column-alert-link').href);
    assert(!s.menu.href.includes('country='), 'dashboard links must show all countries and products');

    const older = s.sandbox.ColumnAlertSummary.load('2026-09-22');
    const oldRequests = s.pending.slice(3);
    const newer = s.sandbox.ColumnAlertSummary.load('2026-09-21');
    assert(oldRequests.every(r => r.options.signal.aborted));
    oldRequests.forEach(r => s.respond(r, ['abnormal','abnormal'])); await older;
    assert.equal(s.badge(), null, 'date change clears old badge');
    s.respond(s.pending[5], ['review']); s.respond(s.pending[6], []); await tick();
    s.respond(s.pending[7], []); await newer;
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '1');
    assert.equal(s.badge(), null, 'review-only totals do not add a red abnormal badge');
    assert(s.menu.href.endsWith('2026-09-21'));

    const retry = s.sandbox.ColumnAlertSummary.load('2026-09-21', true);
    s.respond(s.pending[8], ['abnormal']); s.respond(s.pending[9], [], false); await tick();
    s.respond(s.pending[10], []); await retry;
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '일부 조회 실패');
    assert.match(s.nodes.get('l1-column-alert-breakdown').textContent, /2\/3개 대상 조회 완료/);
    assert.equal(s.badge(), null, 'failure cannot look like zero or a complete count');
    const count = s.pending.length;
    await s.sandbox.ColumnAlertSummary.load('2099-01-01');
    assert.equal(s.pending.length, count, 'future inspection dates do not query unsupported API dates');
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '조회 대기');
    assert.equal(s.nodes.get('l1-column-alert-link').attributes['aria-disabled'], 'true');

    const history = setup();
    const historyRun = history.sandbox.ColumnAlertSummary.load('2026-09-23');
    history.respond(history.pending[0], ['abnormal'], true, {issue_history_error:true,
        issue_history_diagnostic:{code:'issue_storage_busy',error:'이력 DB가 다른 작업에 사용 중입니다.',action:'잠시 후 다시 조회하세요.'}});
    history.respond(history.pending[1], ['review']); await tick();
    history.respond(history.pending[2], []); await historyRun;
    assert.equal(history.nodes.get('l1-column-alert-total').textContent, '2');
    assert.equal(history.badge().textContent, '1', 'storage failure must preserve fetched abnormal counts');
    assert.match(history.nodes.get('l1-column-alert-breakdown').innerHTML, /확인 필요 1/);
    assert.equal(history.nodes.get('l1-column-alert-history').hidden, false);
    assert.match(history.nodes.get('l1-column-alert-history-detail').textContent, /1개 대상/);
    assert.match(history.nodes.get('l1-column-alert-history-detail').textContent, /SEA · TV · Amazon/);
    assert.match(history.nodes.get('l1-column-alert-history-detail').textContent, /이력 DB가 다른 작업에 사용 중/);
    assert.match(history.nodes.get('l1-column-alert-history-detail').textContent, /잠시 후 다시 조회/);
    await history.sandbox.ColumnAlertSummary.load('2099-01-01');
    assert.equal(history.nodes.get('l1-column-alert-history').hidden, true, 'date changes clear stale storage warnings');

    const detail = setup('retail');
    detail.nodes.delete('l1-column-alert-link'); detail.nodes.delete('l1-column-alert-total'); detail.nodes.delete('l1-column-alert-breakdown');
    const detailRun = detail.sandbox.ColumnAlertSummary.load('2026-09-23');
    detail.respond(detail.pending[0], ['abnormal']); detail.respond(detail.pending[1], []); await tick();
    detail.respond(detail.pending[2], []); await detailRun;
    assert.equal(detail.badge().textContent, '1', 'non-dashboard Layer 1 pages also show a badge');
    assert.equal(setup('column_alerts').sandbox.ColumnAlertSummary, undefined, 'avoid a second set of queries on the alert page');

    const collection = setup('collection_statistics');
    collection.nodes.set('cs-filters', new Element()); collection.nodes.set('cs-date', new Element());
    collection.nodes.get('cs-date').value = '2026-09-23';
    collection.events.DOMContentLoaded();
    assert.equal(collection.pending.length, 2, 'collection statistics still loads the shared badge');

    const stats = setupStats('?country=SEA&date=2026-09-23');
    assert.equal(stats.pending.length, 1, 'selected scope starts before global column requests');
    const date = stats.nodes.get('ccs-date');
    const {submit} = stats;
    date.value = '2026-09-22'; date.listeners.change(); submit();
    assert.equal(stats.pending.length, 2, 'an earlier date cannot start its global sweep');
    assert(stats.pending[0].options.signal.aborted);
    stats.pending[0].resolve({ok:true, json:async () => ({rows:[]})});
    await tick();
    assert.equal(stats.pending.length, 2, 'a late response from the old date does not resume the sweep');
    stats.pending[1].resolve({ok:true, json:async () => ({rows:[], country:'SEA', product:'all', retailer:'all', inspection_date:'2026-09-22'})});
    await tick();
    assert.equal(stats.nodes.get('ccs-results').hidden, false);
    assert.equal(stats.pending.length, 4);
    assert(stats.pending.slice(2).every(request => request.url.includes('date=2026-09-22')));
    assert(stats.pending.slice(2).every(request => request.resultsHidden === false), 'the selected result is visible before global requests');
    submit();
    assert.equal(stats.pending.length, 5, 'same-date manual retry also waits for the selected scope');
    assert(!stats.pending[4].url.includes('refresh='), 'manual overview keeps its existing request');
    assert(stats.pending.slice(2, 4).every(request => request.options.signal.aborted));
    stats.pending[4].resolve({ok:false, json:async () => ({error:'Failed selection'})});
    await tick();
    assert.equal(stats.nodes.get('ccs-message').textContent, 'Failed selection');
    assert.equal(stats.pending.length, 7, 'a selected-scope failure still allows the global badge to load');
    stats.respond(stats.pending[5], ['abnormal']);
    stats.respond(stats.pending[6], ['normal']);
    await tick();
    stats.respond(stats.pending[7], ['review']);
    await stats.sandbox.ColumnAlertSummary.load('2026-09-22');
    assert.equal(stats.badge().textContent, '1', 'selected-scope failure preserves the completed global badge');

    submit();
    date.value = '2026-09-21'; date.listeners.change();
    stats.pending[8].resolve({ok:true, json:async () => ({rows:[]})});
    await tick();
    assert.equal(stats.pending.length, 9, 'editing the date without submitting never resumes the old sweep');

    const narrow = setupStats('?country=SEA&product=TV&retailer=Amazon&date=2026-09-23');
    const selected = () => narrow.pending.filter(request => request.url.includes('days=7'));
    assert.equal(selected().length, 1);
    assert(!selected()[0].url.includes('refresh='), 'automatic detail entry uses the cache');
    narrow.submit();
    assert.equal(new URLSearchParams(selected()[1].url.split('?')[1]).get('refresh'), '1');
    assert(narrow.historyChanges.every(url => !url.includes('refresh=')), 'refresh is not part of the URL history');
    const scope = {country:'SEA', product:'TV', retailer:'Amazon'};
    selected()[1].resolve({ok:true, json:async () => ({
        ...scope, inspection_date:'2026-09-23', comparison_date:'2026-09-22', dates:[], columns:[], daily:[], comparisons:[],
    })});
    await tick();
    assert.equal(narrow.nodes.get('ccs-results').hidden, false);
    narrow.events['column-review-saved']({detail:{target:{...scope, source_date:'2026-09-22'}}});
    assert.equal(selected().length, 3, 'saving a review refreshes the displayed detail');
    assert(!selected()[2].url.includes('refresh='), 'automatic detail after saving a review uses the cache');
    const reviewed = setup();
    const reviewedRun = reviewed.sandbox.ColumnAlertSummary.load('2026-09-23');
    reviewed.respond(reviewed.pending[0], [], true, {comparisons:[
        {status:'abnormal',review:{active:true}}, {status:'review',review:{active:true}}, {status:'abnormal'}]});
    reviewed.respond(reviewed.pending[1], []); await tick();
    reviewed.respond(reviewed.pending[2], []); await reviewedRun;
    assert.equal(reviewed.nodes.get('l1-column-alert-total').textContent,'1');
    assert.equal(reviewed.badge().textContent,'1','confirmed columns no longer count as alerts');
    console.log('Layer1 column alert summary: global badge, totals, links, loading, retries, failures, stale dates and statistics pages passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
