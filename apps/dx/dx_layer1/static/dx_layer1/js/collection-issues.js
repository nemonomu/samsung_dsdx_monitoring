(function () {
    'use strict';
    const host = document.getElementById('collection-issues-container');
    if (!host) return;
    const section = window.LAYER1.section;
    const missingOnly = section === 'dashboard';
    const issueLabel = missingOnly ? '미수집' : '수집 이상';
    const countries = {retail:'SEA', seda_retail:'SEDA', seg_retail:'SEG', siel_retail:'SIEL', sem_retail:'SEM', tse_retail:'TSE', seib_retail:'SEIB'};
    const enabled = section === 'dashboard' || section === 'past_review' || Object.hasOwn(countries, section);
    const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const statusText = {open:'미해결', resolved:'복구 검증 완료', excepted:'예외 처리'};
    let selection = {}, status = 'open', rows = [], page = 1, controller, lastKey, selectedIssue, queries, kind = 'count';
    const size = 20;
    const dialog = document.createElement('dialog');
    dialog.className = 'ci-dialog';
    dialog.setAttribute('aria-label','수집 이상 상세 및 조회 SQL');
    document.body.appendChild(dialog);
    async function request(url, options = {}) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error([data.error || '조회하지 못했습니다.', data.action].filter(Boolean).join(' '));
        return data;
    }
    function scope(values) {
        const params = new URLSearchParams({status});
        const country = countries[section] || values.country;
        if (country) params.set('country',country);
        if (values.product) params.set('product',values.product);
        if (values.retailer) params.set('retailer',values.retailer);
        return params;
    }
    function render(data) {
        rows = missingOnly ? data.issues.filter(row => !row.column) : data.issues;
        const pages = Math.max(1,Math.ceil(rows.length/size));
        page = Math.min(page,pages);
        const scans = data.scans || [];
        const unavailable = scans.filter(s=>s.error).length;
        const unchecked = data.target_count-scans.filter(s=>s.scanned_through).length;
        const through = scans.filter(s=>s.scanned_through).map(s=>s.scanned_through).sort()[0];
        const checked = scans.filter(s=>s.last_checked_at).map(s=>s.last_checked_at).sort()[0];
        const deferred = scans.filter(s=>s.start_basis==='first_observed' && s.coverage_start>data.start_date);
        const coverage = `점검 시작 ${data.start_date} · ${through ? '공통 점검 완료 '+through+'까지' : '과거 점검 준비 중'}${unchecked>0?' · 점검 대기 '+unchecked+'개 대상':''}${unavailable?' · 조회 실패 '+unavailable+'개 대상':''}${checked?' · 최근 점검 '+new Date(checked).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):''}`;
        host.innerHTML = `<section class="ci-panel ${rows.length?'':'ci-clear'}" aria-label="과거 미해결 ${issueLabel}"><div class="ci-head"><div><h3>과거 미해결 · ${issueLabel} ${rows.length}건${status!=='open'?' (이력 조회)':''}</h3><p>조회 날짜의 정상 여부와 별개입니다. 원래 누락된 날짜의 복구·검증 전까지 유지합니다.</p></div><div class="ci-controls"><select aria-label="미해결 및 처리 이력" id="ci-status"><option value="open">미해결</option><option value="resolved">복구 완료 이력</option><option value="excepted">예외 처리 이력</option><option value="all">전체 이력</option></select><button type="button" data-ci-refresh>새로고침</button></div></div><p class="ci-note ${unavailable||unchecked?'ci-error':''}">${esc(coverage)}</p>${rows.length?`<div class="ci-scroll"><table><thead><tr><th>국가 · 리테일러</th><th>제품군</th><th>문제 데이터일</th><th>수집 항목</th><th>상태</th><th>상세</th></tr></thead><tbody>${rows.slice((page-1)*size,page*size).map(r=>`<tr><td><b>${esc(r.country)} · ${esc(r.retailer)}</b></td><td>${esc(r.product)}</td><td><b>${esc(r.source_date)}</b></td><td>${esc(r.column||'전체 미수집')}<small>${r.column?'발견 당시 기준 '+esc(r.baseline)+' / 수집 '+r.observed_count+'건':'DB 원본 수집일 · 모든 배치'}</small></td><td><span class="ci-status">${statusText[r.status]||esc(r.status)}</span></td><td><button type="button" data-ci-detail="${r.id}">상세 보기</button> <button type="button" data-ci-sql="${r.id}">조회 SQL</button></td></tr>`).join('')}</tbody></table></div><div class="ci-page"><span>${page} / ${pages}페이지</span><button type="button" data-ci-page="${page-1}" ${page===1?'disabled':''}>이전</button><button type="button" data-ci-page="${page+1}" ${page===pages?'disabled':''}>다음</button></div>`:`<p class="ci-note">${unavailable||unchecked?'아직 전체 점검을 완료하지 못했습니다. 미수집 0건으로 확정하지 않습니다.':'저장된 해당 상태의 이력이 없습니다. 완료 범위 이후의 날짜는 다음 점검에서 확인합니다.'}</p>`}</section>`;
        if (missingOnly) {
            if (!rows.length) host.querySelector('.ci-panel').classList.add('ci-compact');
            host.querySelector('.ci-head p').remove();
            host.querySelectorAll('.ci-note').forEach(note => note.remove());
        }
        document.getElementById('ci-status').value=status;
        if (!missingOnly && deferred.length) {
            const note=document.createElement('p');
            note.className='ci-note';
            note.textContent='최초 데이터 이전은 판정 유보: '+deferred.map(s=>`${s.country} ${s.retailer} ${s.product} (${s.coverage_start}부터 점검)`).join(' · ');
            host.querySelector('.ci-head').after(note);
        }
        document.getElementById('ci-status').onchange=e=>{status=e.target.value;page=1;load(selection,true);};
        host.querySelectorAll('[data-ci-page]').forEach(b=>b.onclick=()=>{page=Number(b.dataset.ciPage);render(data);});
    }
    async function load(values = {}, force = false) {
        if (!enabled) return;
        selection = values;
        const params = scope(values), key = params.toString()+'|'+(values.date||'');
        if (!force && lastKey===key) return;
        if (lastKey !== key) page = 1;
        lastKey = key;
        if (controller) controller.abort();
        controller = new AbortController();
        const current = controller;
        host.hidden = false;
        host.innerHTML='<section class="ci-panel ci-clear"><p class="ci-note" role="status">과거 미해결 이력을 확인하고 있습니다.</p></section>';
        try {
            const data = await request('/dx/layer1/api/collection-issues/?'+params,{signal:current.signal});
            if (current.signal.aborted) return;
            render(data);
        } catch(error) {
            if (current.signal.aborted) return;
            lastKey=null;
            host.innerHTML=`<section class="ci-panel"><p class="ci-note ci-error" role="alert">${esc(error.message)} 미해결 없음으로 처리하지 않습니다. <button type="button" data-ci-refresh>다시 조회</button></p></section>`;
        }
    }
    function sqlView() {
        dialog.querySelector('#ci-sql-text').value=queries[kind];
        dialog.querySelectorAll('[data-ci-kind]').forEach(b=>b.classList.toggle('active',b.dataset.ciKind===kind));
    }
    function openDialog(title, body) {
        dialog.innerHTML=`<h3>${esc(title)}</h3>${body}<p class="ci-message" role="status" id="ci-message"></p><div class="ci-actions"><button type="button" data-ci-close>닫기</button></div>`;
        if (!dialog.open) dialog.showModal();
    }
    function showSql(row, data) {
        queries=data.queries;kind='count';
        openDialog(`${row.country} · ${row.retailer} · ${row.product} · ${row.source_date}`,
            `<p>DB 원본 수집일 기준 · 해당 날짜의 모든 배치. SIEL만 기존 업무 시간대 예외를 적용합니다.</p><div class="ci-tabs"><button type="button" data-ci-kind="count">전체 건수 확인</button><button type="button" data-ci-kind="rows">원본 데이터 조회</button><button type="button" data-ci-kind="batches">배치별 건수</button></div><textarea class="ci-sql" id="ci-sql-text" readonly spellcheck="false" aria-label="조회 SQL"></textarea><div class="ci-actions"><button type="button" data-ci-copy>SQL 복사</button></div>`);
        sqlView();
    }
    async function sql(row) {
        try {
            const data = await request('/dx/layer1/api/collection-issues/sql/?'+new URLSearchParams({country:row.country,product:row.product,retailer:row.retailer,source_date:row.source_date}));
            showSql(row,data);
        } catch(error) {openDialog('조회 SQL',`<p>${esc(error.message)}</p>`);}
    }
    function showDetail(data) {
        selectedIssue=data.issue;queries=data.queries;
        const r=selectedIssue;
        const names={detected:'문제 발견',recovered:'복구 검증 완료',reopened:'문제 재발',acknowledge:'담당자 확인 · 미해결 유지',except:'사유 기록 후 예외 처리',reopen:'예외 취소 · 미해결'};
        openDialog(`${r.country} · ${r.retailer} · ${r.product} · ${r.source_date}`,
            `<p><b>${esc(r.column||'전체 미수집')}</b> · ${statusText[r.status]}<br>발견 당시 ${r.observed_count}건${r.baseline!=null?' / 기준 '+r.baseline+'건':''} · 최근 확인 ${r.current_count}건</p><p>다른 날짜의 정상 수집이나 확인 버튼만으로 해결하지 않습니다. 복구 재검증은 이 날짜를 다시 조회합니다.</p><ol>${r.history.map(h=>`<li>${esc(new Date(h.created_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}))} · ${esc(names[h.action]||h.action)} ${esc(h.username)}${h.reason?' · '+esc(h.reason):''}</li>`).join('')}</ol><label>확인·예외 처리 사유<textarea id="ci-reason" maxlength="1000" rows="2"></textarea></label><div class="ci-actions"><button type="button" data-ci-show-sql>조회 SQL</button><button type="button" data-ci-action="recheck">원래 날짜 복구 재검증</button>${r.status==='open'?'<button type="button" data-ci-action="acknowledge">확인만 기록</button><button type="button" data-ci-action="except">사유로 예외 처리</button>':r.status==='excepted'?'<button type="button" data-ci-action="reopen">예외 취소</button>':''}</div>`);
    }
    host.addEventListener('click',async e=>{
        const b=e.target.closest('button');if(!b)return;
        if(b.hasAttribute('data-ci-refresh'))return load(selection,true);
        const id=b.dataset.ciDetail||b.dataset.ciSql;if(!id)return;
        try {const data=await request('/dx/layer1/api/collection-issues/'+id+'/');if(b.dataset.ciSql)showSql(data.issue,data);else showDetail(data);}
        catch(error){openDialog('수집 이상 상세',`<p>${esc(error.message)}</p>`);}
    });
    dialog.addEventListener('click',async e=>{
        const b=e.target.closest('button');if(!b)return;
        if(b.hasAttribute('data-ci-close'))return dialog.close();
        if(b.dataset.ciKind){kind=b.dataset.ciKind;return sqlView();}
        if(b.hasAttribute('data-ci-show-sql'))return showSql(selectedIssue,{queries});
        if(b.hasAttribute('data-ci-copy')){
            const textarea=dialog.querySelector('#ci-sql-text');let copied=false;
            try{await navigator.clipboard.writeText(textarea.value);copied=true;}catch(_){}
            if(!copied){textarea.focus();textarea.select();try{copied=document.execCommand('copy');}catch(_){}}
            dialog.querySelector('#ci-message').textContent=copied?'SQL을 복사했습니다.':'선택된 SQL을 Ctrl+C로 복사하세요.';return;
        }
        if(b.dataset.ciAction){
            const reason=dialog.querySelector('#ci-reason').value.trim();
            if(b.dataset.ciAction!=='recheck'&&!reason){dialog.querySelector('#ci-message').textContent='처리 사유를 입력해주세요.';return;}
            dialog.querySelectorAll('[data-ci-action]').forEach(x=>x.disabled=true);
            try {
                const data=await request('/dx/layer1/api/collection-issues/'+selectedIssue.id+'/action/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},body:JSON.stringify({action:b.dataset.ciAction,revision:selectedIssue.revision,reason})});
                showDetail({...data,queries});load(selection,true);
            }catch(error){dialog.querySelector('#ci-message').textContent=error.message;dialog.querySelectorAll('[data-ci-action]').forEach(x=>x.disabled=false);}
        }
    });
    window.CollectionIssues={load,sql};
})();
