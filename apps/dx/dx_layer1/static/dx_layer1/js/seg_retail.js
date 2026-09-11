(function() {
    function count(value) {
        if (value === null || value === undefined) return '-';
        return Math.trunc(Number(value) || 0).toLocaleString();
    }

    function retailerRow(row) {
        var batchHtml = row.batch_id
            ? ' <span class="retail-batch-id" style="font-size:11px;color:#64748b;">/ ' +
                esc(row.batch_id) + '</span>'
            : '';
        return '<tr>' +
            '<td class="rt-name">' + esc(row.retailer || '-') + batchHtml + '</td>' +
            '<td>' + count(row.main_count) + '</td>' +
            '<td>' + count(row.bsr_count) + '</td>' +
            '<td class="rt-total">' + count(row.raw_count) + '</td>' +
            '<td class="rt-status ct-nc">' + getStatusBadge(row.status) + '</td></tr>';
    }

    function category(cat, checkIdx, catIdx) {
        var mainCount = count(cat.main_count);
        var countLabel = cat.expected === null || cat.expected === undefined
            ? mainCount + '건'
            : mainCount + '/' + count(cat.expected) + '건';
        return '<div class="sentiment-category-item">' +
            '<div class="sentiment-category-header" onclick="toggleSegCategory(this,' + checkIdx + ',' + catIdx + ')">' +
                '<div class="sentiment-category-info"><span class="toggle-icon-small">▶</span>' +
                '<span class="sentiment-category-name">' + esc(cat.category) + '</span></div>' +
                '<div class="sentiment-category-stats">' + L1.retailQuery.button('SEG', cat, checkIdx, catIdx) +
                '<span class="sentiment-category-count">' +
                countLabel + '</span>' + getStatusBadge(cat.status) + '</div></div>' +
            '<div class="sentiment-two-column retail-single-column" id="seg-cat-' + checkIdx + '-' + catIdx + '">' +
                '<div class="sentiment-column"><div class="retail-rank-wrap">' +
                '<table class="ct ct-grid"><colgroup><col style="width:28%"><col style="width:18%">' +
                '<col style="width:18%"><col style="width:18%"><col style="width:18%"></colgroup>' +
                '<thead><tr><th style="text-align:left">리테일러</th><th>MAIN</th><th>BSR</th>' +
                '<th>총 건수</th><th></th></tr></thead>' +
                '<tbody>' + (cat.retailers || []).map(retailerRow).join('') +
                '<tr class="rt-sum"><td>합계</td><td>' + count(cat.main_count) + '</td><td>' +
                count(cat.bsr_count) + '</td><td>' + count(cat.raw_count) +
                '</td><td></td></tr></tbody></table></div></div></div></div>';
    }

    function render(check, checkIdx) {
        return '<div class="check-item"><div class="check-main retail-check-main" onclick="L1.retailStatus.toggle(this,' + checkIdx + ')">' +
            '<div class="check-info"><div class="check-name"><span class="toggle-icon">▶</span>' +
            renderCountryFlagLabel(check.name || 'SEG Retail') + '</div><div class="check-description">' +
            esc(check.description || '') + '</div></div>' + L1.retailStatus.render(check, checkIdx, 'seg_retail') +
            '<div class="check-stats"><div class="check-stat">' +
            '<div class="value">' + count(check.raw_count) + '</div><div class="label">총 수집량</div></div>' +
            getStatusBadge(check.status) + '</div></div>' +
            '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            '<div class="time-slot-item" style="margin-bottom:16px;"><div class="time-slot-header" style="cursor:default;">' +
            '<div class="time-slot-info"><span class="time-slot-name">수집 시간</span>' +
            '<span class="time-slot-time"><span class="utc">' +
            esc(check.collection_window || 'KST 07:00~12:00') +
            '</span></span></div></div></div><div class="sentiment-categories">' +
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
