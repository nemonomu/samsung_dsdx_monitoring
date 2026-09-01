// ============================================================
// Retail Render Functions
// ============================================================

var SEA_RETAIL_PRODUCTS = [
    { key: 'tv', category: 'TV', retailers: ['Amazon', 'Bestbuy', 'Walmart'] },
    { key: 'ref', category: 'REF', retailers: ['Bestbuy', 'Lowes'] },
    { key: 'ldy', category: 'LDY', retailers: ['Bestbuy', 'Lowes'] }
];
var seaRetailSummaryCache = {};
var seaRetailSummaryDate = '';
var seaRetailSummaryLoadId = 0;

function getSeaRetailProduct(categoryName) {
    var key = String(categoryName || '').toLowerCase();
    for (var i = 0; i < SEA_RETAIL_PRODUCTS.length; i++) {
        if (SEA_RETAIL_PRODUCTS[i].key === key) return SEA_RETAIL_PRODUCTS[i];
    }
    return null;
}

function getRetailSummaryData(categoryName) {
    var key = String(categoryName || '').toLowerCase();
    if (seaRetailSummaryCache && seaRetailSummaryCache[key]) {
        return seaRetailSummaryCache[key];
    }
    if (typeof currentRetailSummary !== 'undefined' && currentRetailSummary) {
        return currentRetailSummary[key] || null;
    }
    return null;
}

function getRetailContractValue(summaryData, categoryData, field, legacyField) {
    if (summaryData && summaryData[field] !== undefined && summaryData[field] !== null && summaryData[field] !== '') {
        return summaryData[field];
    }
    if (categoryData && categoryData[field] !== undefined && categoryData[field] !== null && categoryData[field] !== '') {
        return categoryData[field];
    }
    if (legacyField && summaryData && summaryData[legacyField]) {
        return summaryData[legacyField];
    }
    return '';
}

function formatRetailOffset(offsetDays) {
    if (offsetDays === '' || offsetDays === null || offsetDays === undefined) return '';
    var offset = Number(offsetDays);
    if (!Number.isFinite(offset)) return '';
    if (offset === 0) return 'D';
    return offset > 0 ? 'D+' + offset : 'D' + offset;
}

function renderRetailDateContract(categoryData) {
    var summaryData = getRetailSummaryData(categoryData && categoryData.name);
    var inspectionDate = getRetailContractValue(summaryData, categoryData, 'inspection_date', 'date');
    var sourceDate = getRetailContractValue(summaryData, categoryData, 'source_date');
    var offsetDays = getRetailContractValue(summaryData, categoryData, 'offset_days');
    if (!inspectionDate && !sourceDate && offsetDays === '') return '';

    var offsetLabel = formatRetailOffset(offsetDays);
    return '<span class="retail-date-contract" style="font-size:12px;font-weight:400;color:#64748b;margin-left:10px;">' +
        '검수일 ' + esc(inspectionDate || '-') +
        ' · 데이터일 ' + esc(sourceDate || '-') +
        (offsetLabel ? ' · ' + esc(offsetLabel) : '') +
    '</span>';
}

function retailCount(value) {
    var count = Number(value || 0);
    return Number.isFinite(count) ? count : 0;
}

function hasRetailExtraRank(summaryData, categoryData, categoryName) {
    if (summaryData && typeof summaryData.has_extra_rank === 'boolean') {
        return summaryData.has_extra_rank;
    }
    if (categoryData && typeof categoryData.has_extra_rank === 'boolean') {
        return categoryData.has_extra_rank;
    }
    if (summaryData && summaryData.extra_rank_name) return true;
    var product = getSeaRetailProduct(categoryData && categoryData.name || categoryName);
    return product ? product.key === 'tv' : true;
}

