// 크로스필드 검증 유형 목록으로 돌아가기
function backToCrossfieldSummary() {
    if (isCrossFieldInline()) {
        ViewStack.pop();
        // pop 후 규칙 카드 건수 갱신
        setTimeout(_cfUpdateRuleCardCount, 0);
        return;
    }
    if (window.crossfieldSummaryData && window.crossfieldTitle) {
        AppModal.setTitle('detail', window.crossfieldTitle + ` (${window.crossfieldSummaryData.total_anomalies}건)`);
        renderDetailModal(window.crossfieldTitle, '크로스 필드 검증', window.crossfieldSummaryData);
    }
}

function _cfBuildTseDisplayQueryBox(query, retailerSafe, days) {
    if (!query) return '';
    const queryId = `cf-tse-display-query-${retailerSafe}`;
    return `
        <div class="query-box">
            <div class="query-box-header">
                <span class="query-box-title">${days}일 수정용 조회 SQL</span>
                <button class="btn-copy" onclick="copyQueryToClipboard(document.getElementById('${queryId}'), true)">복사</button>
            </div>
            <pre id="${queryId}" class="query-content">${esc(query)}</pre>
        </div>`;
}

function showRetailerDetail(retailer) {
    const inline = isCrossFieldInline();
    const retailerData = window.crossfieldRetailerData;
    if (!retailerData || !retailerData[retailer]) {
        const message = `
            <div class="inline-detail">
                ${inline ? '<button class="btn-back" onclick="ViewStack.pop()">← 뒤로가기</button>' : ''}
                <div class="inline-detail-body">
                    <p>해당 리테일러의 상세 데이터를 찾을 수 없습니다. 다시 조회해 주세요.</p>
                </div>
            </div>`;
        if (inline) {
            ViewStack.push(message);
        } else {
            AppModal.setTitle('detail', `${retailer} - 상세 조회`);
            AppModal.setBody('detail', message);
            AppModal.open('detail');
        }
        return;
    }

    const data = retailerData[retailer];
    const rows = data.rows;
    const rSummary = (window.crossfieldRetailerSummary || {})[retailer] || {};
    const items = rSummary.items || [];
    const ids = [...new Set(rows
        .map(row => row.id)
        .filter(value => value != null && String(value) !== ''))];
    const listValues = items.length > 0 ? items : ids;
    const listLabel = items.length > 0 ? 'Item' : 'ID';

    const productLine = window.crossfieldProductLine || 'HHP';
    const date = window.crossfieldDate || new Date().toISOString().slice(0, 10);
    const tableName = window.crossfieldTableName
        || (productLine.toUpperCase() === 'HHP' ? 'hhp_retail_com' : 'tv_retail_com');
    const dateCol = window.crossfieldDateCol
        || (productLine.toUpperCase() === 'HHP' ? 'crawl_strdatetime' : 'crawl_datetime');
    const productLineDisplay = productLine.toUpperCase();
    const isTseProductLine = productLineDisplay.startsWith('TSE_');
    const ruleNameDisplay = window.crossfieldRuleName || '';
    const titleText = `${ruleNameDisplay} (${rSummary.count || 0}건)`;
    const subtitleText = `${productLineDisplay} Retail | ${retailer}`;

    const editableCols = inline ? (window.crossfieldEditableCols || new Set()) : new Set();
    const normalReviews = inline ? (window.crossfieldNormalReviews || {}) : {};

    // 동적 컬럼
    const excludeKeys = ['id', 'item', 'account_name', 'page_type'];
    const dynamicKeys = [];
    if (rows.length > 0) {
        Object.keys(rows[0]).forEach(key => {
            if (!excludeKeys.includes(key)) dynamicKeys.push(key);
        });
    }
    const urlKey = dynamicKeys.find(k => k === 'product_url');
    const otherKeys = dynamicKeys.filter(k => k !== 'product_url');

    const _wn = ['일','월','화','수','목','금','토'][new Date(date).getDay()];
    const dateDisplay = `${date}(${_wn})`;

    // Item 목록 토글 + 3일치 쿼리 (모달)
    const retailerSafe = retailer.replace(/[^a-zA-Z0-9]/g, '');
    const itemListDisplay = listValues.join(', ');
    const displayDays = window.crossfieldDays || 1;
    const tseDisplayQuery = (window.crossfieldDisplayQueries || {})[retailer]
        || window.crossfieldDisplayQuery || '';
    const tseQueryBox = isTseProductLine
        ? _cfBuildTseDisplayQueryBox(tseDisplayQuery, retailerSafe, displayDays)
        : '';
    var itemQueryHtml = '';
    if (inline) {
        // 인라인: Item 목록 토글만
        itemQueryHtml = `
            <div class="item-toggle-section">
                <div class="item-toggle-header" onclick="var c=this.nextElementSibling;c.style.display=c.style.display==='none'?'':'none';this.querySelector('.toggle-arrow').textContent=c.style.display==='none'?'▸':'▾';">
                    <span class="toggle-arrow">▸</span> ${listLabel} 목록 (${listValues.length}개)
                </div>
                <div class="item-toggle-content" style="display:none;">
                    <div class="item-copy-header">
                        <span class="item-copy-title">${listLabel} 목록 (${listValues.length}개)</span>
                        <button class="btn-copy" onclick="copyQueryToClipboard(document.getElementById('item-list-${retailerSafe}'))">복사</button>
                    </div>
                    <div id="item-list-${retailerSafe}" class="item-copy-content">${esc(itemListDisplay)}</div>
                </div>
            </div>`;
        if (tseQueryBox) {
            itemQueryHtml += `<div class="query-section">${tseQueryBox}</div>`;
        }
    } else {
        // 모달: Item 목록 + 3일치 쿼리 (원본 모달 로직)
        if (isTseProductLine) {
            const itemListBox = listValues.length > 0 ? `
                <div class="item-list-box">
                    <div class="query-box-header">
                        <span class="query-box-title">${listLabel} 목록 (${listValues.length}개)</span>
                        <button class="btn-copy" onclick="copyQueryToClipboard(this.parentElement.nextElementSibling)">복사</button>
                    </div>
                    <div id="item-list-${retailerSafe}" class="item-list-content">${esc(itemListDisplay)}</div>
                </div>` : '';
            if (tseQueryBox) {
                itemQueryHtml = `<div class="query-section">${itemListBox}${tseQueryBox}</div>`;
            }
        } else {
        const inClause = items.map(item => "'" + item + "'").join(', ');
        var dynamicCols = [];
        const selectFieldsRaw = window.crossfieldSelectFields || '';
        if (selectFieldsRaw) {
            dynamicCols = selectFieldsRaw.split('|').map(function(f) { return f.trim(); }).filter(function(f) { return f; });
        } else {
            const excludeCols = ['id', 'item', dateCol, 'account_name', 'product_url', 'page_type'];
            if (rows.length > 0) {
                Object.keys(rows[0]).forEach(function(key) {
                    if (!excludeCols.includes(key)) dynamicCols.push(key);
                });
            }
        }
        const validationType = window.crossfieldValidationType || '';
        var validationTagCol = '';
        if (validationType === 'cross_detail_mismatch') {
            validationTagCol = "\n'review' || LEAST(CAST(REPLACE(count_of_reviews, ',', '') AS INTEGER), 20)::text || ' -' AS expected_pattern,\nCASE WHEN LOWER(detailed_review_content) LIKE '%review' || LEAST(CAST(REPLACE(count_of_reviews, ',', '') AS INTEGER), 20)::text || ' -%' THEN 'OK' ELSE 'MISSING' END AS validation_tag,";
        }
        var selectCols = ['id', 'account_name', 'item', dateCol].join(', ');
        const query = `SELECT ${selectCols},${validationTagCol}\n${dynamicCols.join(', ')}, product_url\nFROM ${tableName}\nWHERE account_name = '${retailer}'\nAND item IN (${inClause})\nAND DATE(${dateCol}::timestamp) >= DATE('${date}') - INTERVAL '2 days'\nAND DATE(${dateCol}::timestamp) <= DATE('${date}')\nORDER BY item, ${dateCol};`;

        if (items.length > 0) {
            itemQueryHtml = `
                <div class="query-section">
                    <div class="item-list-box">
                        <div class="query-box-header">
                            <span class="query-box-title">Item 목록 (${items.length}개)</span>
                            <button class="btn-copy" onclick="copyQueryToClipboard(this.parentElement.nextElementSibling)">복사</button>
                        </div>
                        <div class="item-list-content">${esc(itemListDisplay)}</div>
                    </div>
                    <div class="query-box">
                        <div class="query-box-header">
                            <span class="query-box-title">3일치 조회 쿼리</span>
                            <button class="btn-copy" onclick="copyQueryToClipboard(this.parentElement.nextElementSibling)">복사</button>
                        </div>
                        <pre class="query-content">${query}</pre>
                    </div>
                </div>`;
        }
        }
    }

    // 규칙에 정의된 기본 표시 컬럼 결정
    const selectFieldsRaw = window.crossfieldSelectFields || '';
    const ruleDisplayCols = selectFieldsRaw ? selectFieldsRaw.split('|').map(f => f.trim()).filter(f => f) : [];

    // 기본 표시 컬럼: 고정 + 규칙 컬럼 (규칙 없으면 otherKeys 전체)
    const fixedKeys = [
        '_no', 'id', 'item', 'retailer_sku_name', 'page_type'
    ];
    const defaultDisplayKeys = ruleDisplayCols.length > 0 ? ruleDisplayCols : otherKeys;

    // 전체 컬럼 정의 (기본 표시 + 나머지 수집 컬럼)
    const allColumns = [
        { key: '_no', label: 'No', width: 50, fixed: true },
        { key: 'id', label: 'id', width: 80 },
        { key: 'item', label: 'item', width: 140 },
        { key: 'page_type', label: 'page_type', width: 80 }
    ];
    otherKeys.forEach(k => {
        allColumns.push({ key: k, label: k, width: 140 });
    });
    if (urlKey) {
        allColumns.push({ key: 'product_url', label: 'product_url', width: 100 });
    }

    // defaultVisibleKeys: 고정 + 규칙 표시 컬럼 + dateCol + product_url
    const defaultVisibleSet = new Set(fixedKeys.concat(defaultDisplayKeys));
    if (urlKey) defaultVisibleSet.add('product_url');
    const dateColKey = otherKeys.find(k => k === 'crawl_datetime' || k === 'crawl_strdatetime');
    if (dateColKey) defaultVisibleSet.add(dateColKey);
    const defaultVisibleKeys = allColumns.filter(c => defaultVisibleSet.has(c.key)).map(c => c.key);

    // 리테일러 전체 수집 컬럼 추가 (컬럼 선택용, 기본 비표시)
    const retailerCols = (window.crossfieldRetailerColumns || {})[retailer] || [];
    const existingKeys = {};
    allColumns.forEach(c => { existingKeys[c.key] = true; });
    retailerCols.forEach(col => {
        if (!existingKeys[col]) {
            allColumns.push({ key: col, label: col, width: 120 });
        }
    });

    // 컨테이너 HTML
    const containerHtml = `<div class="detail-view-wrapper">
        <div id="cf-detail-item-query">${itemQueryHtml}</div>
        <div id="cf-detail-filter-bar"></div>
        <div id="cf-detail-action-bar"></div>
        <div id="cf-detail-table-area"></div>
        <div id="cf-detail-pagination"></div>
    </div>`;

    const daysInputHtml = `<div style="display:flex;align-items:center;gap:6px;margin-right:12px;">
        <label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>
        <input type="number" id="cf-detail-days" value="${displayDays}" min="1" max="30"
            style="width:50px;padding:3px 6px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;font-size:12px;text-align:center;"
            onkeydown="if(event.key==='Enter')reloadCfDays()">
        <button onclick="reloadCfDays()" style="padding:3px 10px;font-size:12px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;background:var(--page-color,#0d9488);color:#fff;cursor:pointer;white-space:nowrap;">조회</button>
    </div>`;

    const wrapper = `<div class="inline-detail-view">
        <div class="inline-detail-header"><div>
            <div class="inline-detail-title">${esc(titleText)}</div>
            <div class="inline-detail-subtitle">${esc(subtitleText)}</div>
        </div><div style="display:flex;align-items:center;">${daysInputHtml}<div class="inline-detail-date">${dateDisplay}</div></div></div>
        <div id="cf-detail-body">${containerHtml}</div>
    </div>`;

    if (inline) {
        ViewStack.push(`
            <div class="inline-detail">
                <button class="btn-back" onclick="ViewStack.pop()">← 뒤로가기</button>
                ${wrapper}
            </div>
        `);
    } else {
        const modalTitle = `${ruleNameDisplay} : ${productLineDisplay} ${retailer} (${rows.length}건)`;
        window.crossfieldCurrentTitle = AppModal.getTitle('detail');
        AppModal.setTitle('detail', modalTitle);
        AppModal.setBody('detail', `
            <button class="btn-back" onclick="backToRetailerList()">← 뒤로가기</button>
            ${wrapper}
        `);
    }

    // 데이터 준비 (CommonTable 형식) - 전체 수집 컬럼 포함
    const tableRows = rows.map((row, idx) => {
        const r = { _no: idx + 1, id: row.id || '-', item: row.item || '-', page_type: row.page_type || '-' };
        otherKeys.forEach(key => {
            r[key] = row[key] !== null && row[key] !== undefined ? String(row[key]) : '-';
        });
        retailerCols.forEach(col => {
            if (!(col in r)) {
                r[col] = row[col] !== null && row[col] !== undefined ? String(row[col]) : '-';
            }
        });
        if (urlKey) {
            r['product_url'] = renderProductUrl(row[urlKey]);
        }
        r._rowId = row.id;
        r._rowDate = (row[dateCol] || '').substring(0, 10);
        return r;
    });

    // 현재 리테일러 저장 (일수 재조회용)
    window._cfCurrentRetailer = retailer;

    // 상태 저장
    window._cfDetailState = {
        _ruleId: window.crossfieldRuleId || '',
        allData: tableRows,
        filteredData: null,
        allColumns: allColumns,
        visibleKeys: defaultVisibleKeys.slice(),
        editableCols: editableCols,
        normalReviews: normalReviews,
        sortState: [],
        table: null,
        filterBar: null,
        pager: null
    };

    // FilterBar
    const filterCols = [{ value: 'id', label: 'id' }, { value: 'item', label: 'item' }];
    otherKeys.forEach(k => filterCols.push({ value: k, label: k }));

    window._cfDetailState.filterBar = new FilterBar('#cf-detail-filter-bar', {
        sticky: false,
        padding: '8px 12px',
        controls: [
            { type: 'select', key: 'filterCol', label: '항목', width: 'auto', options: filterCols },
            { type: 'input', key: 'filterVal', placeholder: '검색어 입력...', onEnter: function() { _cfApplyFilter(); } }
        ],
        onSearch: function() { _cfApplyFilter(); },
        onReset: function() { _cfClearFilter(); },
        columnSelector: {
            columns: allColumns.map(c => ({ key: c.key, label: c.label })),
            fixed: ['_no'],
            defaultVisible: defaultVisibleKeys,
            onUpdate: function(selected) {
                window._cfDetailState.visibleKeys = selected.map(c => c.key);
                _cfRebuildTable();
            }
        },
        right: [
            { type: 'button', label: '정렬 초기화', style: 'outline', size: 'fb', onClick: function() { window._cfDetailState.sortState = []; _cfRebuildTable(); } }
        ]
    }).render();

    // CommonTable + Pagination 빌드
    _cfRebuildTable();

    // 편집/정상처리 이벤트 (인라인만)
    if (inline) {
        setTimeout(function() { _cfBindEditEvents(); }, 100);
    }
}

