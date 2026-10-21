// Appended to the imported editor by scripts/import_dx_manual.py.
const serverMeta = JSON.parse($('guide-meta').textContent);
if (serverMeta.catalogWarning) {
    const notice = document.createElement('p');
    notice.className = 'commonnote';
    notice.textContent = serverMeta.catalogWarning;
    document.querySelector('.main').prepend(notice);
}
let serverVersion = serverMeta.version;
const manualApi = '/dx/documents/manual/';
const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

function renderEditorStatus() {
    document.body.classList.toggle('edit-mode', editing);
    $('editorBar').hidden = !editing && revision === downloadedRevision;
    $('editModeToggle').classList.toggle('on', editing);
    $('editModeToggle').setAttribute('aria-pressed', editing);
    $('editModeToggle').textContent = editing ? '편집 종료' : '편집 모드';
    $('undoEdit').disabled = !undoStack.length || saveBusy;
    $('saveGuide').disabled = saveBusy || revision === downloadedRevision;
    $('saveGuide').textContent = saveBusy ? '저장 중…' : '저장 · Ctrl+S';
    $('editStatus').textContent = saveBusy ? '서버에 저장하고 있습니다.'
        : revision !== downloadedRevision ? '저장하지 않은 변경이 있어요.'
        : serverVersion ? '저장됨 · 버전 ' + serverVersion + (serverMeta.created_by ? ' · ' + serverMeta.created_by : '')
        : '최초 등록본';
    $('editStatus').classList.toggle('dirty', revision !== downloadedRevision);
    for (const id of ['editText', 'editImage', 'manualHistory']) $(id).disabled = saveBusy;
}

async function manualRequest(path, options = {}) {
    const response = await fetch(manualApi + path, {
        credentials: 'same-origin', ...options,
        headers: {'X-CSRFToken': csrfToken, ...options.headers}
    });
    if (response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        throw new Error(response.status === 413 ? '파일이 서버의 업로드 제한을 초과했습니다.' : '저장 응답을 확인하지 못했습니다. 로그인 상태와 연결을 확인하세요.');
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '요청을 처리하지 못했습니다. 다시 시도하세요.');
    return result;
}

async function saveManual() {
    if (saveBusy || revision === downloadedRevision) return;
    if ($('imageEditor').open || $('textEditor').open) {
        showToast('수정 창의 적용 버튼을 누른 뒤 저장하세요.');
        return;
    }
    saveBusy = true;
    $('saveFailure').textContent = '';
    renderEditorStatus();
    const snapshotRevision = revision;
    const snapshot = cloneValue(D);
    const uploaded = [];
    try {
        for (const photo of snapshot.photos) {
            if (!photo.customImage?.startsWith('data:image/')) continue;
            const original = photo.customImage;
            const [header, encoded] = original.split(',');
            const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
            const form = new FormData();
            form.append('image', new Blob([bytes], {type: header.slice(5).split(';')[0]}), photo.name);
            const result = await manualRequest('upload/', {method: 'POST', body: form});
            photo.customImage = result.url;
            uploaded.push({name: photo.name, retailer: photo.retailer, category: photo.category, original, url: result.url});
        }
        const result = await manualRequest('save/', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({version: serverVersion, data: snapshot})
        });
        serverVersion = result.version;
        Object.assign(serverMeta, result);
        downloadedRevision = snapshotRevision;
        for (const image of uploaded) {
            const photo = D.photos.find(p => p.name === image.name && p.retailer === image.retailer && p.category === image.category);
            if (photo?.customImage === image.original) photo.customImage = image.url;
        }
        showToast('서버에 저장했습니다. 버전 ' + serverVersion);
    } catch (error) {
        $('saveFailure').textContent = error.message;
        showToast('저장하지 못했습니다. 현재 수정 내용은 화면에 남아 있습니다.');
    } finally {
        saveBusy = false;
        renderEditorStatus();
    }
}

$('saveGuide').onclick = saveManual;
document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void saveManual();
    }
});
$('manualHistory').onclick = async () => {
    $('historyList').textContent = '이력을 불러오는 중입니다.';
    $('historyDialog').showModal();
    try {
        const result = await manualRequest('history/');
        $('historyList').replaceChildren();
        for (const item of result.revisions) {
            const row = document.createElement('div');
            row.className = 'manual-history-row';
            const description = document.createElement('span');
            description.textContent = item.version === 0 ? '최초 등록본 · 2026-10-19'
                : '버전 ' + item.version + ' · ' + item.created_by + ' · ' + new Date(item.created_at).toLocaleString('ko-KR');
            const button = document.createElement('button');
            button.textContent = '불러오기';
            button.disabled = item.version === serverVersion;
            button.onclick = async () => {
                if (revision !== downloadedRevision && !confirm('저장하지 않은 변경을 버리고 선택한 버전을 불러올까요?')) return;
                button.disabled = true;
                try {
                    const result = await manualRequest('history/?version=' + item.version);
                    for (const key of Object.keys(D)) delete D[key];
                    Object.assign(D, result.data);
                    undoStack.length = 0;
                    changed();
                    selectDataset();
                    $('historyDialog').close();
                    showToast('버전을 불러왔습니다. 저장하면 새 버전으로 등록됩니다.');
                } catch (error) {
                    showToast(error.message);
                    button.disabled = false;
                }
            };
            row.append(description, button);
            $('historyList').append(row);
        }
    } catch (error) {
        $('historyList').textContent = error.message;
    }
};
render();
