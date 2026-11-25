(function () {
    'use strict';
    const dialog = document.getElementById('ccs-note-dialog');
    const form = document.getElementById('ccs-note-form');
    const input = document.getElementById('ccs-note-text');
    const save = document.getElementById('ccs-note-save');
    const cancel = document.getElementById('ccs-note-cancel');
    const notice = document.getElementById('ccs-note-error');
    const endpoint = '/dx/layer1/api/column-statistics/notes/';
    const date = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul'});
    const requests = new Map();
    let active;
    let saving = false;

    async function request(url, options) {
        const response = await fetch(url, options);
        if (response.redirected) throw new Error('로그인 후 다시 시도해주세요.');
        const data = await response.json();
        if (response.ok) return data;
        const error = new Error(data.error || '비고를 불러오지 못했습니다.');
        error.status = response.status;
        error.note = data.note;
        throw error;
    }

    function updateSaveState() {
        save.disabled = !active || saving || active.stale || input.value.trim() === (active.original?.text || '');
    }

    function openEditor(cell, state, column) {
        if (dialog.open) return;
        const original = state.notes.get(column);
        active = {cell, state, column, original, stale: false};
        document.getElementById('ccs-note-title').textContent = `${column} 비고`;
        document.getElementById('ccs-note-scope').textContent = [state.scope.country, state.scope.product, state.scope.retailer].join(' · ');
        notice.hidden = true;
        input.value = original?.text || '';
        updateSaveState();
        dialog.showModal();
        input.focus();
    }

    function renderCell(cell, state) {
        const column = cell.dataset.noteColumn;
        const note = state.notes.get(column);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ccs-note-cell';
        button.title = '더블클릭으로 비고 편집';
        button.setAttribute('aria-label', note?.text ? `${column} 비고 수정` : `${column} 비고 작성`);
        const text = document.createElement('span');
        text.className = 'ccs-note-text';
        text.textContent = note?.text || '—';
        button.append(text);
        if (note?.text) {
            const dates = document.createElement('small');
            dates.className = 'ccs-note-dates';
            dates.textContent = `작성 ${date.format(new Date(note.created_at))}`;
            if (note.revision > 1) dates.textContent += ` · 수정 ${date.format(new Date(note.updated_at))}`;
            button.append(dates);
        }
        cell.ondblclick = () => openEditor(cell, state, column);
        button.onclick = event => {
            if (event.detail === 0) openEditor(cell, state, column);
        };
        cell.replaceChildren(button);
    }

    function render(tbody, {country, product, retailer}) {
        const cells = tbody.querySelectorAll('[data-note-column]');
        if (!cells.length) return;
        const scope = {country, product, retailer};
        const query = new URLSearchParams(scope).toString();
        if (!requests.has(query)) {
            const pending = request(endpoint + '?' + query).then(data => ({scope, notes: new Map(Object.entries(data.notes))}));
            requests.set(query, pending);
        }
        const pending = requests.get(query);
        pending.then(state => {
            for (const cell of cells) if (cell.isConnected) renderCell(cell, state);
        }).catch(() => {
            if (requests.get(query) === pending) requests.delete(query);
            for (const cell of cells) {
                if (cell.isConnected) cell.textContent = '비고 조회 실패';
            }
        });
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!active || save.disabled) return;
        const {cell, state, column, original} = active;
        saving = true;
        updateSaveState();
        cancel.disabled = true;
        input.readOnly = true;
        notice.hidden = true;
        try {
            const data = await request(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value},
                body: JSON.stringify({...state.scope, column, text: input.value.trim(), revision: original?.revision || 0}),
            });
            state.notes.set(column, data.note);
            if (cell.isConnected) renderCell(cell, state);
            dialog.close();
        } catch (error) {
            if (error.status === 409) {
                state.notes.set(column, error.note);
                active.stale = true;
                if (cell.isConnected) renderCell(cell, state);
            }
            notice.textContent = error instanceof SyntaxError ? '비고 저장에 실패했습니다. 잠시 후 다시 시도해주세요.' : error.message;
            notice.hidden = false;
        } finally {
            saving = false;
            cancel.disabled = false;
            input.readOnly = false;
            updateSaveState();
        }
    });
    input.addEventListener('input', updateSaveState);
    cancel.addEventListener('click', () => dialog.close());
    dialog.addEventListener('cancel', event => {
        if (saving) event.preventDefault();
    });
    dialog.addEventListener('close', () => {
        active?.cell.querySelector('button')?.focus();
        active = null;
    });

    window.ColumnStatisticsNotes = {render, reset: () => requests.clear()};
})();