// ---- 크로스필드 상세 CommonTable 헬퍼 ----
function _cfRebuildTable() {
    var st = window._cfDetailState;
    if (!st) return;
    var colMap = {};
    st.allColumns.forEach(c => { colMap[c.key] = c; });
    var visibleCols = st.visibleKeys.map(k => colMap[k]).filter(Boolean);
    st._visibleCols = visibleCols;

    var ctColumns = visibleCols.map(c => ({
        key: c.key,
        label: c.label,
        width: c.width,
        sortable: c.key === 'item',
        align: c.key === '_no' ? 'center' : undefined
    }));

    var el = document.getElementById('cf-detail-table-area');
    if (!el) return;
    el.innerHTML = '';

    st.table = new CommonTable('#cf-detail-table-area', {
        variant: 'detail',
        columns: ctColumns,
        vlines: true,
        section: true,
        showTotalCount: true,
        padding: '6px 12px',
        reorder: true,
        fixedColumns: ['_no'],
        multiSort: true,
        pageSize: 15,
        onPageSizeChange: function(val) {
            if (st.pager) st.pager.options.pageSize = val;
            _cfRenderPage(1);
        },
        onSort: function(sortArr) {
            st.sortState = sortArr;
            _cfSortAndRender();
        }
    }).render();

    var pageSize = 15;
    st.pager = new Pagination('#cf-detail-pagination', {
        pageSize: pageSize,
        showInfo: true,
        padding: '0',
        margin: '0',
        border: 'none',
        onPageChange: function(page) {
            _cfResetPendingEdits();
            _cfRenderPage(page);
        }
    });

    _cfSortAndRender();
}

