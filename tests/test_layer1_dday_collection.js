const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const elements = {};
const requests = [];
const sandbox = {
    document: { getElementById(id) { return elements[id] ||= { innerHTML: '', textContent: '' }; } },
    esc(value) { return String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'); },
    fetch(url) { return new Promise(resolve => requests.push({ url, resolve })); }
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/collection-status.js', 'utf8'), sandbox);
function data(day, states) {
    return { source_date: day, retailers: states.map((status, i) => ({
        retailer: ['Amazon', 'Walmart', 'HomeDepot', 'HomeDepot'][i],
        product: ['TV', 'TV', 'REF', 'LDY'][i], status,
        scheduled_at: day + 'T13:00:00+09:00',
        count: status === 'received' ? 300 : status === 'error' ? null : 0,
        last_collected_at: status === 'received' ? day + ' 13:10:00' : null
    })) };
}
function respond(index, value) { requests[index].resolve({ ok: true, json: async () => value }); }
(async function() {
    const old = sandbox.loadDdayCollection('2026-09-20');
    const next = sandbox.loadDdayCollection('2026-09-21');
    respond(1, data('2026-09-21', ['received', 'waiting', 'scheduled', 'error']));
    await next;
    let html = elements['dday-collection-list'].innerHTML;
    for (const text of ['SEA Amazon TV', 'SEA Walmart TV', 'SEA HomeDepot REF', 'SEA HomeDepot LDY',
                        '수집 확인', '수집 대기', '수집 예정', '조회 실패', '300건', '13:10:00 KST']) {
        assert(html.includes(text), text);
    }
    assert(!html.includes('정상'));
    assert(!html.includes('수집 완료'));
    respond(0, data('2026-09-20', ['waiting', 'waiting', 'waiting', 'waiting']));
    await old;
    assert.strictEqual(elements['dday-collection-list'].innerHTML, html);
    assert(elements['dday-collection-date'].textContent.includes('2026-09-21'));
    assert(requests[1].url.endsWith('date=2026-09-21'));
    const failed = sandbox.loadDdayCollection('2026-09-22');
    requests[2].resolve({ ok: false });
    await failed;
    assert(elements['dday-collection-list'].innerHTML.includes('조회 실패'));
    assert(!elements['dday-collection-list'].innerHTML.includes('수집 대기'));
    const template = fs.readFileSync('apps/dx/dx_layer1/templates/dx_layer1_dashboard.html', 'utf8');
    assert(template.indexOf('id="dday-collection-section"') > template.indexOf('id="period-checks-list"'));
    assert(template.includes('D-DAY 수집 현황'));
    console.log('D-DAY collection card states, placement and stale responses passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