function renderRetailCategory(cat, checkIdx, catIdx) {
    const catStatusClass = getStatusClass(cat.status);
    const hasTimeSlots = cat.time_slots && cat.time_slots.length > 0;

    // Retail은 기준일 전체를 단일 일일 슬롯으로 표시
    let timeSlotsHtml = '';
    if (hasTimeSlots) {
        const slotClass = cat.time_slots.length > 1 ? 'sentiment-two-column' : 'sentiment-two-column retail-single-column';
        timeSlotsHtml = '<div class="' + slotClass + '" id="retail-cat-' + checkIdx + '-' + catIdx + '">' +
            cat.time_slots.map((slot, slotIdx) => renderRetailSlotCard(slot, checkIdx, catIdx, slotIdx, cat.name, cat)).join('') +
        '</div>';
    }

    return '<div class="sentiment-category-item">' +
        '<div class="sentiment-category-header" onclick="toggleRetailCategory(this, ' + checkIdx + ', ' + catIdx + ')">' +
            '<div class="sentiment-category-info">' +
                '<span class="toggle-icon-small">▶</span>' +
                '<span class="sentiment-category-name">' + esc(cat.name) + '</span>' +
                renderRetailDateContract(cat) +
            '</div>' +
            '<div class="sentiment-category-stats">' +
                '<span class="sentiment-category-count">' + retailCount(cat.total).toLocaleString() + '</span>' +
                getStatusBadge(cat.status) +
            '</div>' +
        '</div>' +
        timeSlotsHtml +
    '</div>';
}

// 일일 슬롯별 NULL 컬럼 목록 조회 (categoryName: 'TV', slotName: '일일')
// 반환: [{retailer, columns}] 또는 빈 배열
function getSlotNullColumns(categoryName, slotName) {
    var key = categoryName.toLowerCase();
    var summaryData = getRetailSummaryData(categoryName);
    var data = summaryData && summaryData.null_columns;
    if (!data && typeof currentNullData !== 'undefined' && currentNullData) {
        data = currentNullData[key];
    }
    if (!data) return [];
    var result = [];
    for (var i = 0; i < data.length; i++) {
        var timeSlots = data[i].time_slots || [];
        for (var j = 0; j < timeSlots.length; j++) {
            var ts = timeSlots[j];
            if (ts.time_slot === slotName && ts.null_columns && ts.null_columns.length > 0) {
                result.push({ retailer: data[i].retailer, columns: ts.null_columns.join(', ') });
            }
        }
    }
    return result;
}
function getRetailItemCount(retailer, names) {
    var items = retailer.items || [];
    for (var i = 0; i < items.length; i++) {
        for (var j = 0; j < names.length; j++) {
            if (items[i].name === names[j]) {
                return items[i].count || 0;
            }
        }
    }
    return 0;
}

function renderRetailRankRow(categoryName, period, retailerName, row, status, showExtra, retailerBatchId) {
    if (showExtra === undefined) showExtra = true;
    var batchId = row.batch_id || retailerBatchId || '';
    var batchHtml = batchId
        ? ' <span class="retail-batch-id" style="font-size:11px;color:#64748b;">/ ' + esc(batchId) + '</span>'
        : '';
    var detailUrl = '/dx/layer1/retail/?category=' + encodeURIComponent(categoryName) +
        '&retailer=' + encodeURIComponent(retailerName) +
        '&period=' + encodeURIComponent(period) +
        '&date=' + encodeURIComponent(getSelectedDate());
    return '<tr>' +
        '<td class="rt-name"><a href="' + detailUrl + '">' + esc(retailerName) + '</a>' + batchHtml + '</td>' +
        '<td>' + retailCount(row.main).toLocaleString() + '</td>' +
        '<td>' + retailCount(row.bsr).toLocaleString() + '</td>' +
        (showExtra ? '<td class="rt-extra">' + retailCount(row.extra).toLocaleString() + '</td>' : '') +
        '<td class="rt-total">' + retailCount(row.total).toLocaleString() + '</td>' +
        '<td class="rt-status ct-nc">' + getStatusBadge(status) + '</td>' +
    '</tr>';
}

