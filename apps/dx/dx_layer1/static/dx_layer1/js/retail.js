// ============================================================
// Retail Render Functions
// ============================================================

function renderRetailCategory(cat, checkIdx, catIdx) {
    const catStatusClass = getStatusClass(cat.status);
    const hasTimeSlots = cat.time_slots && cat.time_slots.length > 0;

    // Retail은 기준일 전체를 단일 일일 슬롯으로 표시
    let timeSlotsHtml = '';
    if (hasTimeSlots) {
        const slotClass = cat.time_slots.length > 1 ? 'sentiment-two-column' : 'sentiment-two-column retail-single-column';
        timeSlotsHtml = '<div class="' + slotClass + '" id="retail-cat-' + checkIdx + '-' + catIdx + '">' +
            cat.time_slots.map((slot, slotIdx) => renderRetailSlotCard(slot, checkIdx, catIdx, slotIdx, cat.name)).join('') +
        '</div>';
    }

    return '<div class="sentiment-category-item">' +
        '<div class="sentiment-category-header" onclick="toggleRetailCategory(this, ' + checkIdx + ', ' + catIdx + ')">' +
            '<div class="sentiment-category-info">' +
                '<span class="toggle-icon-small">▶</span>' +
                '<span class="sentiment-category-name">' + cat.name + '</span>' +
            '</div>' +
            '<div class="sentiment-category-stats">' +
                '<span class="sentiment-category-count">' + cat.total.toLocaleString() + '</span>' +
                getStatusBadge(cat.status) +
            '</div>' +
        '</div>' +
        timeSlotsHtml +
    '</div>';
}

