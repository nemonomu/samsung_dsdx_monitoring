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
    const context={L1:{}, URLSearchParams, AbortController, console, fetch,
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
    current=snapshot(); await env.tick(15000);
    assert.equal(row().status,'OK'); assert.equal(row().count,204);
    assert.equal(row()._volumeCounts,undefined,'Old SEA summary must not replace live counts');
    assert.equal(data.checks[0].display_group,'daily');
    current=snapshot(100,50,105); await env.tick(15000); assert.equal(row().status,'VOLUME_LOW');
    current=snapshot(0,0,0); await env.tick(15000); assert.equal(row().status,'CRITICAL');
    current=snapshot();current.rows[0].rules={}; await env.tick(15000);assert.equal(row().status,'INSUFFICIENT');
    env.context.fetch=async()=>{calls++;throw Error('offline');};
    await env.tick(15000);assert.equal(row().status,'ERROR');assert.equal(row().count,204);
    env.context.fetch=async()=>{calls++;return response(snapshot());};
    await env.tick(15000);assert.equal(row().status,'OK');
    env.context.document.hidden=true; env.documentEvents.visibilitychange();
    const before=calls;await env.tick(60000);assert.equal(calls,before);
    env.context.document.hidden=false;env.documentEvents.visibilitychange();await flush();assert.equal(calls,before+1);
    env.setModal(true);await env.tick(15000);assert.equal(calls,before+1);
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
    const racePoll=race.context.L1.liveCollection.poll(()=>({date:selected,countries:['SEA']}),item=>seen.push(item.inspection_date));
    const old=racePoll.refresh();await flush();selected='2026-10-22';await racePoll.refresh();
    resolveOld(response(snapshot()));await old;
    assert.deepEqual(seen,['2026-10-22']);racePoll.stop();

    // Exercise the actual dashboard loader: late saved statistics cannot undo live recovery.
    let resolveSaved;
    const dashboard=setup(async url=>{
        if(url.includes('collection-current')) return response(snapshot());
        if(url.includes('collection-volume')) return new Promise(resolve=>{resolveSaved=resolve;});
        return {ok:true,json:async()=>({summary:{},checks:[{...snapshot(0,0,0).check,is_target_date:true}]})};
    });
    const renders=[];
    Object.assign(dashboard.context,{getSelectedDate:()=>day,loadDdayCollection(){},
        loadCheckStatus:async()=>({}),loadSeaRetailSummaries:async()=>({}),
        recordRender(value){const r=value.checks[0].categories[0].time_slots[0].retailers[0];renders.push([r.status,r.count]);}});
    dashboard.context.L1.initLayer1Page=()=>{};
    dashboard.context.L1.liveCollection.preserveView=render=>render();
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/dashboard.js','utf8'),dashboard.context);
    vm.runInContext('renderLayer1Stats=recordRender;',dashboard.context);
    await dashboard.context.loadStats();await flush();
    assert.deepEqual(renders.at(-1),['OK',204]);
    const oldSnapshot=snapshot(0,0,0);oldSnapshot.rows[0].rules={};oldSnapshot.live=false;
    resolveSaved(response(oldSnapshot));await flush();
    assert.deepEqual(renders.at(-1),['OK',204]);
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
    console.log('Live collection: recollection, deletion, insufficient history, failure recovery, date races, visibility, dialogs and concurrency passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