function _cfSortAndRender() {
    var st = window._cfDetailState;
    if (!st) return;
    var dataArr = st.filteredData || st.allData;

    // 정상 처리된 행 제외
    if (st.editableCols && st.editableCols.size > 0 && st.normalReviews) {
        dataArr = dataArr.filter(function(row) {
            var rowId = row._rowId;
            if (!rowId) return true;
            var hasNormal = false;
            st.editableCols.forEach(function(col) {
                if (st.normalReviews[rowId + '_' + col]) hasNormal = true;
            });
            return !hasNormal;
        });
    }

    if (st.sortState && st.sortState.length > 0) {
        dataArr = dataArr.slice().sort(function(a, b) {
            for (var i = 0; i < st.sortState.length; i++) {
                var s = st.sortState[i];
                var va = a[s.key] || '', vb = b[s.key] || '';
                var na = parseFloat(va), nb = parseFloat(vb);
                var cmp = 0;
                if (!isNaN(na) && !isNaN(nb)) cmp = na - nb;
                else cmp = String(va).localeCompare(String(vb));
                if (cmp !== 0) return s.order === 'asc' ? cmp : -cmp;
            }
            return 0;
        });
    }
    st._sortedData = dataArr;
    _cfRenderPage(1);

    // 헤더 타이틀 건수 갱신
    var titleEl = document.querySelector('.inline-detail-title');
    if (titleEl) {
        titleEl.textContent = titleEl.textContent.replace(/\(\d+건\)/, '(' + dataArr.length + '건)');
    }
}

