/* Correction groups and comparison history on the list itself. No source mutations. */
(function () {
    'use strict';
    var page = 1, sequence = 0, initialized = false, lastDate = null;
    var types = {all:'전체',null_check:'NULL',format_check:'형식',duplicate_check:'중복',cross_field:'크로스필드',field_missing:'누락필드'};
    var focusTypes = {'NULL 검수':'null_check','형식 검수':'format_check','중복 검수':'duplicate_check','크로스필드 검수':'cross_field','누락필드 검수':'field_missing'};
    var selectedType = focusTypes[new URLSearchParams(window.location.search).get('focus')] || 'all';
    var hiddenColumns = new Set();
    var cols = [['no','No'],['category','국가 · 제품군'],['product','Item · 상품명'],['date','수집일'],['field','검수 항목'],['old','수정 전'],['new','수정 후 · 확인값'],['status','처리 결과'],['reviewer','검수자 · 처리 시각'],['url','상품 URL'],['reason','확인 사유'],['detail','상세']];
    var statusNames = {corrected:'수정',normal:'정상 확인',error:'이상 확인',reverted:'취소'};
    function el(id) { return document.getElementById(id); }
    function esc(v) { return L4.escapeHtml(String(v == null ? '' : v)); }
    function val(v) { return v === null ? '<span class="audit-null">NULL</span>' : v === '' ? '<span class="audit-muted">빈 문자열</span>' : v === undefined ? '—' : esc(v); }
    function dateText(v) { var raw = String(v || '원본 미조회'); return esc(raw.slice(0,10)) + (raw.length > 10 ? '<small>' + esc(raw.slice(11)) + '</small>' : ''); }
    function url(v) {
        try { var parsed = new URL(v); if (!['https:','http:'].includes(parsed.protocol) || parsed.username || parsed.password) return '—';
            return '<a href="' + esc(parsed.href) + '" target="_blank" rel="noopener noreferrer">↗ 상품 페이지</a>';
        } catch (_) { return '—'; }
    }
    function select(id, label) { return '<select id="' + id + '" aria-label="' + label + '"><option value="all">전체 ' + label + '</option></select>'; }
    function status() { var active = document.querySelector('#corrections-tabs .log-tab.active'); return active ? active.dataset.status : 'all'; }
    function init() {
        if (initialized) return;
        initialized = true;
        el('corrections-filter-bar').innerHTML = '<div class="audit-list-filters">' + select('corr-country','국가') + select('corr-product','제품군') + select('corr-retailer','리테일러') + select('corr-reviewer','검수자')
            + '<input id="corr-search" placeholder="Item · 컬럼 검색" aria-label="Item 또는 컬럼 검색"><button id="corr-search-btn" class="app-btn">조회</button><button id="corr-reset-btn" class="app-btn app-btn-outline">해제</button></div>';
        ['country','product','retailer','reviewer'].forEach(function (key) { el('corr-' + key).onchange = function () { load(1); }; });
        el('corr-search-btn').onclick = function () { load(1); };
        el('corr-search').onkeydown = function (e) { if (e.key === 'Enter') load(1); };
        el('corr-reset-btn').onclick = function () { ['country','product','retailer','reviewer'].forEach(function (key) { el('corr-' + key).value = 'all'; }); el('corr-search').value = ''; load(1); };
        el('correction-compare-days').onchange = function () { load(1); };
        document.querySelectorAll('[data-corr-status]').forEach(function (button) { button.onclick = function () {
            var tab = document.querySelector('#corrections-tabs .log-tab[data-status="' + button.dataset.corrStatus + '"]');
            if (tab) tab.click();
        }; });
        el('correction-column-options').innerHTML = cols.filter(function (c) { return !['no','detail'].includes(c[0]); }).map(function (c) { return '<label><input type="checkbox" checked data-corr-column="' + c[0] + '"> ' + c[1] + '</label>'; }).join('');
        el('correction-column-options').onchange = function (e) { var key = e.target.dataset.corrColumn; if (!key) return; if (e.target.checked) hiddenColumns.delete(key); else hiddenColumns.add(key); applyColumns(); };
    }
    function options(id, values, label) {
        var select = el(id), saved = select.value;
        select.innerHTML = '<option value="all">전체 ' + label + '</option>' + values.map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + '</option>'; }).join('');
        if (values.includes(saved)) select.value = saved;
    }
    function load(nextPage) {
        if (!initialized) init();
        if (status() === 'bulk_history') return;
        if (nextPage !== undefined) page = nextPage;
        var date = getSelectedDate(); if (!date) return;
        if (lastDate !== date) { page = 1; lastDate = date; }
        var ticket = ++sequence;
        if (window.CorrectionAudit) window.CorrectionAudit.close();
        var params = new URLSearchParams({date:date,type:selectedType,status:status(),page:page,page_size:50,days:el('correction-compare-days').value,
            country:el('corr-country').value,product:el('corr-product').value,retailer:el('corr-retailer').value,reviewer:el('corr-reviewer').value,
            search_field:'item_column',search_value:el('corr-search').value.trim()});
        el('corrections-table-container').innerHTML = '<div class="l4-empty-state">조회 중...</div>';
        return fetch('/dx/layer4/api/corrections/?' + params).then(function (response) { return response.json().then(function (data) { if (!response.ok || !data.success) throw new Error(data.error || '조회 실패'); return data; }); }).then(function (data) {
            if (ticket !== sequence || status() === 'bulk_history') return;
            render(data);
        }).catch(function (error) { if (ticket !== sequence) return; el('corrections-table-container').innerHTML = '<div class="l4-empty-state">' + esc(error.message) + '</div>'; });
    }
    function summary(data) {
        var counts = data.status_counts || {}, total = Object.values(counts).reduce(function (a,b) { return a+b; },0);
        el('corr-total').textContent = total.toLocaleString();
        ['corrected','normal','error','reverted'].forEach(function (s) { el('corr-' + s).textContent = (counts[s] || 0).toLocaleString();
            var tab = el('tab' + s.charAt(0).toUpperCase() + s.slice(1) + 'Count'); if (tab) tab.textContent = counts[s] || 0;
        });
        document.querySelectorAll('[data-corr-status]').forEach(function (b) { b.classList.toggle('active',b.dataset.corrStatus === status()); });
        var totals = data.type_counts || {}, typeTotal = Object.values(totals).reduce(function (a,b) { return a+b; },0);
        el('correction-type-chips').innerHTML = Object.keys(types).map(function (key) { return '<button class="app-btn app-btn-outline ' + (key === selectedType ? 'active' : '') + '" data-corr-type="' + key + '">' + types[key] + ' <b>' + (key === 'all' ? typeTotal : totals[key] || 0) + '</b></button>'; }).join('');
        el('correction-type-label').textContent = types[selectedType];
        el('correction-type-chips').querySelectorAll('button').forEach(function (b) { b.onclick = function () { selectedType = b.dataset.corrType; load(1); }; });
        var opts = data.filter_options || {};
        [['country','countries','국가'],['product','products','제품군'],['retailer','retailers','리테일러'],['reviewer','reviewers','검수자']].forEach(function (x) { options('corr-' + x[0],opts[x[1]] || [],x[2]); });
    }
    function cell(key, content, extra) { return '<td data-col="' + key + '"' + (extra || '') + '>' + content + '</td>'; }
    function render(data) {
        summary(data);
        var html = '<table class="audit-group-table"><thead><tr>' + (status() === 'normal' ? '<th><input type="checkbox" id="audit-list-check-all" aria-label="확인 기록 전체 선택"></th>' : '') + cols.map(function (c) { return '<th data-col="' + c[0] + '">' + c[1] + '</th>'; }).join('') + '</tr></thead><tbody>';
        var number = (data.page - 1) * data.page_size, displayed = 0;
        data.items.forEach(function (item, index) {
            var history = item.comparison_rows || [], span = history.length + 1;
            var rows = history.map(function (r) { return {comparison:r}; }).concat([{target:true}]);
            rows.forEach(function (row, i) {
                displayed++;
                html += '<tr class="' + (row.target ? 'audit-current-row' : 'audit-comparison-row') + '">';
                if (status() === 'normal' && i === 0) html += '<td rowspan="' + span + '">' + (item.review_source ? '<span title="형식검증 화면에서 취소">—</span>' : '<input class="corr-check" type="checkbox" data-id="' + Number(item.id) + '" aria-label="확인 기록 선택">') + '</td>';
                html += cell('no',row.target ? number + index + 1 : '·');
                if (i === 0) {
                    var category = item.category_label || item.table_name;
                    html += cell('category',(typeof renderCountryFlagLabel === 'function' ? renderCountryFlagLabel(category) : esc(category)) + '<small>' + esc(item.retailer || '-') + '</small>',' rowspan="' + span + '"');
                    html += cell('product','<span class="audit-muted">' + esc(item.item || '-') + '</span><strong>' + esc(item.retailer_sku_name || '상품명 미조회') + '</strong>',' rowspan="' + span + '"');
                }
                html += cell('date',dateText(row.target ? item.crawl_time : row.comparison.crawl_time || row.comparison.source_date) + '<span class="audit-badge">' + (row.target ? '검수 대상' : '비교 이력') + '</span>');
                html += cell('field',esc(item.column_name) + '<small>' + esc(types[item.correction_type] || item.correction_type) + '</small>');
                html += cell('old',row.target && item.review_source ? '—' : val(row.target ? item.old_value : row.comparison.field_available ? row.comparison.value : undefined));
                html += cell('new',row.target ? val(item.new_value) : '—');
                html += cell('status','<span class="audit-badge">' + esc(row.target ? statusNames[item.status] || L4.STATUS_NAMES[item.status] || item.status : '비교 이력') + '</span>' + (row.target && item.shared_normal ? '<small>정상 공유 승인 · 최초 ' + esc(item.origin_product) + '</small>' : '') + (row.target && item.status === 'error' ? '<small>이상 확인 · 미수정</small>' : ''));
                html += cell('reviewer',row.target ? esc(item.created_id || '-') + '<small>' + esc(item.created_at) + '</small>' : '—');
                html += cell('url',url(row.target ? item.product_url : row.comparison.product_url));
                html += cell('reason',row.target ? esc(item.reason || item.memo || '-') + (item.history_truncated ? '<small>이력 일부 생략 · 상세에서 확인</small>' : '') + (item.history_notice ? '<small>' + esc(item.history_notice) + '</small>' : '') : '—');
                html += cell('detail',row.target ? '<button class="app-btn app-btn-sm app-btn-outline" data-corr-detail="' + index + '">상세조회</button>' : '—') + '</tr>';
            });
        });
        if (!data.items.length) html += '<tr><td colspan="13" class="l4-empty-state">조건에 맞는 검수기록이 없습니다.</td></tr>';
        el('corrections-table-container').innerHTML = html + '</tbody></table>';
        var cancelButton = el('corr-cancel-btn');
        var selectable = data.items.some(function (item) { return !item.review_source; });
        if (cancelButton) cancelButton.style.display = selectable ? '' : 'none';
        el('correction-row-count').textContent = '검수 대상 ' + data.total.toLocaleString() + '건 · 현재 페이지 비교 이력 포함 ' + displayed + '행';
        el('corrections-table-container').querySelectorAll('[data-corr-detail]').forEach(function (button) { button.onclick = function () { window.CorrectionAudit.open(data.items[Number(button.dataset.corrDetail)]); }; });
        var all = el('audit-list-check-all'); if (all) { all.disabled = !selectable; all.onchange = function () { document.querySelectorAll('.corr-check').forEach(function (check) { check.checked = all.checked; }); }; }
        var pages = el('corrections-pagination'); pages.innerHTML = '<div class="audit-pagination"><span>' + data.page + ' / ' + Math.max(data.total_pages,1) + ' 페이지</span><button class="app-btn app-btn-sm app-btn-outline" id="corr-previous" ' + (data.page <= 1 ? 'disabled' : '') + '>이전</button><button class="app-btn app-btn-sm app-btn-outline" id="corr-next" ' + (data.page >= data.total_pages ? 'disabled' : '') + '>다음</button></div>';
        el('corr-previous').onclick = function () { load(page-1); }; el('corr-next').onclick = function () { load(page+1); };
        applyColumns();
    }
    function applyColumns() { document.querySelectorAll('#corrections-table-container [data-col]').forEach(function (cell) { cell.hidden = hiddenColumns.has(cell.dataset.col); }); }
    window.CorrectionList = {init:init,load:load};
}());
