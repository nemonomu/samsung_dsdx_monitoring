(function () {
    'use strict';
    const api = '/dx/layer1/api/column-review/';
    const esc = window.ColumnComparison.esc;
    const dialog = document.createElement('dialog');
    dialog.className = 'column-review-dialog';
    dialog.setAttribute('aria-labelledby', 'column-review-title');
    document.body.append(dialog);
    let state, attachments = [], busy = false, requestId = 0;
    const error = message => {dialog.querySelector('[data-error]').textContent = message;};
    function release() {
        attachments.forEach(item => URL.revokeObjectURL(item.url));
        attachments = [];
    }
    function close() {
        if (busy) return;
        if (attachments.length || dialog.querySelector('textarea')?.value.trim()) {
            if (!window.confirm('아직 저장하지 않은 이미지와 설명을 닫을까요?')) return;
        }
        dialog.close();
    }
    dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
    dialog.addEventListener('close', () => {requestId++; release(); state = null;});
    function historyHtml(review, older = false) {
        return (review.history || []).map(entry => `<section class="column-review-entry">
            <strong>${entry.action === 'confirm' ? '정상 확인' : '정상 확인 취소'}${older ? ' · 이전 수집 결과' : ''}</strong>
            <p>${esc(entry.username)} · ${esc(new Date(entry.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}))} (KST)</p>
            ${entry.memo ? `<p class="column-review-memo">${esc(entry.memo)}</p>` : ''}
            <div class="column-review-images">${(entry.images || []).map((image, i) => `<a href="${esc(image.url)}" target="_blank" rel="noopener"><img src="${esc(image.url)}" alt="정상 확인 근거 이미지 ${i+1}" loading="lazy"><span>원본 보기</span></a>`).join('')}</div>
            </section>`).join('');
    }
    function previews() {
        dialog.querySelector('[data-previews]').innerHTML = attachments.map((item, i) =>
            `<figure><img src="${item.url}" alt="첨부 이미지 ${i+1}"><button type="button" data-remove="${i}" aria-label="첨부 이미지 ${i+1} 제거">제거</button></figure>`).join('');
    }
    function addFiles(files) {
        if (busy || !state || state.review.active) return;
        if (!files.length) return;
        const all = [...attachments.map(a => a.file), ...files];
        if (all.length > 5 || all.some(f => f.size > 5*1024*1024) || all.reduce((sum, f) => sum+f.size, 0) > 15*1024*1024) {
            error('이미지는 최대 5장, 한 장 5MB, 합계 15MB까지 첨부할 수 있습니다.'); return;
        }
        if (files.some(f => !['image/png','image/jpeg','image/webp'].includes(f.type))) {
            error('PNG·JPG·WEBP 이미지를 첨부하세요.'); return;
        }
        error('');
        attachments.push(...files.map(file => ({file, url:URL.createObjectURL(file)})));
        previews();
    }
    dialog.addEventListener('paste', event => {
        if (busy || !state || state.review.active) return;
        const files = Array.from(event.clipboardData?.items || []).filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
        if (files.length) {event.preventDefault(); addFiles(files);}
    });
    dialog.addEventListener('click', event => {
        if (event.target.closest('[data-close]')) close();
        const remove = event.target.closest('[data-remove]');
        if (remove && !busy) {
            URL.revokeObjectURL(attachments.splice(Number(remove.dataset.remove), 1)[0].url);
            previews();
        }
    });
    function render() {
        const {target:t, comparison:c, review:r} = state;
        const canConfirm = ['abnormal','review'].includes(c.status);
        dialog.innerHTML = `<h2 id="column-review-title">${r.active ? '정상 확인 근거' : canConfirm ? '이상 확인' : '검수 근거 이력'}</h2>
            <p>${esc(t.country)} · ${esc(t.product)} · ${esc(t.retailer)} · <strong>${esc(t.column)}</strong><br>검수일 ${esc(t.inspection_date)} · 데이터일 ${esc(t.source_date)}</p>
            <p>현재 ${esc(c.current)}건 / 평소 기준 ${esc(c.baseline ?? '없음')}건 · 자동 판정: ${esc(window.ColumnComparison.labels[c.status] || c.status)}</p>
            ${historyHtml(r)}
            ${(state.previous || []).length ? `<details><summary>이전 수집 결과의 검수 근거</summary>${state.previous.map(p => historyHtml(p, true)).join('')}</details>` : ''}
            <form><fieldset ${!canConfirm && !r.active ? 'hidden' : ''}>
            ${!r.active ? `<div class="column-review-paste" tabindex="0" role="group" aria-label="근거 이미지 붙여넣기">쇼핑몰 확인 화면을 복사한 뒤 여기를 클릭하고 <strong>Ctrl+V</strong>로 붙여넣으세요.<br><label>이미지 파일 선택 <input type="file" accept="image/png,image/jpeg,image/webp" multiple data-files></label><small>최대 5장 · 한 장 5MB · 합계 15MB</small></div><div class="column-review-images" data-previews></div>` : ''}
            <label>${r.active ? '정상 확인 취소 사유' : '설명 (선택)'}<textarea rows="3" maxlength="1000" ${r.active ? 'required' : ''}></textarea></label>
            <p class="cs-muted">이 날짜의 해당 컬럼에만 적용하며, 자동 수집 수치와 판정은 보존합니다.</p></fieldset>
            <p role="alert" data-error></p><div class="cca-dialog-actions"><button type="button" data-close>닫기</button>${canConfirm || r.active ? `<button type="submit" class="cs-primary">${r.active ? '정상 확인 취소' : '정상 확인'}</button>` : ''}</div></form>`;
        dialog.querySelector('[data-files]')?.addEventListener('change', event => {addFiles(Array.from(event.target.files)); event.target.value = '';});
        dialog.querySelector('form').onsubmit = save;
        if (!r.active && canConfirm) dialog.querySelector('.column-review-paste').focus();
    }
    async function responseJson(response) {
        if (response.redirected) throw new Error('로그인 상태를 확인한 뒤 다시 시도하세요.');
        let data;
        try {data = await response.json();} catch (_) {throw new Error('서버 응답을 확인하지 못했습니다. 첨부 내용은 유지됩니다.');}
        if (!response.ok) throw new Error(data.error || '검수 기록을 처리하지 못했습니다.');
        return data;
    }
    async function save(event) {
        event.preventDefault();
        if (busy) return;
        if (!state.review.active && !attachments.length) {error('정상임을 확인한 근거 이미지를 한 장 이상 붙여넣으세요.'); return;}
        const form = new FormData();
        Object.entries(state.target).forEach(([key,value]) => form.append(key,value));
        form.append('token',state.token);
        form.append('action',state.review.active ? 'cancel' : 'confirm');
        form.append('memo',dialog.querySelector('textarea').value);
        attachments.forEach(a => form.append('images',a.file,a.file.name || 'capture.png'));
        busy = true; error('저장 중입니다…');
        dialog.querySelectorAll('button,input,textarea').forEach(el => el.disabled = true);
        try {
            const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || decodeURIComponent(document.cookie.split('; ').find(c=>c.startsWith('csrftoken='))?.split('=').slice(1).join('=') || '');
            const data = await responseJson(await fetch(api, {method:'POST', body:form, credentials:'same-origin', headers:{'X-CSRFToken':csrf}}));
            release();
            state = {...state, review:data.review, comparison:data.comparison, token:data.token};
            window.ColumnAlertCache?.invalidate(state.target, state.target.inspection_date);
            document.dispatchEvent(new CustomEvent('column-review-saved', {detail:{target:state.target, comparison:data.comparison}}));
            render();
            error('저장했습니다. 근거 이미지는 이 화면에서 다시 확인할 수 있습니다.');
        } catch (e) {error(e.message);}
        finally {busy = false; dialog.querySelectorAll('button,input,textarea').forEach(el => el.disabled = false);}
    }
    async function open(target) {
        if (dialog.open) return;
        const id = ++requestId;
        state = null; release();
        dialog.innerHTML = '<h2 id="column-review-title">이상 확인</h2><p>현재 수집 결과와 검수 근거를 불러오는 중입니다.</p><p role="alert" data-error></p><button type="button" data-close>닫기</button>';
        dialog.showModal();
        try {
            const data = await responseJson(await fetch(api+'?'+new URLSearchParams(target), {credentials:'same-origin', cache:'no-store'}));
            if (id !== requestId || !dialog.open) return;
            state = data; render();
        } catch (e) {if (id === requestId && dialog.open) error(e.message);}
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-column-review]');
        if (button) open(JSON.parse(button.dataset.columnReview));
    });
})();
