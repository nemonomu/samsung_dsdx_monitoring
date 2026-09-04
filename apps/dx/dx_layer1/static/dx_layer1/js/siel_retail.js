// ============================================================
// SIEL Retail Render Functions
// ============================================================

function sielNumber(value) {
    var number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
}

function renderSielRetailerRow(retailer) {
    var mainCount = sielNumber(retailer.main_count);
    var bsrCount = sielNumber(retailer.bsr_count);
    var actual = sielNumber(
        retailer.actual !== undefined ? retailer.actual : retailer.count
    );
    var batchId = retailer.batch_id || '';
    var batchHtml = batchId
        ? ' <span class="retail-batch-id" style="font-size:11px;color:#64748b;">/ ' + esc(batchId) + '</span>'
        : '';

    return '<tr>' +
        '<td class="rt-name">' + esc(retailer.retailer || '-') + batchHtml + '</td>' +
        '<td>' + mainCount.toLocaleString() + '</td>' +
        '<td>' + bsrCount.toLocaleString() + '</td>' +
        '<td class="rt-total">' + actual.toLocaleString() + '</td>' +
        '<td class="rt-status ct-nc">' + getStatusBadge(retailer.status) + '</td>' +
    '</tr>';
}

function renderSielTotalRow(retailers) {
    var totals = retailers.reduce(function(result, retailer) {
        result.main += sielNumber(retailer.main_count);
        result.bsr += sielNumber(retailer.bsr_count);
        result.actual += sielNumber(
            retailer.actual !== undefined ? retailer.actual : retailer.count
        );
        return result;
    }, { main: 0, bsr: 0, actual: 0 });

    return '<tr class="rt-sum">' +
        '<td>합계</td>' +
        '<td>' + totals.main.toLocaleString() + '</td>' +
        '<td>' + totals.bsr.toLocaleString() + '</td>' +
        '<td>' + totals.actual.toLocaleString() + '</td>' +
        '<td></td>' +
    '</tr>';
}

function renderSielCategory(cat, checkIdx, catIdx) {
    var actual = sielNumber(cat.actual !== undefined ? cat.actual : cat.total);
    var retailers = cat.retailers || [];
    var rowsHtml = retailers.length > 0
        ? retailers.map(renderSielRetailerRow).join('') + renderSielTotalRow(retailers)
        : '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);">설정된 리테일러 데이터 없음</td></tr>';

    return '<div class="sentiment-category-item">' +
        '<div class="sentiment-category-header" onclick="toggleSielCategory(this, ' + checkIdx + ', ' + catIdx + ')">' +
            '<div class="sentiment-category-info">' +
                '<span class="toggle-icon-small">▶</span>' +
                '<span class="sentiment-category-name">' + esc(cat.name || cat.category || '') + '</span>' +
            '</div>' +
            '<div class="sentiment-category-stats">' +
                '<span class="sentiment-category-count">' + actual.toLocaleString() + '건</span>' +
                getStatusBadge(cat.status) +
            '</div>' +
        '</div>' +
        '<div class="sentiment-two-column retail-single-column" id="siel-cat-' + checkIdx + '-' + catIdx + '">' +
            '<div class="sentiment-column">' +
                '<div class="retail-rank-wrap">' +
                    '<table class="ct ct-grid">' +
                        '<colgroup>' +
                            '<col style="width:28%">' +
                            '<col style="width:18%">' +
                            '<col style="width:18%">' +
                            '<col style="width:18%">' +
                            '<col style="width:18%">' +
                        '</colgroup>' +
                        '<thead><tr>' +
                            '<th style="text-align:left">리테일러</th>' +
                            '<th>MAIN</th>' +
                            '<th>BSR</th>' +
                            '<th>총 건수</th>' +
                            '<th></th>' +
                        '</tr></thead>' +
                        '<tbody>' + rowsHtml + '</tbody>' +
                    '</table>' +
                '</div>' +
            '</div>' +
        '</div>' +
    '</div>';
}

function renderSielRetailCheck(check, checkIdx) {
    var categories = check.categories || [];
    var actual = sielNumber(check.actual !== undefined ? check.actual : check.total);
    var categoriesHtml = categories.map(function(cat, catIdx) {
        return renderSielCategory(cat, checkIdx, catIdx);
    }).join('');

    return '<div class="check-item">' +
        '<div class="check-main" onclick="toggleTimeSlots(this, ' + checkIdx + ')">' +
            '<div class="check-info">' +
                '<div class="check-name"><span class="toggle-icon">▶</span>' + renderCountryFlagLabel(check.name || 'SIEL Retail') + '</div>' +
                '<div class="check-description">' + esc(check.description || '') + '</div>' +
            '</div>' +
            '<div class="check-stats">' +
                '<div class="check-stat">' +
                    '<div class="value">' + actual.toLocaleString() + '</div>' +
                    '<div class="label">총 수집량</div>' +
                '</div>' +
                getStatusBadge(check.status) +
            '</div>' +
        '</div>' +
        '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            '<div class="time-slot-item" style="margin-bottom:16px;">' +
                '<div class="time-slot-header" style="cursor:default;">' +
                    '<div class="time-slot-info">' +
                        '<span class="time-slot-name">수집 기준</span>' +
                        '<span class="time-slot-time"><span class="utc">' + esc(check.collection_window || 'KST 09:00 완료 기준') + '</span></span>' +
                    '</div>' +
                '</div>' +
            '</div>' +
            '<div class="sentiment-categories">' + categoriesHtml + '</div>' +
        '</div>' +
    '</div>';
}

function toggleSielCategory(element, checkIdx, catIdx) {
    var container = document.getElementById(
        'siel-cat-' + checkIdx + '-' + catIdx
    );
    var icon = element.querySelector('.toggle-icon-small');
    if (!container) return;
    container.classList.toggle('show');
    if (icon) icon.classList.toggle('expanded');
}

L1.renderers.siel_retail = renderSielRetailCheck;
