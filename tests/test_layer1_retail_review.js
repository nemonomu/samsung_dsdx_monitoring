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
    assert(!badge().includes('source'), 'review memo is only visible in the dialog');
    assert.strictEqual(row.status, 'REVIEW', 'automatic status must remain intact');
    assert(!sandbox.L1.retailStatus.render(check, 0, 'sem_retail').includes('60건 감소'));
    const confirmed = JSON.parse(JSON.stringify(row));
    // A not-yet-operating retailer must not hide a completed normal review.
    const preview = {retailer:'AO', status:'PENDING', preview_mode:true,
        actual:0, main_count:0, bsr_count:0, batch_count:0};
    cat.retailers.push(preview); decorate();
    assert(badge(cat).includes('✓ 정상 확인'));
    assert(badge(check).includes('✓ 정상 확인'));
    assert.strictEqual(preview.status, 'PENDING');
    assert(sandbox.L1.retailStatus.rowBadge(preview).includes('수집 예정'));
    // On launch, the same missing retailer participates in the verdict again.
    preview.preview_mode = false; decorate();
    assert(badge(check).includes('대기중'));
    assert(!badge(check).includes('✓ 정상 확인'));
    preview.preview_mode = true; preview.status = 'ERROR'; decorate();
    assert(!badge(check).includes('✓ 정상 확인'));
    assert.strictEqual(check.status, 'ERROR');
    cat.retailers.pop(); decorate();
    // Confirmed Coppel plus uncollected siblings must show collection progress,
    // not a review warning with no outstanding reviews.
    const collecting = {retailer: 'HomeDepot', status: 'COLLECTING', batch_count: 0};
    cat.retailers.push(collecting); decorate();
    assert(badge().includes('✓ 정상 확인'));
    assert(badge(cat).includes('수집중'));
    assert(badge(check).includes('수집중'));
    assert(!badge(cat).includes('확인 필요'));
    collecting.status = 'VERIFYING'; decorate();
    assert(badge(cat).includes('검증 대기'));
    collecting.status = 'OK'; decorate();
    assert(badge(cat).includes('✓ 정상 확인'));
    collecting.batch_count = 2; decorate();
    assert(badge(cat).includes('확인 필요'));
    cat.retailers.pop(); decorate();
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
    for (const checkType of ['retail', 'seda_retail', 'siel_retail', 'seg_retail', 'sem_retail', 'tse_retail']) {
        check.check_type = checkType;
        row.status = 'VOLUME_LOW';
        row.observation_state = 'ready';
        row.volume_alerts = [{metric:'bsr', status:'VOLUME_LOW', baseline:100, actual:53,
            rule:'fixed_100', exact:false, reason:'BSR 53 / 100'}];
        row.bsr_count = 53;
        saved = []; await review.load(date); decorate();
        assert(row._reviewContext, checkType);
        assert(badge().includes('critical'));
        assert(badge().includes('L1.retailReview.open('));
        assert(sandbox.L1.retailStatus.rowBadge(row).includes('이상</button>'));
        saved = [record(row)]; await review.load(date); decorate();
        assert(badge(cat).includes('✓ 정상 확인'));
        const cell = sandbox.L1.retailStatus.bsrCell(row, 53);
        assert(cell.includes('cs-bsr-confirmed'));
        assert(!cell.includes('source'));
        assert(cell.includes('l1-review-label'));
        assert(!cell.includes('cs-bsr-low'));
        assert(!sandbox.L1.retailStatus.render(check, 0, checkType).includes('BSR 53 / 100'));
        saved[0].active = false;
        saved[0].history.push({action:'cancel', memo:'recheck'});
        await review.load(date); decorate();
        assert(badge().includes('이상</button>'));
        assert(sandbox.L1.retailStatus.bsrCell(row, 53).includes('cs-bsr-low'));
    }
    // Metric reviews from statistics also decorate the dashboard, without hiding siblings.
    check.check_type = 'retail';
    row.status = 'VOLUME_LOW'; row.volume_alerts = [
        {metric:'main',status:'VOLUME_REVIEW',baseline:200,actual:160,reason:'MAIN review'},
        {metric:'bsr',status:'VOLUME_LOW',baseline:100,actual:53,rule:'fixed_100',exact:true,reason:'BSR low'}];
    saved=[];await review.load(date);decorate();
    const metricContext={...JSON.parse(JSON.stringify(row._reviewContext)),version:2,environment:'production',metric:'bsr',
        basis:JSON.stringify({alerts:[['bsr',100,53,'fixed_100',true,'VOLUME_LOW']]})};
    saved=[{context:metricContext,active:true,revision:1,history:[{action:'confirm',at:'2026-10-01T01:00:00Z',memo:'checked'}]}];
    await review.load(date);decorate();
    assert(review.reviewed(row,'bsr'));assert(!review.reviewed(row,'main'));assert(!review.reviewed(row));
    assert(badge().includes('확인 필요'));assert(!badge().includes('>이상</button>'));
    assert(sandbox.L1.retailStatus.bsrCell(row,53).includes('cs-bsr-confirmed'));
    saved[0].active=false;saved[0].history.push({action:'cancel',at:'2026-10-01T02:00:00Z'});
    await review.load(date);decorate();assert(!review.reviewed(row,'bsr'));
    // Production legacy confirmations must survive retirement of fixed-100 BSR,
    // including the same BSR count already confirmed under the retired rule.
    for (const [product,source,inspection,main,bsr,total] of [
        ['LDY','2026-11-11','2026-11-12',67,72,77],
        ['LDY','2026-11-12','2026-11-13',72,74,78],
        ['LDY_DRYER','2026-11-15','2026-11-16',94,99,119],
        ['LDY','2026-10-23','2026-10-24',73,66,73],
        ['LDY','2026-10-24','2026-10-25',72,69,73],
        ['LDY','2026-10-26','2026-10-27',73,69,73]]) {
        date=inspection;
        const laundry={retailer:'Costco',main_count:main,bsr_count:bsr,actual:total,batch_id:'batch1',batch_count:1,
            status:'VOLUME_LOW',_volumeBaseStatus:'OK',observation_state:'ready',
            volume_alerts:[{metric:'main',baseline:bsr,actual:main,rule:'main_lt_bsr',status:'VOLUME_LOW',reason:'MAIN below BSR'}]};
        const laundryCat={name:product,source_date:source,retailers:[laundry]};
        const laundryData={checks:[{check_type:'retail',categories:[laundryCat]}]};
        const refresh=async()=>{await review.load(date);review.decorate(laundryData,date);};
        saved=[];await refresh();
        const legacy=record(laundry);
        const oldBasis=JSON.parse(legacy.context.basis);
        oldBasis.alerts.push({metric:'bsr',baseline:100,actual:bsr,rule:'fixed_100',exact:true,status:'VOLUME_REVIEW'});
        legacy.context.basis=JSON.stringify(oldBasis);
        saved=[legacy];await refresh();
        assert(review.reviewed(laundry,'main'),`${product} ${source} must retain MAIN confirmation`);
        assert(badge(laundry).includes('✓ 정상 확인'));
        laundry.volume_alerts.push({metric:'bsr',baseline:50,actual:bsr,rule:'median_28d',status:'VOLUME_LOW'});
        await refresh();
        assert(review.reviewed(laundry,'main'));assert(review.reviewed(laundry,'bsr'));
        assert(review.reviewed(laundry));
        assert(badge(laundry).includes('✓ 정상 확인'));
        assert(!sandbox.L1.retailStatus.bsrCell(laundry,bsr).includes('cs-bsr-low'));
        assert(sandbox.L1.retailStatus.bsrCell(laundry,bsr).includes('cs-bsr-confirmed'));
        laundry.bsr_count=bsr+1;await refresh();assert(!review.reviewed(laundry,'bsr'));
        laundry.bsr_count=bsr;await refresh();assert(review.reviewed(laundry,'bsr'));
        laundry.volume_alerts[1]={...laundry.volume_alerts[1],rule:'another_policy'};
        await refresh();assert(!review.reviewed(laundry,'bsr'));
        laundry.volume_alerts= laundry.volume_alerts.slice(0,1);
        laundry.volume_alerts[0]={...laundry.volume_alerts[0],baseline:bsr+1};
        await refresh();assert(!review.reviewed(laundry,'main'));
        laundry.volume_alerts[0]={...laundry.volume_alerts[0],baseline:bsr};
        await refresh();assert(review.reviewed(laundry,'main'));
        laundry.main_count=main+1;await refresh();assert(!review.reviewed(laundry,'main'));
        laundry.main_count=main;
        for (const other of ['TV','REF']) {
            laundryCat.name=other;legacy.context.product=other;
            await refresh();assert(!review.reviewed(laundry,'main'));
        }
        laundryCat.name=product;legacy.context.product=product;
        await refresh();assert(review.reviewed(laundry,'main'));
        saved.push({context:{...laundry._reviewContext,version:2,metric:'main',environment:'production',
            basis:JSON.stringify({alerts:[['main',bsr,main,'main_lt_bsr',false,'VOLUME_LOW']]})},active:false,
            history:[{action:'cancel',at:'2026-11-17T01:00:00Z',memo:'recheck'}]});
        await refresh();assert(!review.reviewed(laundry,'main'),'later cancellation wins');
    }
    console.log('Layer1 review scopes, tooltips, aggregates, cancellation and escaping passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
