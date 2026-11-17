const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const baseTemplate = fs.readFileSync('apps/dx/dx_layer1/templates/base_layer1.html','utf8');
for (const asset of ['collection-volume','retail-review']) {
    assert(baseTemplate.includes(`dx_layer1/js/${asset}.js' %}?v=20261117-costco-laundry-bsr`),
        `${asset} must invalidate the former exact-100 browser cache`);
}
let saved = [], previous = [], day = '2026-10-13';
const context = {document:{}, console, AbortController, setTimeout, clearTimeout,
    esc: String, fetch:async()=>({ok:true,json:async()=>({date:day,reviews:saved,previous_reviews:previous})})};
context.window = context;
vm.createContext(context);
for (const name of ['layer1-common','collection-volume','retail-review','retail-status']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer1/static/dx_layer1/js/${name}.js`, 'utf8'),context);
}
const review = context.L1.retailReview;
context.getSelectedDate = () => day;
function fixture(bsr=99, observation='observing', status='OK', retailer='Costco', country='SEA', product='REF') {
    const source = day==='2026-10-13'?'2026-10-12':'2026-10-13';
    const row = {retailer,status,batch_id:'batch-'+day,batch_count:1,main_count:300,bsr_count:bsr,count:300};
    const cat = {name:product,source_date:source,time_slots:[{name:'일일',retailers:[row]}]};
    const check = {check_type:country==='SEG'?'seg_retail':'retail',is_target_date:true,source_date:source,categories:[cat],phase:'complete'};
    const data = {checks:[check],summary:{failed:1}};
    const payload = {policy_version:4,inspection_date:day,snapshots:[{country,available:true,source_date:source,
        rows:[{product,retailer,slot:'일일',observation_state:observation,observation_prior_days:3,
            rules:{main:{rule:'median_28d',baseline:300,days:5,low_percent:30}}}]}]};
    context.L1.collectionVolume.decorate(data,payload,day);
    review.decorate(data,day);
    return {row,cat,check,data,payload};
}
(async()=>{
    await review.load(day);
    for (const observation of ['observing', 'ready', 'unknown']) {
        const mismatch = fixture(100, observation);
        mismatch.row.main_count = 99;
        context.L1.collectionVolume.decorate(mismatch.data, mismatch.payload, day);
        review.decorate(mismatch.data, day);
        assert.equal(mismatch.row.status, 'VOLUME_LOW');
        assert.equal(mismatch.check.status, 'VOLUME_LOW');
        assert.equal(mismatch.data.summary.failed, 1);
        assert(context.getStatusBadge(mismatch.row.status, mismatch.row).includes('이상'));
        assert(mismatch.row._reviewReasons.some(reason => reason.includes('MAIN 99건 / BSR 100건')));
        review.decorate(mismatch.data, day);
        assert.equal(mismatch.row.status, 'VOLUME_LOW', 'observation/repeated review decoration cannot soften MAIN < BSR');
    }
    for (const [country,retailer,product] of [['SEG','Expert','TV'],['SEG','Expert','REF'],['SEG','Expert','LDY'],['SEA','Costco','REF'],['SEA','Bestbuy','LDY_DRYER']]) {
        const normal=fixture(100,'observing','OK',retailer,country,product);
        assert.strictEqual(normal.row.status,'OK',`${country} ${retailer} ${product} 300/100 needs no manual review`);
        assert(!normal.row._reviewContext);
        assert.strictEqual(normal.check.status,'OK');
        assert(!context.L1.retailStatus.bsrCell(normal.row,100).includes('l1-review-count'));
        assert.strictEqual(fixture(99,'observing','OK',retailer,country,product).row.status,'VOLUME_REVIEW');
    }
    for (const product of ['LDY','LDY_DRYER']) {
        const laundry=fixture(99,'observing','OK','Costco','SEA',product);
        assert.equal(laundry.row.status,'OK');
        assert(!laundry.row.volume_alerts.some(a=>a.metric==='bsr'));
        assert(!laundry.row._reviewContext);
    }
    const otherNew=fixture(100,'observing','OK','Other');
    assert.strictEqual(otherNew.row.status,'OK');
    assert.strictEqual(otherNew.check.status,'OK');
    assert(context.L1.retailStatus.render(otherNew.check,0,'retail').includes('관찰 중'));
    assert(context.getStatusBadge(otherNew.check.status,otherNew.check).includes('정상'));
    assert(!context.getStatusBadge(otherNew.check.status,otherNew.check).includes('검증 대기'));
    assert(!otherNew.row._reviewContext,'observation alone must not create review work');
    assert(!otherNew.row.volume_alerts.length);
    // Screenshot regression: old exact-100 approvals must not turn current
    // median-normal Costco 74/97 counts into blue manual review cells.
    for (const [product,main,bsr,total,mainBasis,bsrBasis] of [
        ['LDY',74,74,77,72.5,72], ['LDY_DRYER',109,97,109,109,100]]) {
        previous=[{active:true,context:{date:'2026-10-12',source_date:'2026-10-11',country:'SEA',
            product,retailer:'Costco',slot:'일일',counts:[main,bsr,total,1],
            basis:JSON.stringify({alerts:[{metric:'bsr',actual:bsr,baseline:100,exact:true,rule:'fixed_100'}]})}}];
        await review.load(day);
        const current=fixture(bsr,'ready','OK','Costco','SEA',product);
        Object.assign(current.row,{main_count:main,count:total});
        current.payload.snapshots[0].rows[0].rules={
            main:{rule:'median_28d',baseline:mainBasis,days:28,low_percent:30,review_percent:15,high_percent:30},
            bsr:{rule:'median_28d',baseline:bsrBasis,days:28,low_percent:30,high_percent:30,high_status:'VOLUME_LOW'}};
        context.L1.collectionVolume.decorate(current.data,current.payload,day);
        review.decorate(current.data,day);
        assert.equal(current.row.status,'OK');
        assert.equal(current.row.volume_alerts.length,0);
        assert(!current.row._reviewContext);
        assert(!context.L1.retailStatus.bsrCell(current.row,bsr).includes('확인 필요'));
    }
    previous=[];
    await review.load(day);
    let f=fixture();
    assert.strictEqual(f.row.status,'VOLUME_REVIEW');
    assert.strictEqual(f.row._reviewContext.product,'REF');
    assert(context.L1.retailStatus.bsrCell(f.row,99).includes('l1-review-count'));
    assert(context.L1.retailStatus.bsrCell(f.row,99).includes('확인 필요'));
    assert.strictEqual(f.check.status,'VOLUME_REVIEW');
    assert.strictEqual(f.data.summary.failed,0);
    const originalContext=JSON.stringify(f.row._reviewContext);
    review.decorate(f.data,day);
    assert.strictEqual(JSON.stringify(f.row._reviewContext),originalContext,'rerenders must not duplicate reasons');
    saved=[{context:JSON.parse(originalContext),active:true,revision:1,history:[{action:'confirm',memo:'원본99건 확인',username:'tester',at:'2026-10-13T01:00:00Z'}]}];
    await review.load(day); review.decorate(f.data,day);
    assert(review.reviewed(f.row));
    assert(context.L1.retailStatus.bsrCell(f.row,99).includes('정상 확인'));
    assert(review.badge(f.cat,f.cat.status).includes('정상 확인'));
    previous=saved; saved=[]; day='2026-10-14';
    await review.load(day);
    f=fixture(99,'ready');
    assert.strictEqual(f.row.status,'VOLUME_REVIEW','same confirmed count remains reviewable after observation');
    assert(!review.reviewed(f.row),'yesterday must never confirm today');
    assert(f.row._previousReview);
    assert.strictEqual(fixture(98,'ready').row.status,'VOLUME_LOW','changed count is a fresh anomaly');
    assert(!fixture(99,'ready','OK','Other').row._previousReview);
    assert.strictEqual(fixture(99,'observing','ERROR').row.status,'ERROR');
    const missing=fixture(99,'observing');
    missing.row.main_count=missing.row.count=missing.row.bsr_count=0;
    context.L1.collectionVolume.decorate(missing.data,missing.payload,day);
    review.decorate(missing.data,day);
    assert.strictEqual(missing.row.status,'CRITICAL');
    assert(!missing.row._reviewContext);
    saved=[{context:JSON.parse(JSON.stringify(f.row._reviewContext)),active:false,revision:1,history:[{action:'reject',memo:'원본 불일치',username:'tester',at:'2026-10-14T01:00:00Z'}]}];
    await review.load(day); review.decorate(f.data,day);
    assert(review.rejected(f.row));
    assert(review.badge(f.cat,f.cat.status).includes('이상 확정'));
    assert.strictEqual(f.data.summary.failed,1);
    console.log('New collection review: 99 confirm, next-day pending, prior evidence, changed counts, missing/error and rejection passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