function _cfRenderPage(page) {
    var st = window._cfDetailState;
    if (!st || !st.table) return;
    var dataArr = st._sortedData || st.allData;
    var pageSize = (st.table && st.table.getPageSize) ? st.table.getPageSize() : 15;
    if (st.pager) st.pager.options.pageSize = pageSize;
    var start = (page - 1) * pageSize;
    var pageData = dataArr.slice(start, start + pageSize);
    pageData.forEach(function(r, i) { r._no = start + i + 1; });

    var visibleCols = st._visibleCols || st.allColumns;

    // item 기준 rowspan 계산: 첫 행 = span 수, 나머지 행 = 0 (td 생략)
    var itemSpanMap = {};
    var hasItemCol = visibleCols.some(function(c) { return c.key === 'item'; });
    if (hasItemCol) {
        var si = 0;
        while (si < pageData.length) {
            var itemVal = pageData[si].item || '-';
            var spanCount = 1;
            for (var sj = si + 1; sj < pageData.length; sj++) {
                if ((pageData[sj].item || '-') === itemVal) spanCount++;
                else break;
            }
            itemSpanMap[si] = spanCount;
            for (var sk = si + 1; sk < si + spanCount; sk++) {
                itemSpanMap[sk] = 0; // 병합된 행 → td 생략
            }
            si += spanCount;
        }
    }

    // renderBody로 tr을 직접 생성 (td에 data-editable, cell-normal 등 속성 부여)
    var targetDate = window.crossfieldDate || '';
    var _cfPageIdx = 0;
    st.table.renderBody(pageData, function(row) {
        var rowIdx = _cfPageIdx++;
        var tr = '<tr>';
        var rowId = row._rowId;
        var isTargetDate = row._rowDate === targetDate;
        visibleCols.forEach(function(c) {
            // item 컬럼 rowspan 처리
            if (c.key === 'item' && hasItemCol) {
                var span = itemSpanMap[rowIdx];
                if (span === 0) return; // 병합된 하위 행 → td 생략
                tr += '<td' + (span > 1 ? ' rowspan="' + span + '"' : '') + ' style="vertical-align:middle;">' + esc(row.item || '-') + '</td>';
                return;
            }

            var val = row[c.key];
            var displayVal = val !== null && val !== undefined ? String(val) : '-';

            if (c.key === '_no') {
                tr += '<td style="text-align:center;">' + displayVal + '</td>';
                return;
            }
            if (c.key === 'product_url') {
                tr += '<td>' + displayVal + '</td>';
                return;
            }

            var nrKey = rowId + '_' + c.key;
            if (isTargetDate && st.normalReviews[nrKey]) {
                var nr = st.normalReviews[nrKey];
                var tip = '정상 처리됨';
                if (nr.reason) tip += ' | 사유: ' + nr.reason;
                if (nr.memo) tip += ' | 메모: ' + nr.memo;
                tr += '<td class="cell-normal" data-row-id="' + rowId + '" data-col="' + esc(c.key) + '" data-normal-key="' + nrKey + '" title="' + esc(tip) + '">' + esc(displayVal) + '<span class="normal-badge">정상</span></td>';
            } else if (isTargetDate && st.editableCols.has(c.key) && rowId) {
                var isCorrected = row._corrected && row._corrected[c.key];
                if (isCorrected) {
                    tr += '<td class="cell-corrected" data-row-id="' + rowId + '" data-col="' + esc(c.key) + '" title="수정 완료">' + esc(displayVal) + '<span class="corrected-badge">수정됨</span></td>';
                } else {
                    tr += '<td data-editable="true" data-row-id="' + rowId + '" data-col="' + esc(c.key) + '">' + esc(displayVal) + '</td>';
                }
            } else if (isTargetDate && rowId) {
                tr += '<td data-row-id="' + rowId + '" data-col="' + esc(c.key) + '">' + esc(displayVal) + '</td>';
            } else {
                tr += '<td>' + esc(displayVal) + '</td>';
            }
        });
        tr += '</tr>';
        return tr;
    });

    // 페이지네이션 UI 갱신
    if (st.pager) st.pager.render(dataArr.length, page);

    // 총 건수 덮어쓰기
    var countEl = document.querySelector('#cf-detail-table-area .ct-count');
    if (countEl) {
        var suffix = st.filteredData ? ' (필터 적용)' : '';
        countEl.innerHTML = '총 <strong>' + dataArr.length.toLocaleString() + '</strong>건' + suffix;
    }

    // 편집 이벤트 재바인딩
    if (st.editableCols && st.editableCols.size > 0) {
        setTimeout(function() { _cfBindEditEvents(); }, 50);
    }
}

function _cfApplyFilter() {
    var st = window._cfDetailState;
    if (!st || !st.filterBar) return;
    var vals = st.filterBar.getValues();
    var col = vals.filterCol;
    var keyword = (vals.filterVal || '').trim().toLowerCase();
    if (!keyword) { _cfClearFilter(); return; }
    st.filteredData = st.allData.filter(function(r) {
        return String(r[col] || '').toLowerCase().includes(keyword);
    });
    _cfSortAndRender();
}

function _cfClearFilter() {
    var st = window._cfDetailState;
    if (!st) return;
    st.filteredData = null;
    if (st.filterBar) st.filterBar.reset();
    _cfSortAndRender();
}


