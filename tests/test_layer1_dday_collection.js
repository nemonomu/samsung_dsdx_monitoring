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
        retailer: ['Walmart', 'HomeDepot', 'HomeDepot'][i],
        product: ['TV', 'REF', 'LDY'][i], status,
        scheduled_at: day + 'T13:00:00+09:00',
        count: status === 'received' ? 300 : status === 'error' ? null : 0,
        main_count: status === 'received' ? 300 : status === 'error' ? null : 0,
        bsr_count: status === 'received' ? 100 : status === 'error' ? null : 0,
        last_collected_at: status === 'received' ? day + ' 13:10:00' : null
    })) };
}
function respond(index, value) { requests[index].resolve({ ok: true, json: async () => value }); }
(async function() {
    const old = sandbox.loadDdayCollection('2026-09-20');
    const next = sandbox.loadDdayCollection('2026-09-21');
    respond(1, data('2026-09-21', ['received', 'waiting', 'scheduled']));
    await next;
    let html = elements['dday-collection-list'].innerHTML;
    for (const text of ['SEA Walmart TV', 'SEA HomeDepot REF', 'SEA HomeDepot LDY',
                        '수집 확인', '수집 대기', '수집 예정', '300건', '13:10:00 KST']) {
        assert(html.includes(text), text);
    }
    assert(!html.includes('정상'));
    assert(!html.includes('Amazon'));
    assert(sandbox.renderDdayCollection(data('2026-09-21', ['error', 'waiting', 'waiting'])).includes('조회 실패'));
    assert(!html.includes('수집 완료'));
    assert.strictEqual((html.match(/<details /g) || []).length, 4);
    assert.strictEqual((html.match(/<table class="ct ct-grid"/g) || []).length, 3);
    assert(html.includes('sentiment-category-header'));
    assert(html.includes('rt-sum'));
    assert(html.includes('status-badge ok'));
    assert.strictEqual((html.match(/<th>MAIN<\/th><th>BSR<\/th>/g) || []).length, 3);
    assert(html.includes('<td>300</td><td>100</td>'));
    const total = sandbox.ddaySummary(data('2026-09-21', ['received', 'received']).retailers);
    assert.strictEqual(total.mainCount, 600);
    assert.strictEqual(total.bsrCount, 200);
    assert.strictEqual(total.count, 600);
    assert.strictEqual(total.status, 'received');
    const costco = {source_date: '2026-10-06', retailers: [
        {retailer: 'Costco', product: 'TV', status: 'uncollected', count: 0, main_count: 0, bsr_count: 0},
        {retailer: 'Costco', product: 'REF', status: 'received', count: 205, main_count: 205, bsr_count: 100},
        {retailer: 'Costco', product: 'LDY', status: 'received', count: 304, main_count: 300, bsr_count: 100}
    ]};
    const costcoHtml = sandbox.renderDdayCollection(costco);
    const mismatch = {source_date:'2026-10-28', retailers:[
        {retailer:'HomeDepot', product:'REF', status:'received', count:266, main_count:266, bsr_count:100},
        {retailer:'Costco', product:'REF', status:'rank_mismatch', count:124, main_count:80, bsr_count:100,
         status_reason:'MAIN 80건 / BSR 100건 / MAIN이 BSR보다 적음', batch_id:'c20261028_001821'}
    ]};
    const mismatchHtml = sandbox.renderDdayCollection(mismatch);
    const costcoRow = mismatchHtml.match(/<tr aria-label="SEA Costco REF">(.*?)<\/tr>/s)[1];
    assert(costcoRow.includes('<td>80</td><td>100</td>'));
    assert(costcoRow.includes('status-badge critical'));
    assert(costcoRow.includes('>이상</span>'));
    assert(costcoRow.includes('MAIN 80건 / BSR 100건 / MAIN이 BSR보다 적음'));
    assert(!costcoRow.includes('수집 확인'));
    assert.strictEqual(sandbox.ddaySummary(mismatch.retailers).status, 'rank_mismatch');
    assert.strictEqual(sandbox.ddaySummary(mismatch.retailers).count, 390);
    assert.strictEqual((mismatchHtml.match(/>이상<\/span>/g) || []).length, 4, 'row, slot, category and country show the anomaly');
    assert.strictEqual(sandbox.ddaySummary([...mismatch.retailers, {status:'error'}]).status, 'error');
    mismatch.retailers[1] = {...mismatch.retailers[1], main_count:100, status:'received', status_reason:undefined};
    assert.strictEqual(sandbox.ddaySummary(mismatch.retailers).status, 'received');
    assert(!sandbox.renderDdayCollection(mismatch).includes('>이상</span>'));
    assert(costcoHtml.includes('SEA Costco TV'));
    assert(costcoHtml.includes('미수집'));
    assert.strictEqual(sandbox.ddaySummary(costco.retailers).count, 509);
    assert.strictEqual(sandbox.ddaySummary(costco.retailers).status, 'partial');
    assert.strictEqual(sandbox.ddaySummary([costco.retailers[0]]).status, 'uncollected');
    assert(costcoHtml.split('<div class="time-slots-container show">')[0].includes('일부 수집'));
    for (const [states, expected] of [
        [['uncollected', 'uncollected'], 'uncollected'],
        [['received', 'waiting'], 'partial'],
        [['received', 'scheduled'], 'partial'],
        [['scheduled', 'scheduled'], 'scheduled'],
        [['waiting', 'waiting'], 'waiting'],
        [['received', 'abnormal'], 'abnormal'],
        [['received', 'error'], 'error']
    ]) {
        assert.strictEqual(sandbox.ddaySummary(data('2026-10-27', states).retailers).status, expected);
    }
    costco.retailers[0].status = 'error';
    assert.strictEqual(sandbox.ddaySummary(costco.retailers).status, 'error');
    const afternoon = {source_date:'2026-10-26', retailers:[
        {retailer:'Bestbuy', product:'TV', status:'received', count:50, main_count:50, bsr_count:0,
         scheduled_at:'2026-10-26T13:00:00+09:00', scheduled_end_at:'2026-10-26T18:00:00+09:00'},
        {retailer:'Lowes', product:'REF', status:'waiting', count:0, main_count:0, bsr_count:0,
         scheduled_at:'2026-10-26T13:00:00+09:00', scheduled_end_at:'2026-10-26T18:00:00+09:00'}
    ]};
    const afternoonHtml = sandbox.renderDdayCollection(afternoon);
    for (const text of ['SEA Bestbuy TV','SEA Lowes REF','13:00 ~ 18:00 KST','일부 수집','수집 확인','수집 대기']) {
        assert(afternoonHtml.includes(text), text);
    }
    assert.strictEqual(sandbox.ddaySummary(afternoon.retailers).status, 'partial');
    assert.strictEqual(sandbox.ddaySummary([afternoon.retailers[0]]).status, 'received');
    assert.strictEqual(sandbox.ddaySummary([afternoon.retailers[1]]).status, 'waiting');
    const countries = {countries:[{...afternoon,country:'SEA'}, {
        country:'SEDA',source_date:'2026-10-30',display_time_basis:'DB 원본',collection_window:'KST 09:00~15:00',
        retailers:['TV','REF','LDY'].map(product => ({
            retailer:'Casas Bahia',product,status:'received',count:300,main_count:300,bsr_count:100,
            scheduled_at:'2026-10-30T09:00:00+09:00',scheduled_end_at:'2026-10-30T15:00:00+09:00',
            last_collected_at:'2026-10-30 09:28:13',last_collected_timezone:'DB 원본'
        }))
    }]};
    const countriesHtml = sandbox.renderDdayCollection(countries);
    for (const text of ['SEA Retail','SEDA Retail','SEDA Casas Bahia TV','SEDA Casas Bahia REF',
                        'SEDA Casas Bahia LDY','09:00 ~ 15:00 KST','09:28:13 DB 원본']) {
        assert(countriesHtml.includes(text),text);
    }
    assert(!countriesHtml.includes('Magalu'));
    assert(!countriesHtml.includes('SEDA Casas Bahia LDY_DRYER'));
    assert.strictEqual((countriesHtml.match(/id="dday-collection-date-SEA"/g)||[]).length,1);
    assert.strictEqual((countriesHtml.match(/id="dday-collection-date-SEDA"/g)||[]).length,1);
    respond(0, data('2026-09-20', ['waiting', 'waiting', 'waiting']));
    await old;
    assert.strictEqual(elements['dday-collection-list'].innerHTML, html);
    assert(html.includes('수집 대상일: 2026-09-21'));
    assert(html.includes('수집일: DB 원본 날짜 · 표시 시각: KST'));
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
