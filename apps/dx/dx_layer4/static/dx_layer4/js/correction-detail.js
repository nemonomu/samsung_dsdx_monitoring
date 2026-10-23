/* Shared read-only correction detail. SELECT text is fetched from an admin-only API. */
(function () {
    'use strict';
    var sequence = 0;
    var state = null;
    var esc = function (v) { return L4.escapeHtml(String(v == null ? '' : v)); };
    function value(v) {
        if (v === null) return '<span class="audit-null">NULL</span>';
        if (v === '') return '<span class="audit-muted">빈 문자열</span>';
        if (v === undefined) return '<span class="audit-muted">미조회</span>';
        return esc(v);
    }
    function safeURL(v) {
        try {
            var u = new URL(v);
            return ['https:', 'http:'].indexOf(u.protocol) >= 0 && !u.username && !u.password ? u.href : '';
        } catch (_) { return ''; }
    }
    function link(v) {
        var url = safeURL(v);
        return url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">↗ 상품 페이지 열기</a>' : '<span class="audit-muted">등록된 상품 URL 없음</span>';
    }
    function get(url) {
        return fetch(url).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok || data.error) throw new Error(data.error || '조회하지 못했습니다.');
                return data;
            });
        });
    }
    function kv(label, val) { return '<tr><th>' + esc(label) + '</th><td>' + value(val) + '</td></tr>'; }
    function logHtml(item) {
        var rows = kv('검증유형', L4.TYPE_NAMES[item.correction_type] || item.correction_type)
            + kv('원본 테이블', item.table_name) + kv('리테일러 / Item', (item.retailer || '-') + ' / ' + (item.item || '-'))
            + kv('레코드 / 컬럼', String(item.record_id) + ' / ' + item.column_name)
            + kv('검수일', item.crawl_date) + kv('수정 전 값', item.old_value) + kv('수정 후 값', item.new_value)
            + kv('처리 결과', L4.STATUS_NAMES[item.status] || item.status)
            + kv('사유', item.reason || '-') + kv('메모', item.memo || '-')
            + kv('처리자 / 처리 시각', (item.created_id || '-') + ' / ' + (item.created_at || '-'));
        if (item.rule_name) rows += kv('검증 규칙', item.rule_name);
        if (item.status === 'reverted') rows += kv('취소자 / 시각', (item.updated_id || '-') + ' / ' + (item.updated_at || '-')) + kv('취소 사유', item.cancel_memo || '-');
        return '<table class="corr-detail-table">' + rows + '</table>';
    }
    function open(item) {
        state = { item: item, days: 3, ticket: ++sequence };
        AppModal.setTitle('corr-detail', '검수기록 상세');
        AppModal.setBody('corr-detail', '<div class="audit-detail">' + logHtml(item)
            + '<section id="audit-source"><p class="audit-muted">상품 URL과 수집 이력을 조회 중입니다.</p></section></div>');
        AppModal.open('corr-detail');
        load();
    }
    function load() {
        var ticket = ++sequence;
        state.ticket = ticket;
        var id = state.item.id, days = state.days;
        get('/dx/layer4/api/corrections/detail/?id=' + encodeURIComponent(id) + '&days=' + days).then(function (data) {
            if (!state || state.ticket !== ticket || !document.getElementById('audit-source')) return;
            state.data = data;
            render(data);
        }).catch(function (error) {
            if (!state || state.ticket !== ticket || !document.getElementById('audit-source')) return;
            document.getElementById('audit-source').innerHTML = '<p class="audit-muted">' + esc(error.message) + ' 저장된 검수기록은 위에서 확인할 수 있습니다.</p>';
        });
    }
    function render(data) {
        var item = state.item, target = data.target, field = data.field;
        var url = target && target.product_url;
        if (!url) {
            var match = (data.rows || []).find(function (r) { return safeURL(r.product_url); });
            url = match && match.product_url;
        }
        var html = '<div class="audit-source-head"><div><h3>' + esc(data.country + ' · ' + data.product) + ' 원본 데이터 확인</h3>'
            + '<p class="audit-muted">상품 페이지와 저장된 수정 전후 값을 직접 대조하세요. 상품 페이지는 이후 바뀔 수 있습니다.</p></div>'
            + '<div class="audit-url">' + (!target && url ? '<span class="audit-muted">비교 이력의 URL<br></span>' : '') + link(url) + '</div></div>';
        if (!target) html += '<p class="audit-warning">해당 ID·리테일러·Item과 일치하는 원본 행을 찾지 못했습니다. 삭제 또는 식별 정보 변경 여부를 확인하세요.</p>';
        html += '<div class="audit-values"><div><label>검수 당시 수정 전 값</label>' + value(item.old_value) + '</div>'
            + '<div><label>검수 당시 수정 후 값</label>' + value(item.new_value) + '</div>'
            + '<div><label>원본의 현재 저장값 · ' + esc(field) + '</label>' + value(target && data.field_available ? target[field] : undefined) + '</div></div>';
        html += '<div class="audit-toolbar"><b>수집 이력 · ' + esc(data.start_date) + ' ~ ' + esc(data.source_date) + '</b>'
            + '<label>비교 일수 <input id="audit-days" type="number" min="1" max="30" value="' + state.days + '"></label>'
            + '<button class="app-btn app-btn-sm app-btn-outline" id="audit-reload">조회</button>';
        if (window.CORRECTIONS_IS_ADMIN) html += '<button class="app-btn app-btn-sm app-btn-outline" id="audit-query">관리자 조회 SQL</button>';
        html += '</div><p class="audit-muted">' + esc(data.notice) + ' 모든 배치를 표시하며, 비교 행은 검수건수에 포함하지 않습니다.</p>';
        if (data.truncated) html += '<p class="audit-warning">이력이 많아 최신 300행과 해당 검수 대상 행을 표시합니다.</p>';
        var cols = ['id', 'batch_id', 'item', 'retailer_sku_name', 'sku', field, 'product_url'].filter(function (c, i, all) { return data.columns.indexOf(c) >= 0 && all.indexOf(c) === i; });
        html += '<div class="audit-table-wrap"><table class="audit-table"><thead><tr><th>수집일 / 구분</th>' + cols.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>';
        (data.rows || []).forEach(function (r) {
            var isTarget = String(r.id) === String(item.record_id);
            html += '<tr' + (isTarget ? ' class="audit-target"' : '') + '><td>' + esc(r._source_date) + '<br><span class="audit-badge">' + (isTarget ? '검수 대상 원본' : '비교 이력') + '</span></td>';
            cols.forEach(function (c) { html += '<td>' + (c === 'product_url' ? link(r[c]) : value(r[c])) + '</td>'; });
            html += '</tr>';
        });
        if (!data.rows.length) html += '<tr><td colspan="' + (cols.length + 1) + '">수집 이력이 없습니다.</td></tr>';
        html += '</tbody></table></div><div id="audit-sql"></div><h3 class="audit-event-title">이 레코드·컬럼의 처리 이력</h3><div class="audit-events">';
        (data.events || []).forEach(function (e) {
            html += '<div><b>' + esc(L4.STATUS_NAMES[e.status] || e.status || '기록') + '</b> · ' + esc(e.created_id || '-') + ' · ' + esc(e.created_at || '-')
                + '<p>' + value(e.old_value) + ' → ' + value(e.new_value) + '</p><p class="audit-muted">' + esc(e.reason || e.memo || '-') + '</p>';
            if (e.status === 'reverted') html += '<p class="audit-muted">확인 취소 · ' + esc(e.updated_id || '-') + ' · ' + esc(e.updated_at || '-') + ' · ' + esc(e.cancel_memo || '-') + '</p>';
            html += '</div>';
        });
        html += '</div>';
        document.getElementById('audit-source').innerHTML = html;
        document.getElementById('audit-reload').onclick = function () {
            var days = Number(document.getElementById('audit-days').value);
            if (!Number.isInteger(days) || days < 1 || days > 30) return showToast('비교 일수는 1~30일입니다.', 'warning');
            state.days = days; load();
        };
        var queryButton = document.getElementById('audit-query');
        if (queryButton) queryButton.onclick = loadQuery;
    }
    function loadQuery() {
        if (!window.CORRECTIONS_IS_ADMIN || !state) return;
        var ticket = state.ticket;
        get('/dx/layer4/api/corrections/query/?id=' + encodeURIComponent(state.item.id) + '&days=' + state.days).then(function (data) {
            if (!state || ticket !== state.ticket || !document.getElementById('audit-sql')) return;
            var queries = [data.record_sql, data.history_sql];
            document.getElementById('audit-sql').innerHTML = '<div class="audit-query-panel"><h3>원본 확인용 SELECT 쿼리 · 관리자</h3><p class="audit-muted">이 화면은 조회 쿼리만 제공합니다. DB에서 확인하려면 복사한 SELECT를 사용하세요.</p>'
                + queries.map(function (sql, i) { return '<div class="audit-toolbar"><b>' + (i ? 'Item 기간 조회 · 모든 배치' : '검수 대상 원본 행 조회') + '</b><button class="app-btn app-btn-sm app-btn-outline" data-audit-copy="' + i + '">복사</button></div><pre>' + esc(sql) + '</pre>'; }).join('') + '</div>';
            document.querySelectorAll('[data-audit-copy]').forEach(function (b) {
                b.onclick = function () { copy(queries[Number(b.dataset.auditCopy)]); };
            });
        }).catch(function (e) { showToast(e.message, 'error'); });
    }
    function copy(text) {
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(function () { showToast('조회 SQL을 복사했습니다.', 'success'); }).catch(function () { fallbackCopy(text); });
        } else fallbackCopy(text);
    }
    function fallbackCopy(text) {
        var area = document.createElement('textarea'); area.value = text; document.body.appendChild(area); area.select();
        var ok = document.execCommand('copy'); area.remove();
        showToast(ok ? '조회 SQL을 복사했습니다.' : '쿼리 텍스트를 직접 선택해 복사하세요.', ok ? 'success' : 'warning');
    }
    window.CorrectionAudit = { open: open };
}());
