/**
 * Layer 4 수집 현황 — NULL 상세
 */

(function() {
    'use strict';

    var params = new URLSearchParams(window.location.search);
    var category = params.get('category') || 'tv';
    var retailer = params.get('retailer') || '';
    var column = params.get('column') || '';
    var date = params.get('date') || '';

    function loadDetail() {
        var infoEl = document.getElementById('csd-info');
        infoEl.innerHTML = '<strong>' + L4.escapeHtml(retailer) + '</strong> / '
            + '<strong>' + L4.escapeHtml(column) + '</strong> — NULL 항목 ('
            + L4.escapeHtml(date) + ')';

        // 뒤로가기 링크
        var backBtn = document.getElementById('csd-back-btn');
        backBtn.href = '/dx/layer4/collection-status/?date=' + encodeURIComponent(date)
            + '&focus=' + encodeURIComponent('항목별 NULL 현황')
            + '&category=' + encodeURIComponent(category);

        var container = document.getElementById('csd-container');
        container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';

        var url = '/dx/layer4/api/collection-status/null-detail/'
            + '?date=' + encodeURIComponent(date)
            + '&category=' + encodeURIComponent(category)
            + '&retailer=' + encodeURIComponent(retailer)
            + '&column=' + encodeURIComponent(column);

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    container.innerHTML = '<div class="l4-empty-state"><p>' + L4.escapeHtml(data.error || '조회 실패') + '</p></div>';
                    return;
                }
                renderDetail(data);
            })
            .catch(function(e) {
                console.error(e);
                container.innerHTML = '<div class="l4-empty-state"><p>오류가 발생했습니다.</p></div>';
            });
    }

    function renderDetail(data) {
        var container = document.getElementById('csd-container');
        var rows = data.rows || [];
        var columns = data.columns || [];

        if (rows.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>NULL 데이터가 없습니다.</p></div>';
            return;
        }

        var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary);">총 <strong>' + rows.length + '</strong>건</div>';
        html += '<div class="csd-table-wrap"><table class="csd-table">';
        html += '<thead><tr>';
        columns.forEach(function(col) {
            html += '<th>' + L4.escapeHtml(col) + '</th>';
        });
        html += '</tr></thead>';
        html += '<tbody>';
        rows.forEach(function(row) {
            html += '<tr>';
            columns.forEach(function(col) {
                var val = row[col];
                if (col === 'product_url' && /^https?:\/\//i.test(String(val || ''))) {
                    html += '<td>'
                        + '<a href="' + L4.escapeHtml(val) + '" target="_blank" rel="noopener noreferrer" style="color:var(--page-color);text-decoration:none;margin-right:4px;vertical-align:middle;">'
                        + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>'
                        + '<span>' + L4.escapeHtml(val) + '</span></td>';
                } else if (!val && val !== 0) {
                    html += '<td class="csd-null-cell">NULL</td>';
                } else {
                    html += '<td>' + L4.escapeHtml(String(val)) + '</td>';
                }
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';

        container.innerHTML = html;
    }

    L4._sectionInit['collection_status'] = function() {
        loadDetail();
    };
    L4._sectionHandler['collection_status'] = function() {};

})();
