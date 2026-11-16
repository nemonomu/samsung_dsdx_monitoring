(function () {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const imageUrl = value => /^\/dx\/layer1\/rank\/api\/review\/images\/\d+\/$/.test(value || '') ? value : '';
    const reviewed = review => ['구매 가능 확인','품절 확인','판매 종료 확인','순위 변동 확인','수집 오류 확인'].includes(review?.result);
    if (typeof module !== 'undefined' && module.exports) module.exports = {reviewed, imageUrl};
    if (typeof window === 'undefined') return;
    window.RankReviewEditor = {reviewed, create};

    function create() {
        const el = id => document.getElementById('rm-' + id);
        let original = null, photos = [], editing = false, available = false, busy = false, generation = 0, replacement = null;
        const localUrls = new Set();
        function message(text, success = false) {
            el('review-message').textContent = text;
            el('review-message').classList.toggle('success', success);
        }
        function release(photo) {
            if (photo?.file) { URL.revokeObjectURL(photo.url); localUrls.delete(photo.url); }
        }
        function clear() {
            generation++; localUrls.forEach(url => URL.revokeObjectURL(url)); localUrls.clear();
            photos = []; original = null; editing = false; busy = false; replacement = null;
            if (el('photo-zoom').open) el('photo-zoom').close();
            el('photo-image').removeAttribute('src'); el('photos').replaceChildren();
            el('photo-files').value = ''; el('photo-replace').value = '';
        }
        function open(review, canSave) {
            clear(); original = review; available = canSave;
            photos = (review.photos || []).map(p => ({...p, url: imageUrl(p.url)}));
            editing = available && !review.revision;
            el('review-result').value = review.result; el('memo').value = review.memo;
            render(); history();
        }
        function render() {
            const saved = !!original?.revision;
            el('review-result').disabled = !editing || busy;
            el('memo').disabled = !editing || busy;
            el('save').hidden = !editing; el('save').disabled = busy || !available;
            el('save').textContent = saved ? '수정 내용 저장' : '확인 기록 저장';
            el('cancel-edit').hidden = !editing || !saved; el('cancel-edit').disabled = busy;
            el('photo-drop').hidden = !editing; el('photo-choose').disabled = busy;
            el('review-summary').hidden = !saved;
            el('review-summary').innerHTML = saved ? `<div><b class="${reviewed(original)?'rm-reviewed':''}">${esc(original.result)}</b><small>마지막 저장 · ${esc(original.username)} · ${esc(original.updated_at)}</small></div>${editing?'<span class="rm-muted">수정 중 · 저장 후 반영</span>':`<button type="button" id="rm-edit" ${available?'':'disabled'}>수정</button>`}` : '';
            el('edit')?.addEventListener('click', () => { editing = true; message(''); render(); });
            renderPhotos();
        }
        function renderPhotos() {
            el('photo-count').textContent = photos.length ? `(${photos.length})` : '';
            el('photo-empty').hidden = !!photos.length;
            el('photos').innerHTML = photos.map((p,i) => `<div class="rm-photo-card"><button type="button" class="rm-photo-open" data-photo="${i}" aria-label="${esc(p.name)} 확대"><img src="${esc(p.url)}" alt="${esc(p.name)}"></button><div class="rm-photo-info"><span>${esc(p.name)}</span>${editing?`<div><button type="button" data-replace="${i}" ${busy?'disabled':''}>교체</button><button type="button" data-delete="${i}" ${busy?'disabled':''}>삭제</button></div>`:''}</div></div>`).join('');
        }
        function history() {
            el('history').innerHTML = (original.history || []).slice().reverse().map((r,i) => `<div class="rm-history-entry"><b class="${reviewed(r)?'rm-reviewed':''}">${esc(r.result)}</b> · ${esc(r.username)} · ${esc(r.at)}<br>${esc(r.memo)}<div class="rm-history-photos">${(r.photos || []).map((p,j) => `<button type="button" data-history-photo="${i}:${j}">${esc(p.name)} 보기</button>`).join('')}</div></div>`).join('') || '<p class="rm-muted">확인 이력이 없습니다.</p>';
        }
        function zoom(photo) {
            const url = photo.file ? photo.url : imageUrl(photo.url);
            if (!url) { message('사진 경로를 확인할 수 없습니다. 다시 조회해주세요.'); return; }
            el('photo-title').textContent = photo.name;
            el('photo-error').hidden = true; el('photo-image').hidden = false;
            el('photo-image').src = url; el('photo-zoom').showModal();
        }
        function dirty() {
            return !!original && editing && (el('review-result').value !== original.result || el('memo').value !== original.memo ||
                photos.some(p => p.file) || JSON.stringify(photos.map(p => p.id)) !== JSON.stringify((original.photos || []).map(p => p.id)));
        }
        function mayClose() {
            return !busy && (!dirty() || window.confirm('저장하지 않은 변경사항을 버리고 닫을까요?'));
        }
        function body(token, revision) {
            const value = {token, revision, result: el('review-result').value, memo: el('memo').value};
            let count = 0;
            value.photo_refs = photos.map(p => p.file ? `new:${count++}` : p.id);
            // Keep the existing JSON path for edits without newly uploaded files.
            if (!count) return {body: JSON.stringify(value), headers: {'Content-Type':'application/json'}};
            const form = new FormData();
            Object.entries(value).forEach(([k,v]) => form.append(k, k === 'photo_refs' ? JSON.stringify(v) : String(v)));
            photos.filter(p => p.file).forEach(p => form.append('images', p.file, p.name));
            return {body: form, headers: {}};
        }
        async function addFiles(files, replaceIndex = null) {
            if (!editing || busy) return;
            const list = Array.from(files); if (!list.length) return;
            const kept = photos.filter((p,i) => i !== replaceIndex);
            if ((replaceIndex !== null && list.length !== 1) || kept.length + list.length > 5) { message('사진은 최대 5장까지 첨부할 수 있습니다.'); return; }
            if (kept.reduce((n,p) => n + (p.file?.size ?? p.size ?? 0),0) + list.reduce((n,f) => n + f.size,0) > 15*1024*1024) { message('사진 합계는 15MB 이하여야 합니다.'); return; }
            const seq = generation, added = []; busy = true; render();
            try {
                for (const file of list) {
                    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) throw Error('PNG, JPG, WEBP 이미지만 첨부할 수 있습니다.');
                    if (file.size > 5*1024*1024) throw Error('사진 한 장은 5MB 이하여야 합니다.');
                    const url = URL.createObjectURL(file); localUrls.add(url);
                    const photo = {name:file.name || `붙여넣은_사진_${photos.length+added.length+1}.png`, file, url}; added.push(photo);
                    const img = new Image(); img.src = url;
                    await img.decode();
                    if (img.naturalWidth * img.naturalHeight > 20000000) throw Error('사진은 2천만 화소 이하여야 합니다.');
                }
                if (seq !== generation) { added.forEach(release); return; }
                if (replaceIndex === null) photos.push(...added);
                else { release(photos[replaceIndex]); photos.splice(replaceIndex,1,added[0]); }
                message('사진을 첨부했습니다. 저장 버튼을 누르면 반영됩니다.', true);
            } catch (error) {
                added.forEach(release);
                if (seq === generation) message(error.name === 'EncodingError' ? '사진 파일을 읽을 수 없습니다.' : error.message);
            } finally { if (seq === generation) { busy = false; render(); } }
        }
        el('photo-choose').addEventListener('click', () => el('photo-files').click());
        el('photo-files').addEventListener('change', async e => { await addFiles(e.target.files); e.target.value = ''; });
        el('photo-replace').addEventListener('change', async e => { const index = replacement; replacement = null; if (index !== null) await addFiles(e.target.files,index); e.target.value = ''; });
        el('dialog').addEventListener('paste', e => {
            if (!editing || busy || el('photo-zoom').open) return;
            const files = Array.from(e.clipboardData?.items || []).filter(i => i.kind === 'file' && i.type.startsWith('image/')).map(i => i.getAsFile()).filter(Boolean);
            if (files.length) { e.preventDefault(); addFiles(files); }
        });
        el('photo-drop').addEventListener('dragover', e => { e.preventDefault(); el('photo-drop').classList.add('drag'); });
        el('photo-drop').addEventListener('dragleave', () => el('photo-drop').classList.remove('drag'));
        el('photo-drop').addEventListener('drop', e => { e.preventDefault(); el('photo-drop').classList.remove('drag'); addFiles(e.dataTransfer.files); });
        el('photos').addEventListener('click', e => {
            const view = e.target.closest('[data-photo]'), remove = e.target.closest('[data-delete]'), replace = e.target.closest('[data-replace]');
            if (view) zoom(photos[Number(view.dataset.photo)]);
            if (remove && editing && !busy) { release(photos[Number(remove.dataset.delete)]); photos.splice(Number(remove.dataset.delete),1); renderPhotos(); message('사진 삭제는 저장 후 반영됩니다. 이전 사진은 확인 이력에 남습니다.', true); }
            if (replace && editing && !busy) { replacement = Number(replace.dataset.replace); el('photo-replace').click(); }
        });
        el('history').addEventListener('click', e => {
            const button = e.target.closest('[data-history-photo]'); if (!button) return;
            const [i,j] = button.dataset.historyPhoto.split(':').map(Number);
            zoom(original.history.slice().reverse()[i].photos[j]);
        });
        el('photo-close').addEventListener('click', () => el('photo-zoom').close());
        el('photo-zoom').addEventListener('close', () => el('photo-image').removeAttribute('src'));
        el('photo-image').addEventListener('error', () => { el('photo-image').hidden = true; el('photo-error').hidden = false; });
        el('cancel-edit').addEventListener('click', () => {
            if (busy || (dirty() && !window.confirm('수정한 내용을 취소하고 저장된 기록으로 되돌릴까요?'))) return;
            open(original, available); message('');
        });
        window.addEventListener('beforeunload', e => { if (dirty() || busy) { e.preventDefault(); e.returnValue = ''; } });
        return {open, clear, dirty, mayClose, body, get busy() { return busy; }, get editing() { return editing; }, lock(value) { busy = value; render(); }};
    }
})();