// Retail 일일 슬롯 테이블 렌더링
function renderRetailSlotCard(slot, checkIdx, catIdx, slotIdx, categoryName, categoryData) {
    var period = slot.name;

    // retail-summary API에서 rank별 건수 가져오기
    var summaryData = getRetailSummaryData(categoryName);
    var showExtra = hasRetailExtraRank(summaryData, categoryData, categoryName);
    var extraName = (summaryData && summaryData.extra_rank_name) ||
        (categoryData && categoryData.extra_rank_name) || 'Extra';
    var slotIdx2 = slotIdx;

    // 리테일러별 status 매핑 (slot.retailers에서 가져옴)
    var statusMap = {};
    var slotRetailerSet = {};
    if (slot.retailers) {
        slot.retailers.forEach(function(r) {
            var retailerKey = String(r.retailer || '').toLowerCase();
            statusMap[retailerKey] = r.status;
            slotRetailerSet[retailerKey] = true;
        });
    }

    // 테이블 행 생성
    var rowsHtml = '';
    var totals = { main: 0, bsr: 0, extra: 0, total: 0 };
    var renderedRows = 0;

    if (summaryData && summaryData.summary) {
        summaryData.summary.forEach(function(ret) {
            if (!ret || !ret.retailer) return;
            // 해당 슬롯에 속하는 리테일러만 표시
            if (Object.keys(slotRetailerSet).length > 0 && !slotRetailerSet[ret.retailer.toLowerCase()]) return;
            var row = null;
            var summaryRows = ret.rows || [];
            for (var rowIdx = 0; rowIdx < summaryRows.length; rowIdx++) {
                if (summaryRows[rowIdx].time_slot === period) {
                    row = summaryRows[rowIdx];
                    break;
                }
            }
            if (!row) row = summaryRows[slotIdx2];
            if (!row) return;
            totals.main += retailCount(row.main);
            totals.bsr += retailCount(row.bsr);
            if (showExtra) totals.extra += retailCount(row.extra);
            totals.total += retailCount(row.total);
            var retailerKey = String(ret.retailer).toLowerCase();
            var rStatus = statusMap[retailerKey] || 'PENDING';
            rowsHtml += renderRetailRankRow(
                categoryName, period, ret.retailer, row, rStatus,
                showExtra, ret.batch_id
            );
            renderedRows += 1;
        });
    }

    if (renderedRows === 0 && slot.retailers && slot.retailers.length > 0) {
        slot.retailers.forEach(function(ret) {
            if (!ret || !ret.retailer) return;
            var row = {
                main: getRetailItemCount(ret, ['Main Rank']),
                bsr: getRetailItemCount(ret, ['BSR Rank']),
                extra: getRetailItemCount(ret, ['Promotion Position', 'Trend Rank']),
                total: ret.count || 0,
                batch_id: ret.batch_id || ''
            };
            totals.main += retailCount(row.main);
            totals.bsr += retailCount(row.bsr);
            if (showExtra) totals.extra += retailCount(row.extra);
            totals.total += retailCount(row.total);
            rowsHtml += renderRetailRankRow(
                categoryName, period, ret.retailer, row,
                ret.status || 'PENDING', showExtra, ret.batch_id
            );
            renderedRows += 1;
        });
    }

    // 합계 행
    var totalRowHtml = '<tr class="rt-sum">' +
        '<td>합계</td>' +
        '<td>' + totals.main.toLocaleString() + '</td>' +
        '<td>' + totals.bsr.toLocaleString() + '</td>' +
        (showExtra ? '<td>' + totals.extra.toLocaleString() + '</td>' : '') +
        '<td>' + totals.total.toLocaleString() + '</td>' +
        '<td></td>' +
    '</tr>';

    // NULL 컬럼
    var nullItems = getSlotNullColumns(categoryName, period);
    var nullHtml = '';
    if (nullItems.length > 0) {
        nullHtml = '<div class="null-summary">' +
            '<div class="null-summary-title">⚠ NULL 컬럼</div>' +
            '<div class="null-summary-table-wrap">' +
            '<table class="null-summary-table">' +
                '<thead><tr><th>리테일러</th><th>NULL 컬럼</th></tr></thead>' +
                '<tbody>' +
                nullItems.map(function(n) {
                    return '<tr><td>' + esc(n.retailer) + '</td><td class="null-col-cell">' + esc(n.columns) + '</td></tr>';
                }).join('') +
                '</tbody>' +
            '</table>' +
            '</div>' +
        '</div>';
    }

    return '<div class="sentiment-column">' +
        '<div class="sentiment-column-header">' +
                '<span class="sentiment-column-title">' + period + '</span>' +
            '<div class="sentiment-column-stats">' +
                '<span class="sentiment-column-count">' + retailCount(slot.total).toLocaleString() + '건</span>' +
                getStatusBadge(slot.status) +
            '</div>' +
        '</div>' +
        '<div class="retail-rank-wrap">' +
            '<table class="ct ct-grid">' +
                '<colgroup>' +
                    (showExtra
                        ? '<col style="width:22%"><col style="width:14%"><col style="width:14%"><col style="width:14%"><col style="width:14%"><col style="width:14%">'
                        : '<col style="width:28%"><col style="width:18%"><col style="width:18%"><col style="width:18%"><col style="width:18%">') +
                '</colgroup>' +
                '<thead><tr>' +
                    '<th style="text-align:left">리테일러</th>' +
                    '<th>MAIN</th>' +
                    '<th>BSR</th>' +
                    (showExtra ? '<th>' + esc(extraName) + '</th>' : '') +
                    '<th>총 건수</th>' +
                    '<th></th>' +
                '</tr></thead>' +
                '<tbody>' + rowsHtml + totalRowHtml + '</tbody>' +
            '</table>' +
            nullHtml +
        '</div>' +
    '</div>';
}

