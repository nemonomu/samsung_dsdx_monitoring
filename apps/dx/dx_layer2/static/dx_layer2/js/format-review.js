(function () {
    'use strict';
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const labels = {pending:'확인 필요', error:'오류 확정', baseline_normal:'기존 기준상 정상', legacy_normal:'과거 정상 처리 · 재확인', registered_normal:'등록한 정상'};
    const actionLabels = {normal:'정상 값 일괄 등록', error:'오류 일괄 확정', revoke:'기준 등록 취소', undo:'처리 취소'};
    const supports = table => table === 'tv_retail' || /^(sea|siel|tse|seda|seg|sem|seib)_(tv|ref|ldy|ldy_dryer)_retail$/.test(table);
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
            if (event.target.id === 'fr-reason') { state.reason=event.target.value; clearMessage(); }
        });
        dialog.addEventListener('paste', event => {
            const files = [...(event.clipboardData?.items || [])].filter(i=>i.kind==='file' && i.type.startsWith('image/')).map(i=>i.getAsFile());
            if (files.length && !state.busy && !state.evidenceDetail && state.tab!=='history') { event.preventDefault(); addCaptures(files); }
        });
        dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    }
    function close() {
        if (state?.busy) { message('처리가 끝난 뒤 닫아주세요.'); return; }
        sequence++; controller?.abort(); dialog.close();
        if (state?.changed) window.location.reload();
    }
    async function request(body, signal, extra = {}) {
        const params = {table:state.table, retailer:state.retailer, date:state.date};
        const options = {credentials:'same-origin', signal};
        let url = '/dx/layer2/api/format-review/';
        if (body) {
            const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '');
            Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRFToken':decodeURIComponent(csrf)}, body:JSON.stringify({...params, ...body})});
        } else url += '?' + new URLSearchParams({...params, ...extra});
        const response = await fetch(url, options);
        if(response.status===413)throw new Error('요청 크기가 너무 큽니다. 캡처나 확인 URL 수를 줄여주세요.');
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
        state = {table, retailer, date:date || getSelectedDate(), field, tab:'issues', search:'', selected:new Set(), changed:false, busy:false, reason:'', captures:[], checkedURLs:new Set(), uploading:false};
        dialog.innerHTML = '<div class="fr-header"><h2>형식검증 일괄 검토</h2><button data-fr="close">닫기</button></div><div class="fr-body">현재 수집 대상과 기준을 불러오는 중입니다…</div>';
        if (!dialog.open) dialog.showModal();
        try { const data = await request(null, controller.signal); if (seq !== sequence) return; state.data = data; render(); }
        catch (error) { if (error.name === 'AbortError') return; dialog.querySelector('.fr-body').textContent = error.message; }
    }
    function render() {
        const data = state.data;
        const fields = [...new Set((state.tab==='registered' ? data.registrations : data.groups.filter(g=>g.tab===state.tab && baselineAllowed(g))).map(g => g.field))].sort();
        if (!fields.includes(state.field)) state.field='';
        dialog.innerHTML = `<div class="fr-header"><div><h2>형식검증 · 값별 일괄 검토</h2><div class="fr-muted">${escape(data.context.country)} / ${escape(state.retailer)} / ${escape(data.context.product)} · 조회일 ${escape(data.date)} · 수집일 ${escape(data.source_date)}</div></div><button data-fr="close">닫기</button></div>
            <div class="fr-body"><div class="fr-note">현재 검증 대상 ${data.record_count}건을 컬럼·값별로 묶습니다. 비교 이력은 처리 대상에서 제외합니다. 상품 URL을 확인한 뒤 정상 값을 등록하면 같은 국가·리테일러·컬럼의 동일 값은 TV·REF·LDY·LDY_DRYER에 함께 적용되며 다음 수집에도 정상으로 인정됩니다. 오류 값은 다음 수집에서 다시 검증합니다.</div>
            ${!data.available?'<div class="fr-warning">검토 저장소 마이그레이션이 필요합니다. 조회만 가능하며 저장은 비활성화됩니다.</div>':''}
            <div class="fr-tabs">${[['issues','이상 검출 확인'],['baseline','기존 정상 재확인'],['registered','등록한 정상 관리'],['history','처리 이력']].map(([key,label])=>`<button data-fr="tab" data-tab="${key}" aria-pressed="${state.tab===key}">${label}</button>`).join('')}</div>
            <div class="fr-tools"><label>컬럼 <select id="fr-field"><option value="">전체 컬럼</option>${fields.map(f=>`<option value="${escape(f)}" ${state.field===f?'selected':''}>${escape(f)}</option>`).join('')}</select></label><input id="fr-search" type="search" aria-label="수집 값 검색" placeholder="값 검색" value="${escape(state.search)}"><button data-fr="select-all">검색된 그룹 전체 선택</button><button data-fr="clear">선택 해제</button></div>
            <div class="fr-layout"><div id="fr-groups"></div><aside><div id="fr-selected"></div><p class="fr-muted">정상 등록·등록 취소는 같은 국가·리테일러·컬럼의 TV·REF·LDY·LDY_DRYER에 공유됩니다. 오류 확정은 현재 상품군에 적용하며 원본 값은 수정하지 않습니다. 사유를 적고 처리 버튼을 누르면 바로 저장됩니다.</p><label for="fr-reason">확인 / 취소 사유</label><textarea id="fr-reason" maxlength="1000" placeholder="페이지 확인 결과와 처리 근거를 입력하세요">${escape(state.reason)}</textarea><div id="fr-evidence-input"><details><summary>확인한 상품 URL 선택 <span id="fr-url-count"></span></summary><p class="fr-muted">실제로 페이지를 확인한 URL만 체크하세요. 최대 100개.</p><div id="fr-checked-urls"></div></details><label class="fr-upload">캡처 첨부 (선택)<input id="fr-files" type="file" accept="image/png,image/jpeg,image/webp" multiple></label><p class="fr-muted">Ctrl+V 붙여넣기 가능 · 최대 3장. 큰 이미지는 저장 크기에 맞춰 축소합니다. 대표 상품의 캡처를 일괄 처리 근거로 함께 저장합니다.</p><div id="fr-captures"></div></div><div class="fr-actions"><button data-fr="review" data-decision="normal">정상 값 일괄 등록</button><button data-fr="review" data-decision="error">오류 일괄 확정</button></div><div id="fr-message" role="status" aria-live="polite"></div></aside></div></div>`;
        renderGroups();
    }
    function baselineAllowed(group) { return state.tab!=='baseline' || !(state.data.baseline_excluded_fields || []).includes(group.field); }
    function visibleGroups() {
        return state.data.groups.filter(g => g.tab === state.tab && baselineAllowed(g) && (!state.field || g.field === state.field) && g.value.toLowerCase().includes(state.search.toLowerCase()));
    }
    function policyRow(policy) {
        return `<article class="fr-group"><b>${escape(policy.field)}</b><div class="fr-value">${escape(policy.value)}</div><p>${escape(policy.origin_product || state.data.context.product)}에서 등록 · ${escape(policy.actor)} · ${escape(policy.created_at)} · 적용 시작 ${escape(policy.date)}</p><p>${escape(policy.reason)}</p><button data-fr="evidence" data-event="${policy.event_id}">확인 근거 보기</button> <button data-fr="revoke" data-key="${policy.key}">등록 취소</button></article>`;
    }
    function groupContext(group) {
        const pattern = group.rule?.pattern;
        const description = group.rule?.description;
        const reasons = group.reasons || [];
        const queries = group.queries || {};
        const queryBlock = (title, sql) => sql ? `<div class="fr-query"><div><b>${title}</b><button data-fr="copy-sql" type="button">SQL 복사</button></div><pre>${escape(sql)}</pre></div>` : '';
        return `<div class="fr-rule"><b>검증규칙 허용 패턴</b><code>${escape(pattern || '등록된 허용 패턴 없음')}</code>${description ? `<small>${escape(description)}</small>` : ''}</div>
            <div class="fr-reasons"><b>이상 / 확인 필요 이유</b><span>${escape(reasons.join(' · ') || (group.states.error ? '이전에 오류로 확정한 값입니다.' : '기존 기준 통과 값의 재확인 대상입니다.'))}</span></div>
            <details class="fr-queries"><summary>조회 SQL · 이번 처리 대상 / 동일 값 전체 이력</summary>${queryBlock('이번 처리 대상 ID 조회', queries.targets)}${queryBlock('동일 값 전체 이력 조회', queries.all_values)}</details>`;
    }
    function renderGroups() {
        if (!state.data || !el('groups')) return;
        clearMessage();
        dialog.classList.toggle('fr-viewing', !!state.evidenceDetail);
        dialog.querySelector('.fr-tools').hidden = state.tab==='history' || !!state.evidenceDetail;
        el('evidence-input').hidden = state.tab==='history';
        dialog.querySelector('.fr-actions').hidden = ['history','registered'].includes(state.tab);
        dialog.querySelectorAll('[data-fr="select-all"], [data-fr="clear"]').forEach(b=>b.hidden=state.tab==='registered');
        if (state.evidenceDetail) {
            renderEvidence();
        } else if (state.tab === 'history') {
            el('groups').innerHTML = `<p class="fr-note">최근 ${state.data.history.length}건 · 확인 근거에서 처리 당시 상품·URL과 캡처를 볼 수 있습니다. 취소된 처리도 기록을 보존합니다.</p>` + (state.data.history.map(e=>`<article class="fr-event"><b>${escape(actionLabels[e.action] || e.action)} · ${e.count}건 / ${e.groups}개 값 ${e.is_del?'(취소됨)':''}</b><p>${escape(e.origin_product || state.data.context.product)}에서 처리 · ${escape(e.actor)} · ${escape(e.created_at)} · 조회일 ${escape(e.inspection_date)}</p><p>${escape(e.reason)}</p><button data-fr="evidence" data-event="${e.id}">확인 근거 보기 · 캡처 ${e.capture_count}장</button> ${!e.is_del&&e.action!=='undo'?`<button data-fr="undo" data-event="${e.id}">이 처리 취소</button>`:''}</article>`).join('') || '<p>처리 이력이 없습니다.</p>');
        } else if (state.tab === 'registered') {
            const policies = state.data.registrations.filter(p => (!state.field || p.field === state.field) && p.value.toLowerCase().includes(state.search.toLowerCase()));
            el('groups').innerHTML = policies.filter(p=>p.action==='normal').map(policyRow).join('') || '<p>등록한 정상 값이 없습니다.</p>';
            const rejected = policies.filter(p=>p.action==='error');
            if (rejected.length) el('groups').innerHTML += `<details><summary>오류 추적 기준 관리 (${rejected.length})</summary>${rejected.map(policyRow).join('')}</details>`;
        } else {
            const groups = visibleGroups();
            el('groups').innerHTML = (state.tab === 'baseline' ? '<p class="fr-note">기존 기준 통과와 과거 정상 처리는 새 정상 등록과 구분합니다. 아직 원본을 재확인하지 않은 상태이며 오류 건수에 포함하지 않습니다.</p>' : '') + (groups.map(g=>`<article class="fr-group ${state.selected.has(g.key)?'selected':''}"><label><input type="checkbox" data-group="${g.key}" ${state.selected.has(g.key)?'checked':''}><b>${escape(g.field)}</b> <strong>${g.count}건</strong></label><div class="fr-value">${escape(g.value)}</div><div class="fr-badges">${Object.entries(g.states).map(([key,count])=>`<span class="fr-badge ${key}">${escape(labels[key])} ${count}</span>`).join('')}</div>${groupContext(g)}<div class="fr-links">대표 URL: ${g.records.slice(0,3).map(link).join(' ')}</div><details><summary>전체 상품·URL·검출 근거 (${g.count}건)</summary><div class="fr-scroll"><table><thead><tr><th>상품</th><th>수집일시</th><th>상품 URL</th><th>검토 상태 / 근거</th></tr></thead><tbody>${g.records.map(r=>`<tr><td>${escape(r.item)}<br>${escape(r.name)}</td><td>${escape(r.collected_at)}</td><td>${link(r)}</td><td>${escape(labels[r.state])}<br>${escape(r.original_error?.reason || '')}</td></tr>`).join('')}</tbody></table></div></details></article>`).join('') || '<p class="fr-empty">해당 값 그룹이 없습니다.</p>');
        }
        renderSelection(); renderCaptures();
    }
    function renderSelection() {
        const groups = state.data.groups.filter(g=>state.selected.has(g.key));
        el('selected').innerHTML = state.tab==='history' ? '<b>처리 취소</b>' : `<strong>${groups.reduce((n,g)=>n+g.count,0)}건</strong> / ${groups.length}개 값 선택`;
        el('selected').nextElementSibling.textContent=state.tab==='history' ? '취소 사유를 입력한 뒤, 취소할 이력의 ‘이 처리 취소’를 누르세요. 저장된 확인 근거는 보존됩니다.' : '정상 등록·등록 취소는 같은 국가·리테일러·컬럼의 TV·REF·LDY·LDY_DRYER에 공유됩니다. 오류 확정은 현재 상품군에 적용하며 원본 값은 수정하지 않습니다. 등록 취소 시에도 아래에 사유를 입력하세요.';
        dialog.querySelectorAll('[data-fr="review"]').forEach(b=>b.disabled=!groups.length || !state.data.available || state.busy || state.uploading || ['registered','history'].includes(state.tab));
        const records = new Map(groups.flatMap(g=>g.records).filter(r=>safeURL(r.url)).map(r=>[r.url,r]));
        state.checkedURLs = new Set([...state.checkedURLs].filter(url=>records.has(url)));
        el('checked-urls').innerHTML = [...records].map(([url,r])=>`<label><input type="checkbox" data-checked-url="${escape(url)}" ${state.checkedURLs.has(url)?'checked':''}>${link(r)}</label>`).join('') || '<p class="fr-muted">값 그룹을 선택하면 URL이 표시됩니다.</p>';
        el('url-count').textContent = `(${state.checkedURLs.size}개 확인)`;
    }
    function message(text) { if (el('message')) el('message').textContent=text; }
    function clearMessage() {
        message('');
    }
    function onChange(event) {
        if (event.target.id==='fr-files') { addCaptures([...event.target.files]); event.target.value=''; }
        if (event.target.dataset.checkedUrl) {
            const url=event.target.dataset.checkedUrl;
            if(state.busy) {event.target.checked=state.checkedURLs.has(url);return;}
            if(event.target.checked && state.checkedURLs.size>=100){event.target.checked=false;message('확인 URL은 최대 100개까지 선택하세요.');return;}
            event.target.checked ? state.checkedURLs.add(url) : state.checkedURLs.delete(url);
            clearMessage(); el('url-count').textContent=`(${state.checkedURLs.size}개 확인)`;
        }
        if (event.target.dataset.group) {
            const key = event.target.dataset.group;
            if (state.busy) { event.target.checked=state.selected.has(key); return; }
            event.target.checked ? state.selected.add(key) : state.selected.delete(key);
            event.target.closest('.fr-group').classList.toggle('selected', event.target.checked);
            clearMessage(); renderSelection();
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
            state.data=await request(); state.selected.clear(); state.reason=''; state.captures=[]; state.checkedURLs.clear();
            render(); message('처리 결과를 반영했습니다. 닫으면 요약·사이드바도 새로 조회합니다.');
        } catch (error) {
            clearMessage();
            message(error.message + (state.changed ? ' 처리 후 조회에 실패했다면 다시 열어 상태를 확인하세요.' : ''));
        } finally {
            state.busy=false; dialog.querySelectorAll('button').forEach(b=>b.disabled=false); renderSelection();
        }
    }
    async function applyReview(decision, keys) {
        const reason = el('reason').value.trim();
        if (!reason) { message('확인 또는 취소 사유를 입력하세요.'); el('reason').focus(); return; }
        if(state.uploading){message('캡처 준비가 끝난 뒤 처리하세요.');return;}
        const snapshots = Object.fromEntries(state.data.groups.filter(g=>keys.includes(g.key)).map(g=>[g.key,g.snapshot]));
        await mutate({action:'review',decision,keys,reason,evidence:evidencePayload(),snapshots});
    }
    function evidencePayload() {
        return {checked_urls:[...state.checkedURLs], captures:state.captures.map(c=>({name:c.name,data:c.data}))};
    }
    function renderCaptures() {
        el('captures').innerHTML=state.captures.map((c,index)=>`<figure><img src="${c.preview}" alt="${escape(c.name)}"><figcaption>${escape(c.name)} <button data-fr="remove-capture" data-index="${index}" aria-label="${escape(c.name)} 삭제">삭제</button></figcaption></figure>`).join('');
    }
    async function prepareCapture(file) {
        if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>20*1024*1024) throw new Error('PNG·JPEG·WebP 이미지 (20MB 이하)만 첨부하세요.');
        const source=URL.createObjectURL(file);
        try {
            const img=new Image(); img.src=source; await img.decode();
            if(img.naturalWidth*img.naturalHeight>16000000)throw new Error('캡처는 최대 1,600만 화소까지 첨부할 수 있습니다.');
            const canvas=document.createElement('canvas');
            const scale=Math.min(1,2000/Math.max(img.naturalWidth,img.naturalHeight));
            canvas.width=Math.max(1,Math.round(img.naturalWidth*scale)); canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));
            const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height);
            let preview=canvas.toDataURL('image/png');
            if(preview.length>270000) {
                for(const quality of [.9,.8,.65,.5,.35]) {preview=canvas.toDataURL('image/jpeg',quality);if(preview.length<=270000)break;}
            }
            if(preview.length>270000)throw new Error('저장 크기(200KB)를 초과합니다. 필요한 부분만 잘라서 첨부하세요.');
            const ext=preview.startsWith('data:image/png')?'png':'jpg';
            return {name:((file.name || 'capture').replace(/\.[^.]+$/,'').slice(0,140) || 'capture')+'.'+ext,preview,data:preview.split(',')[1]};
        } finally {URL.revokeObjectURL(source);}
    }
    async function addCaptures(files) {
        if(state.busy || state.uploading)return;
        if(state.captures.length+files.length>3){message('캡처는 최대 3장까지 첨부하세요.');return;}
        const session=state;
        state.uploading=true;clearMessage();renderSelection();message('캡처를 준비하고 있습니다…');
        try {
            const captures=[];
            for(const file of files)captures.push(await prepareCapture(file));
            if(state!==session)return;
            state.captures.push(...captures);renderCaptures();message('캡처를 준비했습니다. 처리 버튼을 누르면 함께 저장됩니다.');
        } catch(error){if(state===session)message(error.message);}
        finally{session.uploading=false;if(state===session)renderSelection();}
    }
    function renderEvidence() {
        const e=state.evidenceDetail;
        const checked=new Set(e.checked_urls);
        el('groups').innerHTML=`<button data-fr="evidence-back">← 목록으로</button><h3>확인 근거 · ${escape(actionLabels[e.action])} ${e.is_del?'(취소됨)':''}</h3><p>${escape(e.context.country)} / ${escape(e.context.retailer_name)} / ${escape(e.context.product)} · 조회일 ${escape(e.inspection_date)}</p><p>${escape(e.actor)} · ${escape(e.created_at)}</p><div class="fr-evidence-reason">${escape(e.reason)}</div><p class="fr-note">처리 당시 저장한 근거입니다. URL의 현재 페이지 내용은 이후 달라질 수 있습니다. 캡처는 이 일괄 처리에 공통으로 적용한 대표 근거입니다.</p><h4>캡처 ${e.captures.length}장 · 클릭하여 원본 크기로 보기</h4><div class="fr-evidence-images">${e.captures.map(c=>`<a href="${escape(c.url)}" target="_blank" rel="noopener noreferrer"><img src="${escape(c.url)}" alt="${escape(c.name)}"><span>${escape(c.name)}</span></a>`).join('') || '<p>첨부한 캡처가 없습니다.</p>'}</div><p>실제 확인으로 체크한 URL: ${checked.size}개${checked.size?'':' (별도 기록 없음)'}</p>${e.targets.map(t=>`<article class="fr-group"><b>${escape(t.field)}</b><div class="fr-value">${escape(t.value)}</div><p>${t.count}건 · 수집일 ${escape(t.source_date)}</p><details><summary>처리 당시 전체 상품·URL (${t.records.length}건)</summary><div class="fr-scroll"><table><thead><tr><th>상품</th><th>상품 URL</th><th>확인 여부</th></tr></thead><tbody>${t.records.map(r=>`<tr><td>${escape(r.item)}<br>${escape(r.name)}</td><td>${link(r)}</td><td>${checked.has(r.url)?'확인한 URL':'처리 대상'}</td></tr>`).join('')}</tbody></table></div></details></article>`).join('')}`;
    }
    async function copySQL(button) {
        const sql = button.closest('.fr-query')?.querySelector('pre')?.textContent;
        if (!sql) return;
        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(sql);
        else {
            const input = document.createElement('textarea');
            input.value = sql; input.style.position = 'fixed'; input.style.opacity = '0';
            document.body.appendChild(input); input.select();
            const copied = document.execCommand('copy'); input.remove();
            if (!copied) throw new Error('SQL 복사에 실패했습니다. SQL을 선택해서 복사해 주세요.');
        }
        message('조회 SQL을 복사했습니다.');
    }
    async function onClick(event) {
        if (state?.busy) return;
        const card = event.target.closest('.fr-group');
        if (card && !event.target.closest('a, button, input, label, select, textarea, details')) {
            const checkbox = card.querySelector('input[data-group]');
            if (checkbox && window.getSelection()?.isCollapsed !== false) checkbox.click();
            return;
        }
        const b=event.target.closest('[data-fr]');
        if (!b) return;
        const action=b.dataset.fr;
        try {
            if(action==='close')close();
            if(action==='tab'){state.tab=b.dataset.tab;state.evidenceDetail=null;state.selected.clear();render();}
            if(action==='evidence'){
                const seq=sequence, tab=state.tab;
                const detail=await request(null,controller.signal,{event_id:b.dataset.event});
                if(seq===sequence && state.tab===tab){state.evidenceDetail=detail;renderGroups();el('groups').scrollIntoView({block:'start'});}
            }
            if(action==='evidence-back'){state.evidenceDetail=null;renderGroups();}
            if(action==='remove-capture'){state.captures.splice(Number(b.dataset.index),1);clearMessage();renderCaptures();}
            if(action==='copy-sql')await copySQL(b);
            if(action==='select-all'){visibleGroups().forEach(g=>state.selected.add(g.key));renderGroups();}
            if(action==='clear'){state.selected.clear();renderGroups();}
            if(action==='review')await applyReview(b.dataset.decision,[...state.selected]);
            if(action==='revoke')await applyReview('revoke',[b.dataset.key]);
            if(action==='undo'){
                const reason=el('reason').value.trim();
                if(!reason){message('처리 취소 사유를 입력하세요.');el('reason').focus();return;}
                await mutate({action:'undo',event_id:Number(b.dataset.event),revision:state.data.revision,shared_revision:state.data.shared_revision,reason});
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
