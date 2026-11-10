/* Read-only validation audit with separate administrator completion checks. */
(function () {
    'use strict';
    const root = document.getElementById('validation-review');
    if (!root) return;
    const body = document.getElementById('vr-body');
    const back = document.getElementById('vr-back');
    const kind = root.dataset.kind;
    const hasDetailTools = kind === 'null_check' || kind === 'cross_field';
    const labels = {corrected: '값 수정', auto: '자동확인', normal: '수동확인', error: '오류 확인', reverted: '확인 취소'};
    const routes = {null_check: '/dx/layer2/null/', format_check: '/dx/layer2/format/', cross_field: '/dx/layer3/cross-field/', field_missing: '/dx/layer3/field-missing/'};
    let state = new URLSearchParams(location.search), serial = 0, controller;
    const saving = new Set();
    let leaving=false, recovering;
    window.addEventListener('pagehide',()=>{leaving=true;});
    window.addEventListener('pageshow',()=>{leaving=false;});
    const pendingKey = 'validation-review-pending:'+root.dataset.reviewUser;
    function pendingChecks() {
        try { const value=JSON.parse(sessionStorage.getItem(pendingKey) || '{}'); return value && typeof value==='object' && !Array.isArray(value)?value:{}; }
        catch (_) { return {}; }
    }
    function rememberCheck(id, value) {
        try {
            const pending=pendingChecks();
            if(value) pending[id]=value; else delete pending[id];
            if(Object.keys(pending).length) sessionStorage.setItem(pendingKey,JSON.stringify(pending));
            else sessionStorage.removeItem(pendingKey);
        } catch (_) { /* keepalive still protects the request if storage is unavailable. */ }
    }
    function saveStatus(message) {
        const status=document.getElementById('vr-save-status');
        if(status) { status.textContent=message;status.hidden=!message; }
    }
    async function recoverChecks() {
        const pending=Object.entries(pendingChecks());
        if(!pending.length) return;
        saveStatus('진행 중이던 체크 저장을 확인하고 있습니다…');
        const results=await Promise.all(pending.map(async ([id,entry]) => {
            try {
                if(!entry || !entry.payload || typeof entry.payload.checked!=='boolean') return false;
                const {checked,...scope}=entry.payload;
                for(let attempt=0;attempt<20;attempt++) {
                    const abort=new AbortController();
                    const timer=setTimeout(()=>abort.abort(),4000);
                    let response,data;
                    try {
                        response=await fetch(root.dataset.checkApi+'?'+new URLSearchParams(scope),{
                            credentials:'same-origin',cache:'no-store',signal:abort.signal,
                        });
                        data=await response.json();
                    } finally { clearTimeout(timer); }
                    if(!response.ok || !data.success) return false;
                    if(data.check.checked===checked) return true;
                    if(Date.now()-entry.startedAt>60000) return false;
                    await new Promise(resolve=>setTimeout(resolve,400));
                }
                return false;
            } catch (_) { return false; }
            finally { rememberCheck(id,null); }
        }));
        saveStatus(results.every(Boolean)?'':'체크 저장을 확인하지 못했습니다. 현재 저장된 상태를 표시합니다. 체크 상태를 확인해 주세요.');
    }
    const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const button = (label, action, disabled) => '<button type="button" class="app-btn app-btn-md app-btn-outline" data-action="'+action+'"'+(disabled?' disabled':'')+'>'+label+'</button>';
    const chips = counts => '<div class="vr-chips">'+Object.keys(labels).filter(k => counts[k]).map(k => '<span class="vr-chip '+k+'">'+labels[k]+' '+counts[k]+'건</span>').join('')+'</div>';
    function value(v, known) {
        if (known === false) return '<span class="vr-missing">저장값 없음</span>';
        if (v === null) return '<span class="vr-null">NULL</span>';
        if (v === undefined) return '<span class="vr-missing">—</span>';
        if (v === '') return '<span class="vr-missing">빈 문자열</span>';
        if (typeof v === 'string' && !v.trim()) return '<span class="vr-missing">공백 '+v.length+'자</span>';
        return esc(v);
    }
    function link(url) {
        if (!/^https?:\/\//i.test(url || '')) return value(url);
        return '<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">↗ '+esc(url)+'</a>';
    }
    function navigate(changes, replace) {
        Object.entries(changes).forEach(([key, val]) => val === null ? state.delete(key) : state.set(key, val));
        state.set('type', kind);
        history[replace ? 'replaceState' : 'pushState']({}, '', '?'+state.toString());
        load();
    }
    function title() {
        const field = state.get('field');
        return '<h2>'+esc(field ? field+' '+root.dataset.label+' 검수 조회' : state.get('retailer') !== null ? state.get('retailer')+' · '+root.dataset.label+' 검수' : root.dataset.label+' 검수')+'</h2>'+
            '<p class="vr-sub">'+esc(state.get('label') || '')+(state.get('retailer') !== null ? ' | '+esc(state.get('retailer')) : '')+' · 검수일 '+esc(state.get('date'))+'</p>';
    }
    function checkInfo(check) {
        return check && check.checked ? '확인: '+(check.actor || '')+(check.updated_at?' · '+check.updated_at.slice(0,19).replace('T',' '):'') : '';
    }
    function retailerCard(row) {
        const check = row.check || {};
        return '<div class="vr-retailer-card" data-card-index="'+row.index+'"><button type="button" class="vr-card" data-index="'+row.index+'"><div class="vr-card-head"><h3>'+esc(row.retailer || '(리테일러 없음)')+'</h3><strong>검수 '+row.total+'건</strong></div>'+chips(row.counts)+'</button>'+
            '<div class="vr-check-row"><label><input type="checkbox" data-check-index="'+row.index+'"'+(check.checked?' checked':'')+' aria-label="'+esc(row.retailer || '리테일러 없음')+' 검수 완료"> 검수 완료</label><span class="vr-check-info" role="status">'+esc(checkInfo(check))+'</span></div></div>';
    }
    function reviewPriority(row) {
        if(row.check && row.check.checked) return 1;
        // Mixed cards and other manual decisions remain in the pending group.
        return Object.keys(row.counts || {}).some(key=>key!=='auto' && row.counts[key]>0)?0:2;
    }
    function groupedCards(data, renderCard=retailerCard) {
        const groups=[new Map(),new Map(),new Map()];
        data.items.forEach((row,index)=>{
            const group=groups[reviewPriority(row)],name=row.country+' '+row.product;
            if(!group.has(name)) group.set(name,[]);
            group.get(name).push({...row,index});
        });
        return groups.map((group,priority)=>!group.size?'':'<section data-review-priority="'+priority+'"><h2>'+['검수 대기','검수 완료','자동확인'][priority]+'</h2>'+Array.from(group,([name,rows])=>'<div class="vr-panel"><h2>'+esc(name)+'</h2><p class="vr-sub">검수일 '+esc(state.get('date'))+'</p>'+rows.map(renderCard).join('')+'</div>').join('')+'</section>').join('');
    }
    function reorderCards(data) {
        const container=body.querySelector('.vr-list-groups');
        if(!container) return;
        const focused=document.activeElement;
        const restoreFocus=container.contains(focused);
        const cards=new Map(Array.from(container.querySelectorAll('[data-card-index]'),card=>[card.dataset.cardIndex,card]));
        const holder=document.createElement('div');
        holder.innerHTML=groupedCards(data,row=>'<div data-card-slot="'+row.index+'"></div>');
        holder.querySelectorAll('[data-card-slot]').forEach(slot=>slot.replaceWith(cards.get(slot.dataset.cardSlot)));
        // Move existing nodes so other in-flight saves, focus and messages survive.
        container.replaceChildren(...holder.childNodes);
        if(restoreFocus) focused.focus({preventScroll:true});
    }
    async function saveCheck(input, row, listData) {
        const previous = !!(row.check && row.check.checked);
        const info = input.closest('.vr-check-row').querySelector('.vr-check-info');
        input.disabled = true;
        info.textContent = '저장 중…';
        saveStatus('');
        const payload={date:state.get('date'),type:kind,table:row.table_name,retailer:row.retailer || '',checked:input.checked};
        const id=Date.now()+':'+Math.random().toString(36).slice(2);
        rememberCheck(id,{payload,startedAt:Date.now()});
        try {
            const response = await fetch(root.dataset.checkApi, {
                method:'POST', credentials:'same-origin', keepalive:true,
                headers:{'Content-Type':'application/json','X-CSRFToken':root.querySelector('[name=csrfmiddlewaretoken]').value},
                body:JSON.stringify(payload),
            });
            const data = await response.json().catch(() => null);
            if (!response.ok || !data || !data.success) throw new Error(data && data.error || '체크 저장에 실패했습니다. 다시 시도해 주세요.');
            row.check = data.check;
            input.checked = !!data.check.checked;
            info.textContent = checkInfo(data.check) || '체크 해제됨';
            if(input.isConnected) reorderCards(listData);
        } catch(error) {
            input.checked = previous;
            info.textContent = error.message || '체크 저장에 실패했습니다. 다시 시도해 주세요.';
        } finally { if(!leaving) rememberCheck(id,null);input.disabled = false; }
    }
    function list(data) {
        if (state.has('table')) {
            body.innerHTML = '<div class="vr-panel">'+title()+chips(data.counts)+'<div class="vr-fields">'+data.items.map((r,i) => '<button class="vr-card" data-index="'+i+'"><div class="vr-card-head">'+esc(r.column_name)+(r.rule_name?'<div class="vr-sub">'+esc(r.rule_name)+'</div>':'')+'<strong>검수 '+r.total+'건</strong></div>'+chips(r.counts)+'</button>').join('')+'</div>'+(!data.items.length?'<div class="vr-empty">선택한 검수일의 처리 이력이 없습니다.</div>':'')+'</div>';
        } else {
            body.innerHTML = '<div class="vr-panel">'+title()+chips(data.counts)+'</div><div class="vr-list-groups">'+groupedCards(data)+'</div>'+(!data.items.length?'<div class="vr-panel vr-empty">선택한 검수일의 처리 이력이 없습니다.</div>':'');
        }
        body.querySelectorAll('[data-index]').forEach(el => el.addEventListener('click', () => {
            const row = data.items[Number(el.dataset.index)];
            if (state.has('table')) navigate({field: row.column_name, rule: row.rule_id == null ? null : row.rule_id, view:'records', page:1, columns:null});
            else navigate({table:row.table_name, retailer:row.retailer || '', label:row.country+' '+row.product});
        }));
        body.querySelectorAll('[data-check-index]').forEach(input => input.addEventListener('change', () => {
            const promise=saveCheck(input,data.items[Number(input.dataset.checkIndex)],data);
            saving.add(promise);
            promise.finally(()=>saving.delete(promise));
        }));
    }
    function columnControls(data) {
        if (!hasDetailTools) return '';
        const selected = new Set(data.selected_columns || []);
        return '<div class="vr-tool-actions"><div class="vr-column-wrap">'+
            button('컬럼 선택','toggle-columns',!data.available_columns).replace('data-action="toggle-columns"','data-action="toggle-columns" aria-controls="vr-columns" aria-expanded="false"')+
            '<div class="vr-columns" id="vr-columns" hidden><strong>컬럼 선택</strong><p class="vr-sub">기본 정보와 검수 대상 컬럼은 항상 표시됩니다. 추가 컬럼은 원본 현재값입니다.</p><div class="vr-column-options">'+
            (data.available_columns || []).map(c => '<label><input type="checkbox" name="vr-column" value="'+esc(c)+'"'+(selected.has(c)?' checked':'')+'> '+esc(c)+'</label>').join('')+
            '</div><div class="vr-column-actions">'+button('적용','apply-columns')+button('기본 컬럼','default-columns')+button('닫기','close-columns')+'</div></div></div>'+button('정렬 초기화','reset-sort')+'</div>';
    }
    function detailHeader(data) {
        if (!hasDetailTools) return '<div class="vr-panel">'+title()+chips(data.counts)+'</div>';
        const day = state.get('date') || '';
        const parts = day.split('-').map(Number);
        const weekday = parts.length === 3 ? '일월화수목금토'[new Date(parts[0],parts[1]-1,parts[2]).getDay()] : '';
        const items = new Map();
        data.groups.forEach(group => {
            const row = group.rows[group.rows.length-1];
            const missing = row.item == null || String(row.item).trim() === '';
            items.set(missing?'id:'+row.id:'item:'+row.item, missing?'Item 없음 · ID '+row.id:String(row.item));
        });
        return '<div class="vr-panel vr-detail-panel"><div class="vr-detail-heading"><div>'+title()+'</div>'+
            '<form id="vr-days" class="vr-days"><label>일수: <input name="days" type="number" min="1" max="30" required value="'+esc(state.get('days') || 3)+'"></label><button class="app-btn app-btn-primary" type="submit">조회</button><span>'+esc(day)+(weekday?'('+weekday+')':'')+'</span></form></div>'+
            '<div class="vr-query-row"><details class="vr-items"><summary>Item 목록 ('+items.size+'개)</summary><ul>'+Array.from(items.values(), item=>'<li class="vr-copy" tabindex="0">'+esc(item)+'</li>').join('')+'</ul><small>현재 페이지 기준</small></details>'+
            '<section class="vr-query"><div class="vr-query-heading"><span>'+esc(state.get('days') || 3)+'일치 Item 조회 SQL</span>'+button('복사','copy-query',!data.query)+'</div><pre tabindex="0">'+esc(data.query || '현재 페이지에 조회할 Item이 없습니다.')+'</pre></section></div></div>'+
            '<div class="vr-review-status">'+chips(data.counts)+'<span>선택한 검수일의 처리 이력 · SQL은 현재 페이지 Item의 원본 조회</span></div>';
    }
    function sortHeading(key, label) {
        if (!hasDetailTools) return '<th>'+label+'</th>';
        const active = state.get('sort_by') === key;
        const descending = state.get('sort_order') === 'desc';
        return '<th aria-sort="'+(active?(descending?'descending':'ascending'):'none')+'"><button type="button" class="vr-sort" data-action="sort-'+key+'">'+label+' <span>'+ (active?(descending?'↓':'↑'):'↕')+'</span></button></th>';
    }
    async function copyQuery(text, control) {
        try {
            let copied = false;
            if (window.isSecureContext && navigator.clipboard) {
                try { await navigator.clipboard.writeText(text); copied = true; } catch (_) { /* HTTP/fallback below. */ }
            }
            if (!copied) {
                const active = document.activeElement;
                const input = document.createElement('textarea');
                input.value = text; input.style.position = 'fixed'; input.style.opacity = '0';
                document.body.appendChild(input);
                try { input.focus(); input.select(); copied = document.execCommand('copy'); }
                finally { input.remove(); if (active) active.focus(); }
            }
            control.textContent = copied ? '복사됨' : '복사 실패 · SQL 선택 후 Ctrl+C';
        } catch (_) { control.textContent = '복사 실패 · SQL 선택 후 Ctrl+C'; }
    }
    function table(data) {
        const field = data.field;
        const refs = hasDetailTools && data.selected_columns
            ? data.selected_columns.filter(c => c !== field)
            : data.columns.filter(c => !['id','item','retailer_sku_name','product_url','account_name','batch_id','crawl_datetime','crawl_strdatetime',field].includes(c));
        const columns = [field,...refs];
        let number = (data.page-1)*10;
        const searchChoice = hasDetailTools ? '<label>항목 <select name="q_field">'+Object.entries({all:'전체',id:'id',item:'item',reviewer:'검증자',value:'값'}).map(([k,v])=>'<option value="'+k+'"'+((state.get('q_field') || 'all')===k?' selected':'')+'>'+v+'</option>').join('')+'</select></label>' : '<span>검색</span>';
        const days = hasDetailTools ? '' : '<label>일수 <input name="days" type="number" min="1" max="30" value="'+esc(state.get('days') || 3)+'"></label>';
        let html = detailHeader(data)+'<form class="vr-tools" id="vr-search">'+searchChoice+'<input name="q" aria-label="검색어" placeholder="검색어 입력..." value="'+esc(state.get('q') || '')+'"><select name="status" aria-label="처리 상태"><option value="all">전체 처리</option>'+Object.entries(labels).map(([k,v]) => '<option value="'+k+'"'+(state.get('status')===k?' selected':'')+'>'+v+'</option>').join('')+'</select>'+days+'<button class="app-btn app-btn-md app-btn-primary">조회</button>'+button('해제','clear')+columnControls(data)+'</form><div class="vr-help"><span>셀 클릭 후 Ctrl+C로 복사 · 읽기 전용</span><span>수정 전·후: 저장된 검수 값'+(refs.length?' · 참고 열: 원본 현재값':'')+'</span></div><div class="vr-scroll"><table><thead><tr><th>No</th>'+sortHeading('id','id')+'<th>수집일</th>'+sortHeading('item','item')+'<th>retailer_sku_name</th>'+columns.map(c => '<th>'+esc(c)+(c!==field?' (참고)':'')+'</th>').join('')+'<th>검수 상태</th><th>product_url</th><th>확인 사유</th><th>확인 근거</th></tr></thead><tbody>';
        data.groups.forEach(group => {
            number++;
            const last = group.rows[group.rows.length-1];
            group.rows.forEach((r,index) => {
                const after = r._phase.endsWith('후'), before = r._phase.endsWith('전');
                html += '<tr'+(index===0?' class="vr-group-start"':'')+'>';
                if(index===0) html += '<td rowspan="'+group.rows.length+'">'+number+'</td>';
                html += '<td class="vr-copy" tabindex="0">'+value(r.id)+'</td><td class="vr-date">'+esc(r._source_date)+'<span class="vr-phase '+(after?'after':before?'before':'')+'">'+esc(r._phase)+'</span></td>';
                if(index===0) html += '<td class="vr-item vr-copy" tabindex="0" rowspan="'+group.rows.length+'">'+value(last.item)+'</td><td class="vr-name vr-copy" tabindex="0" rowspan="'+group.rows.length+'">'+value(last.retailer_sku_name)+'</td>';
                html += columns.map(c => '<td class="vr-copy '+(c===field?(after?'vr-after':before?'vr-before':''):'')+'" tabindex="0">'+value(r[c],c===field?r._known:undefined)+'</td>').join('');
                html += '<td>'+(r._state?'<span class="vr-chip '+esc(r._status)+'">'+esc(r._state)+'</span>':r._phase==='비교 이력'?'<small>비교 이력</small>':'—')+'</td><td>'+link(r.product_url)+'</td><td>'+esc(r._reason || '—')+(r._memo && r._memo!==r._reason?'<br><small>'+esc(r._memo)+'</small>':'')+(r._cancel_memo?'<br><small>취소: '+esc(r._cancel_memo)+'</small>':'')+'</td><td>'+esc(r._reviewed_at || '')+(r._reviewer?' · '+esc(r._reviewer):'')+(after&&r._status==='auto'?'<br><small>원 확인 시각 · 자동 적용</small>':'')+(after&&r._context_available===false?'<br><small>원본 없음 · 저장 이력</small>':'')+'</td></tr>';
            });
        });
        html += '</tbody></table></div>'+(!data.groups.length?'<div class="vr-empty">조건에 맞는 처리 이력이 없습니다.</div>':'')+(data.groups.some(g=>g.truncated)?'<p class="vr-note">비교 이력이 많아 일부만 표시했습니다. 조회 일수를 줄여 주세요.</p>':'')+'<div class="vr-pagination"><span class="vr-total">검수 '+data.total+'건 · 페이지당 10건</span>'+button('이전','prev',data.page<=1)+'<span>'+data.page+' / '+data.pages+'</span>'+button('다음','next',data.page>=data.pages)+'</div>';
        body.innerHTML = html;
        document.getElementById('vr-search').addEventListener('submit', e => {
            e.preventDefault(); const form = new FormData(e.target);
            navigate({q:form.get('q'), q_field:hasDetailTools?form.get('q_field'):null, status:form.get('status'), days:hasDetailTools?(state.get('days') || 3):form.get('days'), page:1});
        });
        if (hasDetailTools) document.getElementById('vr-days').addEventListener('submit', e => {
            e.preventDefault(); navigate({days:new FormData(e.target).get('days'), page:1});
        });
        body.querySelectorAll('[data-action]').forEach(el => el.addEventListener('click', () => {
            const action=el.dataset.action;
            if (action==='copy-query') { copyQuery(data.query, el); return; }
            if (action==='toggle-columns' || action==='close-columns') {
                const panel = document.getElementById('vr-columns');
                panel.hidden = action==='close-columns' || !panel.hidden;
                body.querySelector('[data-action="toggle-columns"]').setAttribute('aria-expanded', String(!panel.hidden));
                return;
            }
            if (action==='reset-sort') { navigate({sort_by:null,sort_order:null,page:1}); return; }
            if (action==='sort-id' || action==='sort-item') {
                const key=action.slice(5);
                navigate({sort_by:key,sort_order:state.get('sort_by')===key && state.get('sort_order')!=='desc'?'desc':'asc',page:1}); return;
            }
            if (action==='apply-columns') {
                const columns = Array.from(body.querySelectorAll('input[name="vr-column"]:checked'), input => input.value);
                navigate({columns:columns.join(',')}); return;
            }
            if (action==='default-columns') { navigate({columns:null}); return; }
            navigate(action==='clear'?{q:null,q_field:null,status:null,page:1}:{page:data.page+(action==='prev'?-1:1)});
        }));
        body.querySelectorAll('.vr-copy').forEach(el => el.addEventListener('click', () => {
            const selection=window.getSelection(), range=document.createRange(); range.selectNodeContents(el);selection.removeAllRanges();selection.addRange(range);
        }));
    }
    async function load() {
        const sequence = ++serial;
        if(controller) controller.abort();
        controller = new AbortController();
        back.textContent = state.has('field')?'← 상세목록':state.has('table')?'← 목록':'← 검증 화면';
        body.innerHTML='<div class="vr-panel vr-empty">검수 이력을 불러오는 중입니다.</div>';
        try {
            if(saving.size) await Promise.allSettled(Array.from(saving));
            if(Object.keys(pendingChecks()).length) {
                if(!recovering) recovering=recoverChecks().finally(()=>{recovering=null;});
                await recovering;
            }
            if(sequence!==serial) return;
            const response=await fetch(root.dataset.api+'?'+state.toString(), {signal:controller.signal, credentials:'same-origin', cache:'no-store'});
            const data=await response.json();
            if(sequence!==serial) return;
            if(!response.ok || !data.success) throw new Error(data.error || '검수 이력을 불러오지 못했습니다.');
            if(state.get('view')==='records') table(data); else list(data);
        } catch(error) {
            if(sequence!==serial || error.name==='AbortError') return;
            body.innerHTML='<div class="vr-error">'+esc(error.message)+' '+button('다시 조회','retry')+'</div>';
            body.querySelector('button').addEventListener('click', load);
        }
    }
    back.addEventListener('click', () => {
        if(state.has('field')) navigate({field:null,rule:null,view:null,page:null,q:null,q_field:null,status:null,columns:null,sort_by:null,sort_order:null});
        else if(state.has('table')) navigate({table:null,retailer:null,label:null});
        else location.assign(routes[kind]+'?date='+encodeURIComponent(state.get('date') || ''));
    });
    window.addEventListener('popstate', () => {state=new URLSearchParams(location.search);if(state.get('date') && window.filterBar)filterBar.setDate(state.get('date'));load();});
    window.handleSearch=window.loadData=function () {navigate({date:getSelectedDate(),page:1},true);};
    window.onSubitemClick=function(section, focus, code) {
        const paths={null_validation:'/dx/layer2/null/',format_validation:'/dx/layer2/format/',anomaly_validation:'/dx/layer2/anomaly/',cross_field:'/dx/layer3/cross-field/',field_missing:'/dx/layer3/field-missing/',time_series:'/dx/layer3/time-series/',category_spec:'/dx/layer3/category-spec/'};
        if(paths[section]) location.assign(paths[section]+'?'+new URLSearchParams({date:getSelectedDate(),focus:focus||'',detail_code:code||''}));
    };
    initFilterBar();
    state.set('type',kind);state.set('date',getSelectedDate());
    load();
})();