function getRetailSummaryTotal(summaryData) {
    if (summaryData && summaryData.totals && summaryData.totals.grand_total !== undefined) {
        return retailCount(summaryData.totals.grand_total);
    }
    var total = 0;
    var rows = summaryData && summaryData.summary || [];
    rows.forEach(function(retailer) {
        total += retailCount(retailer && retailer.total);
    });
    return total;
}

function buildSeaRetailFallbackCategories() {
    return SEA_RETAIL_PRODUCTS.map(function(product) {
        var summaryData = getRetailSummaryData(product.key);
        var total = getRetailSummaryTotal(summaryData);
        var summaryRetailers = summaryData && summaryData.summary || [];
        var retailers = product.retailers.map(function(retailerName) {
            var summaryRetailer = null;
            for (var i = 0; i < summaryRetailers.length; i++) {
                if (String(summaryRetailers[i].retailer || '').toLowerCase() === retailerName.toLowerCase()) {
                    summaryRetailer = summaryRetailers[i];
                    break;
                }
            }
            return {
                retailer: retailerName,
                count: retailCount(summaryRetailer && summaryRetailer.total),
                batch_id: summaryRetailer && summaryRetailer.batch_id || '',
                status: 'PENDING',
                items: []
            };
        });
        return {
            name: product.category,
            product_line: product.key,
            total: total,
            expected: 0,
            status: 'PENDING',
            inspection_date: getRetailContractValue(summaryData, null, 'inspection_date', 'date'),
            source_date: getRetailContractValue(summaryData, null, 'source_date'),
            offset_days: getRetailContractValue(summaryData, null, 'offset_days'),
            has_extra_rank: summaryData
                ? summaryData.has_extra_rank
                : product.key === 'tv',
            extra_rank_name: summaryData && summaryData.extra_rank_name ||
                (product.key === 'tv' ? 'Promotion' : ''),
            time_slots: [{
                name: '일일',
                total: total,
                expected: 0,
                status: 'PENDING',
                retailers: retailers
            }]
        };
    });
}

