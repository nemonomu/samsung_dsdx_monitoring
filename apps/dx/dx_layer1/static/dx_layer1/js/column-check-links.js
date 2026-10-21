(function () {
    'use strict';
    const api = '/dx/layer1/api/column-alert-links/';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const identity = row => [row.country, row.product, row.retailer.toLowerCase().replace(/[^a-z0-9]/g, ''), row.column === '전체 미수집' ? '' : row.column].join('|');
    const safeURL = url => {try {return ['http:', 'https:'].includes(new URL(url).protocol);} catch (_) {return false;}};
    let records = new Map(), guides = {}, state = 'loading', manualError = false, redraw, getRows, target, busy = false;
    const dialog = document.getElementById('cca-url-dialog');
    const form = document.getElementById('cca-url-form');
    const input = document.getElementById('cca-url-input');
    const error = document.getElementById('cca-url-error');
    const status = document.getElementById('cca-link-status');
    async function request(options) {
        const response = await fetch(api, {credentials:'same-origin', ...options});
        if (response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) throw new Error('로그인 상태를 확인하고 다시 시도하세요.');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'URL 정보를 불러오지 못했습니다.');
        return data;
    }
    async function load() {
        state = 'loading';redraw();
        try {
            const data = await request();
            records = new Map(data.links.map(record => [record.key, record]));
            guides = data.guides;manualError = data.manual_error;state = 'ready';
            status.textContent = manualError ? '매뉴얼 연결을 확인하지 못했습니다. 다시 시도해주세요.' : '';
        } catch (err) {state = 'error';status.textContent = err.message;}
        redraw();
    }
    function cells(row, index) {
        if (state !== 'ready') return `<td colspan="2">${state === 'loading' ? '링크 확인 중…' : '<button type="button" class="ccs-link" data-link-retry>링크 다시 조회</button>'}</td>`;
        const key = identity(row), record = records.get(key), url = safeURL(record?.url) ? record.url : '';
        const guide = guides[key];
        return `<td class="cca-url-cell"><div class="cca-link-actions">${url
            ? `<a class="ccs-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">페이지 열기 ↗</a><button type="button" class="ccs-link" data-url-copy="${index}">복사</button><button type="button" class="ccs-link" data-url-edit="${index}">수정</button>`
            : `<button type="button" class="ccs-link" data-url-edit="${index}">URL 등록</button>`}</div></td><td>${guide && guide.startsWith('/dx/documents/manual/?')
            ? `<a class="ccs-link" href="${esc(guide)}" target="_blank" rel="noopener noreferrer">메뉴얼 확인 ↗</a>`
            : manualError ? '<button type="button" class="ccs-link" data-link-retry>연결 다시 확인</button>' : '<span class="cs-muted">가이드 미등록</span>'}</td>`;
    }
    async function copy(url) {
        try {
            if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(url);
            else throw new Error();
        } catch (_) {
            // The deployed HTTP page may not expose the Clipboard API.
            const text = document.createElement('textarea');
            text.value = url;text.style.position = 'fixed';text.style.opacity = '0';
            document.body.append(text);text.select();
            const copied = document.execCommand('copy');text.remove();
            if (!copied) throw new Error('복사하지 못했습니다. URL 수정 창에서 주소를 선택해 복사해주세요.');
        }
    }
    function init(render, rows) {
        redraw = render;getRows = rows;
        document.getElementById('cca-body').addEventListener('click', async event => {
            if (event.target.closest('[data-link-retry]')) {void load();return;}
            const button = event.target.closest('[data-url-copy],[data-url-edit]');
            if (!button || busy || state !== 'ready') return;
            const row = getRows()[Number(button.dataset.urlCopy ?? button.dataset.urlEdit)];
            if (!row) return;
            const record = records.get(identity(row));
            if (button.hasAttribute('data-url-copy')) {
                try {await copy(record.url);status.textContent = 'URL을 복사했습니다.';}
                catch (err) {status.textContent = err.message;}
                return;
            }
            target = {country:row.country, product:row.product, retailer:row.retailer,
                column:row.column === '전체 미수집' ? '' : row.column, revision:record?.revision || 0};
            document.getElementById('cca-url-target').textContent = `${row.country} · ${row.retailer} · ${row.product} · ${row.column}`;
            input.value = record?.url || '';error.textContent = '';
            dialog.showModal();input.focus();
        });
        document.getElementById('cca-url-cancel').onclick = () => {if (!busy) dialog.close();};
        dialog.addEventListener('cancel', event => {if (busy) event.preventDefault();});
        form.addEventListener('submit', async event => {
            event.preventDefault();if (busy || !form.reportValidity()) return;
            busy = true;error.textContent = '';
            const buttons = form.querySelectorAll('button');buttons.forEach(b => b.disabled = true);
            try {
                const data = await request({method:'POST', headers:{'Content-Type':'application/json',
                    'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},
                    body:JSON.stringify({...target, url:input.value.trim()})});
                records.set(data.link.key, data.link);dialog.close();redraw();status.textContent = 'URL을 저장했습니다.';
            } catch (err) {error.textContent = err.message;}
            finally {busy = false;buttons.forEach(b => b.disabled = false);}
        });
        void load();
    }
    window.ColumnCheckLinks = {cells, init};
})();
