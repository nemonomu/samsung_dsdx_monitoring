const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('static/js/validation-review.js','utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
class Element {
    constructor(dataset={}) {this.dataset=dataset;this.handlers={};this.innerHTML='';}
    addEventListener(name, fn) {this.handlers[name]=fn;}
    querySelectorAll(selector) {
        const attribute=selector==='[data-index]'?'index':selector==='[data-action]'?'action':null;
        if(!attribute) return [];
        return [...this.innerHTML.matchAll(new RegExp('data-'+attribute+'="([^"]+)"','g'))].map(m=>new Element({[attribute]:m[1]}));
    }
    querySelector() {return this.retry ||= new Element();}
}
function setup(kind='null_check', query='', fetcher) {
    const root=new Element({kind,label:kind,api:'/dx/layer2/api/admin-review/'}), body=new Element(), back=new Element(), form=new Element();
    const requests=[], events={};
    const summary={success:true,counts:{corrected:1},items:[{table_name:'public.test',country:'SEIB',product:'LDY',retailer:'MediaMarkt',column_name:'sku',rule_id:2,total:1,counts:{corrected:1}}]};
    const base={id:57,item:'14383021',_source_date:'2026-11-06',retailer_sku_name:'<script>bad()</script>',product_url:'javascript:bad()',_known:true};
    const detail={success:true,field:'sku',columns:['id','item','retailer_sku_name','sku','product_url'],counts:{corrected:1},total:1,page:1,pages:1,groups:[{id:1,rows:[
        {...base,id:54,_source_date:'2026-11-05',sku:null,_phase:'비교 이력'},
        {...base,sku:null,_phase:'수정 전'},
        {...base,sku:'WW90T554DAX',_phase:'수정 후',_status:'corrected',_state:'값 수정',_reviewer:'reviewer',_reviewed_at:'2026-11-06 10:10:24'}]}]};
    if(kind==='cross_field') Object.assign(detail,{available_columns:['count_of_reviews','star_rating'],selected_columns:['count_of_reviews'],query:"SELECT source.count_of_reviews FROM test WHERE item = 'A''001';"});
    let capturedCards=[], capturedActions=[], checkedColumns=[];
    const oldQuery=body.querySelectorAll.bind(body);
    body.querySelectorAll=selector=> {
        if(selector==='input[name="vr-column"]:checked') return checkedColumns.map(value=>({value}));
        const result=oldQuery(selector);if(selector==='[data-index]')capturedCards=result;
        if(selector==='[data-action]')capturedActions=result;
        return result;
    };
    const copied=[];
    const sandbox={console,URLSearchParams,AbortController,FormData,
        location:{search:'?type='+kind+'&date=2026-11-06'+query,assign(url){this.assigned=url;}},
        history:{pushState(_a,_b,url){sandbox.location.search=url;},replaceState(_a,_b,url){sandbox.location.search=url;}},
        navigator:{clipboard:{writeText:async text=>copied.push(text)}},isSecureContext:true,
        document:{getElementById:id=>({'validation-review':root,'vr-body':body,'vr-back':back,'vr-search':form}[id]),
            body:{appendChild(input){this.input=input;}},
            createElement:()=>({style:{},focus(){},select(){},remove(){}}),
            execCommand:()=>{copied.push(sandbox.document.body.input.value);return true;}},
        initFilterBar(){},getSelectedDate:()=> '2026-11-06',addEventListener:(name,fn)=>events[name]=fn,
        fetch: async(url,options)=> {requests.push({url,options});return fetcher?fetcher(url,options):{ok:true,json:async()=>url.includes('view=records')?detail:summary};},
    };
    sandbox.window=sandbox;
    Object.defineProperty(sandbox,'top',{value:sandbox,writable:false,configurable:false});
    vm.runInNewContext(code,sandbox);
    return {body,back,form,requests,sandbox,events,summary,detail,copied,cards:()=>capturedCards,
        action:name=>capturedActions.find(el=>el.dataset.action===name),select:values=>checkedColumns=values};
}
(async()=>{
    for(const kind of ['null_check','cross_field','format_check','field_missing']) {
        const ui=setup(kind);await tick();
        assert.match(ui.body.innerHTML,/MediaMarkt/);
        await ui.cards()[0].handlers.click();await tick();
        assert.match(ui.body.innerHTML,/vr-fields/);
        await ui.cards()[0].handlers.click();await tick();
        assert.match(ui.body.innerHTML,/수정 전/);assert.match(ui.body.innerHTML,/수정 후/);
        assert.equal((ui.body.innerHTML.match(/2026-11-06<span/g)||[]).length,2);
        assert.match(ui.body.innerHTML,/WW90T554DAX/);
        assert.match(ui.body.innerHTML,/&lt;script&gt;/);
        assert(!ui.body.innerHTML.includes('href="javascript:'));
        assert(!ui.body.innerHTML.includes('이력 보기'));
        assert(!ui.body.innerHTML.includes('>저장<'));
        assert.equal(ui.body.innerHTML.includes('컬럼 선택'),kind==='cross_field');
        if(kind==='cross_field') {
            assert.match(ui.body.innerHTML,/count_of_reviews \(참고\)/);
            assert.match(ui.body.innerHTML,/Item 조회 SQL/);
            ui.action('copy-query').handlers.click();await tick();
            assert.equal(ui.copied[0],ui.detail.query);
            ui.sandbox.isSecureContext=false;
            ui.action('copy-query').handlers.click();await tick();
            assert.equal(ui.copied[1],ui.detail.query);
            ui.select(['star_rating']);ui.action('apply-columns').handlers.click();await tick();
            assert.equal(new URLSearchParams(ui.sandbox.location.search).get('columns'),'star_rating');
            assert(ui.requests.at(-1).url.includes('columns=star_rating'));
            ui.select([]);ui.action('apply-columns').handlers.click();await tick();
            assert.equal(new URLSearchParams(ui.sandbox.location.search).get('columns'),'');
            ui.action('default-columns').handlers.click();await tick();
            assert(!new URLSearchParams(ui.sandbox.location.search).has('columns'));
        }
        assert(ui.requests.every(r=>!r.options.method || r.options.method==='GET'));
        await ui.back.handlers.click();await tick();assert.match(ui.body.innerHTML,/vr-fields/);
        await ui.back.handlers.click();await tick();assert.match(ui.body.innerHTML,/MediaMarkt/);
        await ui.back.handlers.click();assert(ui.sandbox.location.assigned.includes('date=2026-11-06'));
    }
    const error=setup('null_check','',async()=>({ok:false,json:async()=>({error:'관리자만 조회 가능합니다.'})}));await tick();
    assert.match(error.body.innerHTML,/관리자만 조회/);assert(error.body.retry.handlers.click);
    const pending=[];
    const race=setup('null_check','',url=>new Promise(resolve=>pending.push({url,resolve})));
    race.sandbox.handleSearch();
    pending[1].resolve({ok:true,json:async()=>({success:true,counts:{},items:[]})});await tick();
    pending[0].resolve({ok:true,json:async()=>race.summary});await tick();
    assert(!race.body.innerHTML.includes('MediaMarkt'),'stale response replaced the newest date');
    assert.match(race.body.innerHTML,/처리 이력이 없습니다/);
    console.log('Admin review: four kinds, navigation, same-day pairs, escaping, permissions, empty state and request races passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