function renderRetailCheck(check, checkIdx) {
    const hasCategories = check.categories && check.categories.length > 0;
    const statusClass = getStatusClass(check.status);

    // Display server schedule times while the data table stays daily aggregated.
    const timeInfo = check.time_info || { am: { us: '00:00', kst: '14:00' }, pm: { us: '12:00', kst: '02:00' } };
    const isDst = timeInfo.is_dst || (timeInfo.am && timeInfo.am.is_dst) || false;
    const kstLabel = isDst ? 'KST(DST)' : 'KST';
    const amInfo = timeInfo.am || { us: getSelectedDate() + ' 00:00', kst: getSelectedDate() + ' 13:00' };
    const pmInfo = timeInfo.pm || { us: getSelectedDate() + ' 12:00', kst: getSelectedDate() + ' 01:00' };
    const amUsTime = amInfo.us ? amInfo.us.split(' ')[1] || amInfo.us : '00:00';
    const pmUsTime = pmInfo.us ? pmInfo.us.split(' ')[1] || pmInfo.us : '12:00';

    const timeHeader = '<div class="time-slot-item" style="margin-bottom: 16px;">' +
        '<div class="time-slot-header" style="cursor: default;">' +
            '<div class="time-slot-info">' +
                '<span class="time-slot-name">서버별 시간</span>' +
                '<span class="time-slot-time" style="display: flex; flex-direction: row; align-items: center; gap: 24px;">' +
                    '<span class="utc">[오전] US(NY) ' + amUsTime + ' ' + kstLabel + ' ' + amInfo.kst + '</span>' +
                    '<span class="utc">[오후] US(NY) ' + pmUsTime + ' ' + kstLabel + ' ' + pmInfo.kst + '</span>' +
                '</span>' +
            '</div>' +
        '</div>' +
    '</div>';

    var displayCategories = hasCategories ? check.categories : buildSeaRetailFallbackCategories();
    let categoriesHtml = '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
        timeHeader +
        '<div class="sentiment-categories">' +
            displayCategories.map(function(cat, catIdx) {
                return renderRetailCategory(cat, checkIdx, catIdx);
            }).join('') +
        '</div>' +
    '</div>';

    return '<div class="check-item">' +
        '<div class="check-main" onclick="toggleTimeSlots(this, ' + checkIdx + ')">' +
            '<div class="check-info">' +
                '<div class="check-name">' +
                    '<span class="toggle-icon">▶</span>' +
                    check.name +
                '</div>' +
                '<div class="check-description">' + check.description + '</div>' +
            '</div>' +
            '<div class="check-criteria">' +
                '<button class="btn-columns-info" onclick="event.stopPropagation(); openColumnsModal()">수집 항목 정보</button>' +
            '</div>' +
            '<div class="check-stats">' +
                '<div class="check-stat">' +
                    '<div class="value">' + (check.actual !== undefined ? check.actual.toLocaleString() : '-') + '</div>' +
                    '<div class="label">총 수집량</div>' +
                '</div>' +
                getStatusBadge(check.status) +
            '</div>' +
        '</div>' +
        categoriesHtml +
    '</div>';
}

function toggleRetailCategory(element, checkIdx, catIdx) {
    const container = document.getElementById('retail-cat-' + checkIdx + '-' + catIdx);
    const icon = element.querySelector('.toggle-icon-small');

    if (container) {
        container.classList.toggle('show');
        if (icon) {
            icon.classList.toggle('expanded');
        }
    }
}

// ============================================================
// Raw Data View (인라인)
// ============================================================

var rawView = new RawDataView({
    apiUrl: '/dx/layer1/retail/api/raw-data/',
    backUrl: '/dx/layer1/retail/',
    title: function(p) { return 'SEA Retail - ' + p.retailer + ' (' + p.period + ')'; },
    urlParams: ['category', 'retailer', 'period']
});


// ============================================================
// Columns Info Modal
// ============================================================
var columnsData = null;
var currentColumnsTab = 'tv';

function openColumnsModal() {
    AppModal.setTitle('columns', '수집 항목 정보');
    AppModal.setBody('columns',
        '<div class="columns-modal-tabs">' +
            '<button class="columns-tab active" onclick="switchColumnsTab(\'tv\')">TV</button>' +
        '</div>' +
        '<div class="columns-table-wrapper"><table class="columns-table" id="columnsTable"><thead id="columnsTableHead"></thead><tbody id="columnsTableBody"></tbody></table></div>'
    );
    AppModal.open('columns');

    if (!columnsData) {
        loadColumnsData();
    } else {
        renderColumnsTable();
    }
}

function closeColumnsModal() {
    AppModal.close('columns');
}

function switchColumnsTab(tab) {
    currentColumnsTab = tab;

    // 탭 버튼 활성화
    var tabs = document.querySelectorAll('.columns-tab');
    tabs.forEach(function(t) {
        t.classList.remove('active');
        if (t.textContent.toLowerCase() === tab) {
            t.classList.add('active');
        }
    });

    renderColumnsTable();
}

function loadColumnsData() {
    fetch('/dx/layer1/retail/api/columns/')
        .then(function(response) { return response.json(); })
        .then(function(data) {
            columnsData = data;
            renderColumnsTable();
        })
        .catch(function(error) {
            console.error('Error loading columns data:', error);
        });
}

