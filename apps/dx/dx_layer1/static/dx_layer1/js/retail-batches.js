(function() {
    var buttons = new WeakMap();
    var details = new WeakMap();
    var sequence = 0;

    function render(data) {
        var rows = data.batches || [];
        var body = rows.map(function(batch, index) {
            var period = batch.started_at || '-';
            if (batch.ended_at && batch.ended_at !== batch.started_at) period += ' ~ ' + batch.ended_at;
            return '<tr><td class="l1-batch-id">' + esc(batch.batch_id || '배치 ID 없음') + '</td>' +
                '<td>' + esc(period) + '</td><td>' + Number(batch.main_count || 0).toLocaleString() + '</td>' +
                '<td>' + Number(batch.bsr_count || 0).toLocaleString() + '</td><td>' +
                (batch.applied ? '<span class="status-badge ok">반영</span>' : '—') + '</td>' +
                '<td><button type="button" class="l1-retail-query-button" onclick="event.stopPropagation();L1.retailBatches.sql(this,' + index + ')">조회 SQL</button></td></tr>';
        }).join('');
        return '<div class="l1-batch-panel"><div class="l1-batch-heading"><strong>' + esc(data.retailer) +
            ' 배치별 내역</strong><button type="button" class="l1-retail-query-button" onclick="event.stopPropagation();L1.retailBatches.reload(this)">새로고침</button></div>' +
            '<div class="l1-batch-note">수집 대상일 ' + esc(data.source_date) + ' · ' + esc(data.time_basis) +
            ' · 조회 시점 기준: ' + esc(data.aggregation_basis) + '</div>' +
            (rows.length ? '<div class="l1-batch-table-wrap"><table class="ct ct-grid"><colgroup><col style="width:23%"><col style="width:29%">' +
                '<col style="width:10%"><col style="width:10%"><col style="width:15%"><col style="width:13%"></colgroup><thead><tr><th>배치 ID</th><th>수집 시간</th>' +
                '<th>MAIN</th><th>BSR</th><th>현재 집계 반영</th><th>쿼리 조회</th></tr></thead><tbody>' + body + '</tbody></table></div>'
                : '<div class="l1-batch-note">해당 날짜에 조회되는 배치가 없습니다.</div>') + '</div>';
    }

    async function load(state) {
        if (state.loading) return;
        state.loading = true;
        state.cell.innerHTML = '<div class="l1-batch-panel" role="status">배치별 내역을 조회하는 중...</div>';
        try {
            var params = new URLSearchParams(state.context);
            var response = await fetch('/dx/layer1/api/retail-batches/?' + params.toString());
            if (!response.ok) throw new Error('batch details unavailable');
            var data = await response.json();
            if (data.error) throw new Error('batch details unavailable');
            if (!state.row.isConnected) return;
            state.data = data;
            state.cell.innerHTML = render(data);
        } catch (_) {
            if (!state.row.isConnected) return;
            state.data = null;
            state.cell.innerHTML = '<div class="l1-batch-panel" role="alert">배치 내역 조회에 실패했습니다. ' +
                '<button type="button" class="l1-retail-query-button" onclick="event.stopPropagation();L1.retailBatches.reload(this)">다시 조회</button></div>';
        } finally { state.loading = false; }
    }

    function toggle(button) {
        var state = buttons.get(button);
        if (!state) {
            var parent = button.closest('tr');
            var row = document.createElement('tr');
            row.className = 'l1-batch-detail';
            row.id = 'l1-batch-detail-' + (++sequence);
            var cell = document.createElement('td');
            cell.colSpan = parent.cells.length;
            row.appendChild(cell);
            parent.insertAdjacentElement('afterend', row);
            state = { row: row, cell: cell, context: JSON.parse(button.dataset.batchContext), data: null, loading: false };
            buttons.set(button, state);
            details.set(row, state);
            button.setAttribute('aria-controls', row.id);
        }
        var open = button.getAttribute('aria-expanded') !== 'true';
        button.setAttribute('aria-expanded', String(open));
        button.textContent = '배치 ' + button.dataset.batchCount + '개 ' + (open ? '▴' : '▾');
        state.row.hidden = !open;
        if (open && !state.data) return load(state);
    }

    function reload(button) {
        var state = details.get(button.closest('.l1-batch-detail'));
        if (state) return load(state);
    }

    function sql(button, index) {
        var state = details.get(button.closest('.l1-batch-detail'));
        var batch = state && state.data && state.data.batches[index];
        if (batch) L1.retailQuery.showSql(state.data.retailer + ' / ' + (batch.batch_id || '배치 ID 없음') + ' 조회 SQL', batch.sql);
    }

    L1.retailBatches = { toggle: toggle, reload: reload, sql: sql, render: render };
})();
