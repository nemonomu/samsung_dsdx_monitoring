// One metric decision shared by statistics and the past-incident list.
(function () {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function request(options, target) {
        const url = '/dx/layer1/api/volume-review/' + (options ? '' : '?' + new URLSearchParams(target));
        const response = await fetch(url, options || {});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '처리하지 못했습니다. 다시 조회해주세요.');
        return data;
    }
    async function open(target) {
        const dialog = document.createElement('dialog');
        dialog.className = 'l1-review-dialog';
        dialog.setAttribute('aria-label', '수집량 정상 확인');
        dialog.innerHTML = '<h2>수집량 정상 확인</h2><div data-body>현재 수집 결과를 확인하고 있습니다.</div><p role="status" data-message></p><div class="l1-review-actions"><button type="button" data-close>닫기</button></div>';
        document.body.appendChild(dialog);
        dialog.querySelector('[data-close]').onclick = () => dialog.close();
        dialog.addEventListener('close', () => dialog.remove(), {once:true});
        dialog.showModal();
        try {
            const data = await request(null, target);
            if (!dialog.open) return;
            const decided = ['confirm', 'reject'].includes(data.decision?.action);
            const history = data.history.length ? data.history : data.decision ? [data.decision] : [];
            dialog.querySelector('[data-body]').innerHTML = `<p>${esc(target.country)} · ${esc(target.retailer)} · ${esc(target.product)} · ${esc(target.metric.toUpperCase())}<br>검수일 ${esc(data.inspection_date)} · 수집일 ${esc(target.source_date)}<br>배치 ${esc(data.batch_id)}</p>
                <p>MAIN ${esc(data.counts[0])}건 · BSR ${esc(data.counts[1])}건 · 총 ${esc(data.counts[2])}건</p>
                <p>${data.reasons.map(esc).join('<br>')}</p>
                <p>${data.decision?.action === 'confirm' ? '✓ 정상 확인 완료' : data.decision?.action === 'reject' ? '이상 확정' : '미처리'} · 이 날짜의 ${esc(target.metric.toUpperCase())} 항목에만 적용합니다.</p>
                <ol>${history.map(h => `<li>${esc(new Date(h.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}))} · ${esc(h.username)} · ${esc({confirm:'정상 확인',cancel:'확인 취소',reject:'이상 확정'}[h.action] || h.action)} · ${esc(h.memo)}</li>`).join('')}</ol>
                <form><label>처리 사유<textarea required maxlength="1000" rows="3"></textarea></label><div class="l1-review-actions"><button type="submit">${decided ? '확인 취소' : '정상 확인 처리'}</button></div></form>`;
            dialog.querySelector('form').onsubmit = async event => {
                event.preventDefault();
                const button = dialog.querySelector('[type=submit]');
                button.disabled = true;
                try {
                    await request({method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},
                        body:JSON.stringify({...target, token:data.token, revision:data.revision,
                            action:decided ? 'cancel' : 'confirm', memo:dialog.querySelector('textarea').value.trim()})});
                    dialog.close();
                    window.dispatchEvent(new CustomEvent('collection-review-changed', {detail:target}));
                } catch (error) {
                    dialog.querySelector('[data-message]').textContent = error.message;
                    button.disabled = false;
                }
            };
        } catch (error) { dialog.querySelector('[data-message]').textContent = error.message; }
    }
    window.CollectionVolumeReview = {open};
})();
