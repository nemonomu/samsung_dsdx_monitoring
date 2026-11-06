/* Administrator-only, read-only validation audit. No mutation endpoints. */
(function () {
    'use strict';
    const root = document.getElementById('validation-review');
    if (!root) return;
    const body = document.getElementById('vr-body');
    const back = document.getElementById('vr-back');
    const kind = root.dataset.kind;
    const labels = {corrected: '값 수정', auto: '자동확인', normal: '수동확인', error: '오류 확인', reverted: '확인 취소'};
    const routes = {null_check: '/dx/layer2/null/', format_check: '/dx/layer2/format/', cross_field: '/dx/layer3/cross-field/', field_missing: '/dx/layer3/field-missing/'};
    let state = new URLSearchParams(location.search), serial = 0, controller;
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
    function list(data) {
        if (state.has('table')) {
            body.innerHTML = '<div class="vr-panel">'+title()+chips(data.counts)+'<div class="vr-fields">'+data.items.map((r,i) => '<button class="vr-card" data-index="'+i+'"><div class="vr-card-head">'+esc(r.column_name)+(r.rule_name?'<div class="vr-sub">'+esc(r.rule_name)+'</div>':'')+'<strong>검수 '+r.total+'건</strong></div>'+chips(r.counts)+'</button>').join('')+'</div>'+(!data.items.length?'<div class="vr-empty">선택한 검수일의 처리 이력이 없습니다.</div>':'')+'</div>';
        } else {
            const groups = new Map();
            data.items.forEach((r,i) => {const k=r.country+' '+r.product;if(!groups.has(k))groups.set(k,[]);groups.get(k).push({...r,index:i});});
            body.innerHTML = '<div class="vr-panel">'+title()+chips(data.counts)+'</div>'+Array.from(groups, ([name, rows]) => '<div class="vr-panel"><h2>'+esc(name)+'</h2><p class="vr-sub">검수일 '+esc(state.get('date'))+'</p>'+rows.map(r => '<button class="vr-card" data-index="'+r.index+'"><div class="vr-card-head"><h3>'+esc(r.retailer || '(리테일러 없음)')+'</h3><strong>검수 '+r.total+'건</strong></div>'+chips(r.counts)+'</button>').join('')+'</div>').join('')+(!data.items.length?'<div class="vr-panel vr-empty">선택한 검수일의 처리 이력이 없습니다.</div>':'');
        }
        body.querySelectorAll('[data-index]').forEach(el => el.addEventListener('click', () => {
            const row = data.items[Number(el.dataset.index)];
            if (state.has('table')) navigate({field: row.column_name, rule: row.rule_id == null ? null : row.rule_id, view:'records', page:1, columns:null});
            else navigate({table:row.table_name, retailer:row.retailer || '', label:row.country+' '+row.product});
        }));
    }
    function crossTools(data) {
        if (kind !== 'cross_field' || !data.available_columns) return '';
        const selected = new Set(data.selected_columns || []);
        return '<details class="vr-columns"><summary>컬럼 선택</summary><p class="vr-sub">기본 정보와 검수 대상 컬럼은 항상 표시됩니다. 추가 컬럼은 원본 현재값입니다.</p><div class="vr-column-options">'+
            data.available_columns.map(c => '<label><input type="checkbox" name="vr-column" value="'+esc(c)+'"'+(selected.has(c)?' checked':'')+'> '+esc(c)+'</label>').join('')+
            '</div><div class="vr-column-actions">'+button('적용','apply-columns')+button('기본 컬럼','default-columns')+'</div></details>'+
            (data.query ? '<details class="vr-query" open><summary>'+esc(state.get('days') || 3)+'일치 Item 조회 SQL · 현재 페이지</summary>'+button('복사','copy-query')+'<pre tabindex="0">'+esc(data.query)+'</pre><small>선택한 컬럼과 현재 페이지의 Item에 대한 원본 현재값 조회 SQL입니다.</small></details>' : '');
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
        const refs = kind === 'cross_field' && data.selected_columns
            ? data.selected_columns.filter(c => c !== field)
            : data.columns.filter(c => !['id','item','retailer_sku_name','product_url','account_name','batch_id','crawl_datetime','crawl_strdatetime',field].includes(c));
        const columns = [field,...refs];
        let number = (data.page-1)*10;
        let html = '<div class="vr-panel">'+title()+chips(data.counts)+'</div><form class="vr-tools" id="vr-search"><label>검색 <input name="q" placeholder="Item · ID · 검증자 · 값" value="'+esc(state.get('q') || '')+'"></label><select name="status" aria-label="처리 상태"><option value="all">전체 처리</option>'+Object.entries(labels).map(([k,v]) => '<option value="'+k+'"'+(state.get('status')===k?' selected':'')+'>'+v+'</option>').join('')+'</select><label>일수 <input name="days" type="number" min="1" max="30" value="'+esc(state.get('days') || 3)+'"></label><button class="app-btn app-btn-md app-btn-primary">조회</button>'+button('해제','clear')+'</form><div class="vr-help"><span>셀 클릭 후 Ctrl+C로 복사 · 읽기 전용</span><span>수정 전·후: 저장된 검수 값'+(refs.length?' · 참고 열: 원본 현재값':'')+'</span></div><div class="vr-scroll"><table><thead><tr><th>No</th><th>id</th><th>수집일</th><th>item</th><th>retailer_sku_name</th>'+columns.map(c => '<th>'+esc(c)+(c!==field?' (참고)':'')+'</th>').join('')+'<th>검수 상태</th><th>product_url</th><th>확인 사유</th><th>확인 근거</th></tr></thead><tbody>';
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
        body.innerHTML = html.replace('</form>', '</form>'+crossTools(data));
        document.getElementById('vr-search').addEventListener('submit', e => {
            e.preventDefault(); const form = new FormData(e.target);
            navigate({q:form.get('q'), status:form.get('status'), days:form.get('days'), page:1});
        });
        body.querySelectorAll('[data-action]').forEach(el => el.addEventListener('click', () => {
            const action=el.dataset.action;
            if (action==='copy-query') { copyQuery(data.query, el); return; }
            if (action==='apply-columns') {
                const columns = Array.from(body.querySelectorAll('input[name="vr-column"]:checked'), input => input.value);
                navigate({columns:columns.join(',')}); return;
            }
            if (action==='default-columns') { navigate({columns:null}); return; }
            navigate(action==='clear'?{q:null,status:null,page:1}:{page:data.page+(action==='prev'?-1:1)});
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
        if(state.has('field')) navigate({field:null,rule:null,view:null,page:null,q:null,status:null,columns:null});
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
