const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const elements = {};
function element(id, options = []) {
    const listeners = {};
    const field = {
        id, options, value: '', hidden: false, disabled: false, textContent: '', className: '',
        addEventListener(name, callback) { listeners[name] = callback; },
        fire(name) { listeners[name]({preventDefault() {}}); },
        reportValidity() { return true; },
        get innerHTML() { return this.html || ''; },
        set innerHTML(value) {
            this.html = value;
            if (id === 'cs-retailer') {
                this.options = [...value.matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g)]
                    .map(match => ({value: match[1]}));
                this.value = '';
            }
        },
    };
    elements[id] = field;
    return field;
}
element('cs-country', ['', 'SEA'].map(value => ({value})));
element('cs-product', ['', 'TV'].map(value => ({value})));
element('cs-retailer');
element('cs-days', ['5', '7', '14', '49'].map(value => ({value})));
for (const id of ['cs-date', 'cs-filters', 'cs-message', 'cs-results', 'cs-summary',
    'cs-selection', 'cs-table-body', 'cs-updated']) element(id);

const weeks = [];
for (let week = 0; week < 7; week++) {
    const monday = new Date(Date.UTC(2026, 8, 14 - week * 7));
    const start = monday.toISOString().slice(0, 10);
    const daily = [];
    for (let offset = 0; offset < 7; offset++) {
        const date = new Date(monday.getTime() + offset * 86400000).toISOString().slice(0, 10);
        const state = date === '2026-09-17' ? 'pending' : date === '2026-09-18' ? 'unknown' : 'complete';
        const total = date === '2026-09-16' ? 0 : date === '2026-09-19' ? 300 : date === '2026-09-20' ? 400 : 100;
        daily.push({date, state, main: total, bsr: 50, total, comparison_state: 'ready', alerts: []});
    }
    weeks.push({start, rows: [{product: 'TV', retailer: 'Bestbuy', slot: 'daily', daily}]});
}

let onReady;
const requests = [];
const context = {
    document: {getElementById: id => elements[id], addEventListener: (_name, callback) => { onReady = callback; }},
    location: {pathname: '/dx/layer1/collection-statistics/', search: '?country=SEA&product=TV&retailer=Bestbuy&days=5&date=2026-09-20'},
    history: {replaceState() {}}, URLSearchParams, AbortController, setTimeout, clearTimeout,
    fetch: async url => {
        requests.push(new URL(url, 'http://local.test'));
        return {ok: true, json: async () => ({retailers: ['Bestbuy'], weeks, updated_at: null})};
    },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-statistics.js', 'utf8'), context);

async function flush() {
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
}

(async () => {
    await onReady();
    await flush();
    assert.strictEqual(elements['cs-retailer'].value, 'Bestbuy');
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 1);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/<tr>/g) || []).length, 5);
    assert(elements['cs-table-body'].innerHTML.startsWith('<tr><td>2026-09-16</td>'));
    assert(elements['cs-summary'].innerHTML.includes('233.3'), '0건은 평균에 포함하고 미집계는 제외');
    assert(elements['cs-table-body'].innerHTML.includes('2026-09-16'));
    assert(elements['cs-table-body'].innerHTML.includes('미수집'));

    elements['cs-days'].value = '14';
    elements['cs-days'].fire('change');
    elements['cs-filters'].fire('submit');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 2);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/<tr>/g) || []).length, 14);
    assert(elements['cs-table-body'].innerHTML.startsWith('<tr><td>2026-09-07</td>'));

    elements['cs-days'].value = '49';
    elements['cs-days'].fire('change');
    elements['cs-filters'].fire('submit');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 7);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/<tr>/g) || []).length, 49);
    assert(elements['cs-table-body'].innerHTML.startsWith('<tr><td>2026-08-03</td>'));
    elements['cs-date'].value = '2026-09-22';
    elements['cs-date'].fire('change');
    await flush();
    elements['cs-filters'].fire('submit');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 8,
        '49일이 주 중간에 끝나면 걸친 8개 주만 조회');
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/<tr>/g) || []).length, 49);
    console.log('Daily collection statistics: 5-day average and 2/7-week daily views passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
