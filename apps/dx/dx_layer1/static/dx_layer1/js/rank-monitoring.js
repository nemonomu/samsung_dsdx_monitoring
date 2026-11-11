(function () {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const tier = rank => rank >= 1 && rank <= 300 ? Math.floor((rank - 1) / 100) : -1;
    const priority = {data:0, return:1, missing:2, next_missing:2, swing:3, unassessed:4, new:5, stable:6};
    const numeric = cell => ['ranked', 'outside'].includes(cell.state) && cell.rank != null;
    function safeUrl(value) {
        try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; }
        catch (_) { return ''; }
    }
    function filterProducts(products, state) {
        const query = state.query.trim().toLocaleLowerCase();
        return products.filter(p => (state.view === 'all' || p.review_needed) &&
            (state.signal === 'all' || p.signals[state.signal]) &&
            (state.tier === 'all' || (p.cells[0].state === 'ranked' && tier(p.cells[0].rank) === Number(state.tier))) &&
            (!query || `${p.name} ${p.item} ${p.sku}`.toLocaleLowerCase().includes(query)))
            .sort((a,b) => (state.sort === 'priority' ? priority[a.status] - priority[b.status] : 0) ||
                (a.cells[0].rank ?? Infinity) - (b.cells[0].rank ?? Infinity) || a.item.localeCompare(b.item));
    }
    function csvCell(value) {
        let text = String(value ?? '');
        if (/^[\s]*[=+@\-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
        return '"' + text.replace(/"/g, '""') + '"';
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {filterProducts, safeUrl, csvCell, tier};
    if (typeof document === 'undefined' || !document.getElementById('rm-config')) return;
    const config = JSON.parse(document.getElementById('rm-config').textContent);
    const el = id => document.getElementById('rm-' + id);
    const state = {view:'all', signal:'all', tier:'all', sort:'rank', query:'', page:1};
    let result = null, selected = null, controller = null, requestNumber = 0, detailNumber = 0, searchTimer = null;
    let loading = false, moreController = null, moreNumber = 0, moreLoading = false, moreError = '', moreExpired = false;
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) loadMore();
    }, {rootMargin:'300px 0px'});
    const badge = (status, label) => `<span class="rm-badge ${status}">${esc(label)}</span>`;
    const reasons = {
        data:'배치 ID·ITEM 누락·유효하지 않은 순위·동일 ITEM의 복수 순위를 확인하세요.',
        return:'기준일만 미발견 후 복귀. 당일 상품 상태와 수집 로그 확인이 필요합니다.',
        missing:'300위 내 미발견. 품절·판매 종료 또는 범위 밖 이동을 확인하세요.',
        next_missing:'기준일에는 수집됐지만 다음 날 300위 안에서 보이지 않습니다. 다음 날의 상품 상태를 확인하세요.',
        swing:'계속 수집됐더라도 큰 순위 이동은 원인 확인 대상입니다.',
        new:'기준일 300위 안에 진입한 상품입니다.',
        unassessed:'비교할 날짜의 수집 데이터가 부족합니다.',
        stable:'예시 기준의 점검 신호가 없습니다.',
    };
    function cellLabel(cell, index) {
        if (numeric(cell)) return cell.rank + '위';
        if (cell.state === 'unavailable') return result.coverage[index].state === 'pending' ? '수집 대기' : '당일 데이터 없음';
        return {absent:'미발견', invalid:'순위값 확인', ambiguous:'복수 순위', identity:'ITEM 확인', batch:'배치 ID 확인'}[cell.state] || '확인 필요';
    }
    function rankCell(product, index) {
        const cell = product.cells[index], before = product.cells[index-1];
        const delta = before && numeric(cell) && numeric(before) ? cell.rank - before.rank : null;
        let sub = numeric(cell) ? (index === 0 ? '비교 기준' : delta == null ? '이전 순위 없음' : delta === 0 ? '변동 없음' :
            `${delta > 0 ? '↓' : '↑'} ${Math.abs(delta)}위 ${delta > 0 ? '하락' : '상승'}`) :
            cell.state === 'absent' ? '해당 배치에서 미발견' : '누락 확정 아님';
        if (cell.state === 'outside') sub += ' · 300위 밖';
        return `<div class="rm-rank ${cell.state} ${delta != null && Math.abs(delta) >= result.criteria.swing ? 'jump' : ''}"><strong>${numeric(cell) ? `${cell.rank}<small>위</small>` : esc(cellLabel(cell,index))}</strong><span class="${delta > 0 ? 'down' : delta < 0 ? 'up' : ''}">${esc(sub)}</span></div>`;
    }
    function message(text, error=false) { el('message').hidden = !text; el('message').textContent = text; el('message').classList.toggle('error',error); }
    function options() {
        const product = config.catalog.find(c => c.product === el('product').value);
        el('retailer').innerHTML = product.retailers.map(r => `<option>${esc(r)}</option>`).join('');
    }
    function dirty() {
        stopMore(); clearTimeout(searchTimer); loading = false;
        requestNumber++; controller?.abort(); el('load').disabled = false;
        result = null; selected = null; el('results').hidden = true;
        if (el('dialog').open) el('dialog').close();
        message('조회 조건이 변경되었습니다. 조회 버튼을 눌러주세요.');
    }
    function paramsFor(pin=true) {
        const params = new URLSearchParams({country:config.country, mode:config.mode, product:el('product').value,
            retailer:el('retailer').value, date:el('date').value, ...state});
        if (pin && result) params.set('snapshot',result.snapshot);
        return params;
    }
    async function load(event, pinned=false) {
        event?.preventDefault(); clearTimeout(searchTimer);
        stopMore(); loading = true; moreError = ''; moreExpired = false;
        const seq = ++requestNumber;
        controller?.abort(); controller = new AbortController();
        const signal = controller.signal;
        selected = null; detailNumber++; if (el('dialog').open) el('dialog').close();
        const params = paramsFor(pinned);
        if (!pinned) {state.page=1;params.set('page','1');result=null;}
        el('load').disabled = true; el('results').hidden = true;
        message('순위 비교 결과를 조회하고 있습니다.');
        try {
            let data;
            for (let attempt=0; attempt<20; attempt++) {
                const response = await fetch('/dx/layer1/rank/api/data/?' + params, {signal});
                if (response.redirected) throw new Error('로그인이 만료되었습니다. 다시 로그인해주세요.');
                data = await response.json();
                if (!response.ok) throw new Error(data.error || '순위 조회에 실패했습니다.');
                if (seq !== requestNumber) return;
                if (response.status !== 202) break;
                message('순위 비교 결과를 준비 중입니다. 아직 누락 여부를 판단하지 않습니다.');
                if (attempt===19) throw new Error('결과 준비가 지연되고 있습니다. 잠시 후 조회 버튼을 눌러주세요.');
                await new Promise(resolve=>setTimeout(resolve,1000));
                if (seq !== requestNumber) return;
            }
            result = data; state.page=data.pagination.page;
            el('results').hidden = false;
            const warnings = [];
            if (!data.review_storage_available) warnings.push(data.review_storage_message);
            if (data.cache_state.state === 'refreshing') warnings.push('이전 완료 결과를 표시 중이며 새 결과를 준비하고 있습니다. 갱신 결과는 조회 버튼으로 확인하세요.');
            if (data.cache_state.state === 'refresh_failed') warnings.push('갱신에 실패하여 이전 완료 결과를 표시합니다. 조회 시각을 확인해주세요.');
            if (data.cache_state.state === 'pinned' && data.cache_state.age_seconds >= 60) warnings.push('목록·상세는 같은 조회 시점의 결과입니다. 최신 결과는 조회 버튼으로 확인하세요.');
            if (!data.coverage[0].available || !data.coverage[1].available) warnings.push('D-1 또는 D의 비교 가능한 데이터가 없어 유지율 판단을 보류합니다.');
            if (!data.counts.all) warnings.push(config.mode === 'samsung' ? '조회 범위에 상품명으로 식별된 삼성 상품이 없습니다.' : '조회 범위에 비교할 상품이 없습니다.');
            message(warnings.join(' ')); renderSummary(); renderTable();
        } catch (error) {
            if (seq !== requestNumber || error.name === 'AbortError') return;
            message(error.message || '조회에 실패했습니다.',true);
        } finally {
            if (seq === requestNumber) {
                loading = false; el('load').disabled = false;
                renderProgress();
            }
        }
    }
    function loadPage() { if (result) load(null,true); }
    function stopMore() {
        observer?.disconnect(); moreNumber++; moreController?.abort(); moreLoading = false;
    }
    function renderProgress() {
        observer?.disconnect();
        if (!result || el('results').hidden) return;
        const hasMore = result.pagination.page < result.pagination.pages;
        el('range').textContent = `${result.products.length} / ${result.pagination.count}개 표시`;
        el('more-status').textContent = moreError || (moreLoading ? '상품을 이어서 불러오는 중…' :
            hasMore ? '아래로 스크롤하면 상품이 계속 표시됩니다.' : result.products.length ? '모든 상품을 표시했습니다.' : '조건에 맞는 상품이 없습니다.');
        el('more-status').classList.toggle('error', Boolean(moreError));
        el('more').hidden = !hasMore || moreLoading || moreExpired || (observer !== null && !moreError);
        el('more').disabled = loading || moreLoading;
        el('more').textContent = moreError ? '다시 불러오기' : '상품 더 보기';
        el('scroll-end').setAttribute('aria-busy', String(moreLoading));
        if (hasMore && !loading && !moreLoading && !moreError) observer?.observe(el('scroll-end'));
    }
    async function loadMore() {
        if (!result || loading || moreLoading || moreError || el('results').hidden || result.pagination.page >= result.pagination.pages) return;
        const basis = result, seq = requestNumber, moreSeq = ++moreNumber;
        const next = result.pagination.page + 1;
        const params = paramsFor(); params.set('page', String(next));
        moreController = new AbortController(); moreLoading = true; renderProgress();
        try {
            const response = await fetch('/dx/layer1/rank/api/data/?' + params, {signal:moreController.signal});
            if (response.redirected) throw new Error('로그인이 만료되었습니다. 다시 로그인해주세요.');
            const data = await response.json();
            if (seq !== requestNumber || moreSeq !== moreNumber || basis !== result) return;
            if (response.status === 409) moreExpired = true;
            if (!response.ok || response.status === 202) throw new Error(data.error || '상품을 이어서 불러오지 못했습니다.');
            if (data.pagination.page !== next || !data.products.length) throw new Error('목록을 이어서 불러오지 못했습니다. 조회 버튼으로 다시 확인해주세요.');
            // Keep the same snapshot and existing DOM rows while appending the next batch.
            result.products.push(...data.products); result.pagination = data.pagination; state.page = next;
            el('table-body').insertAdjacentHTML('beforeend', rowsHtml(data.products));
        } catch (error) {
            if (seq !== requestNumber || moreSeq !== moreNumber || error.name === 'AbortError') return;
            moreError = error.message || '상품을 이어서 불러오지 못했습니다.';
        } finally {
            if (seq === requestNumber && moreSeq === moreNumber && basis === result) {
                moreLoading = false; renderProgress();
            }
        }
    }
    function renderSummary() {
        el('basis').textContent = `${result.country} / ${result.product} / ${result.retailer} · ${result.basis} · 조회 ${new Date(result.updated_at).toLocaleString('ko-KR')}` +
            (config.mode === 'samsung' ? ' · 삼성 판별: 상품명에 Samsung 또는 삼성이 명시된 상품. 전체 리테일러 순위 유지.' : '') +
            (result.sku_from_master ? ' · SKU: 현재 아이템 마스터 값(수집 당시 값과 다를 수 있음).' : '');
        el('coverage').innerHTML = result.coverage.map((day,i) => `<div class="rm-day ${i === 1 ? 'current' : ''}"><strong>${['어제 D-1','기준일 D','다음 날 D+1'][i]} · ${esc(day.date)}</strong><p class="${day.available ? '' : 'rm-warning'}">${day.available ? `비교 가능한 상품 ${day.ranked_count}개 / 원본 ${day.raw_count}행` : day.state === 'pending' ? '수집 대기 · 미발견 집계 안 함' : day.state === 'invalid' ? '유효 순위 없음 · 비교 보류' : '당일 데이터 없음 · 개별 상품 누락 판단 보류'}</p><p>배치: ${esc(day.batch_id ?? '없음')}</p></div>`).join('');
        el('bands').innerHTML = result.bands.map(b => `<tr><td><span class="rm-tier tier${b.tier}">${['상위','중위','하위'][b.tier]}</span> ${b.tier*100+1}–${(b.tier+1)*100}위</td><td>${b.count}개</td><td>${b.kept}개</td><td>${b.moved}개</td><td>${b.missing}개</td><td>${b.unknown}개</td><td><b>${b.rate == null ? '—' : b.rate+'%'}</b> / ${b.target}% 이상</td><td>${badge(b.rate == null ? 'unassessed' : b.below_target ? 'swing' : 'kept',b.rate == null ? '판단 보류' : b.below_target ? '기준 미달 · 확인 필요' : '예시 기준 충족')}</td></tr>`).join('');
        const top = result.bands[0];
        el('top-exits').textContent = `상위 100위 상품: 101–300위로 이동 ${top.moved}개 · 300위 내 미발견 ${top.missing}개 · 판단 보류 ${top.unknown}개. 미발견은 상품 링크에서 품절·판매 종료 여부를 확인하세요.`;
        el('all-count').textContent = result.counts.all; el('review-count').textContent = result.counts.review;
        el('table-head').innerHTML = `<tr class="rm-group"><th colspan="4">상품 정보</th><th colspan="3">수집일별 MAIN 순위</th><th colspan="2">점검 / 확인</th></tr><tr><th>전일 구간</th><th>상품명<span>retailer_sku_name</span></th><th>ITEM<span>item</span></th><th>SKU<span>sku</span></th>${result.dates.map((d,i)=>`<th class="rm-center ${i===1?'rm-today':''}">${['어제','기준일','다음 날'][i]}<span>${esc(d)}</span></th>`).join('')}<th>점검 신호 / 확인할 내용</th><th>확인 기록 / 상세</th></tr>`;
    }
    function renderTable() {
        if (!result) return;
        document.querySelectorAll('[data-view]').forEach(button => {const active = button.dataset.view === state.view;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
        el('tab-note').textContent = state.view === 'all' ? '전체 상품을 전일 순위순으로 확인' : '식별/순위 오류 → 일시 누락 → 미발견 → 급변';
        el('signals').innerHTML = '<span class="rm-muted">점검 신호</span>' + [['all','전체 신호'],['return','일시 누락 의심'],['missing','D 미발견'],['next_missing','D+1 미발견'],['swing','순위 급변'],['data','식별값 / 순위 확인']].map(([key,label])=>`<button type="button" data-signal="${key}" aria-pressed="${state.signal===key}" class="${state.signal===key?'active':''}">${label} ${key==='all'?'':result.counts[key]}</button>`).join('') + '<span class="rm-muted">신호 간 중복 포함</span>';
        el('table-body').innerHTML = rowsHtml(result.products) || '<tr><td colspan="9" class="rm-empty">조건에 맞는 상품이 없습니다.</td></tr>';
        renderProgress();
    }
    function rowsHtml(products) {
        return products.map(p => {const band = p.cells[0].state === 'ranked' ? tier(p.cells[0].rank) : -1;return `<tr class="rm-row ${p.status}"><td><span class="rm-tier tier${band}">${band<0?'—':['상위','중위','하위'][band]}</span></td><td><div class="rm-product-name">${esc(p.name || '상품명 없음')}</div>${p.samsung?'<div class="rm-product-sub">SAMSUNG · 상품명 기준</div>':''}</td><td class="rm-identity"><code>${esc(p.item || '—')}</code></td><td class="rm-identity"><code>${esc(p.sku || '—')}</code></td>${[0,1,2].map(i=>`<td class="rm-center ${i===1?'rm-today':''}">${rankCell(p,i)}</td>`).join('')}<td>${badge(p.status,p.label)}<div class="rm-reason">${reasons[p.status]}</div></td><td><div class="rm-record">${esc(p.review.result)}</div><button data-key="${esc(p.key)}" type="button">상품 확인 ↗</button></td></tr>`;}).join('');
    }
    function history() {
        el('history').innerHTML = selected.review.history.slice().reverse().map(r=>`<div class="rm-history-entry"><b>${esc(r.result)}</b> · ${esc(r.username)} · ${esc(r.at)}<br>${esc(r.memo)}</div>`).join('') || '<p class="rm-muted">확인 이력이 없습니다.</p>';
    }
    async function detail(key) {
        const seq = ++detailNumber, basis = result;
        selected=null;el('detail').textContent='상품 근거를 불러오는 중…';el('history').textContent='';
        el('review-message').textContent='';el('save').disabled=true;el('memo').value='';el('dialog').showModal();
        try {
            const params=paramsFor();params.set('key',key);
            const response=await fetch('/dx/layer1/rank/api/detail/?'+params);
            if (response.redirected) throw new Error('로그인이 만료되었습니다.');
            const data=await response.json();if(!response.ok) throw new Error(data.error || '상품 상세 조회에 실패했습니다.');
            if(seq!==detailNumber || basis!==result || !el('dialog').open) return;
            selected=data;
        } catch(error) {
            if(seq===detailNumber && basis===result) el('detail').textContent=error.message;
            return;
        }
        const url = safeUrl(selected.url);
        el('detail').innerHTML = `<h4>${esc(selected.name || '상품명 없음')}</h4>${badge(selected.status,selected.label)}<dl><dt>ITEM</dt><dd>${esc(selected.item || '—')}</dd><dt>SKU</dt><dd>${esc(selected.sku || '—')}</dd></dl><p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">상품 페이지 열기 ↗</a>`:'유효한 상품 URL이 없습니다.'}</p><div class="rm-detail-days">${selected.cells.map((c,i)=>`<div><b>${esc(result.dates[i])}</b>${rankCell(selected,i)}<p>배치: ${esc(c.batch_id ?? '—')}</p><p>원본 수집 시각: ${esc(c.collected_at || '—')}</p><p>원본 ID: ${esc(c.record_ids.join(', ') || '—')}</p></div>`).join('')}</div><p class="rm-muted">${reasons[selected.status]} 확인 기록은 현재 비교 근거에 저장되며 배치·순위가 바뀌면 다시 확인합니다.</p>`;
        el('review-result').value = selected.review.result;
        el('memo').value = selected.review.memo;
        el('review-message').textContent = selected.review_storage_available ? '' : selected.review_storage_message;
        el('review-message').classList.remove('success');
        el('save').disabled = !selected.review_storage_available; history();
    }
    async function save(event) {
        event.preventDefault();if (!selected || !selected.review_storage_available) return;
        const current = selected, snapshot = result;
        el('save').disabled=true;el('review-message').textContent='저장 중…';el('review-message').classList.remove('success');
        try {
            const response = await fetch('/dx/layer1/rank/api/review/', {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#rm-review-form [name=csrfmiddlewaretoken]').value},body:JSON.stringify({token:current.review_token,result:el('review-result').value,memo:el('memo').value,revision:current.review.revision})});
            if (response.redirected) throw new Error('로그인이 만료되었습니다. 다시 로그인해주세요.');
            const data = await response.json();if (!response.ok) throw new Error(data.error || '저장하지 못했습니다.');
            if (snapshot!==result || current!==selected) return;
            current.review=data.review;const listed=result.products.find(p=>p.key===current.key);if(listed)listed.review={result:data.review.result};el('review-message').textContent='확인 기록을 저장했습니다.';el('review-message').classList.add('success');history();renderTable();
        } catch(error) {if (current===selected) el('review-message').textContent=error.message;}
        finally {if (current===selected) el('save').disabled=false;}
    }
    async function exportCsv() {
        if (!result) return;
        el('export').disabled=true;
        try {
            const response=await fetch('/dx/layer1/rank/api/export/?'+paramsFor());
            if(response.redirected) throw new Error('로그인이 만료되었습니다.');
            if(!response.ok) {const data=await response.json();throw new Error(data.error || '내보내기에 실패했습니다.');}
            const url=URL.createObjectURL(await response.blob());
            const a=document.createElement('a');a.href=url;a.download='rank-export.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        } catch(error) {message(error.message,true);} finally {el('export').disabled=false;}
    }
    el('product').innerHTML=config.catalog.map(c=>`<option>${esc(c.product)}</option>`).join('');options();
    const initialDate=new URLSearchParams(location.search).get('date');
    el('date').value=/^\d{4}-\d{2}-\d{2}$/.test(initialDate || '')?initialDate:config.date;el('date').max=config.date;
    el('review-result').innerHTML=config.results.map(r=>`<option>${esc(r)}</option>`).join('');
    el('form').addEventListener('submit',load);el('product').addEventListener('change',()=>{options();dirty();});
    el('retailer').addEventListener('change',dirty);el('date').addEventListener('change',dirty);
    document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{state.view=b.dataset.view;state.signal='all';state.sort=state.view==='all'?'rank':'priority';state.page=1;el('sort').value=state.sort;loadPage();}));
    el('signals').addEventListener('click',e=>{const button=e.target.closest('[data-signal]');if(button){state.signal=button.dataset.signal;state.page=1;loadPage();}});
    el('tier').addEventListener('change',e=>{state.tier=e.target.value;state.page=1;loadPage();});
    el('sort').addEventListener('change',e=>{state.sort=e.target.value;state.page=1;loadPage();});
    el('search').addEventListener('input',e=>{stopMore();state.query=e.target.value;state.page=1;clearTimeout(searchTimer);searchTimer=setTimeout(loadPage,250);});
    el('table-body').addEventListener('click',e=>{const button=e.target.closest('[data-key]');if(button)detail(button.dataset.key);});
    el('more').addEventListener('click',()=>{moreError='';loadMore();});
    el('close').addEventListener('click',()=>{detailNumber++;el('dialog').close();});el('review-form').addEventListener('submit',save);el('export').addEventListener('click',exportCsv);
    load();
})();
