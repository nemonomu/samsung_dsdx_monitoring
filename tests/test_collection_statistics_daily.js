const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const elements = {};
function element(id, values = []) {
    const listeners = {};
    const field = {
        id, options: values.map(value => ({value})), value: values[0] || '',
        hidden: false, textContent: '', className: '',
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
element('cs-country', ['ALL', 'SEA', 'SEG']);
element('cs-product', ['ALL', 'TV', 'REF']);
element('cs-retailer', ['']);
element('cs-days', ['5', '7', '14', '49']);
for (const id of ['cs-date', 'cs-filters', 'cs-message', 'cs-results', 'cs-selection',
    'cs-table-head', 'cs-table-body', 'cs-updated']) element(id);

const weeks = [];
for (let week = 0; week < 8; week++) {
    const monday = new Date(Date.UTC(2026, 8, 14 - week * 7));
    const start = monday.toISOString().slice(0, 10);
    const rows = [];
    for (const [country, product, retailer, base] of [
        ['SEA', 'TV', 'Amazon', 240], ['SEA', 'TV', 'Bestbuy', 100],
        ['SEA', 'REF', 'Lowes', 300], ['SEG', 'TV', 'OTTO', 200],
    ]) {
        const daily = [];
        for (let offset = 0; offset < 7; offset++) {
            const date = new Date(monday.getTime() + offset * 86400000).toISOString().slice(0, 10);
            const state = retailer === 'Bestbuy' && date === '2026-09-17' ? 'pending'
                : retailer === 'Bestbuy' && date === '2026-09-18' ? 'unknown' : 'complete';
            const total = retailer === 'Bestbuy' && date === '2026-09-16' ? 0
                : retailer === 'Bestbuy' && date === '2026-09-19' ? 300
                    : retailer === 'Bestbuy' && date === '2026-09-20' ? 400 : base;
            const alerts = retailer === 'Bestbuy' && date === '2026-09-19' ? [{status: 'VOLUME_LOW'}]
                : retailer === 'OTTO' && date === '2026-09-20' ? [{status: 'VOLUME_HIGH'}] : [];
            daily.push({date, state, main: Math.max(0, total - 10), bsr: 50, total, comparison_state: 'ready', alerts});
        }
        rows.push({country, product, retailer, slot: 'daily', daily});
    }
    weeks.push({start, rows, updated_at: null});
}

let onReady;
const requests = [];
const context = {
    document: {getElementById: id => elements[id], addEventListener: (_name, callback) => { onReady = callback; }},
    location: {pathname: '/dx/layer1/collection-statistics/', search: '?date=2026-09-20'},
    history: {replaceState() {}}, URLSearchParams, AbortController, setTimeout, clearTimeout,
    fetch: async url => {
        requests.push(new URL(url, 'http://local.test'));
        return {ok: true, json: async () => ({weeks, updated_at: null})};
    },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-statistics.js', 'utf8'), context);

async function flush() {
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
}

(async () => {
    onReady();
    await flush();
    assert.strictEqual(elements['cs-country'].value, 'ALL');
    assert.strictEqual(elements['cs-product'].value, 'ALL');
    assert.strictEqual(elements['cs-retailer'].value, '');
    assert.strictEqual(elements['cs-days'].value, '5');
    assert.strictEqual(Number(requests[0].searchParams.get('weeks')), 1);
    assert.strictEqual(requests[0].searchParams.get('country'), 'ALL');
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-retailer-row"/g) || []).length, 4);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-country-row"/g) || []).length, 2);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-product-row"/g) || []).length, 3);
    assert.strictEqual((elements['cs-table-head'].innerHTML.match(/<th /g) || []).length, 22);
    assert(elements['cs-table-head'].innerHTML.includes('rowspan="2">총수량 하루 평균'));
    assert(elements['cs-table-head'].innerHTML.includes('>MAIN</th><th scope="col">BSR</th><th scope="col" class="cs-total-heading">총수량</th>'));
    assert.match(elements['cs-table-body'].innerHTML,
        /cs-country-row[^>]*><th[^>]*>SEA<\/th>.*cs-product-row[^>]*><th[^>]*>TV<\/th>.*Amazon.*Bestbuy.*cs-product-row[^>]*><th[^>]*>REF<\/th>.*Lowes.*cs-country-row[^>]*><th[^>]*>SEG<\/th>.*OTTO/s);
    assert(!elements['cs-table-body'].innerHTML.includes('<small>SEA · TV</small>'));
    assert(elements['cs-table-body'].innerHTML.includes('Bestbuy'));
    assert(elements['cs-table-body'].innerHTML.includes('Lowes'));
    assert(elements['cs-table-body'].innerHTML.includes('OTTO'));
    assert(elements['cs-table-body'].innerHTML.includes('233.3'), '0건은 평균에 포함하고 미집계는 제외');
    assert(elements['cs-table-body'].innerHTML.includes('3/5일 집계'));
    assert.match(elements['cs-table-body'].innerHTML,
        /<td class="cs-day-cell">230<\/td><td class="cs-day-cell">50<\/td><td class="cs-day-cell cs-total"[^>]*><strong>240<\/strong>/);
    assert(elements['cs-table-body'].innerHTML.includes('class="cs-day-cell cs-total low"'));
    assert(elements['cs-table-body'].innerHTML.includes('class="cs-day-cell cs-total high"'));
    assert(elements['cs-table-body'].innerHTML.includes('class="cs-day-cell cs-unavailable" colspan="3"'));

    elements['cs-country'].value = 'SEG';
    elements['cs-country'].fire('change');
    assert.strictEqual(requests.length, 1, '국가 필터는 저장된 결과를 즉시 사용');
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-retailer-row"/g) || []).length, 1);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-country-row"/g) || []).length, 1);
    assert(elements['cs-table-body'].innerHTML.includes('OTTO'));

    elements['cs-country'].value = 'SEA';
    elements['cs-country'].fire('change');
    elements['cs-product'].value = 'TV';
    elements['cs-product'].fire('change');
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-retailer-row"/g) || []).length, 2);
    assert.strictEqual((elements['cs-table-body'].innerHTML.match(/class="cs-product-row"/g) || []).length, 1);
    assert.deepStrictEqual(elements['cs-retailer'].options.map(item => item.value), ['', 'Amazon', 'Bestbuy']);

    elements['cs-days'].value = '14';
    elements['cs-days'].fire('change');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 2);
    assert.strictEqual((elements['cs-table-head'].innerHTML.match(/<th /g) || []).length, 58);
    assert(elements['cs-table-head'].innerHTML.includes('09-07'));

    elements['cs-days'].value = '49';
    elements['cs-days'].fire('change');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 7);
    assert.strictEqual((elements['cs-table-head'].innerHTML.match(/<th /g) || []).length, 198);
    elements['cs-date'].value = '2026-09-22';
    elements['cs-date'].fire('change');
    await flush();
    assert.strictEqual(Number(requests.at(-1).searchParams.get('weeks')), 8);
    console.log('Daily statistics: default all, per-retailer averages, local filters and 2/7-week dates passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
