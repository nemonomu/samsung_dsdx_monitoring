const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const flush = () => new Promise(resolve => setImmediate(resolve));
const day = '2026-10-23';
const basis = value => ({baseline:value, days:28, rule:'median_28d', low_percent:30, review_percent:15, high_percent:30});
function snapshot(main=199, bsr=100, total=204, date=day) {
    return {country:'SEA', inspection_date:date, source_date:'2026-10-22', live:true, available:true,
        rows:[{product:'LDY', retailer:'Lowes', slot:'일일', observation_state:'ready', rules:{main:basis(196), bsr:basis(100)}}],
        check:{check_type:'retail', inspection_date:date, source_date:'2026-10-22', status:'OK', actual:total,
            categories:[{name:'LDY', source_date:'2026-10-22', status:'OK', time_slots:[{name:'일일', status:'OK',
                retailers:[{retailer:'Lowes', status:'OK', collection_phase:'complete', count:total, batch_id:'recollected',
                    main_count:main, bsr_count:bsr, items:[{name:'Main Rank',count:main},{name:'BSR Rank',count:bsr}]}]}]}]}};
}
function setup(fetch) {
    let now=0, serial=0, modal=false;
    const timers=new Map(), events={}, documentEvents={};
    class TestDate extends Date {
        constructor(...args) { super(...(args.length ? args : [day + 'T12:00:00'])); }
        static now() { return now; }
    }
    const context={Date:TestDate,L1:{}, URLSearchParams, AbortController, console, fetch,
        document:{hidden:false, querySelector:()=>modal,
            addEventListener:(name,fn)=>{documentEvents[name]=fn;}, removeEventListener:name=>delete documentEvents[name]},
        window:{addEventListener:(name,fn)=>{events[name]=fn;}, removeEventListener:name=>delete events[name]},
        setTimeout(fn,ms){const id=++serial; timers.set(id,{fn,at:now+ms}); return id;},
        clearTimeout:id=>timers.delete(id)};
    vm.createContext(context);
    for (const file of ['collection-volume','live-collection']) vm.runInContext(fs.readFileSync(
        `apps/dx/dx_layer1/static/dx_layer1/js/${file}.js`,'utf8'),context);
    return {context,events,documentEvents,setModal(value){modal=value;},async tick(ms){
        now+=ms; for(const [id,t] of [...timers]) if(t.at<=now){timers.delete(id);t.fn();} await flush();
    }};
}
const response = item => ({ok:true,json:async()=>({inspection_date:item.inspection_date,policy_version:4,snapshots:[item]})});
(async()=>{
    let calls=0, current=snapshot(0,0,0);
    const env=setup(async(_url,options)=>{calls++;assert.equal(options.cache,'no-store');return response(current);});
    const data={summary:{},checks:[{...current.check,is_target_date:true,display_group:'daily'}]};
    const summaries={ldy:{inspection_date:day,source_date:'2026-10-22',summary:[{retailer:'Lowes',rows:[
        {time_slot:'일일',main:0,bsr:0,total:0}]}]}};
    const received=[];
    const poll=env.context.L1.liveCollection.poll(()=>({date:day,countries:['SEA']}),item=>{
        received.push(item);
        env.context.L1.liveCollection.applyDashboard(data,item);
        env.context.L1.collectionVolume.decorate(data,{inspection_date:day,policy_version:4,snapshots:[item]},day,summaries);
    });
    const row=()=>data.checks[0].categories[0].time_slots[0].retailers[0];
    await poll.refresh(); assert.equal(row().status,'CRITICAL');
    current=snapshot(); await env.tick(60000);
    assert.equal(row().status,'OK'); assert.equal(row().count,204);
    assert.equal(row()._volumeCounts,undefined,'Old SEA summary must not replace live counts');
    assert.equal(data.checks[0].display_group,'daily');
    current=snapshot(100,50,105); await env.tick(60000); assert.equal(row().status,'VOLUME_LOW');
    current=snapshot(0,0,0); await env.tick(60000); assert.equal(row().status,'CRITICAL');
    current=snapshot();current.rows[0].rules={}; await env.tick(60000);assert.equal(row().status,'INSUFFICIENT');
    env.context.fetch=async()=>{calls++;throw Error('offline');};
    await env.tick(60000);assert.equal(row().status,'ERROR');assert.equal(row().count,204);
    env.context.fetch=async()=>{calls++;return response(snapshot());};
    await env.tick(60000);assert.equal(row().status,'OK');
    env.context.document.hidden=true; env.documentEvents.visibilitychange();
    const before=calls;await env.tick(60000);assert.equal(calls,before);
    env.context.document.hidden=false;env.documentEvents.visibilitychange();await flush();assert.equal(calls,before+1);
    env.setModal(true);await env.tick(60000);assert.equal(calls,before+1);
    env.setModal(false);env.events.focus();await flush();assert.equal(calls,before+2);
    poll.stop();await env.tick(30000);assert.equal(calls,before+2);

    // Date switches abort an old request; even a server ignoring abort cannot overwrite the new date.
    let selected=day, resolveOld, active=0, peak=0;
    const race=setup((url,{signal})=>{
        const p=new URL(url,'http://test').searchParams;
        if(p.get('date')===day)return new Promise(resolve=>{resolveOld=resolve;});
        return Promise.resolve(response({...snapshot(199,100,204,p.get('date')),country:p.get('country')}));
    });
    const seen=[];
    let completedSweeps=0;
    const racePoll=race.context.L1.liveCollection.poll(()=>({date:selected,countries:['SEA']}),
        item=>seen.push(item.inspection_date),()=>{completedSweeps++;});
    const old=racePoll.refresh(true);await flush();selected='2026-10-22';await racePoll.refresh(true);
    resolveOld(response(snapshot()));await old;
    assert.deepEqual(seen,['2026-10-22']);
    assert.equal(completedSweeps,1);
    racePoll.stop();

    // Only the dashboard batches rendering. It still rereads every country on the next sweep.
    let resolveSaved, seaMain=199, seaTotal=204, failSeg=false;
    const kinds = {SEA:'retail', SEDA:'seda_retail', SEG:'seg_retail', SIEL:'siel_retail',
        SEM:'sem_retail', TSE:'tse_retail', SEIB:'seib_retail', SEUK:'seuk_retail'};
    const scoped = (country, main, bsr, total) => {
        const item = snapshot(main, bsr, total);
        item.country = country;
        item.check.check_type = kinds[country];
        item.check.is_target_date = true;
        return item;
    };
    const countryReads=[], pendingLive=[];
    const dashboard=setup(async url=>{
        if(url.includes('collection-current')) {
            const country=new URL(url,'http://test').searchParams.get('country');
            countryReads.push(country);
            return new Promise(resolve=>pendingLive.push(() => resolve(country === 'SEG' && failSeg
                ? {ok:false,json:async()=>({})}
                : response(country === 'SEA' ? scoped(country, seaMain, 100, seaTotal) : scoped(country,199,100,204)))));
        }
        if(url.includes('collection-volume')) return new Promise(resolve=>{resolveSaved=resolve;});
        return {ok:true,json:async()=>({summary:{},checks:Object.keys(kinds).map(country=>scoped(country,0,0,0).check)})};
    });
    const renders=[], ddayReads=[];
    let reviewReads=0, statusReads=0;
    Object.assign(dashboard.context,{getSelectedDate:()=>day,loadDdayCollection(date, keepVisible){ddayReads.push([date, keepVisible]);},
        loadCheckStatus:async()=>{statusReads++;return {};},loadSeaRetailSummaries:async()=>({}),
        recordRender(value){renders.push(value.checks.map(check=>{
            const row=check.categories[0].time_slots[0].retailers[0]; return [row.status,row.count];
        }));}});
    dashboard.context.L1.initLayer1Page=()=>{};
    dashboard.context.L1.retailReview = {async load(){reviewReads++;}};
    dashboard.context.L1.liveCollection.preserveView=render=>render();
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js','utf8'),dashboard.context);
    vm.runInContext('renderLayer1Stats=recordRender;',dashboard.context);
    await dashboard.context.loadStats();await flush();
    assert.equal(countryReads.length,0, 'no immediate duplicate country read');
    assert.deepEqual(ddayReads,[[day,undefined]]);
    dashboard.events.focus(); await flush();
    assert.deepEqual(ddayReads,[[day,undefined]], 'focus must not duplicate initial D-DAY request');
    await dashboard.tick(10000);
    dashboard.context.document.hidden=true; dashboard.documentEvents.visibilitychange();
    dashboard.context.document.hidden=false; dashboard.documentEvents.visibilitychange();
    await dashboard.tick(50000);
    const beforeFirstSweep=renders.length;
    assert.equal(pendingLive.length,3);
    pendingLive.splice(0).forEach(resolve=>resolve()); await flush();
    assert.equal(renders.length,beforeFirstSweep,'partial results do not repaint the dashboard');
    while(pendingLive.length) {pendingLive.splice(0).forEach(resolve=>resolve());await flush();}
    assert.equal(renders.length,beforeFirstSweep+1);
    assert.deepEqual([...new Set(countryReads)].sort(),Object.keys(kinds).sort());
    assert.equal(countryReads.length,8);
    assert.deepEqual(renders.at(-1)[0],['OK',204]);
    dashboard.events.focus(); await flush();
    assert.equal(countryReads.length,8,'focus after automatic refresh must not make another request');
    const oldSnapshot=snapshot(0,0,0);oldSnapshot.rows[0].rules={};oldSnapshot.live=false;
    resolveSaved(response(oldSnapshot));await flush();
    assert.deepEqual(renders.at(-1)[0],['OK',204]);
    seaMain=198;
    const beforeSecondSweep=renders.length;
    await dashboard.tick(60000);
    while(pendingLive.length) {pendingLive.splice(0).forEach(resolve=>resolve());await flush();}
    assert.equal(countryReads.length,16,'previously normal countries are read again on the next sweep');
    assert.equal(renders.length,beforeSecondSweep+1);
    assert.deepEqual(renders.at(-1)[0],['OK',204]);
    const revised = dashboard.context.currentStatsData.checks[0].categories[0].time_slots[0].retailers[0];
    assert.equal(revised.batch_id,'recollected');
    assert.equal(revised.main_count,198);
    seaMain=100; seaTotal=105; failSeg=true;
    const beforeThirdSweep=renders.length;
    await dashboard.tick(60000);
    while(pendingLive.length) {pendingLive.splice(0).forEach(resolve=>resolve());await flush();}
    assert.equal(countryReads.length,24);
    assert.equal(renders.length,beforeThirdSweep+1);
    assert.deepEqual(renders.at(-1)[0],['VOLUME_LOW',105]);
    assert.deepEqual(renders.at(-1)[2],['ERROR',204]);
    assert.equal(ddayReads.length,1);
    assert.equal(reviewReads,1);
    assert.equal(statusReads,1);
    dashboard.context.liveCollectionPoll.stop();

    // Bound concurrent country reads and do not duplicate a still-running sweep on focus.
    const pending=[];
    const parallel=setup(url=>new Promise(resolve=>{
        active++;peak=Math.max(peak,active);
        const country=new URL(url,'http://test').searchParams.get('country');
        pending.push(()=>{active--;resolve(response({...snapshot(),country}));});
    }));
    const many=parallel.context.L1.liveCollection.poll(()=>({date:day,countries:['SEA','SEDA','SIEL','SEG','SEM','TSE','SEIB']}),()=>{});
    const sweep=many.refresh();await flush();parallel.events.focus();assert.equal(pending.length,3);
    while(pending.length){pending.splice(0).forEach(resolve=>resolve());await flush();}
    await sweep;assert.equal(peak,3);many.stop();
    const past=setup(async()=>{throw Error('past days must not poll');});
    let pastReads=0;past.context.fetch=async()=>{pastReads++;return response(snapshot());};
    const pastPoll=past.context.L1.liveCollection.poll(()=>({date:'2026-10-22',countries:['SEA']}),()=>{});
    await past.tick(60000);await pastPoll.refresh();past.events.focus();await flush();
    assert.equal(pastReads,0);pastPoll.stop();
    console.log('Live collection: recollection, deletion, insufficient history, failure recovery, date races, visibility, dialogs and concurrency passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
