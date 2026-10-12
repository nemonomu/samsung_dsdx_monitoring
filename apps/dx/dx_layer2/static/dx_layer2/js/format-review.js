(function () {
    'use strict';
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const labels = {pending:'확인 필요', error:'오류 확정', baseline_normal:'기존 기준상 정상', legacy_normal:'과거 정상 처리 · 재확인', registered_normal:'등록한 정상'};
    const actionLabels = {normal:'정상 값 일괄 등록', error:'오류 일괄 확정', revoke:'기준 등록 취소', undo:'처리 취소'};
    const supports = table => table === 'tv_retail' || /^(sea|siel|tse|seda|seg|sem)_(tv|ref|ldy|ldy_dryer)_retail$/.test(table);
    let dialog, state, sequence = 0, controller;
    const el = id => dialog.querySelector('#fr-' + id);
    function button(table, retailer, field = '') {
        return `<button class="btn-detail" data-format-review-table="${escape(table)}" data-format-review-retailer="${escape(retailer)}" data-format-review-field="${escape(field)}">값별 일괄 검토</button>`;
    }
    function safeURL(value) {
        try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
        catch (_) { return ''; }
    }
    function link(row) {
        const url = safeURL(row.url);
        return url ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer" title="${escape(row.name)}">${escape(row.item || row.id)} ↗</a>` : '<span class="fr-muted">유효한 URL 없음</span>';
    }
    function ensureDialog() {
        if (dialog) return;
        dialog = document.createElement('dialog');
        dialog.className = 'format-review';
        dialog.setAttribute('aria-label', '형식검증 값별 일괄 검토');
        document.body.appendChild(dialog);
        dialog.addEventListener('click', onClick);
        dialog.addEventListener('change', onChange);
        dialog.addEventListener('input', event => {
            if (event.target.id === 'fr-search') { state.search = event.target.value; renderGroups(); }
            if (event.target.id === 'fr-reason') invalidatePreview();
        });
        dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    }
    function close() {
        if (state?.busy) { message('처리가 끝난 뒤 닫아주세요.'); return; }
        sequence++; controller?.abort(); dialog.close();
        if (state?.changed) window.location.reload();
    }
    async function request(body, signal) {
        const params = {table:state.table, retailer:state.retailer, date:state.date};
        const options = {credentials:'same-origin', signal};
        let url = '/dx/layer2/api/format-review/';
        if (body) {
            const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '');
            Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRFToken':decodeURIComponent(csrf)}, body:JSON.stringify({...params, ...body})});
        } else url += '?' + new URLSearchParams(params);
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || '검토 정보를 불러오지 못했습니다.');
        return data;
    }
    async function open(table, retailer, date, field = '') {
        if (!supports(table)) return;
        ensureDialog();
        if (state?.busy) return;
        controller?.abort(); controller = new AbortController();
        const seq = ++sequence;
        state = {table, retailer, date:date || getSelectedDate(), field, tab:'issues', search:'', selected:new Set(), changed:false, busy:false, previewVersion:0};
        dialog.innerHTML = '<div class="fr-header"><h2>형식검증 일괄 검토</h2><button data-fr="close">닫기</button></div><div class="fr-body">현재 수집 대상과 기준을 불러오는 중입니다…</div>';
        if (!dialog.open) dialog.showModal();
        try { const data = await request(null, controller.signal); if (seq !== sequence) return; state.data = data; render(); }
        catch (error) { if (error.name === 'AbortError') return; dialog.querySelector('.fr-body').textContent = error.message; }
    }
    function render() {
        const data = state.data;
        const fields = [...new Set(data.groups.map(g => g.field))].sort();
        dialog.innerHTML = `<div class="fr-header"><div><h2>형식검증 · 값별 일괄 검토</h2><div class="fr-muted">${escape(data.context.country)} / ${escape(state.retailer)} / ${escape(data.context.product)} · 조회일 ${escape(data.date)} · 수집일 ${escape(data.source_date)}</div></div><button data-fr="close">닫기</button></div>
            <div class="fr-body"><div class="fr-note">현재 검증 대상 ${data.record_count}건을 컬럼·값별로 묶습니다. 비교 이력은 처리 대상에서 제외합니다. 상품 URL을 확인한 뒤 정상 값을 등록하면 같은 범위의 동일 값은 다음 수집에도 정상으로 인정됩니다. 오류 값은 다음 수집에서 다시 검증합니다.</div>
            ${!data.available?'<div class="fr-warning">검토 저장소 마이그레이션이 필요합니다. 조회만 가능하며 저장은 비활성화됩니다.</div>':''}
            <div class="fr-tabs">${[['issues','이상 검출 확인'],['baseline','기존 정상 재확인'],['registered','등록한 정상 관리']].map(([key,label])=>`<button data-fr="tab" data-tab="${key}" aria-pressed="${state.tab===key}">${label}</button>`).join('')}</div>
            <div class="fr-tools"><label>컬럼 <select id="fr-field"><option value="">전체 컬럼</option>${fields.map(f=>`<option value="${escape(f)}" ${state.field===f?'selected':''}>${escape(f)}</option>`).join('')}</select></label><input id="fr-search" type="search" aria-label="수집 값 검색" placeholder="값 검색" value="${escape(state.search)}"><button data-fr="select-all">검색된 그룹 전체 선택</button><button data-fr="clear">선택 해제</button></div>
            <div class="fr-layout"><div id="fr-groups"></div><aside><div id="fr-selected"></div><p class="fr-muted">정상인 문구만 함께 선택하세요. 정상·오류 처리는 선택한 범위의 정확히 같은 값에 적용되며 원본 값은 수정하지 않습니다.</p><label for="fr-reason">확인 / 취소 사유</label><textarea id="fr-reason" maxlength="1000" placeholder="페이지 확인 결과와 처리 근거를 입력하세요"></textarea><div class="fr-actions"><button data-fr="preview" data-decision="normal">정상 값 일괄 등록</button><button data-fr="preview" data-decision="error">오류 일괄 확정</button></div><div id="fr-message" role="status" aria-live="polite"></div><div id="fr-preview" hidden></div></aside></div>
            <details class="fr-history"><summary>처리 이력 · 최근 ${data.history.length}건</summary>${data.history.map(e=>`<div class="fr-event"><b>${escape(actionLabels[e.action] || e.action)} · ${e.count}건 / ${e.groups}개 값 ${e.is_del?'(취소됨)':''}</b><div>${escape(e.actor)} · ${escape(e.created_at)} · 조회일 ${escape(e.inspection_date)}</div><div>${escape(e.reason)}</div>${!e.is_del&&e.action!=='undo'?`<button data-fr="undo" data-event="${e.id}">이 처리 취소</button>`:''}</div>`).join('') || '<p>처리 이력이 없습니다.</p>'}</details></div>`;
        renderGroups();
    }
    function visibleGroups() {
        return state.data.groups.filter(g => g.tab === state.tab && (!state.field || g.field === state.field) && g.value.toLowerCase().includes(state.search.toLowerCase()));
    }
    function policyRow(policy) {
        return `<article class="fr-group"><b>${escape(policy.field)}</b><div class="fr-value">${escape(policy.value)}</div><p>${escape(policy.actor)} · ${escape(policy.created_at)} · 적용 시작 ${escape(policy.date)}</p><p>${escape(policy.reason)}</p><button data-fr="revoke" data-key="${policy.key}">등록 취소</button></article>`;
    }
    function renderGroups() {
        if (!state.data || !el('groups')) return;
        invalidatePreview();
        if (state.tab === 'registered') {
            const policies = state.data.registrations.filter(p => (!state.field || p.field === state.field) && p.value.toLowerCase().includes(state.search.toLowerCase()));
            el('groups').innerHTML = policies.filter(p=>p.action==='normal').map(policyRow).join('') || '<p>등록한 정상 값이 없습니다.</p>';
            const rejected = policies.filter(p=>p.action==='error');
            if (rejected.length) el('groups').innerHTML += `<details><summary>오류 추적 기준 관리 (${rejected.length})</summary>${rejected.map(policyRow).join('')}</details>`;
        } else {
            const groups = visibleGroups();
            el('groups').innerHTML = (state.tab === 'baseline' ? '<p class="fr-note">기존 기준 통과와 과거 정상 처리는 새 정상 등록과 구분합니다. 아직 원본을 재확인하지 않은 상태이며 오류 건수에 포함하지 않습니다.</p>' : '') + (groups.map(g=>`<article class="fr-group ${state.selected.has(g.key)?'selected':''}"><label><input type="checkbox" data-group="${g.key}" ${state.selected.has(g.key)?'checked':''}><b>${escape(g.field)}</b> <strong>${g.count}건</strong></label><div class="fr-value">${escape(g.value)}</div><div class="fr-badges">${Object.entries(g.states).map(([key,count])=>`<span class="fr-badge ${key}">${escape(labels[key])} ${count}</span>`).join('')}</div><div class="fr-links">대표 URL: ${g.records.slice(0,3).map(link).join(' ')}</div><details><summary>전체 상품·URL·검출 근거 (${g.count}건)</summary><div class="fr-scroll"><table><thead><tr><th>상품</th><th>수집일시</th><th>상품 URL</th><th>검토 상태 / 근거</th></tr></thead><tbody>${g.records.map(r=>`<tr><td>${escape(r.item)}<br>${escape(r.name)}</td><td>${escape(r.collected_at)}</td><td>${link(r)}</td><td>${escape(labels[r.state])}<br>${escape(r.original_error?.reason || '')}</td></tr>`).join('')}</tbody></table></div></details></article>`).join('') || '<p class="fr-empty">해당 값 그룹이 없습니다.</p>');
        }
        renderSelection();
    }
    function renderSelection() {
        const groups = state.data.groups.filter(g=>state.selected.has(g.key));
        el('selected').innerHTML = `<strong>${groups.reduce((n,g)=>n+g.count,0)}건</strong> / ${groups.length}개 값 선택`;
        dialog.querySelectorAll('[data-fr="preview"]').forEach(b=>b.disabled=!groups.length || !state.data.available || state.busy || state.tab==='registered');
    }
    function message(text) { if (el('message')) el('message').textContent=text; }
    function invalidatePreview() {
        state.previewVersion++;
        state.preview=null;
        if(el('preview'))el('preview').hidden=true;
    }
    function onChange(event) {
        if (event.target.dataset.group) {
            const key = event.target.dataset.group;
            event.target.checked ? state.selected.add(key) : state.selected.delete(key);
            invalidatePreview(); renderSelection();
        }
        if (event.target.id==='fr-field') { state.field=event.target.value; state.selected.clear(); renderGroups(); }
    }
    async function mutate(body) {
        if (state.busy) return;
        state.busy=true; renderSelection();
        dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
        try {
            await request(body);
            state.changed=true;
            if (typeof invalidateLayer2SidebarStats==='function') invalidateLayer2SidebarStats(state.date);
            state.data=await request(); state.selected.clear(); state.preview=null;
            render(); message('처리 결과를 반영했습니다. 닫으면 요약·사이드바도 새로 조회합니다.');
        } catch (error) {
            invalidatePreview();
            message(error.message + (state.changed ? ' 처리 후 조회에 실패했다면 다시 열어 상태를 확인하세요.' : ''));
        } finally {
            state.busy=false; dialog.querySelectorAll('button').forEach(b=>b.disabled=false); renderSelection();
        }
    }
    async function showPreview(decision, keys) {
        const reason = el('reason').value.trim();
        if (!reason) { message('확인 또는 취소 사유를 입력하세요.'); el('reason').focus(); return; }
        const seq = sequence;
        invalidatePreview();
        const version = state.previewVersion;
        const preview = await request({action:'preview',decision,keys,reason});
        if (seq!==sequence || version!==state.previewVersion) return;
        state.preview=preview;
        el('preview').hidden=false;
        el('preview').innerHTML=`<h3>${escape(actionLabels[decision])} 미리보기</h3><p><b>${preview.count}건 / ${preview.groups}개 값</b> · 수집일 ${escape(preview.source_date)}</p><p>${escape(preview.scope.country)} / ${escape(state.retailer)} / ${escape(preview.scope.product)}</p>${preview.targets.map(t=>`<p><b>${escape(t.field)}</b> · ${escape(t.value)} · ${t.count}건</p>`).join('')}<p>${decision==='normal'?'같은 범위의 동일 값은 다음 수집에도 정상으로 인정합니다.':decision==='error'?'같은 오류 값은 다음 수집에서 재검증하며, 값이 바뀌면 기존 검증 기준으로 판단합니다.':'등록 기준을 취소하고 다시 검증합니다.'}</p><button data-fr="apply">${preview.count}건에 적용</button><button data-fr="cancel-preview">닫기</button>`;
    }
    async function onClick(event) {
        const b=event.target.closest('[data-fr]');
        if (!b || state?.busy) return;
        const action=b.dataset.fr;
        try {
            if(action==='close')close();
            if(action==='tab'){state.tab=b.dataset.tab;state.selected.clear();render();}
            if(action==='select-all'){visibleGroups().forEach(g=>state.selected.add(g.key));renderGroups();}
            if(action==='clear'){state.selected.clear();renderGroups();}
            if(action==='preview')await showPreview(b.dataset.decision,[...state.selected]);
            if(action==='revoke')await showPreview('revoke',[b.dataset.key]);
            if(action==='cancel-preview')invalidatePreview();
            if(action==='apply'&&state.preview)await mutate({action:'apply',token:state.preview.token});
            if(action==='undo'){
                const reason=el('reason').value.trim();
                if(!reason){message('처리 취소 사유를 입력하세요.');el('reason').focus();return;}
                await mutate({action:'undo',event_id:Number(b.dataset.event),revision:state.data.revision,reason});
            }
        } catch(error){message(error.message);}
    }
    document.addEventListener('click',event=>{
        const b=event.target.closest('[data-format-review-table]');
        if(!b)return;
        event.preventDefault();event.stopPropagation();
        open(b.dataset.formatReviewTable,b.dataset.formatReviewRetailer,typeof getSelectedDate==='function'?getSelectedDate():'',b.dataset.formatReviewField);
    },true);
    window.FormatReview={open,button,supports,safeURL};
}());