// 일수 변경하여 크로스필드 상세 재조회
async function reloadCfDays() {
    var daysInput = document.getElementById('cf-detail-days');
    var days = daysInput ? parseInt(daysInput.value) || 1 : 1;
    if (days < 1) days = 1;
    if (days > 30) days = 30;

    var productLine = (window.crossfieldProductLine || 'tv').toLowerCase();
    var date = window.crossfieldDate || '';
    var ruleId = window._cfDetailState?._ruleId || '';
    var currentRetailer = window._cfCurrentRetailer || '';

    if (!ruleId || !date) return;

    // 로딩 표시
    var tableArea = document.getElementById('cf-detail-table-area');
    if (tableArea) tableArea.innerHTML = '<p style="text-align:center;padding:20px;">데이터를 불러오는 중...</p>';

    try {
        var data = await fetchAPI(`/layer3/api/cross-field-detail/?date=${date}&type=${productLine}&rule_id=${ruleId}&days=${days}`);
        if (data.error) {
            if (tableArea) tableArea.innerHTML = '<p style="color:red;">오류: ' + esc(data.error) + '</p>';
            return;
        }

        // 데이터 갱신
        var anomalies = data.anomalies || [];
        var retailerData = {};
        anomalies.forEach(function(row) {
            var retailer = row.account_name || 'Unknown';
            if (!retailerData[retailer]) retailerData[retailer] = { items: [], rows: [] };
            retailerData[retailer].rows.push(row);
            if (row.item && !retailerData[retailer].items.includes(row.item)) {
                retailerData[retailer].items.push(row.item);
            }
        });

        window.crossfieldRetailerData = retailerData;
        window.crossfieldRetailerSummary = data.retailer_summary || {};
        window.crossfieldAnomalies = anomalies;
        window.crossfieldEditableCols = new Set(data.editable_columns || []);
        window.crossfieldNormalReviews = data.normal_reviews || {};
        window.crossfieldRetailerColumns = data.retailer_columns || {};
        window.crossfieldDisplayQuery = data.query || '';
        window.crossfieldDisplayQueries = data.queries || {};
        window.crossfieldDays = data.days || days;
        window.crossfieldPendingEdits = {};

        // 현재 리테일러 데이터 갱신
        if (currentRetailer && retailerData[currentRetailer]) {
            var rows = retailerData[currentRetailer].rows;
            var items = retailerData[currentRetailer].items;
            var ids = [...new Set(rows
                .map(function(row) { return row.id; })
                .filter(function(value) {
                    return value != null && String(value) !== '';
                }))];
            var listValues = items.length > 0 ? items : ids;
            var listLabel = items.length > 0 ? 'Item' : 'ID';
            var editableCols = window.crossfieldEditableCols;
            var normalReviews = window.crossfieldNormalReviews;

            // 동적 컬럼
            var excludeKeys = ['id', 'item', 'account_name', 'page_type'];
            var dynamicKeys = [];
            if (rows.length > 0) {
                Object.keys(rows[0]).forEach(function(key) {
                    if (!excludeKeys.includes(key)) dynamicKeys.push(key);
                });
            }
            var urlKey = dynamicKeys.find(function(k) { return k === 'product_url'; });
            var otherKeys = dynamicKeys.filter(function(k) { return k !== 'product_url'; });

            var tableRows = rows.map(function(row, idx) {
                var r = { _no: idx + 1, id: row.id || '-', item: row.item || '-', page_type: row.page_type || '-' };
                otherKeys.forEach(function(key) {
                    r[key] = row[key] !== null && row[key] !== undefined ? String(row[key]) : '-';
                });
                if (urlKey) {
                    r['product_url'] = renderProductUrl(row[urlKey]);
                }
                r._rowId = row.id;
                var dateCol = window.crossfieldDateCol
                    || ((window.crossfieldProductLine || 'tv').toUpperCase() === 'HHP' ? 'crawl_strdatetime' : 'crawl_datetime');
                r._rowDate = (row[dateCol] || '').substring(0, 10);
                return r;
            });

            var st = window._cfDetailState;
            if (st) {
                st.allData = tableRows;
                st.filteredData = null;
                st.editableCols = editableCols;
                st.normalReviews = normalReviews;
                st.sortState = [];

                // 컬럼 갱신: 추가된 수집 컬럼 반영
                var existKeys = {};
                st.allColumns.forEach(function(c) { existKeys[c.key] = true; });
                otherKeys.forEach(function(k) {
                    if (!existKeys[k]) {
                        st.allColumns.splice(st.allColumns.length - (urlKey ? 1 : 0), 0, { key: k, label: k, width: 120 });
                        existKeys[k] = true;
                    }
                });

                // 타이틀 업데이트
                var titleEl = document.querySelector('.inline-detail-title');
                var daysLabel = days > 1 ? ' / ' + days + '일치' : '';
                var ruleNameDisplay = window.crossfieldRuleName || '';
                if (titleEl) titleEl.textContent = ruleNameDisplay + ' (' + rows.length + '건' + daysLabel + ')';
                if (!isCrossFieldInline()) {
                    var productLineDisplay = (
                        window.crossfieldProductLine || ''
                    ).toUpperCase();
                    AppModal.setTitle(
                        'detail',
                        ruleNameDisplay + ' : ' + productLineDisplay + ' '
                        + currentRetailer + ' (' + rows.length + '건'
                        + daysLabel + ')'
                    );
                }

                // 아이템 목록 갱신
                var retailerSafe = currentRetailer.replace(/[^a-zA-Z0-9]/g, '');
                var itemListEl = document.getElementById('item-list-' + retailerSafe);
                if (itemListEl) {
                    itemListEl.textContent = listValues.join(', ');
                    var itemTitle = itemListEl.previousElementSibling
                        ? itemListEl.previousElementSibling.querySelector(
                            '.item-copy-title, .query-box-title'
                        )
                        : null;
                    if (itemTitle) {
                        itemTitle.textContent = listLabel + ' 목록 ('
                            + listValues.length + '개)';
                    }
                }
                var toggleHeader = document.querySelector('.item-toggle-header');
                if (toggleHeader) {
                    var arrow = toggleHeader.querySelector('.toggle-arrow');
                    var arrowText = arrow ? arrow.textContent : '▸';
                    toggleHeader.innerHTML = '<span class="toggle-arrow">'
                        + arrowText + '</span> ' + listLabel + ' 목록 ('
                        + listValues.length + '개)';
                }

                var displayQuery = (window.crossfieldDisplayQueries || {})[currentRetailer]
                    || window.crossfieldDisplayQuery || '';
                var queryEl = document.getElementById('cf-tse-display-query-' + retailerSafe);
                if (queryEl && displayQuery) {
                    queryEl.textContent = displayQuery;
                    var queryTitle = queryEl.parentElement
                        ? queryEl.parentElement.querySelector('.query-box-title')
                        : null;
                    if (queryTitle) queryTitle.textContent = days + '일치 최신 배치 조회 SQL';
                }

                _cfRebuildTable();
            }
        } else {
            if (tableArea) tableArea.innerHTML = '<p>해당 리테일러의 데이터가 없습니다.</p>';
        }
    } catch (err) {
        console.error('reloadCfDays error:', err);
        if (tableArea) tableArea.innerHTML = '<p style="color:red;">데이터 로드 실패</p>';
    }
}