function renderColumnsTable() {
    if (!columnsData) return;

    var data = columnsData[currentColumnsTab];
    var allColumns = data.all_columns;
    var columnsByRetailer = data.columns;
    var retailers = Object.keys(columnsByRetailer);

    // 헤더 렌더링
    var thead = document.getElementById('columnsTableHead');
    var headerHtml = '<tr><th>컬럼명</th>';
    retailers.forEach(function(retailer) {
        headerHtml += '<th>' + retailer + '</th>';
    });
    headerHtml += '</tr>';
    thead.innerHTML = headerHtml;

    // 바디 렌더링
    var tbody = document.getElementById('columnsTableBody');
    var bodyHtml = '';

    allColumns.forEach(function(col) {
        bodyHtml += '<tr>';
        bodyHtml += '<td>' + esc(col) + '</td>';
        retailers.forEach(function(retailer) {
            var hasColumn = columnsByRetailer[retailer].indexOf(col) !== -1;
            if (hasColumn) {
                bodyHtml += '<td class="col-check">O</td>';
            } else {
                bodyHtml += '<td class="col-empty">-</td>';
            }
        });
        bodyHtml += '</tr>';
    });

    tbody.innerHTML = bodyHtml;
}

// ============================================================
// Data Loading
// ============================================================

function syncSeaRetailSummaryGlobals(summaryCache) {
    var summaries = {};
    var nullColumns = {};
    SEA_RETAIL_PRODUCTS.forEach(function(product) {
        var summaryData = summaryCache[product.key];
        if (!summaryData) return;
        summaries[product.key] = summaryData;
        nullColumns[product.key] = summaryData.null_columns || [];
    });
    currentRetailSummary = summaries;
    currentNullData = nullColumns;
}

async function loadSeaRetailSummaries(inspectionDate) {
    var selectedInspectionDate = inspectionDate || getSelectedDate();
    var loadId = ++seaRetailSummaryLoadId;
    seaRetailSummaryDate = selectedInspectionDate;
    seaRetailSummaryCache = {};

    var results = await Promise.all(SEA_RETAIL_PRODUCTS.map(async function(product) {
        var url = '/dx/layer1/retail/api/summary/?type=' + encodeURIComponent(product.key) +
            '&date=' + encodeURIComponent(selectedInspectionDate);
        try {
            var response = await fetch(url);
            if (response.ok === false) throw new Error('HTTP ' + response.status);
            var data = await response.json();
            if (data && data.error) throw new Error(data.error);
            return { key: product.key, data: data };
        } catch (error) {
            console.error('SEA Retail ' + product.category + ' summary load failed:', error);
            return { key: product.key, data: null };
        }
    }));

    // 날짜 변경 중 먼저 시작한 응답이 최신 화면을 덮어쓰지 않도록 한다.
    if (loadId !== seaRetailSummaryLoadId) return seaRetailSummaryCache;

    var nextCache = {};
    results.forEach(function(result) {
        if (result.data) nextCache[result.key] = result.data;
    });
    seaRetailSummaryCache = nextCache;
    syncSeaRetailSummaryGlobals(nextCache);
    return nextCache;
}

async function loadSectionData() {
    if (rawView.checkUrlAndShow()) return;

    // 기존 summary view
    try {
        var selectedDate = getSelectedDate();

        try { currentCheckStatus = await loadCheckStatus(selectedDate); }
        catch (e) { currentCheckStatus = null; }

        var response = await fetch('/dx/layer1/api/stats/?date=' + selectedDate + '&check_type=retail');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        var data = await response.json();
        currentStatsData = data;

        // 선택한 검수일을 그대로 전달해 TV/REF/LDY를 각각 조회한다.
        await loadSeaRetailSummaries(selectedDate);

        var check = data.checks ? data.checks.find(function(c) { return c.check_type === 'retail'; }) : null;
        var checkIdx = check ? data.checks.indexOf(check) : 0;
        if (!check) check = { name: 'SEA Retail', description: '데이터 없음', check_type: 'retail', status: 'PENDING', categories: [] };

        var container = document.getElementById('section-content');
        var html = renderRetailCheck(check, checkIdx);
        html = html.replace('<div class="check-item">', '<div class="check-item" data-check-type="retail">');
        container.innerHTML = html;
        addCheckBadges();
        expandSectionContent();
    } catch (error) {
        console.error('Load failed:', error);
        document.getElementById('section-content').innerHTML = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터를 불러올 수 없습니다</div><div class="check-description">잠시 후 다시 시도해주세요.</div></div></div></div>';
    }
}

function loadAllData() { loadSectionData(); }

L1.initLayer1Page({ modals: [{ name: 'columns', style: 'wide' }] });

L1.renderers.retail = renderRetailCheck;
