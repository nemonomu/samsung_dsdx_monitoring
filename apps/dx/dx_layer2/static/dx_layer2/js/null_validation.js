let modalState = {
    type: null,
    tableName: null,
    tableParam: null,
    retailer: null,
    count: 0,
    currentPage: 1,
    totalPages: 1,
    totalGroups: 0,
    nullFieldsData: null,
    selectedField: null
};
var _dupPageSize = 50;
const SEA_TSE_NULL_HISTORY_TABLES = new Set([
    'tv_retail',
    'sea_ref_retail',
    'sea_ldy_retail',
    'tse_tv_retail',
    'tse_ref_retail',
    'tse_ldy_retail'
]);

function getDefaultNullHistoryDays(tableParam) {
    return SEA_TSE_NULL_HISTORY_TABLES.has(String(tableParam || '').toLowerCase())
        ? 3
        : 1;
}

function getDefaultFormatHistoryDays(tableParam) {
    return SEA_TSE_NULL_HISTORY_TABLES.has(String(tableParam || '').toLowerCase())
        ? 3
        : 1;
}

function parseLayer2DetailResponse(response) {
    return response.json()
        .catch(function() { return {}; })
        .then(function(data) {
            if (!response.ok || data.error) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            return data;
        });
}

function _escapeTseSqlHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function _tseSqlLiteral(value) {
    return "'" + String(value == null ? '' : value).replace(/'/g, "''") + "'";
}

function _isTseSqlIdentifier(value, allowQualified) {
    const pattern = allowQualified
        ? /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$/
        : /^[A-Za-z_][A-Za-z0-9_]*$/;
    return pattern.test(String(value || ''));
}

function _tseHistoryStartDate(date, days) {
    const parsed = new Date(date + 'T00:00:00');
    parsed.setDate(parsed.getDate() - Math.max(0, days - 1));
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, '0');
    const day = String(parsed.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function _tseNextDate(date) {
    const parsed = new Date(date + 'T00:00:00');
    parsed.setDate(parsed.getDate() + 1);
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, '0');
    const day = String(parsed.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function _tseRecordItems(records) {
    return [...new Set(records
        .map(row => row.item)
        .filter(value => value != null && String(value).trim() !== '')
        .map(value => String(value)))].sort();
}

function _tseCountryScope() {
    return `(country = 'TSE'
       OR country IS NULL
       OR TRIM(CAST(country AS TEXT)) = '')`;
}

function _buildTseNullQuery(fieldName, data, records, queryColumns, date, days) {
    const tableName = data.actual_table || '';
    const retailer = data.query_retailer || '';
    if (!_isTseSqlIdentifier(tableName, true)
        || !_isTseSqlIdentifier(fieldName, false)
        || !queryColumns.length
        || queryColumns.some(col => !_isTseSqlIdentifier(col, false))) {
        return '';
    }

    const selectSql = queryColumns.map(col => `    ${col}`).join(',\n');
    const tableSql = tableName;
    const retailerSql = _tseSqlLiteral(retailer);
    const startDateSql = _tseSqlLiteral(_tseHistoryStartDate(date, days));
    const endDateSql = _tseSqlLiteral(_tseNextDate(date));
    const countryScopeSql = _tseCountryScope();
    let accountScope = `LOWER(account_name) = LOWER(${retailerSql})`;
    if (data.query_include_unassigned === true) {
        accountScope = `(${accountScope}\n       OR account_name IS NULL\n       OR TRIM(CAST(account_name AS TEXT)) = '')`;
    }

    const items = _tseRecordItems(records);
    const hasMissingItem = records.some(
        row => row.item == null || String(row.item).trim() === ''
    );
    const missingItemIds = [...new Set(records
        .filter(row => row.item == null || String(row.item).trim() === '')
        .map(row => Number(row.id))
        .filter(id => Number.isSafeInteger(id) && id > 0))];
    const recordConditions = [];
    if (items.length > 0) {
        recordConditions.push(
            `item IN (\n${items.map(item => `    ${_tseSqlLiteral(item)}`).join(',\n')}\n  )`
        );
    }
    if (hasMissingItem && missingItemIds.length > 0) {
        recordConditions.push(`id IN (${missingItemIds.join(', ')})`);
    }
    if (recordConditions.length === 0) return '';

    return `SELECT
${selectSql}
FROM ${tableSql}
WHERE ${accountScope}
  AND ${countryScopeSql}
  AND (${recordConditions.join('\n       OR ')})
  AND DATE(crawl_datetime::timestamp) >= DATE ${startDateSql}
  AND DATE(crawl_datetime::timestamp) <= DATE ${endDateSql}
ORDER BY item, crawl_datetime;`;
}

function _buildTseNullQueryHtml(fieldName, data, records, queryColumns, date, days) {
    const items = _tseRecordItems(records);
    const ids = records.map(row => row.id).filter(Boolean);
    const query = _buildTseNullQuery(
        fieldName, data, records, queryColumns, date, days
    );
    let html = '<div class="item-query-section">';
    if (items.length > 0) {
        html += `<div class="item-list-box">
            <div class="item-copy-header"><span class="item-copy-title">Item 목록 (${items.length}개)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
            <div class="item-copy-content">${_escapeTseSqlHtml(items.join(', '))}</div>
        </div>`;
    } else if (ids.length > 0) {
        html += `<div class="item-list-box">
            <div class="item-copy-header"><span class="item-copy-title">ID 목록 (${ids.length}개)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
            <div class="item-copy-content">${_escapeTseSqlHtml(ids.join(', '))}</div>
        </div>`;
    }
    if (query) {
        const label = `${days}일 수정용 조회 SQL`;
        html += `<div class="query-box">
            <div class="item-copy-header"><span class="item-copy-title">${label} (${_escapeTseSqlHtml(date)} 기준)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
            <pre class="query-content">${_escapeTseSqlHtml(query)}</pre>
        </div>`;
    }
    html += '</div>';
    return html;
}

function openDetailModal(type, tableName, retailer, count, page = 1, fieldsDetailJson = null, tableCode = null) {
    if (count === 0) { showToast('조회된 데이터가 없습니다.', 'info'); return; }

    const typeNames = { 'null': 'NULL 검증', 'format': '형식 검증', 'duplicate': '중복 검증' };
    const titleText = `${retailer} - ${typeNames[type]} 오류`;
    const subtitleText = `${tableName} | ${count}건의 오류 데이터`;

    const date = getSelectedDate();
    const tableParam = tableCode || (tableName === 'YouTube' ? 'youtube' :
                       tableName === 'YouTube Logs' ? 'youtube_logs' :
                       tableName === 'YouTube Comments' ? 'youtube_comments' :
                       tableName === 'YouTube Videos' ? 'youtube_videos' :
                       tableName === 'SEA Retail' ? 'tv_retail' :
                       tableName === 'SEA TV' ? 'tv_retail' :
                       tableName === 'SEA REF' ? 'sea_ref_retail' :
                       tableName === 'SEA LDY' ? 'sea_ldy_retail' :
                       tableName === 'TV Retail' ? 'tv_retail' :
                       tableName === 'HHP Retail' ? 'hhp_retail' :
                       tableName === 'TSE TV' ? 'tse_tv_retail' :
                       tableName === 'TSE REF' ? 'tse_ref_retail' :
                       tableName === 'TSE LDY' ? 'tse_ldy_retail' :
                       tableName === 'Market' ? 'market' :
                       tableName.toLowerCase().replace(' ', '_'));

    if (isInlineMode()) {
        // 섹션 페이지: ViewStack 인라인 교체
        var _d = new Date(date + 'T00:00:00');
        var _w = ['일','월','화','수','목','금','토'][_d.getDay()];
        var dateLabel = date + '(' + _w + ')';
        ViewStack.push(`
            <div class="inline-detail-view">
                <div class="inline-detail-header">
                    <div>
                        <div class="inline-detail-title">${titleText}</div>
                        <div class="inline-detail-subtitle" id="detail-subtitle">${subtitleText}</div>
                    </div>
                    <div style="display:flex;align-items:center;"><div class="inline-detail-date">${dateLabel}</div></div>
                </div>
                <div id="detail-body"><div class="modal-loading">데이터 로딩 중...</div></div>
            </div>
        `);
    } else {
        // 대시보드: AppModal
        AppModal.setTitle('l2-detail', titleText);
        AppModal.setBody('l2-detail', '<div id="modal-subtitle" style="font-size:13px;color:var(--text-secondary);margin:-8px 0 16px;">' + subtitleText + '</div><div id="modal-body"><div class="modal-loading">데이터 로딩 중...</div></div>');
        AppModal.open('l2-detail');
    }

    const defaultDays = type === 'null'
        ? getDefaultNullHistoryDays(tableParam)
        : type === 'format'
            ? getDefaultFormatHistoryDays(tableParam)
            : 1;
    modalState = { type, tableName, tableParam, retailer, count, currentPage: page, totalPages: 1, totalGroups: 0, nullFieldsData: null, selectedField: null, days: defaultDays };

    // NULL 검증: fieldsDetail이 있으면 API 호출 없이 바로 요약 표시
    if (type === 'null' && fieldsDetailJson) {
        const fieldCounts = typeof fieldsDetailJson === 'string' ? JSON.parse(fieldsDetailJson) : fieldsDetailJson;
        renderNullFieldSummary({ field_counts: fieldCounts, date: date });
        return;
    }

    let apiUrl;
    if (type === 'format') {
        apiUrl = `/dx/layer2/api/format-detail/?table=${tableParam}&retailer=${retailer}&date=${date}&days=${defaultDays}`;
    } else if (type === 'duplicate') {
        apiUrl = `/dx/layer2/api/anomaly-detail/?table=${tableParam}&retailer=${retailer}&date=${date}&page=${page}&page_size=${_dupPageSize}`;
    } else {
        apiUrl = `/dx/layer2/api/detail/?type=${type}&table=${tableParam}&retailer=${retailer}&date=${date}`;
    }

    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            // 중복 검증: 메타데이터가 data.results 안에 있음
            var dupResults = (type === 'duplicate' && data.results) ? data.results : null;
            if (dupResults && dupResults.total_pages) {
                modalState.totalPages = dupResults.total_pages;
                modalState.totalGroups = dupResults.total_groups;
                modalState.currentPage = dupResults.page || 1;
            } else if (data.total_pages) {
                modalState.totalPages = data.total_pages;
                modalState.totalGroups = data.total_groups;
                modalState.currentPage = data.page || 1;
            }

            var subtitle = getDetailSubtitle();
            if (subtitle) subtitle.textContent = tableName + ' | ' + (modalState.count || 0) + '건의 오류 데이터';

            if (type === 'format') {
                modalState.formatFieldsData = data;
                renderFormatFieldSummary(data, tableParam);
            } else {
                renderDetailTable(type, data, tableParam);
            }
        })
        .catch(error => {
            console.error('Detail Error:', error);
            const body = getDetailBody();
            if (body) body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">데이터 로딩 실패</div>';
        });
}

// NULL 필드별 요약 표시
function renderNullFieldSummary(data) {
    const body = getDetailBody();
    const date = data.date || getSelectedDate();

    // 백엔드에서 계산한 필드별 건수 사용
    const fieldCounts = data.field_counts || {};

    modalState.nullFieldsData = data;
    modalState.selectedField = null;

    let html = '';

    if (!isInlineMode()) {
        html += `<div class="modal-toolbar">
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="null-modal-date" value="${date}"
                    onchange="reloadNullData(this.value)">
            </div>
        </div>`;
    }

    const sortedFields = Object.entries(fieldCounts).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);

    if (sortedFields.length === 0) {
        html += '<p style="text-align: center; color: var(--text-secondary);">NULL 오류 데이터가 없습니다.</p>';
    } else {
        html += '<div class="null-field-summary-container">';
        sortedFields.forEach(([field, count]) => {
            html += `
                <div class="null-field-card" onclick="showNullFieldDetail('${field}')">
                    <div class="null-field-card-name">${field}</div>
                    <div class="null-field-card-count">${count}건</div>
                </div>
            `;
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

// NULL 필드별 상세 데이터 표시 — API 호출로 해당 컬럼만 조회
function showNullFieldDetail(fieldName, pushStack = true) {
    const body = getDetailBody();
    if (body) body.innerHTML = '<div class="modal-loading">데이터 로딩 중...</div>';

    const tableParam = modalState.tableParam;
    const date = modalState.nullFieldsData?.date || getSelectedDate();
    const days = modalState.days || 1;
    const retailer = modalState.retailer || '';

    modalState.selectedField = fieldName;

    const query = new URLSearchParams({
        table: tableParam,
        retailer: retailer,
        date: date,
        days: String(days),
        column: fieldName
    });
    const apiUrl = `/dx/layer2/api/null-detail/?${query.toString()}`;

    return fetch(apiUrl)
        .then(parseLayer2DetailResponse)
        .then(data => {
            renderNullFieldDetailView(fieldName, data, pushStack);
        })
        .catch(error => {
            console.error('Null Field Detail Error:', error);
            if (body) body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">상세 조회 실패</div>';
        });
}

// NULL 필드별 상세 데이터 렌더링 (API 응답 기반)
function renderNullFieldDetailView(fieldName, data, pushStack = true) {
    const body = getDetailBody();
    const records = data.results || [];
    const displayConfig = data.display_config || {};
    const queryConfig = data.query_config || {};
    const dateColumn = data.date_column || 'crawl_datetime';
    const tableParam = modalState.tableParam;
    const date = data.date || getSelectedDate();
    const isSeaTv = tableParam === 'tv_retail';
    const isSeaAppliance = /^sea_(ref|ldy)_retail$/.test(tableParam);
    const isSeaRetail = isSeaTv || isSeaAppliance;
    const isLegacyRetail = isSeaTv || tableParam === 'hhp_retail';
    const isSeaDMinusOneSource = isSeaRetail || tableParam === 'youtube';
    const isRetail = isLegacyRetail || isSeaRetail;
    const isTseRetail = /^tse_(tv|ref|ldy)_retail$/.test(tableParam);
    const supportsDayHistory = isLegacyRetail
        || (isSeaAppliance && data.supports_day_history === true)
        || (isTseRetail && data.supports_day_history === true);
    const defaultDays = getDefaultNullHistoryDays(tableParam);
    const currentDays = supportsDayHistory
        ? Math.min(
            30,
            Math.max(1, Number(data.history_days || modalState.days || defaultDays))
        )
        : 1;
    if (supportsDayHistory) modalState.days = currentDays;
    const sourceScope = isSeaDMinusOneSource && data.source_date
        ? ` | 검수일 ${data.inspection_date || date} · 데이터일 ${data.source_date}`
        : '';

    const fieldConfig = displayConfig[fieldName] || {};
    const selectColumns = fieldConfig.select_columns || [];
    const columnHeaders = fieldConfig.column_headers || {};
    const queryColumns = queryConfig[fieldName] || [];
    const daysInputHtml = supportsDayHistory ? `<div style="display:flex;align-items:center;gap:6px;margin-right:12px;">
        <label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>
        <input type="number" id="detail-days" value="${currentDays}" min="1" max="30"
            style="width:50px;padding:3px 6px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;font-size:12px;text-align:center;"
            onkeydown="if(event.key==='Enter')reloadNullDays()">
        <button onclick="reloadNullDays()" style="padding:3px 10px;font-size:12px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;background:var(--page-color,#0d9488);color:#fff;cursor:pointer;white-space:nowrap;">조회</button>
    </div>` : '';

    // 칼럼 설정: displayConfig가 있으면 동적 생성, 없으면 기본 config 사용
    var columns;
    if (selectColumns.length > 0) {
        columns = selectColumns.map(function(col) {
            const isRetailSourceDate = col === 'crawl_datetime'
                || col === 'crawl_strdatetime';
            return {
                key: col,
                label: isRetailSourceDate ? col : (columnHeaders[col] || col),
                width: isRetailSourceDate ? 190 : 120
            };
        });
    } else {
        columns = getColumnConfig('null', tableParam);
    }

    // Item/쿼리 HTML (대시보드 모달에서만 표시)
    var itemQueryHtml = '';
    if (!isInlineMode()) {
        itemQueryHtml += `<div class="modal-toolbar">
            <button class="btn-back" onclick="backToNullFieldSummary()">← 뒤로가기</button>
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="null-modal-date" value="${date}"
                    onchange="reloadNullData(this.value)">
            </div>
            ${(isSeaRetail || isTseRetail) ? daysInputHtml : ''}
        </div>`;
        itemQueryHtml += `<h4 style="margin-bottom: 12px; font-size: 15px;">${fieldName} NULL 오류 (${records.length}건)</h4>`;
    }

    if (records.length === 0) {
        var emptyHtml = itemQueryHtml + '<p>해당 필드의 NULL 오류 데이터가 없습니다.</p>';
        if (isInlineMode()) {
            var _de = new Date(date + 'T00:00:00');
            var _we = ['일','월','화','수','목','금','토'][_de.getDay()];
            var wrapper = `<div class="inline-detail-view">
                <div class="inline-detail-header"><div>
                    <div class="inline-detail-title">${fieldName} NULL 오류 (0건)</div>
                    <div class="inline-detail-subtitle" id="detail-subtitle">${modalState.tableName} | ${modalState.retailer}${sourceScope}</div>
                </div><div class="inline-detail-date">${date}(${_we})</div></div>
                <div id="detail-body">${emptyHtml}</div>
            </div>`;
            if (pushStack) ViewStack.push(wrapper); else { var c = ViewStack.getContainer(); if (c) c.innerHTML = wrapper; }
        } else {
            body.innerHTML = emptyHtml;
        }
        return;
    }

    // Item/쿼리 섹션 생성 (retail만)
    if (isRetail) {
        const items = [...new Set(records.map(r => r.item).filter(Boolean))].sort();
        const ids = records.map(r => r.id).filter(Boolean);

        if (isInlineMode()) {
            var listLabel = items.length > 0 ? 'Item 목록 (' + items.length + '개)' : ids.length > 0 ? 'ID 목록 (' + ids.length + '개)' : '';
            var listContent = items.length > 0 ? items.join(', ') : ids.join(', ');
            if (listLabel) {
                itemQueryHtml += `<div class="item-toggle-section">
                    <div class="item-toggle-header" onclick="var c=this.nextElementSibling;var h=c.style.display==='none';c.style.display=h?'':'none';this.querySelector('.toggle-arrow').textContent=h?'▾':'▸';">
                        <span class="toggle-arrow">▸</span> ${listLabel}
                    </div>
                    <div class="item-toggle-content" style="display:none;">
                        <div class="item-copy-header"><span class="item-copy-title">${listLabel}</span><button class="btn-copy" onclick="event.stopPropagation();copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                        <div class="item-copy-content">${listContent}</div>
                    </div>
                </div>`;
            }
        } else {
            const tblName = data.actual_table || (
                tableParam === 'tv_retail'
                    ? 'tv_retail_com' : 'hhp_retail_com'
            );
            const retailerName = modalState.retailer || '';
            const queryCols = queryColumns.length > 0 ? queryColumns.join(', ') : '*';

            if (items.length > 0) {
                const inClause = items.map(item => `'${item}'`).join(', ');
                const sourceDate = data.source_date || date;
                const batchId = String(data.batch_id || '').replace(/'/g, "''");
                const historyStartDate = _tseHistoryStartDate(
                    sourceDate, currentDays
                );
                const seaQueryCols = queryColumns.length > 0
                    ? queryColumns.map(function(column) {
                        return 'source.' + column;
                    }).join(', ')
                    : 'source.*';
                const seaApplianceHistoryQuery = currentDays > 1
                    ? `WITH latest_batches AS (\n  SELECT DISTINCT ON (LEFT(TRIM(CAST(${dateColumn} AS TEXT)), 10))\n         LEFT(TRIM(CAST(${dateColumn} AS TEXT)), 10) AS source_date,\n         batch_id\n  FROM ${tblName}\n  WHERE LEFT(TRIM(CAST(${dateColumn} AS TEXT)), 10) BETWEEN '${historyStartDate}' AND '${sourceDate}'\n    AND account_name = '${retailerName}'\n    AND UPPER(TRIM(COALESCE(page_type, ''))) = 'MAIN'\n  ORDER BY LEFT(TRIM(CAST(${dateColumn} AS TEXT)), 10), id DESC\n)\nSELECT ${seaQueryCols}\nFROM ${tblName} source\nJOIN latest_batches latest\n  ON LEFT(TRIM(CAST(source.${dateColumn} AS TEXT)), 10) = latest.source_date\n AND source.batch_id IS NOT DISTINCT FROM latest.batch_id\nWHERE source.account_name = '${retailerName}'\n  AND source.item IN (${inClause})\n  AND UPPER(TRIM(COALESCE(source.page_type, ''))) IN ('MAIN', 'BSR')\nORDER BY source.item, source.${dateColumn} ASC;`
                    : `SELECT ${queryCols}\nFROM ${tblName}\nWHERE account_name = '${retailerName}'\n  AND item IN (${inClause})\n  AND LEFT(TRIM(CAST(${dateColumn} AS TEXT)), 10) = '${sourceDate}'\n  AND batch_id = '${batchId}'\n  AND UPPER(TRIM(COALESCE(page_type, ''))) IN ('MAIN', 'BSR')\nORDER BY item, ${dateColumn} ASC;`;
                const seaTvHistoryQuery = `SELECT ${queryCols}\nFROM ${tblName}\nWHERE account_name = '${retailerName}'\n  AND item IN (${inClause})\n  AND ${dateColumn}::timestamp >= '${historyStartDate}'::timestamp\n  AND ${dateColumn}::timestamp < '${_tseNextDate(sourceDate)}'::timestamp\nORDER BY item, ${dateColumn} ASC;`;
                const seaHistoryQuery = isSeaAppliance
                    ? seaApplianceHistoryQuery
                    : seaTvHistoryQuery;
                const query3Days = isSeaRetail
                    ? seaHistoryQuery
                    : `SELECT ${queryCols}\nFROM ${tblName}\nWHERE account_name = '${retailerName}'\n  AND item IN (${inClause})\n  AND DATE(${dateColumn}::timestamp) >= DATE('${date}') - INTERVAL '2 days'\n  AND DATE(${dateColumn}::timestamp) <= DATE('${date}')\nORDER BY item, ${dateColumn} ASC;`;
                const queryLabel = isSeaRetail
                    ? `${currentDays}일치 조회 쿼리 (기준 데이터일 ${sourceDate})`
                    : `3일치 조회 쿼리 (${date} 기준)`;
                itemQueryHtml += `<div class="item-query-section">
                    <div class="item-list-box">
                        <div class="item-copy-header"><span class="item-copy-title">Item 목록 (${items.length}개)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                        <div class="item-copy-content">${items.join(', ')}</div>
                    </div>
                    <div class="query-box">
                        <div class="item-copy-header"><span class="item-copy-title">${queryLabel}</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                        <pre class="query-content">${query3Days}</pre>
                    </div>
                </div>`;
            } else if (ids.length > 0) {
                const queryById = `SELECT ${queryCols}\nFROM ${tblName}\nWHERE id IN (${ids.join(', ')});`;
                itemQueryHtml += `<div class="item-query-section">
                    <div class="item-list-box">
                        <div class="item-copy-header"><span class="item-copy-title">ID 목록 (${ids.length}개)</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                        <div class="item-copy-content">${ids.join(', ')}</div>
                    </div>
                    <div class="query-box">
                        <div class="item-copy-header"><span class="item-copy-title">ID 기반 조회 쿼리</span><button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button></div>
                        <pre class="query-content">${queryById}</pre>
                    </div>
                </div>`;
            }
        }
    }

    if (isTseRetail) {
        itemQueryHtml += _buildTseNullQueryHtml(
            fieldName, data, records, queryColumns, date, currentDays
        );
    }

    // 컨테이너 HTML 생성
    var containerHtml = buildDetailContainerHtml({ itemQueryHtml: itemQueryHtml });

    if (isInlineMode()) {
        var _dn = new Date(date + 'T00:00:00');
        var _wn = ['일','월','화','수','목','금','토'][_dn.getDay()];
        const fieldTitle = currentDays > 1
            ? `${fieldName} NULL 오류 항목 (${records.length}건 / ${currentDays}일치)`
            : `${fieldName} NULL 오류 (${records.length}건)`;
        const fieldSubtitle = `${modalState.tableName} | ${modalState.retailer}${sourceScope}`;
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

    // CommonTable + FilterBar + Pagination 렌더
    renderDetailWithTable({
        config: columns,
        data: records,
        tableParam: tableParam,
        type: 'null',
        selectCols: data.select_cols || null,
        editableCols: data.editable_cols || [],
        actualTable: data.actual_table || '',
        crawlDate: date,
        editableDate: isSeaRetail ? (data.source_date || date) : date,
        dateColumn: data.date_column || '',
        normalReviews: data.normal_reviews || {},
        enableModalColumnSelector: isTseRetail
    });
}

// 클립보드 복사 함수 (HTTPS/HTTP 모두 지원)
function copyToClipboard(element) {
    const text = element.textContent;
    const btn = element.previousElementSibling.querySelector('.btn-copy');

    function showSuccess() {
        if (btn) {
            const originalText = btn.textContent;
            btn.textContent = '복사됨!';
            btn.style.background = '#22c55e';
            setTimeout(() => {
                btn.textContent = originalText;
                btn.style.background = '';
            }, 1500);
        }
    }

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(showSuccess).catch(err => {
            console.error('복사 실패:', err);
            fallbackCopy(text, showSuccess);
        });
    } else {
        fallbackCopy(text, showSuccess);
    }
}

function fallbackCopy(text, onSuccess) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '-9999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        document.execCommand('copy');
        onSuccess();
    } catch (err) {
        console.error('복사 실패:', err);
        alert('복사에 실패했습니다.');
    }
    document.body.removeChild(textArea);
}

function backToNullFieldSummary() {
    if (isInlineMode()) {
        ViewStack.pop();
        return;
    }
    const data = modalState.nullFieldsData;
    renderNullFieldSummary(data);
}