// ============================================================
// 크로스필드 셀 수정 / 정상 처리
// ============================================================

function _cfBindEditEvents() {
    var container = document.querySelector('#cf-detail-table-area') || document.querySelector('.inline-detail-body') || document.querySelector('.app-modal-body');
    if (!container) return;
    var tableEl = container.querySelector('table');
    if (!tableEl) return;

    // 중복 바인딩 방지
    if (tableEl._cfEditBound) return;
    tableEl._cfEditBound = true;

    // 클릭: 셀 선택 또는 정상처리/취소 바
    tableEl.addEventListener('click', function(e) {
        var td = e.target.closest('td[data-editable]');
        var normalTd = !td ? e.target.closest('td.cell-normal') : null;
        var correctedTd = (!td && !normalTd) ? e.target.closest('td.cell-corrected') : null;
        var reviewTd = (!td && !normalTd && !correctedTd) ? e.target.closest('td[data-row-id]') : null;
        var prev = tableEl.querySelector('.cell-selected');
        if (prev) prev.classList.remove('cell-selected');
        _cfHideReviewBar();
        if (td) {
            if (td.classList.contains('cell-pending')) {
                window._cfSelectedCell = td;
                // 변경 예정 셀은 확인 바 안 띄움
            } else {
                td.classList.add('cell-selected');
                window._cfSelectedCell = td;
                _cfShowReviewBar(td, 'normal');
            }
        } else if (normalTd) {
            window._cfSelectedCell = null;
            // cell-normal은 무시 (정상처리 완료된 셀)
        } else if (correctedTd) {
            window._cfSelectedCell = null;
            // cell-corrected는 무시 (수정 완료된 셀)
        } else if (reviewTd) {
            reviewTd.classList.add('cell-selected');
            window._cfSelectedCell = null;
            _cfShowReviewBar(reviewTd, 'normal');
        } else {
            window._cfSelectedCell = null;
        }
    });

    // 테이블 외부 클릭 시 선택 해제
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#cf-detail-table-area') && !e.target.closest('#cf-review-bar')) {
            var sel = tableEl.querySelector('.cell-selected');
            if (sel) sel.classList.remove('cell-selected');
            window._cfSelectedCell = null;
            _cfHideReviewBar();
        }
    });

    // Ctrl+V 붙여넣기
    document.addEventListener('paste', function(e) {
        var td = window._cfSelectedCell;
        if (!td || !td.dataset.editable || document.querySelector('.cell-edit-overlay')) return;
        e.preventDefault();
        var pastedText = (e.clipboardData || window.clipboardData).getData('text').trim();
        _cfApplyEdit(td, pastedText);
    });

    // 더블클릭: 직접 입력 모드
    tableEl.addEventListener('dblclick', function(e) {
        var td = e.target.closest('td[data-editable]');
        if (!td || document.querySelector('.cell-edit-overlay')) return;

        e.preventDefault();
        e.stopPropagation();

        var oldText = td.textContent.trim();
        if (oldText === '-') oldText = '';

        var rect = td.getBoundingClientRect();
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'cell-edit-overlay';
        input.value = oldText;
        input.style.cssText = 'position:fixed;z-index:9999;'
            + 'left:' + rect.left + 'px;top:' + rect.top + 'px;'
            + 'width:' + rect.width + 'px;height:' + rect.height + 'px;';
        document.body.appendChild(input);
        setTimeout(function() { input.focus(); input.select(); }, 0);

        var committed = false;
        function commit() {
            if (committed) return;
            committed = true;
            var newVal = input.value.trim();
            input.remove();
            if (newVal === oldText) return;
            _cfApplyEdit(td, newVal);
        }

        input.addEventListener('keydown', function(ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
            if (ev.key === 'Escape') { committed = true; input.remove(); }
        });
        input.addEventListener('blur', commit);
    });
}

function _cfApplyEdit(td, newVal) {
    var rowId = td.dataset.rowId;
    var colName = td.dataset.col;
    var oldText = td.textContent.trim();
    if (oldText === '-') oldText = '';
    if (newVal === oldText) return;
    _cfHideReviewBar();
    td.textContent = newVal || '-';
    td.classList.add('cell-pending');
    var editKey = rowId + '_' + colName;
    var pendingEdits = window.crossfieldPendingEdits || {};
    var prev = pendingEdits[editKey];
    pendingEdits[editKey] = {
        table_name: window.crossfieldTableName,
        row_id: parseInt(rowId),
        column_name: colName,
        new_value: newVal,
        _oldValue: prev ? prev._oldValue : oldText,
        crawl_date: window.crossfieldDate || '',
        td: td
    };
    window.crossfieldPendingEdits = pendingEdits;
    _cfUpdateSaveButton();
}

function _cfUpdateSaveButton() {
    var container = document.querySelector('#cf-detail-table-area') || document.querySelector('.inline-detail-body') || document.querySelector('.app-modal-body');
    if (!container) return;
    var wrap = document.getElementById('cf-edit-actions');
    var pendingEdits = window.crossfieldPendingEdits || {};
    var count = Object.keys(pendingEdits).length;
    if (count === 0) {
        if (wrap) wrap.remove();
        return;
    }
    if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'cf-edit-actions';
        wrap.className = 'detail-edit-actions';
        var infoSpan = document.createElement('span');
        infoSpan.id = 'cf-edit-info';
        infoSpan.className = 'edit-actions-info';
        var btnGroup = document.createElement('div');
        btnGroup.style.cssText = 'display:flex;gap:8px;';
        var btnCancel = document.createElement('button');
        btnCancel.className = 'btn-cancel-edits';
        btnCancel.textContent = '취소';
        btnCancel.addEventListener('click', _cfCancelAllEdits);
        var btnSave = document.createElement('button');
        btnSave.id = 'cf-btn-save';
        btnSave.className = 'btn-save-edits';
        btnSave.addEventListener('click', _cfSaveAllEdits);
        btnGroup.appendChild(btnCancel);
        btnGroup.appendChild(btnSave);
        wrap.appendChild(infoSpan);
        wrap.appendChild(btnGroup);
        var actionBar = document.getElementById('cf-detail-action-bar');
        if (actionBar) {
            actionBar.appendChild(wrap);
        } else {
            var tableEl = container.querySelector('table');
            if (tableEl) tableEl.parentNode.insertBefore(wrap, tableEl);
        }
    }
    document.getElementById('cf-edit-info').textContent = count + '건 변경됨';
    document.getElementById('cf-btn-save').textContent = '저장';
}

