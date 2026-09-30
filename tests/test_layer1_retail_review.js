const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = 'apps/dx/dx_layer1/static/dx_layer1/js/';
let saved = [], date = '2026-09-30';
const sandbox = {
    document: {}, localStorage: {}, console, AbortController, setTimeout, clearTimeout,
    esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    fetch: async () => ({ok: true, json: async () => ({date, reviews: saved})}),
};
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const name of ['layer1-common', 'collection-volume', 'retail-review', 'retail-status']) {
    vm.runInContext(fs.readFileSync(base + name + '.js', 'utf8'), sandbox);
}
const review = sandbox.L1.retailReview;
const row = {retailer: 'Coppel', main_count: 160, bsr_count: 100, actual: 160,
    expected_precise: 220, allowed_deviation: 50, history_day_count: 4,
    batch_id: 'c1', batch_count: 1, status: 'REVIEW', observation_state: 'observing'};
const cat = {name: 'LDY', source_date: date, status: 'REVIEW', retailers: [row]};
const check = {check_type: 'sem_retail', status: 'REVIEW', categories: [cat]};
const data = {checks: [check]};
function decorate() { review.decorate(data, date); }
function badge(item = row) { return sandbox.getStatusBadge(item.status, item); }
function record(item) {
    return {context: JSON.parse(JSON.stringify(item._reviewContext)), active: true, revision: 1,
        history: [{action: 'confirm', username: 'tester', at: '2026-09-30T03:00:00Z', memo: '<script>"source"</script>'}]};
}

(async () => {
    await review.load(date);
    decorate();
    assert(badge().includes('volume-review'));
    assert(badge().includes('MAIN 과거 4일 평균 220건'));
    assert(badge().includes('60건 감소'));
    assert(badge().includes('확인 필요'));
    assert(!badge().includes('warning'));
    assert(badge(cat).includes('미확인 1건'));
    saved = [record(row)];
    await review.load(date); decorate();
    assert(badge().includes('✓ 정상 확인'));
    assert(badge(cat).includes('✓ 정상 확인'));
    assert(badge(check).includes('✓ 정상 확인'));
    assert(!badge().includes('<script>'));
    assert(badge().includes('&quot;source&quot;'));
    assert.strictEqual(row.status, 'REVIEW', 'automatic status must remain intact');
    assert(!sandbox.L1.retailStatus.render(check, 0, 'sem_retail').includes('60건 감소'));
    const confirmed = JSON.parse(JSON.stringify(row));
    for (const [field, value] of [['batch_id', 'c2'], ['main_count', 159], ['expected_precise', 221], ['batch_count', 2]]) {
        row[field] = value; decorate();
        assert(!review.reviewed(row), field + ' change must reopen review');
        row[field] = confirmed[field];
    }
    date = '2026-10-01'; decorate(); assert(!review.reviewed(row));
    date = '2026-09-30'; decorate(); assert(review.reviewed(row));
    // A separate pending review prevents a green aggregate.
    const second = {...row, retailer: 'Liverpool', batch_id: 'l1'};
    cat.retailers.push(second); decorate();
    assert(badge(cat).includes('미확인 1건'));
    assert(!badge(cat).includes('>✓ 정상 확인'));
    second.status = 'CRITICAL'; cat.status = 'CRITICAL'; decorate();
    assert(badge(cat).includes('critical'));
    cat.retailers.pop(); cat.status = 'REVIEW';
    saved[0].active = false; await review.load(date); decorate();
    assert(!review.reviewed(row));
    assert(badge().includes('확인 필요'));
    row.status = 'VOLUME_REVIEW'; row._volumeBaseStatus = 'OK'; row.observation_state = 'ready';
    row.volume_alerts = [{metric: 'bsr', status: 'VOLUME_REVIEW', baseline: 100, actual: 84, percent: -16,
        reason: 'BSR 과거 중앙값 100개 / 수집 84개 / 15% 이상 감소 / 확인 필요'}];
    decorate();
    assert(badge().includes('15% 이상 감소'));
    saved = [record(row)]; await review.load(date); decorate();
    assert(sandbox.L1.retailStatus.bsrCell(row, 84).includes('✓ 정상 확인'));
    row.volume_alerts.push({metric: 'main', status: 'VOLUME_HIGH', reason: 'MAIN 30% 증가'});
    decorate(); assert(!review.reviewed(row), 'new reason must reopen review');
    assert(sandbox.getStatusBadge('OK').includes('>정상<'));
    assert(review.reasons({status: 'REVIEW', main_count: 0, expected: 40})[0].includes('MAIN 데이터가 없어'));
    console.log('Layer1 review scopes, tooltips, aggregates, cancellation and escaping passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
