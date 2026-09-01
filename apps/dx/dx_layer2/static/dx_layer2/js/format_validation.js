// ==================== 형식 검증: 필드별 요약 → 상세 (null 패턴) ====================
function renderFormatFieldSummary(data, tableParam) {
    const body = getDetailBody();
    const records = data.records || data.results || [];
    const date = data.date || getSelectedDate();

    // 백엔드에서 계산한 필드별 건수 사용
    const fieldCounts = data.field_counts || {};

    modalState.formatFieldsData = data;
    modalState.selectedField = null;

    let html = '';

    if (!isInlineMode()) {
        html += `<div class="modal-toolbar">
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="fmt-modal-date" value="${date}"
                    onchange="reloadFormatData(this.value)">
            </div>
        </div>`;
    }

    const sortedFields = Object.entries(fieldCounts).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);

    if (sortedFields.length === 0) {
        html += '<p style="text-align: center; color: var(--text-secondary);">형식 오류 데이터가 없습니다.</p>';
    } else {
        html += '<div class="null-field-summary-container">';
        sortedFields.forEach(([field, count]) => {
            html += `
                <div class="null-field-card" onclick="showFormatFieldDetail('${field}')">
                    <div class="null-field-card-name">${field}</div>
                    <div class="null-field-card-count">${count}건</div>
                </div>
            `;
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

function showFormatFieldDetail(fieldName, pushStack = true) {
    const body = getDetailBody();
    const data = modalState.formatFieldsData;
    const records = data.records || data.results || [];
    const tableParam = modalState.tableParam;
    const date = data.date || getSelectedDate();
    const isTseRetail = /^tse_(tv|ref|ldy)_retail$/.test(tableParam);
    const isRetail = tableParam === 'tv_retail' || tableParam === 'hhp_retail' || isTseRetail;
    const currentDays = modalState.days || 1;

    var filteredRecords;
    if (currentDays > 1 && isRetail) {
        // days > 1: 조회 날짜에 해당 필드 오류인 item 추출 → 해당 item 전체 레코드 표시
        var targetDateStr = date;
        var errorItems = new Set();
        records.forEach(function(record) {
            var recDate = (record.crawl_datetime || '').substring(0, 10);
            if (recDate === targetDateStr && (record.error_fields || []).includes(fieldName)) {
                if (record.item) errorItems.add(record.item);
            }
        });
        if (errorItems.size > 0) {
            filteredRecords = records.filter(function(record) { return errorItems.has(record.item); });
        } else {
            filteredRecords = records.filter(function(record) { return (record.error_fields || []).includes(fieldName); });
        }
    } else {
        filteredRecords = records.filter(record => {
            return (record.error_fields || []).includes(fieldName);
        });
    }

    modalState.selectedField = fieldName;

    // 각 레코드에 위배사유 컬럼 추가
    filteredRecords.forEach(function(r) {
        var ed = r.error_details && r.error_details[fieldName];
        r._error_reason = ed ? (ed.rule + ': ' + ed.reason) : '';
    });

    // 칼럼 설정: 리테일러는 디폴트 5개 + 위배사유, 나머지는 전체 컬럼 + 위배사유
    var columnNames = data.column_names || [];
    var reasonCol = { key: '_error_reason', label: '위배사유', width: 200 };
    var columns;
    var selectCols = [];
    if (isRetail && columnNames.length > 0) {
        var defaultKeys = isTseRetail
            ? ['id', 'item', 'retailer_sku_name', 'crawl_datetime', fieldName, 'product_url']
            : ['id', 'item', 'crawl_datetime', fieldName, 'product_url'];
        var _seen = {};
        columns = [];
        defaultKeys.forEach(function(k) {
            if (_seen[k]) return;
            _seen[k] = true;
            columns.push({ key: k, label: k === 'product_url' ? 'URL' : k, width: k === 'id' ? 80 : 120 });
        });
        columns.push(reasonCol);
        selectCols = columnNames;
    } else if (columnNames.length > 0) {
        columns = columnNames.map(function(col) {
            return { key: col, label: col === 'product_url' ? 'URL' : col, width: col === 'id' ? 80 : 120 };
        });
        columns.push(reasonCol);
    } else {
        columns = [
            { key: 'id', label: 'ID', width: 80 },
            { key: 'item', label: 'Item', width: 150 },
            { key: 'crawl_datetime', label: '수집일', width: 120 },
            reasonCol
        ];
    }

    // Item 목록 HTML
    var itemQueryHtml = '';
    if (!isInlineMode()) {
        itemQueryHtml += `<div class="modal-toolbar">
            <button class="btn-back" onclick="backToFormatFieldSummary()">← 뒤로가기</button>
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="fmt-modal-date" value="${date}"
                    onchange="reloadFormatData(this.value)">
            </div>
            ${isTseRetail ? `<div class="modal-date-picker">
                <label>일수:</label>
                <input type="number" id="fmt-modal-days" value="${currentDays}" min="1" max="30"
                    style="width:58px;" onkeydown="if(event.key==='Enter')reloadFormatDays()">
                <button class="btn-detail" onclick="reloadFormatDays()">조회</button>
            </div>` : ''}
        </div>`;
        itemQueryHtml += `<h4 style="margin-bottom: 12px; font-size: 15px;">${fieldName} 형식 오류 (${filteredRecords.length}건)</h4>`;
    }

    if (filteredRecords.length === 0) {
        var emptyHtml = itemQueryHtml + '<p>해당 필드의 형식 오류 데이터가 없습니다.</p>';
        if (isInlineMode()) {
            var _de = new Date(date + 'T00:00:00');
            var _we = ['일','월','화','수','목','금','토'][_de.getDay()];
            var wrapper = `<div class="inline-detail-view">
                <div class="inline-detail-header"><div>
                    <div class="inline-detail-title">${fieldName} 형식 오류 (0건)</div>
                    <div class="inline-detail-subtitle" id="detail-subtitle">${modalState.tableName} | ${modalState.retailer}</div>
                </div><div class="inline-detail-date">${date}(${_we})</div></div>
                <div id="detail-body">${emptyHtml}</div>
            </div>`;
            if (pushStack) ViewStack.push(wrapper); else { var c = ViewStack.getContainer(); if (c) c.innerHTML = wrapper; }
        } else {
            body.innerHTML = emptyHtml;
        }
        return;
    }

    // Item/쿼리 섹션 (retail만)
    if (isRetail) {
        const items = [...new Set(filteredRecords.map(r => r.item).filter(Boolean))].sort();
        if (isTseRetail) {
            const queryColumns = ((data.query_config || {})[fieldName]) || [];
            itemQueryHtml += _buildTseNullQueryHtml(
                fieldName, data, filteredRecords, queryColumns, date, currentDays
            );
        } else if (isInlineMode() && items.length > 0) {
            itemQueryHtml += `<div class="item-toggle-section">
                <div class="item-toggle-header" onclick="var c=this.nextElementSibling;var h=c.style.display==='none';c.style.display=h?'':'none';this.querySelector('.toggle-arrow').textContent=h?'▾':'▸';">
                    <span class="toggle-arrow">▸</span> Item 목록 (${items.length}개)
                </div>
                <div class="item-toggle-content" style="display:none;">
                    <div class="item-copy-header"><span class="item-copy-title">Item 목록 (${items.length}개)</span><button class="btn-copy" onclick="event.stopPropagation();copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                    <div class="item-copy-content">${items.join(', ')}</div>
                </div>
            </div>`;
        } else if (!isInlineMode() && items.length > 0) {
            const tblName = tableParam === 'tv_retail' ? 'tv_retail_com' : 'hhp_retail_com';
            const retailerName = modalState.retailer || '';
            const dateCol = tableParam === 'hhp_retail' ? 'crawl_strdatetime' : 'crawl_datetime';
            const inClause = items.map(item => `'${item}'`).join(', ');
            const query3Days = `SELECT id, ${dateCol}, account_name, item, ${fieldName}\nFROM ${tblName}\nWHERE account_name = '${retailerName}'\n  AND item IN (${inClause})\n  AND DATE(${dateCol}::timestamp) >= DATE('${date}') - INTERVAL '2 days'\n  AND DATE(${dateCol}::timestamp) <= DATE('${date}')\nORDER BY item, ${dateCol} ASC;`;
            itemQueryHtml += `<div class="item-query-section">
                <div class="item-list-box">
                    <div class="item-copy-header"><span class="item-copy-title">Item 목록 (${items.length}개)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                    <div class="item-copy-content">${items.join(', ')}</div>
                </div>
                <div class="query-box">
                    <div class="item-copy-header"><span class="item-copy-title">3일치 조회 쿼리 (${date} 기준)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                    <pre class="query-content">${query3Days}</pre>
                </div>
            </div>`;
        }
    }

    // 컨테이너 HTML 생성
    var containerHtml = buildDetailContainerHtml({ itemQueryHtml: itemQueryHtml });

    if (isInlineMode()) {
        var _dn = new Date(date + 'T00:00:00');
        var _wn = ['일','월','화','수','목','금','토'][_dn.getDay()];
        const fieldTitle = currentDays > 1
            ? `${fieldName} 형식 오류 항목 (${filteredRecords.length}건 / ${currentDays}일치)`
            : `${fieldName} 형식 오류 (${filteredRecords.length}건)`;
        const fieldSubtitle = `${modalState.tableName} | ${modalState.retailer}`;
        var daysInputHtml = isRetail ? `<div style="display:flex;align-items:center;gap:6px;margin-right:12px;">
            <label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>
            <input type="number" id="fmt-detail-days" value="${currentDays}" min="1" max="30"
                style="width:50px;padding:3px 6px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;font-size:12px;text-align:center;"
                onkeydown="if(event.key==='Enter')reloadFormatDays()">
            <button onclick="reloadFormatDays()" style="padding:3px 10px;font-size:12px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;background:var(--page-color,#0d9488);color:#fff;cursor:pointer;white-space:nowrap;">조회</button>
        </div>` : '';
        const wrapper = `<div class="inline-detail-view">
            <div class="inline-detail-header"><div>
                <div class="inline-detail-title">${fieldTitle}</div>
                <div class="inline-detail-subtitle" id="detail-subtitle">${fieldSubtitle}</div>
            </div><div style="display:flex;align-items:center;">${daysInputHtml}<div class="inline-detail-date">${date}(${_wn})</div></div></div>
            <div id="detail-body">${containerHtml}</div>
        </div>`;
        if (pushStack) ViewStack.push(wrapper); else { var c = ViewStack.getContainer(); if (c) c.innerHTML = wrapper; }
    } else {
        body.innerHTML = containerHtml;
    }

    // CommonTable + FilterBar + Pagination 렌더 (deep copy로 원본 데이터 보호)
    var detailRecords = JSON.parse(JSON.stringify(filteredRecords));
    renderDetailWithTable({
        config: columns,
        selectCols: selectCols,
        data: detailRecords,
        tableParam: tableParam,
        type: 'format',
        editableCols: data.editable_cols || [],
        actualTable: data.actual_table || '',
        crawlDate: date,
        normalReviews: data.normal_reviews || {}
    });
}

function backToFormatFieldSummary() {
    if (isInlineMode()) {
        ViewStack.pop();
        return;
    }
    const data = modalState.formatFieldsData;
    const tableParam = modalState.tableParam;
    renderFormatFieldSummary(data, tableParam);
}

async function reloadFormatData(date) {
    const body = getDetailBody();
    body.innerHTML = '<div class="modal-loading">데이터를 불러오는 중...</div>';

    const { tableParam, retailer, selectedField } = modalState;

    try {
        const days = modalState.days || 1;
        const response = await fetch(`/dx/layer2/api/format-detail/?table=${tableParam}&retailer=${retailer}&date=${date}&days=${days}`);
        const data = await response.json();

        modalState.formatFieldsData = data;

        const records = data.records || data.results || [];
        var subtitle = getDetailSubtitle();
        if (subtitle) subtitle.textContent = `${modalState.tableName} | ${records.length}건의 오류 데이터`;

        if (selectedField) {
            showFormatFieldDetail(selectedField, false);
        } else {
            renderFormatFieldSummary(data, tableParam);
        }
    } catch (error) {
        console.error('Error:', error);
        body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">데이터 로드 실패</div>';
    }
}

async function reloadNullData(date) {
    const body = getDetailBody();
    body.innerHTML = '<div class="modal-loading">데이터를 불러오는 중...</div>';

    const { selectedField } = modalState;

    if (selectedField) {
        // 필드 상세 화면: 해당 컬럼만 재조회
        showNullFieldDetail(selectedField, false);
    } else {
        // 요약 화면: stats API로 건수 재조회
        try {
            const response = await fetch(`/dx/layer2/api/stats/?date=${date}`);
            const statsData = await response.json();

            // dxData에서 해당 리테일러의 fields_detail 찾기
            const nullType = (statsData.validation_types || []).find(v => v.type === 'null');
            const table = (nullType?.tables || []).find(
                t => t.table === modalState.tableParam || t.table_name === modalState.tableName
            );
            const retailerData = (table?.retailers || []).find(r => r.retailer === modalState.retailer);
            const fieldCounts = retailerData?.fields_detail || {};

            modalState.nullFieldsData = { field_counts: fieldCounts, date: date };
            renderNullFieldSummary(modalState.nullFieldsData);
        } catch (error) {
            console.error('Error:', error);
            body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">데이터 로드 실패</div>';
        }
    }
}

function reloadNullDays() {
    var daysInput = document.getElementById('detail-days') || document.getElementById('null-modal-days');
    var defaultDays = typeof getDefaultNullHistoryDays === 'function'
        ? getDefaultNullHistoryDays(modalState.tableParam)
        : 1;
    var days = parseInt(daysInput && daysInput.value) || defaultDays;
    if (days < 1) days = 1;
    if (days > 30) days = 30;
    modalState.days = days;

    var date;
    var dateInput = document.getElementById('null-modal-date');
    date = dateInput ? dateInput.value : getSelectedDate();

    reloadNullData(date);
}

function reloadFormatDays() {
    var daysInput = document.getElementById('fmt-detail-days') || document.getElementById('fmt-modal-days');
    var days = parseInt(daysInput && daysInput.value) || 1;
    if (days < 1) days = 1;
    if (days > 30) days = 30;
    modalState.days = days;

    var date;
    var dateInput = document.getElementById('fmt-modal-date');
    date = dateInput ? dateInput.value : getSelectedDate();

    reloadFormatData(date);
}

function goToPage(page) {
    if (page < 1 || page > modalState.totalPages) return;
    openDetailModal(modalState.type, modalState.tableName, modalState.retailer, modalState.count, page);
}

function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = date.getHours();
    const ampm = hours < 12 ? '오전' : '오후';

    return `${year}-${month}-${day} ${ampm}`;
}

function formatDateOnly(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    return `${year}-${month}-${day}`;
}
