/* Shared read-only correction detail. SELECT text is fetched from an admin-only API. */
(function () {
    'use strict';
    var sequence = 0;
    var state = null;
    var modalReady = false;
    var opener = null;
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
        var review = item.review_source === 'format_review';
        var rows = kv('검증유형', L4.TYPE_NAMES[item.correction_type] || item.correction_type)
            + kv('원본 테이블', item.table_name) + kv('리테일러 / Item', (item.retailer || '-') + ' / ' + (item.item || '-'))
            + kv('레코드 / 컬럼', String(item.record_id) + ' / ' + item.column_name)
            + kv('검수일', item.crawl_date) + (review ? kv('확인 당시 값', item.new_value) : kv('수정 전 값', item.old_value) + kv('수정 후 값', item.new_value))
            + kv('처리 결과', ({normal:'정상 확인',error:'이상 확인',reverted:'취소'})[item.status] || L4.STATUS_NAMES[item.status] || item.status)
            + kv('사유', item.reason || '-') + kv('메모', item.memo || '-')
            + kv('처리자 / 처리 시각', (item.created_id || '-') + ' / ' + (item.created_at || '-'));
        if (item.rule_name) rows += kv('검증 규칙', item.rule_name);
        if (item.status === 'reverted') rows += kv('취소자 / 시각', (item.updated_id || '-') + ' / ' + (item.updated_at || '-')) + kv('취소 사유', item.cancel_memo || '-');
        return '<table class="corr-detail-table">' + rows + '</table>';
    }
    function open(item) {
        if (!modalReady) {
            AppModal.create('corr-detail', { style: 'wide', closeOnOverlay: true });
            var modal = document.getElementById('modal-corr-detail');
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.querySelector('.app-modal__title').id = 'correction-detail-title';
            modal.setAttribute('aria-labelledby', 'correction-detail-title');
            modal.querySelector('.app-modal__close').setAttribute('aria-label', '검수기록 상세 닫기');
            new MutationObserver(function () {
                if (!modal.classList.contains('show')) {
                    state = null; sequence++;
                    AppModal.setBody('corr-detail', '');
                    if (opener && opener.isConnected) opener.focus({preventScroll:true});
                }
            }).observe(modal, {attributes:true,attributeFilter:['class']});
            modal.addEventListener('keydown', function (event) {
                if (event.key !== 'Tab') return;
                var focusable = Array.from(modal.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex="0"]')).filter(function (node) { return node.getClientRects().length && !node.disabled; });
                var first = focusable[0], last = focusable[focusable.length - 1];
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            });
            modalReady = true;
        }
        opener = document.activeElement;
        state = { item: item, days: 3, ticket: ++sequence };
        var content = '<div class="audit-detail"><details class="audit-saved-log"><summary>검수 당시 저장 기록 · 사유 · 메모</summary>' + logHtml(item)
            + '</details><section id="audit-source"><p class="audit-muted">상품 URL과 수집 이력을 조회 중입니다.</p></section></div>';
        AppModal.setTitle('corr-detail', '검수기록 상세');
        AppModal.setBody('corr-detail', content);
        AppModal.open('corr-detail');
        AppModal.getBody('corr-detail').scrollTop = 0;
        document.querySelector('#modal-corr-detail .app-modal__close').focus({preventScroll:true});
        load();
    }
    function close() {
        if (modalReady) AppModal.close('corr-detail');
        state = null; sequence++;
    }
    function load() {
        var ticket = ++sequence;
        state.ticket = ticket;
        var id = state.item.id, days = state.days;
        var params = state.item.review_source === 'format_review' ? new URLSearchParams({review_event_id:state.item.review_event_id,target:state.item.review_target,record:state.item.review_record}) : new URLSearchParams({id:id,days:days});
        get('/dx/layer4/api/corrections/detail/?' + params).then(function (data) {
            if (!state || state.ticket !== ticket || !document.getElementById('audit-source')) return;
            state.data = data;
            render(data);
        }).catch(function (error) {
            if (!state || state.ticket !== ticket || !document.getElementById('audit-source')) return;
            document.getElementById('audit-source').innerHTML = '<p class="audit-muted">' + esc(error.message) + ' 저장된 검수기록은 위에서 확인할 수 있습니다.</p>';
        });
    }
    function render(data) {
        if (data.review_source === 'format_review') return renderReview(data);
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
        var cols = data.columns;
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
        if ((data.review_events || []).length) {
            html += '<h3 class="audit-event-title">이 레코드·컬럼의 형식 확인 기록</h3><div class="audit-events">';
            data.review_events.forEach(function (e, i) {
                html += '<div><b>' + esc(e.review_action === 'normal' ? '정상 확인' : '이상 확인') + '</b> · ' + esc(e.created_id) + ' · ' + esc(e.created_at)
                    + '<p>확인 당시 값: ' + value(e.new_value) + '</p><p>' + esc(e.reason) + '</p><button class="app-btn app-btn-sm app-btn-outline" data-review-detail="' + i + '">확인 증빙·취소 이력</button></div>';
            });
            html += '</div>';
        }
        document.getElementById('audit-source').innerHTML = html;
        document.querySelectorAll('[data-review-detail]').forEach(function (button) { button.onclick = function () { open(data.review_events[Number(button.dataset.reviewDetail)]); }; });
        document.getElementById('audit-reload').onclick = function () {
            var days = Number(document.getElementById('audit-days').value);
            if (!Number.isInteger(days) || days < 1 || days > 30) return showToast('비교 일수는 1~30일입니다.', 'warning');
            state.days = days; load();
        };
        var queryButton = document.getElementById('audit-query');
        if (queryButton) queryButton.onclick = loadQuery;
    }
    function renderReview(data) {
        var labels = {normal:'정상 확인',error:'이상 확인',revoke:'승인 취소',undo:'처리 취소'};
        var html = '<h3>형식 확인 당시 저장 기록</h3><p class="audit-muted">검수일 ' + esc(data.inspection_date) + ' · 원본 수집일 ' + esc(data.source_date)
            + ' · 최초 처리 제품군 ' + esc(data.origin_product) + '</p><p>'
            + (data.shared_normal ? '같은 국가·리테일러·컬럼·정확한 값의 정상 승인을 제품군 간 공유합니다. 다른 제품군의 개별 상품을 직접 확인했다는 뜻은 아닙니다.' : '이상임을 확인한 기록이며 수정·해결 완료가 아닙니다. 실제 확인한 원본 레코드에만 적용됩니다.') + '</p>'
            + '<div class="audit-values"><div><label>확인 컬럼</label>' + esc(data.field) + '</div><div><label>확인 당시 값</label>' + value(data.value) + '</div><div><label>확인 사유</label>' + esc(data.reason) + '</div></div>'
            + '<h3>확인 대상 상품 · 당시 저장 정보</h3><div class="audit-table-wrap"><table class="audit-table"><thead><tr><th>레코드</th><th>Item · 상품명</th><th>수집 시각 원문</th><th>상품 URL</th></tr></thead><tbody>';
        (data.records || []).forEach(function (r) { html += '<tr><td>' + esc(r.id) + '</td><td>' + esc(r.item) + '<br>' + esc(r.name) + '</td><td>' + esc(r.collected_at || '미저장') + '</td><td>' + link(r.url) + '</td></tr>'; });
        html += '</tbody></table></div><h3>확인한 URL · 첨부 증빙</h3>';
        (data.checked_urls || []).forEach(function (u) { html += '<p>' + link(u) + '</p>'; });
        (data.captures || []).forEach(function (c) {
            // Only the authenticated, environment-scoped capture endpoint is embedded.
            if (!/^\/dx\/layer2\/api\/format-review\/capture\/\d+\/$/.test(c.url)) return;
            html += '<details><summary>' + esc(c.name) + '</summary><img loading="lazy" style="max-width:100%;height:auto" src="' + esc(c.url) + '" alt="' + esc(c.name) + '"></details>';
        });
        if (!(data.checked_urls || []).length && !(data.captures || []).length) html += '<p class="audit-muted">저장된 증빙이 없습니다.</p>';
        html += '<h3>동일 값의 처리·취소 이력</h3><div class="audit-events">';
        (data.history || []).forEach(function (e) { html += '<div><b>' + esc(labels[e.action] || e.action) + '</b> · ' + esc(e.product) + ' · ' + esc(e.actor) + ' · ' + esc(e.created_at) + (e.is_del ? ' · 취소된 처리' : '') + '<p>' + esc(e.reason) + '</p></div>'; });
        html += '</div>' + (data.history_truncated ? '<p>최근 처리 이력 100건을 표시합니다.</p>' : '');
        if ((data.correction_history || []).length) {
            html += '<h3 class="audit-event-title">이 레코드·컬럼의 수정 이력</h3><div class="audit-events">';
            data.correction_history.forEach(function (e) { html += '<div><b>' + esc(L4.STATUS_NAMES[e.status] || e.status) + '</b> · ' + esc(e.created_id) + ' · ' + esc(e.created_at)
                + '<p>' + value(e.old_value) + ' → ' + value(e.new_value) + '</p><p>' + esc(e.reason || e.memo || '') + '</p></div>'; });
            html += '</div>';
        }
        document.getElementById('audit-source').innerHTML = html;
    }
    function loadQuery() {
        if (!window.CORRECTIONS_IS_ADMIN || !state) return;
        var ticket = state.ticket;
        get('/dx/layer4/api/corrections/query/?id=' + encodeURIComponent(state.item.id) + '&days=' + state.days).then(function (data) {
            if (!state || ticket !== state.ticket || !document.getElementById('audit-sql')) return;
            document.getElementById('audit-sql').innerHTML = '<div class="audit-query-panel"><h3>원본 확인용 SELECT 쿼리 · 관리자</h3><p class="audit-muted">검수 항목과 관련된 컬럼을 함께 조회합니다. 이 화면은 조회 쿼리만 제공하며 DB 값을 변경하지 않습니다.</p>'
                + '<div class="audit-toolbar"><b>' + state.days + '일치 Item 조회 · 모든 배치</b><button class="app-btn app-btn-sm app-btn-outline" id="audit-copy-query">복사</button></div><pre>' + esc(data.sql) + '</pre></div>';
            document.getElementById('audit-copy-query').onclick = function () { copy(data.sql); };
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
    window.CorrectionAudit = { open: open, close: close };
}());