// 일일 슬롯별 NULL 컬럼 목록 조회 (categoryName: 'TV', slotName: '일일')
// 반환: [{retailer, columns}] 또는 빈 배열
function getSlotNullColumns(categoryName, slotName) {
    if (!currentNullData) return [];
    var key = categoryName.toLowerCase();
    var data = currentNullData[key];
    if (!data) return [];
    var result = [];
    for (var i = 0; i < data.length; i++) {
        for (var j = 0; j < data[i].time_slots.length; j++) {
            var ts = data[i].time_slots[j];
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

function renderRetailRankRow(categoryName, period, retailerName, row, status) {
    return '<tr>' +
        '<td class="rt-name"><a href="/dx/layer1/retail/?category=' + encodeURIComponent(categoryName) + '&retailer=' + encodeURIComponent(retailerName) + '&period=' + encodeURIComponent(period) + '&date=' + getSelectedDate() + '">' + esc(retailerName) + '</a></td>' +
        '<td>' + row.main.toLocaleString() + '</td>' +
        '<td>' + row.bsr.toLocaleString() + '</td>' +
        '<td class="rt-extra">' + row.extra.toLocaleString() + '</td>' +
        '<td class="rt-total">' + row.total.toLocaleString() + '</td>' +
        '<td class="rt-status ct-nc">' + getStatusBadge(status) + '</td>' +
    '</tr>';
}

// Retail 일일 슬롯 테이블 렌더링
function renderRetailSlotCard(slot, checkIdx, catIdx, slotIdx, categoryName) {
    var period = slot.name;
    var key = categoryName.toLowerCase();

    // retail-summary API에서 rank별 건수 가져오기
    var summaryData = currentRetailSummary && currentRetailSummary[key];
    var extraName = (summaryData && summaryData.extra_rank_name) || 'Extra';
    var slotIdx2 = slotIdx;

    // 리테일러별 status 매핑 (slot.retailers에서 가져옴)
    var statusMap = {};
    var slotRetailerSet = {};
    if (slot.retailers) {
        slot.retailers.forEach(function(r) {
            statusMap[r.retailer] = r.status;
            slotRetailerSet[r.retailer.toLowerCase()] = true;
        });
    }

    // 테이블 행 생성
    var rowsHtml = '';
    var totals = { main: 0, bsr: 0, extra: 0, total: 0 };
    var renderedRows = 0;

    if (summaryData && summaryData.summary) {
        summaryData.summary.forEach(function(ret) {
            // 해당 슬롯에 속하는 리테일러만 표시
            if (Object.keys(slotRetailerSet).length > 0 && !slotRetailerSet[ret.retailer.toLowerCase()]) return;
            var row = ret.rows && ret.rows[slotIdx2];
            if (!row) return;
            totals.main += row.main;
            totals.bsr += row.bsr;
            totals.extra += row.extra;
            totals.total += row.total;
            var rStatus = statusMap[ret.retailer] || 'PENDING';
            rowsHtml += renderRetailRankRow(categoryName, period, ret.retailer, row, rStatus);
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
                total: ret.count || 0
            };
            totals.main += row.main;
            totals.bsr += row.bsr;
            totals.extra += row.extra;
            totals.total += row.total;
            rowsHtml += renderRetailRankRow(categoryName, period, ret.retailer, row, ret.status || 'PENDING');
            renderedRows += 1;
        });
    }

    // 합계 행
    var totalRowHtml = '<tr class="rt-sum">' +
        '<td>합계</td>' +
        '<td>' + totals.main.toLocaleString() + '</td>' +
        '<td>' + totals.bsr.toLocaleString() + '</td>' +
        '<td>' + totals.extra.toLocaleString() + '</td>' +
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
                '<span class="sentiment-column-count">' + slot.total.toLocaleString() + '건</span>' +
                getStatusBadge(slot.status) +
            '</div>' +
        '</div>' +
        '<div class="retail-rank-wrap">' +
            '<table class="ct ct-grid">' +
                '<colgroup>' +
                    '<col style="width:22%">' +
                    '<col style="width:14%">' +
                    '<col style="width:14%">' +
                    '<col style="width:14%">' +
                    '<col style="width:14%">' +
                    '<col style="width:14%">' +
                '</colgroup>' +
                '<thead><tr>' +
                    '<th style="text-align:left">리테일러</th>' +
                    '<th>MAIN</th>' +
                    '<th>BSR</th>' +
                    '<th>' + esc(extraName) + '</th>' +
                    '<th>총 건수</th>' +
                    '<th></th>' +
                '</tr></thead>' +
                '<tbody>' + rowsHtml + totalRowHtml + '</tbody>' +
            '</table>' +
            nullHtml +
        '</div>' +
    '</div>';
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

    let categoriesHtml = '';
    if (hasCategories) {
        categoriesHtml = '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            timeHeader +
            '<div class="sentiment-categories">' +
                check.categories.map((cat, catIdx) => renderRetailCategory(cat, checkIdx, catIdx)).join('') +
            '</div>' +
        '</div>';
    } else {
        var defaultCats = ['TV'];
        var defaultRets = ['Amazon', 'Bestbuy', 'Walmart'];
        categoriesHtml = '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            timeHeader +
            '<div class="sentiment-categories">' +
                defaultCats.map(function(catName) {
                    return '<div class="sentiment-category-item">' +
                        '<div class="sentiment-category-header">' +
                            '<div class="sentiment-category-info">' +
                                '<span class="toggle-icon-small">▶</span>' +
                                '<span class="sentiment-category-name">' + catName + '</span>' +
                            '</div>' +
                            '<div class="sentiment-category-stats">' +
                                '<span class="sentiment-category-count">0</span>' +
                                '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                            '</div>' +
                        '</div>' +
                        '<div class="sentiment-two-column">' +
                            ['일일'].map(function(period) {
                                return '<div class="sentiment-column pending">' +
                                    '<div class="sentiment-column-header">' +
                                        '<span class="sentiment-column-title">' + period + ' (0건)</span>' +
                                        '<div class="sentiment-column-stats">' +
                                            '<span class="sentiment-column-count">0/0</span>' +
                                            '<span class="sentiment-column-rate pending">0%</span>' +
                                            '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                                        '</div>' +
                                    '</div>' +
                                    '<div class="sentiment-retailer-list">' +
                                        defaultRets.map(function(ret) {
                                            return '<div class="sentiment-retailer-item pending">' +
                                                '<span class="sentiment-retailer-name">' + ret + '</span>' +
                                                '<div class="sentiment-retailer-stats">' +
                                                    '<span class="sentiment-retailer-count">0/0건</span>' +
                                                    '<span class="sentiment-retailer-rate pending">0%</span>' +
                                                    '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                                                '</div>' +
                                            '</div>';
                                        }).join('') +
                                    '</div>' +
                                '</div>';
                            }).join('') +
                        '</div>' +
                    '</div>';
                }).join('') +
            '</div>' +
        '</div>';
    }

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
                '<span class="criteria-item ok">정상: 200↑</span>' +
                '<span class="criteria-item critical">심각: 200↓</span>' +
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

        // Retail Summary 데이터 로딩 (TV)
        try {
            var tvSum = await fetch('/dx/layer1/retail/api/summary/?type=tv&date=' + selectedDate).then(r => r.json());
            currentRetailSummary = { tv: tvSum };
            currentNullData = { tv: tvSum.null_columns || [] };
        } catch (e) {
            currentRetailSummary = null;
            currentNullData = null;
        }

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
