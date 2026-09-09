(function() {
    function count(value) {
        if (value === null || value === undefined) return '-';
        return Math.trunc(Number(value) || 0).toLocaleString();
    }

    function retailerRow(row) {
        var history = row.history || [];
        var average = history.length
            ? '<details><summary>' + count(row.expected) + '</summary>' +
                '<div style="font-size:12px;white-space:nowrap;">' +
                history.map(function(day) {
                    return esc(day.source_date) + ': ' + count(day.main_count) + '건';
                }).join('<br>') + '</div></details>'
            : '<span title="이전 수집 이력 없음">-</span>';
        return '<tr>' +
            '<td class="rt-name">' + esc(row.retailer) +
                '<div style="font-size:11px;color:#64748b;">' + esc(row.batch_id || '-') + '</div></td>' +
            '<td>' + count(row.main_count) + '</td>' +
            '<td>' + count(row.bsr_count) + '</td>' +
            '<td class="rt-total">' + count(row.raw_count) + '</td>' +
            '<td>' + average + '</td>' +
            '<td>' + (row.difference > 0 ? '+' : '') + count(row.difference) + '</td>' +
            '<td>' + getStatusBadge(row.status) + '</td></tr>';
    }

    function category(cat, checkIdx, catIdx) {
        return '<div class="sentiment-category-item">' +
            '<div class="sentiment-category-header" onclick="toggleSegCategory(this,' + checkIdx + ',' + catIdx + ')">' +
                '<div class="sentiment-category-info"><span class="toggle-icon-small">▶</span>' +
                '<span class="sentiment-category-name">' + esc(cat.category) + '</span></div>' +
                '<div class="sentiment-category-stats"><span class="sentiment-category-count">' +
                count(cat.raw_count) + '건</span>' + getStatusBadge(cat.status) + '</div></div>' +
            '<div class="sentiment-two-column retail-single-column" id="seg-cat-' + checkIdx + '-' + catIdx + '">' +
                '<div class="sentiment-column"><div class="retail-rank-wrap" style="overflow-x:auto;">' +
                '<table class="ct ct-grid"><thead><tr><th>리테일러</th><th>MAIN</th><th>BSR</th>' +
                '<th>총 건수</th><th>MAIN 평균</th><th>평균 대비 차이</th><th>상태</th></tr></thead>' +
                '<tbody>' + (cat.retailers || []).map(retailerRow).join('') +
                '<tr class="rt-sum"><td>합계</td><td>' + count(cat.main_count) + '</td><td>' +
                count(cat.bsr_count) + '</td><td>' + count(cat.raw_count) + '</td><td>' +
                count(cat.expected) + '</td><td></td><td></td></tr></tbody></table></div></div></div></div>';
    }

    function render(check, checkIdx) {
        return '<div class="check-item"><div class="check-main" onclick="toggleTimeSlots(this,' + checkIdx + ')">' +
            '<div class="check-info"><div class="check-name"><span class="toggle-icon">▶</span>' +
            renderCountryFlagLabel(check.name || 'SEG Retail') + '</div><div class="check-description">' +
            esc(check.description || '') + '</div></div><div class="check-stats"><div class="check-stat">' +
            '<div class="value">' + count(check.raw_count) + '</div><div class="label">총 수집량</div></div>' +
            getStatusBadge(check.status) + '</div></div>' +
            '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            '<div style="margin-bottom:12px;">검수일 ' + esc(check.inspection_date) +
            ' · 데이터일 ' + esc(check.source_date) + ' (D) · ' + esc(check.collection_window) + '</div>' +
            '<div style="font-size:12px;color:#64748b;margin-bottom:12px;">' +
            'MAIN·BSR은 순위가 있는 행 수이며 같은 상품이 겹칠 수 있습니다. 총 건수는 실제 행 수입니다.<br>' +
            'MAIN 평균: 당일 제외, 0건 제외, 최근 수집일 최대 7개, 소수점 버림. 평균을 누르면 계산에 사용한 날짜를 볼 수 있습니다.' +
            (check.status_basis === 'collection_presence'
                ? '<br>평균 차이는 참고용이며, 수집 완료 후 0건인 경우 심각으로 표시합니다.' : '') +
            '</div><div class="sentiment-categories">' +
            (check.categories || []).map(function(cat, catIdx) { return category(cat, checkIdx, catIdx); }).join('') +
            '</div></div></div>';
    }

    window.toggleSegCategory = function(element, checkIdx, catIdx) {
        var container = document.getElementById('seg-cat-' + checkIdx + '-' + catIdx);
        var icon = element.querySelector('.toggle-icon-small');
        if (!container) return;
        container.classList.toggle('show');
        if (icon) icon.classList.toggle('expanded');
    };
    L1.renderers.seg_retail = render;
})();