function _cfResetPendingEdits() {
    window.crossfieldPendingEdits = {};
    var wrap = document.getElementById('cf-edit-actions');
    if (wrap) wrap.remove();
}

function _cfCancelAllEdits() {
    var edits = window.crossfieldPendingEdits || {};
    Object.keys(edits).forEach(function(k) {
        var edit = edits[k];
        if (edit.td) {
            edit.td.classList.remove('cell-pending');
            var origVal = edit._oldValue;
            edit.td.textContent = (origVal === null || origVal === undefined || origVal === '') ? '-' : origVal;
        }
    });
    window.crossfieldPendingEdits = {};
    _cfUpdateSaveButton();
}

function _cfSaveAllEdits() {
    var edits = window.crossfieldPendingEdits || {};
    var keys = Object.keys(edits);
    if (keys.length === 0) return;

    _cfShowMemoDialog(function(memo) {
        _cfDoSaveEdits(memo);
    });
}

function _cfDoSaveEdits(memo) {
    var edits = window.crossfieldPendingEdits || {};
    var keys = Object.keys(edits);
    if (keys.length === 0) return;

    var btn = document.getElementById('cf-btn-save');
    if (btn) { btn.disabled = true; btn.textContent = '저장 중...'; }

    var ruleId = (window._cfDetailState && window._cfDetailState._ruleId) || window.crossfieldRuleId || null;

    var requests = keys.map(function(k) {
        var edit = edits[k];
        return fetch('/dx/layer3/api/update-cell/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                table_name: edit.table_name,
                row_id: edit.row_id,
                column_name: edit.column_name,
                new_value: edit.new_value,
                crawl_date: edit.crawl_date,
                memo: memo || '',
                rule_id: ruleId
            })
        }).then(function(r) { return r.json(); }).then(function(res) {
            return { key: k, success: res.success, error: res.error };
        }).catch(function() {
            return { key: k, success: false, error: '네트워크 오류' };
        });
    });

    Promise.all(requests).then(function(results) {
        var successCount = 0;
        var failCount = 0;
        var st = window._cfDetailState;
        results.forEach(function(r) {
            var edit = edits[r.key];
            if (r.success) {
                successCount++;
                // 캐시 데이터 업데이트
                if (st && st.allData && edit) {
                    var rowId = edit.row_id;
                    var colName = edit.column_name;
                    var newVal = edit.new_value;
                    st.allData.forEach(function(row) {
                        if (row._rowId == rowId && row[colName] !== undefined) {
                            row[colName] = newVal !== null && newVal !== undefined ? String(newVal) : '-';
                            if (!row._corrected) row._corrected = {};
                            row._corrected[colName] = true;
                        }
                    });
                }
                delete edits[r.key];
            } else {
                failCount++;
            }
        });
        if (successCount > 0) showToast(successCount + '건 저장 완료', 'success');
        if (failCount > 0) showToast(failCount + '건 저장 실패', 'error');
        _cfUpdateSaveButton();

        // 캐시 업데이트 후 테이블 재렌더링
        if (successCount > 0) {
            _cfSortAndRender();
        }
    });
}

// 수정 저장용 메모 다이얼로그
function _cfShowMemoDialog(callback) {
    var overlay = document.createElement('div');
    overlay.className = 'memo-dialog-overlay';
    overlay.innerHTML = '<div class="memo-dialog">'
        + '<div class="memo-dialog-title">수정 메모</div>'
        + '<textarea class="memo-dialog-input" placeholder="수정 사유 입력 (선택사항)" rows="3"></textarea>'
        + '<div class="memo-dialog-buttons">'
        + '<button class="memo-dialog-cancel">취소</button>'
        + '<button class="memo-dialog-confirm">확인</button>'
        + '</div></div>';
    document.body.appendChild(overlay);
    setTimeout(function() { overlay.classList.add('show'); }, 10);
    var textarea = overlay.querySelector('.memo-dialog-input');
    textarea.focus();
    function closeDlg() {
        overlay.classList.remove('show');
        setTimeout(function() { overlay.remove(); }, 200);
    }
    overlay.querySelector('.memo-dialog-cancel').addEventListener('click', closeDlg);
    overlay.querySelector('.memo-dialog-confirm').addEventListener('click', function() {
        var memo = textarea.value.trim();
        closeDlg();
        callback(memo);
    });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeDlg();
    });
}

// ==================== 정상 처리 ====================
function _cfShowReviewBar(td, mode) {
    _cfHideReviewBar();
    var bar = document.createElement('div');
    bar.id = 'cf-review-bar';
    bar.className = 'null-review-bar';
    var colName = td.dataset.col || '';
    var rowId = td.dataset.rowId || '';
    var infoText = colName + ' (ID: ' + rowId + ') — 이상치';
    var info = document.createElement('span');
    info.className = 'null-review-info';
    info.textContent = infoText;
    var btn = document.createElement('button');
    btn.className = 'btn-null-normal';
    btn.textContent = '확인';
    btn.addEventListener('click', function() {
        _cfShowReviewDialog(function(reason, memo) {
            _cfSubmitReview(td, 'normal', memo, reason);
        });
    });
    bar.appendChild(info);
    bar.appendChild(btn);
    var actionBar = document.getElementById('cf-detail-action-bar');
    if (actionBar) {
        actionBar.appendChild(bar);
    } else {
        var container = document.querySelector('#cf-detail-table-area') || document.querySelector('.inline-detail-body');
        if (container) {
            var tableEl = container.querySelector('table');
            if (tableEl) tableEl.parentNode.insertBefore(bar, tableEl);
        }
    }
}

function _cfHideReviewBar() {
    var bar = document.getElementById('cf-review-bar');
    if (bar) bar.remove();
}

