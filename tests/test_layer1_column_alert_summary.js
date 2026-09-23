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
    for (const id of ['l1-column-alert-catalog','l1-column-alert-link','l1-column-alert-total','l1-column-alert-breakdown']) nodes.set(id, new Element());
    nodes.get('l1-column-alert-catalog').textContent = JSON.stringify([{country:'SEA',product:'TV',retailers:['Amazon','Bestbuy','Walmart']}]);
    const menu = new Element(), pending = [], events = {};
    const sandbox = {
        console, URLSearchParams, AbortController, Intl, Date, structuredClone, LAYER1:{section},
        document:{getElementById:id => nodes.get(id) || null, querySelector:() => menu, createElement:() => new Element(), addEventListener:(k,fn) => {events[k] = fn;}},
        fetch:(url,options) => new Promise(resolve => pending.push({url,options,resolve})),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(read('static/js/sidebar.js'), sandbox);
    vm.runInContext(read(path + 'column-alert-cache.js'), sandbox);
    vm.runInContext(read(path + 'column-alert-summary.js'), sandbox);
    const respond = (req, statuses, ok = true) => req.resolve({ok,json:async () => ({comparisons:statuses.map(status => ({status}))})});
    return {sandbox,nodes,menu,pending,respond,events,badge:() => menu.querySelector('.sidebar-issue-badge')};
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
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '조회 실패');
    assert.equal(s.badge(), null, 'failure cannot look like zero or a complete count');
    const count = s.pending.length;
    await s.sandbox.ColumnAlertSummary.load('2099-01-01');
    assert.equal(s.pending.length, count, 'future inspection dates do not query unsupported API dates');
    assert.equal(s.nodes.get('l1-column-alert-total').textContent, '조회 대기');
    assert.equal(s.nodes.get('l1-column-alert-link').attributes['aria-disabled'], 'true');

    const detail = setup('retail');
    detail.nodes.delete('l1-column-alert-link'); detail.nodes.delete('l1-column-alert-total'); detail.nodes.delete('l1-column-alert-breakdown');
    const detailRun = detail.sandbox.ColumnAlertSummary.load('2026-09-23');
    detail.respond(detail.pending[0], ['abnormal']); detail.respond(detail.pending[1], []); await tick();
    detail.respond(detail.pending[2], []); await detailRun;
    assert.equal(detail.badge().textContent, '1', 'non-dashboard Layer 1 pages also show a badge');
    assert.equal(setup('column_alerts').sandbox.ColumnAlertSummary, undefined, 'avoid a second set of queries on the alert page');

    const stats = setup('column_statistics');
    stats.nodes.set('ccs-filters', new Element()); stats.nodes.set('ccs-date', new Element());
    stats.nodes.get('ccs-date').value = '2026-09-23';
    stats.events.DOMContentLoaded();
    assert.equal(stats.pending.length, 2, 'statistics pages load without common FilterBar');
    stats.nodes.get('ccs-date').value = '2026-09-22'; stats.nodes.get('ccs-filters').listeners.submit();
    assert(stats.pending[0].options.signal.aborted);
    assert(stats.pending[2].url.includes('date=2026-09-22'));
    console.log('Layer1 column alert summary: global badge, totals, links, loading, retries, failures, stale dates and statistics pages passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
