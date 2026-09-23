const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor() {
        this.value = ''; this.textContent = ''; this.innerHTML = '';
        this.hidden = false; this.options = []; this.children = [];
        this.listeners = {}; this.attributes = {};
    }
    add(option) { this.options.push(option); }
    appendChild(child) { this.children.push(child); }
    insertBefore(child) { this.appendChild(child); child.remove = () => { this.children = this.children.filter(c => c !== child); }; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    querySelector(selector) {
        if (selector === 'button') return this.button;
        if (selector.includes('sidebar-issue-badge')) return this.children.find(c => c.className === 'sidebar-issue-badge') || null;
        return null;
    }
    reportValidity() { return true; }
}
const read = path => fs.readFileSync(path, 'utf8');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
    const nodes = new Map();
    const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
    get('cca-filters').button = new Element();
    get('cca-country').options.push({value: ''});
    get('cca-catalog').textContent = JSON.stringify([{country:'SEA', product:'TV', retailers:['Amazon','Bestbuy','Walmart']}]);
    get('cca-loading').hidden = true;
    const link = new Element(), pending = [];
    const sandbox = {
        console, URLSearchParams, AbortController, Intl, Date, structuredClone, LAYER1: {},
        Option: function(label, value) { return {label, value}; },
        location: {search:'?date=2026-09-23'}, history:{replaceState(){}},
        document: {getElementById:get, querySelector:() => link, createElement:() => new Element(), addEventListener(){}},
        fetch: (url, options) => new Promise(resolve => pending.push({url, options, resolve})),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(read('static/js/sidebar.js'), sandbox);
    vm.runInContext(read(base + 'column-alert-cache.js'), sandbox);
    vm.runInContext(read(base + 'column-comparison.js'), sandbox);
    vm.runInContext(read(base + 'column-alerts.js'), sandbox);
    const respond = (request, statuses, ok = true) => request.resolve({ok, json:async () => ({comparison_date:'2026-09-23', comparisons:statuses.map((status, i) => ({column:'field_'+i,status,history_days:7,baseline:10,current:1,ratio:10,delta:-9}))})});
    const badge = () => link.querySelector('.sidebar-issue-badge');
    const spinner = () => link.children.find(c => c.className === 'cca-sidebar-loading');
    const submit = () => get('cca-filters').listeners.submit({preventDefault(){}});
    return {get, pending, respond, badge, spinner, submit};
}
(async () => {
    const s = setup();
    assert.equal(s.pending.length, 2, 'preserve bounded request concurrency');
    assert.equal(s.get('cca-loading').hidden, false);
    assert.equal(s.get('cca-progress-bar').value, 0);
    assert.equal(s.spinner().hidden, false);
    assert.equal(s.badge(), null);
    s.respond(s.pending[0], ['abnormal', 'review']); await tick();
    assert.equal(s.get('cca-progress-bar').value, 1);
    assert.equal(s.pending.length, 3);
    assert.equal(s.badge(), null, 'partial results must not become a final badge');
    s.respond(s.pending[1], ['abnormal']); s.respond(s.pending[2], ['normal']); await tick();
    assert.equal(s.get('cca-loading').hidden, true);
    assert.equal(s.spinner().hidden, true);
    assert.equal(s.badge().textContent, '2', 'count abnormal only, not review');
    assert.match(s.get('cca-progress').textContent, /전체 3개 대상 확인 완료 · 이상 2건 · 확인 필요 1건/);
    s.get('cca-search').value = 'nonexistent'; s.get('cca-search').listeners.input();
    assert.equal(s.badge().textContent, '2', 'search does not change the completed query count');

    s.get('cca-date').listeners.change();
    assert.equal(s.badge(), null, 'changing criteria clears stale counts');
    assert.equal(s.get('cca-loading').hidden, true);
    s.submit();
    const stale = s.pending.slice(3);
    s.get('cca-date').listeners.change();
    assert(stale.every(r => r.options.signal.aborted));
    stale.forEach(r => s.respond(r, ['abnormal'])); await tick();
    assert.equal(s.badge(), null, 'aborted results cannot restore a count');
    assert.equal(s.get('cca-progress').textContent, '선택한 조건으로 조회해주세요.');

    const failed = setup();
    failed.respond(failed.pending[0], ['abnormal']);
    failed.respond(failed.pending[1], [], false); await tick();
    failed.respond(failed.pending[2], ['abnormal']); await tick();
    assert.equal(failed.badge(), null, 'a failed query cannot publish an incomplete final count');
    assert.equal(failed.spinner().hidden, true);
    assert.match(failed.get('cca-progress').textContent, /조회 실패 1개/);
    assert.match(failed.get('cca-progress').textContent, /일부 결과/);

    const zero = setup();
    zero.respond(zero.pending[0], ['review']); zero.respond(zero.pending[1], ['normal']); await tick();
    zero.respond(zero.pending[2], []); await tick();
    assert.equal(zero.badge(), null, 'hide zero abnormal count');
    assert.match(zero.get('cca-progress').textContent, /이상 0건 · 확인 필요 1건/);
    console.log('Column alert progress: loading, completion, abnormal-only counts, filters, cancellation, failures and zero passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