// 정상 처리 공통 다이얼로그 (이유 선택 필수 + 메모 선택)
// checkType: 'cross_field' | 'field_missing' 등 — review-reasons API 파라미터
function _cfShowReviewDialog(callback) {
    _showReviewDialog('cross_field', callback);
}

function _cfSubmitReview(td, status, memo, reason) {
    var rowId = td.dataset.rowId || (td.dataset.normalKey && td.dataset.normalKey.split('_')[0]);
    var colName = td.dataset.col || (td.dataset.normalKey && td.dataset.normalKey.split('_').slice(1).join('_'));
    if (!rowId || !colName) return;

    var retailerVal = window._cfCurrentRetailer || '';
    var ruleId = (window._cfDetailState && window._cfDetailState._ruleId) || window.crossfieldRuleId || null;

    fetch('/dx/layer3/api/review/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
            table_name: window.crossfieldTableName,
            record_id: parseInt(rowId),
            column_name: colName,
            status: status,
            memo: memo || '',
            reason: reason || '',
            crawl_date: window.crossfieldDate || '',
            retailer: retailerVal,
            rule_id: ruleId
        })
    }).then(function(r) { return r.json(); })
    .then(function(res) {
        if (res.success) {
            _cfHideReviewBar();
            var nrKey = rowId + '_' + colName;
            if (!window.crossfieldNormalReviews) window.crossfieldNormalReviews = {};
            window.crossfieldNormalReviews[nrKey] = { memo: memo, reason: reason, created_id: '', created_at: '' };
            showToast('확인 처리 완료', 'success');
            // 테이블 재렌더링 (정상 처리 행 제외 + 건수 갱신)
            _cfSortAndRender();
        } else {
            showToast(res.error || '처리 실패', 'error');
        }
    }).catch(function() {
        showToast('네트워크 오류', 'error');
    });
}

// 규칙 요약 카드 건수 갱신 (정상 처리 반영, 리테일러 목록→규칙 요약으로 돌아갈 때)
function _cfUpdateRuleCardCount() {
    var ruleId = window.crossfieldRuleId;
    var retailerData = window.crossfieldRetailerData;
    var normalReviews = window.crossfieldNormalReviews || {};
    var editableCols = window.crossfieldEditableCols || new Set();
    if (!ruleId || !retailerData) return;

    // 현재 규칙의 실제 활성 건수 계산
    var activeCount = 0;
    Object.keys(retailerData).forEach(function(retailer) {
        retailerData[retailer].rows.forEach(function(row) {
            var rowId = row.id;
            if (!rowId) { activeCount++; return; }
            var hasNormal = false;
            editableCols.forEach(function(col) {
                if (normalReviews[rowId + '_' + col]) hasNormal = true;
            });
            if (!hasNormal) activeCount++;
        });
    });

    // 해당 규칙 카드의 건수 갱신
    var card = document.querySelector('.rule-summary-card[data-rule-id="' + ruleId + '"]');
    if (card) {
        var countEl = card.querySelector('.rule-count');
        if (countEl) {
            countEl.textContent = activeCount + '건';
            countEl.className = 'rule-count' + (activeCount === 0 ? ' zero' : '');
        }
    }

    // 전체 타이틀 건수 갱신 (모든 규칙 카드의 건수 합산)
    var totalActive = 0;
    document.querySelectorAll('.rule-summary-card[data-rule-id] .rule-count').forEach(function(el) {
        var num = parseInt(el.textContent) || 0;
        totalActive += num;
    });
    var headerEl = document.querySelector('.rule-summary-section-header span');
    if (headerEl) {
        headerEl.textContent = headerEl.textContent.replace(/\(\d+건\)/, '(' + totalActive + '건)');
    }
}

// 리테일러 카드 + 상위 타이틀 건수 갱신 (정상 처리 반영)
function _cfUpdateRetailerCounts() {
    var retailerData = window.crossfieldRetailerData;
    var normalReviews = window.crossfieldNormalReviews || {};
    var editableCols = window.crossfieldEditableCols || new Set();
    if (!retailerData || editableCols.size === 0) return;

    var totalActive = 0;
    Object.keys(retailerData).forEach(function(retailer) {
        var rows = retailerData[retailer].rows;
        var activeCount = rows.filter(function(row) {
            var rowId = row.id;
            if (!rowId) return true;
            var hasNormal = false;
            editableCols.forEach(function(col) {
                if (normalReviews[rowId + '_' + col]) hasNormal = true;
            });
            return !hasNormal;
        }).length;
        totalActive += activeCount;

        // 리테일러 카드 건수 갱신
        var card = document.querySelector('.rule-summary-card[data-retailer="' + retailer + '"]');
        if (card) {
            var countEl = card.querySelector('.rule-count');
            if (countEl) {
                countEl.textContent = activeCount + '건';
                countEl.className = 'rule-count' + (activeCount === 0 ? ' zero' : '');
            }
        }
    });

    // 상위 타이틀 건수 갱신
    var headerEl = document.querySelector('.rule-summary-section-header span');
    if (headerEl) {
        headerEl.textContent = headerEl.textContent.replace(/\(\d+건\)/, '(' + totalActive + '건)');
    }
}

// 리테일러 목록으로 돌아가기
function backToRetailerList() {
    if (isCrossFieldInline()) {
        ViewStack.pop();
        // pop 후 리테일러 카드 건수 갱신
        setTimeout(_cfUpdateRetailerCounts, 0);
        return;
    }
    if (window.crossfieldRetailerData && window.crossfieldCurrentTitle) {
        const retailerData = window.crossfieldRetailerData;

        let html = '';
        html += `<button class="btn-back" onclick="backToCrossfieldSummary()">← 뒤로가기</button>`;

        html += '<div class="retailer-list-container">';
        Object.keys(retailerData).sort().forEach(retailer => {
            const items = retailerData[retailer].items;
            const rowCount = retailerData[retailer].rows.length;
            html += `
                <div class="retailer-card" onclick="showRetailerDetail('${escJs(retailer)}')">
                    <div class="retailer-card-name">${esc(retailer)}</div>
                    <div class="retailer-card-count">${rowCount}건 (${items.length} items)</div>
                </div>
            `;
        });
        html += '</div>';

        AppModal.setTitle('detail', window.crossfieldCurrentTitle);
        AppModal.setBody('detail', html);
    }
}

// ESC 키로 모달 닫기
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        AppModal.close('detail');
    }
});

