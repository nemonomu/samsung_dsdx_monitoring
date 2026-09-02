function toggleFieldMissing() {
    const content = document.getElementById('field-missing-content');
    const toggle = document.getElementById('field-missing-toggle');

    if (content.classList.contains('show')) {
        content.classList.remove('show');
        toggle.textContent = '▶';
    } else {
        content.classList.add('show');
        toggle.textContent = '▼';
    }
}

const fieldMissingRetailers = {
    tv: ['Amazon', 'Bestbuy', 'Walmart'],
    sea_ref: ['Bestbuy', 'Lowes'],
    sea_ldy: ['Bestbuy', 'Lowes']
};

function fieldMissingProductLabel(productLine) {
    return { tv: 'TV', sea_ref: 'REF', sea_ldy: 'LDY' }[productLine] || String(productLine || '').toUpperCase();
}

// 현재 선택된 SEA 제품군
let currentFieldMissingPL = 'tv';

// 탭 전환
function switchFieldMissingTab(pl) {
    if (!fieldMissingRetailers[pl]) {
        pl = 'tv';
    }
    currentFieldMissingPL = pl;

    // 탭 버튼 스타일 변경
    document.querySelectorAll('.field-missing-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.pl === pl) {
            tab.classList.add('active');
        }
    });

    // 배지 ID 업데이트 및 리테일러 이름 업데이트
    const retailers = fieldMissingRetailers[pl];
    const plLabel = fieldMissingProductLabel(pl);
    document.querySelectorAll('.field-missing-retailer-card').forEach(card => {
        const retailer = card.dataset.retailer;
        const isVisible = retailers.includes(retailer);
        card.style.display = isVisible ? '' : 'none';
        if (!isVisible) return;

        const badgeEl = card.querySelector('.retailer-badge');
        if (badgeEl) badgeEl.id = `badge-${pl}-${retailer}`;

        // 리테일러 이름 업데이트 (TV_Amazon, HHP_Bestbuy 등)
        const nameEl = document.getElementById(`retailer-name-${retailer}`);
        if (nameEl) nameEl.textContent = `${plLabel}_${retailer}`;
    });

    // 데이터 로드
    loadAllRetailersMissing();
}

// 리테일러별 누락 데이터 캐시 (모달 표시용)
let retailerMissingCache = {};

// 모든 리테일러 데이터 로드
async function loadAllRetailersMissing() {
    const date = getSelectedDate();
    const retailers = fieldMissingRetailers[currentFieldMissingPL] || [];
    let totalMissing = 0;
    let totalFields = 0;

    for (const retailer of retailers) {
        try {
            const data = await fetchAPI(`/layer3/api/field-missing/?date=${date}&type=${currentFieldMissingPL}&retailer=${retailer}`);
            const inspectionDate = data.inspection_date || date;
            const sourceDate = data.source_date || data.date || date;

            const missingCount = data.summary?.total_missing_cases || 0;
            const fieldsCount = data.summary?.fields_with_issues || 0;
            totalMissing += missingCount;
            totalFields += fieldsCount;

            // 배지 업데이트
            const badgeEl = document.getElementById(`badge-${currentFieldMissingPL}-${retailer}`);
            if (badgeEl) {
                if (missingCount === 0) {
                    badgeEl.className = 'retailer-badge ok';
                    badgeEl.textContent = '정상';
                } else if (missingCount < 10) {
                    badgeEl.className = 'retailer-badge warning';
                    badgeEl.textContent = `${missingCount}건`;
                } else {
                    badgeEl.className = 'retailer-badge critical';
                    badgeEl.textContent = `${missingCount}건`;
                }
            }

            // 누락 데이터 캐시 저장 (모달용)
            const cacheKey = `${currentFieldMissingPL}-${retailer}`;
            retailerMissingCache[cacheKey] = {
                missingFields: data.missing_fields || [],
                summary: data.summary || {},
                date: inspectionDate,
                sourceDate: sourceDate,
                prevDates: data.prev_dates || []
            };

            const dateScopeEl = document.getElementById('field-missing-date-scope');
            if (dateScopeEl) {
                dateScopeEl.textContent = `검수일 ${inspectionDate} · 데이터일 ${sourceDate} · D-1`;
            }
        } catch (error) {
            console.error(`Error loading ${retailer}:`, error);
            const badgeEl = document.getElementById(`badge-${currentFieldMissingPL}-${retailer}`);
            if (badgeEl) {
                badgeEl.className = 'retailer-badge';
                badgeEl.textContent = '-';
            }
        }
    }

    // 헤더 요약 업데이트 (대시보드에만 존재)
    const elTotal = document.getElementById('field-missing-total');
    const elFields = document.getElementById('field-missing-fields');
    if (elTotal) elTotal.textContent = totalMissing.toLocaleString();
    if (elFields) elFields.textContent = totalFields;

    const statusBadge = document.getElementById('field-missing-status');
    if (statusBadge) {
        if (totalMissing === 0) {
            statusBadge.className = 'status-badge ok';
            statusBadge.textContent = 'OK';
        } else if (totalMissing < 10) {
            statusBadge.className = 'status-badge warning';
            statusBadge.textContent = 'WARNING';
        } else {
            statusBadge.className = 'status-badge critical';
            statusBadge.textContent = 'CRITICAL';
        }
    }
}

// 누락분 요약 상태 관리
let missingSummaryState = {
    retailer: '',
    productLine: '',
    date: ''
};

// 누락분 요약 버튼 (인라인 또는 모달)
function viewMissingSummary(retailer, dateOverride = null) {
    missingSummaryState.retailer = retailer;
    missingSummaryState.productLine = currentFieldMissingPL;
    missingSummaryState.date = dateOverride || getSelectedDate();

    // 누락필드 섹션이면 인라인
    if (window.LAYER3 && window.LAYER3.section === 'field_missing') {
        viewMissingSummaryInline(retailer, missingSummaryState.date);
        return;
    }

    AppModal.setTitle('detail', `${fieldMissingProductLabel(currentFieldMissingPL)} - ${retailer} 필드별 누락 요약`);
    AppModal.open('detail');

    // 날짜가 변경된 경우 API 재호출
    if (dateOverride) {
        loadMissingSummaryData(retailer, dateOverride);
    } else {
        renderMissingSummaryFromCache(retailer);
    }
}

// 캐시에서 요약 렌더링
function renderMissingSummaryFromCache(retailer) {
    const cacheKey = `${currentFieldMissingPL}-${retailer}`;
    const cached = retailerMissingCache[cacheKey];

    if (!cached) {
        AppModal.setBody('detail', '<p style="text-align: center; padding: 40px;">데이터를 먼저 로드해주세요.</p>');
        return;
    }

    renderMissingSummary(
        cached.missingFields, cached.summary, cached.date,
        cached.prevDates, retailer, cached.sourceDate
    );
}

// API로 요약 데이터 로드
async function loadMissingSummaryData(retailer, date) {
    AppModal.setBody('detail', '<p style="text-align: center; padding: 40px;">데이터를 불러오는 중...</p>');

    try {
        const data = await fetchAPI(`/layer3/api/field-missing/?date=${date}&type=${currentFieldMissingPL}&retailer=${retailer}`);

        const missingFields = data.missing_fields || [];
        const summary = data.summary || {};
        const prevDates = data.prev_dates || [];

        renderMissingSummary(
            missingFields, summary, data.inspection_date || date,
            prevDates, retailer, data.source_date || data.date || date
        );
    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p style="text-align: center; padding: 40px;">데이터 로드 실패</p>');
    }
}

// 요약 화면 렌더링
function renderMissingSummary(missingFields, summary, date, prevDates, retailer, sourceDate) {
    const periodStart = prevDates.length > 0
        ? prevDates.slice().sort()[0]
        : (sourceDate || date);
    const periodEnd = sourceDate || date;

    if (missingFields.length === 0) {
        AppModal.setBody('detail', `
            <div style="padding: 40px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                <div style="font-size: 16px; font-weight: 600; color: #059669;">누락된 필드가 없습니다</div>
                <div style="font-size: 13px; margin-top: 8px; color: var(--text-secondary);">기간: ${periodStart} ~ ${periodEnd}</div>
            </div>`);
        return;
    }

    // 상단: 기간 조회 + 요약 정보
    let html = `<div style="margin-bottom: 16px; padding: 12px; background: var(--bg-primary); border-radius: 8px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <label style="font-weight: 500;">조회 날짜:</label>
            <input type="date" id="summary-date-input" value="${date}"
                style="padding: 4px 8px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px;">
            <button onclick="changeSummaryDate('${escJs(retailer)}')" style="padding: 4px 12px; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px;">조회</button>
        </div>
        <span style="color: #6b7280;">|</span>
        <span><strong>기간:</strong> ${periodStart} ~ ${periodEnd}</span>
        <span><strong>총 누락:</strong> <span style="color: #dc2626;">${summary.total_missing_cases || 0}건</span></span>
        <span><strong>문제 필드:</strong> ${summary.fields_with_issues || 0}개</span>
    </div>`;

    // 테이블 (세로 스크롤)
    html += '<div style="max-height: calc(70vh - 180px); overflow-y: auto;">';
    html += '<table class="detail-table"><thead><tr>';
    html += '<th style="width: 40%; position: sticky; top: 0; background: #f8f9fa;">필드명</th>';
    html += '<th style="width: 20%; text-align: right; position: sticky; top: 0; background: #f8f9fa;">누락 item 수</th>';
    html += '<th style="width: 20%; text-align: right; position: sticky; top: 0; background: #f8f9fa;">누락 건수</th>';
    html += '<th style="width: 20%; text-align: right; position: sticky; top: 0; background: #f8f9fa;">비고</th>';
    html += '</tr></thead><tbody>';

    missingFields.forEach(f => {
        const itemCount = f.today_missing_items || 0;
        const rowCount = f.today_null_rows || 0;
        let statusClass = '';
        let statusText = '';

        if (itemCount >= 20) {
            statusClass = 'color: #dc2626; font-weight: 600;';
            statusText = '심각';
        } else if (itemCount >= 10) {
            statusClass = 'color: #f59e0b; font-weight: 600;';
            statusText = '주의';
        } else if (itemCount > 0) {
            statusClass = 'color: #6b7280;';
            statusText = '경미';
        }

        // 필드명 클릭 시 상세 보기
        html += `<tr style="cursor: pointer;" onclick="viewFieldMissingDetail('${escJs(retailer)}', '${escJs(f.column)}', '${escJs(date)}')">
            <td style="font-weight: 500; color: #2563eb;">${esc(f.column)}</td>
            <td style="text-align: right; ${statusClass}">${itemCount}개</td>
            <td style="text-align: right; ${statusClass}">${rowCount}건</td>
            <td style="text-align: right; ${statusClass}">${statusText}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    html += '</div>';
    html += '<p style="margin-top: 12px; font-size: 12px; color: #6b7280;">* 필드명을 클릭하면 해당 필드의 누락 item 3일치 데이터를 볼 수 있습니다.</p>';

    AppModal.setBody('detail', html);
}

// 요약 날짜 변경
function changeSummaryDate(retailer) {
    const newDate = document.getElementById('summary-date-input').value;
    if (!newDate) return;

    missingSummaryState.date = newDate;
    loadMissingSummaryData(retailer, newDate);
}

// --- 인라인 요약 뷰 ---
async function viewMissingSummaryInline(retailer, date) {
    var actualDate = date || getSelectedDate();
    var cacheKey = currentFieldMissingPL + '-' + retailer;
    var cached = retailerMissingCache[cacheKey];

    // 캐시가 있고 같은 날짜면 캐시 사용
    if (cached && cached.date === actualDate) {
        _fmRenderSummaryInline(
            cached.missingFields, cached.summary, cached.date,
            cached.prevDates, retailer, cached.sourceDate
        );
    } else {
        // 로딩 표시 후 API 호출
        var loadingHtml = '<div class="detail-view-wrapper" style="padding:40px;text-align:center;">데이터를 불러오는 중...</div>';
        ViewStack.push(loadingHtml, fieldMissingProductLabel(currentFieldMissingPL) + ' - ' + retailer + ' 필드별 누락 요약');
        try {
            var data = await fetchAPI('/layer3/api/field-missing/?date=' + (date || getSelectedDate()) + '&type=' + currentFieldMissingPL + '&retailer=' + retailer);
            var missingFields = data.missing_fields || [];
            var summary = data.summary || {};
            var prevDates = data.prev_dates || [];
            var actualDate = data.inspection_date || date || getSelectedDate();
            var sourceDate = data.source_date || data.date || actualDate;
            ViewStack.pop();
            _fmRenderSummaryInline(
                missingFields, summary, actualDate, prevDates,
                retailer, sourceDate
            );
        } catch (e) {
            console.error(e);
            ViewStack.pop();
            showToast('데이터 로드 실패', 'error');
        }
    }
}

function _fmRenderSummaryInline(missingFields, summary, date, prevDates, retailer, sourceDate) {
    var plUpper = fieldMissingProductLabel(currentFieldMissingPL);
    var totalMissing = summary.total_missing_cases || 0;

    var titleText = plUpper + ' - ' + retailer + ' 필드별 누락 요약 (' + totalMissing + '건)';

    // 카드 목록
    var cardsHtml = '';
    if (missingFields.length === 0) {
        cardsHtml = '<div style="padding:40px;text-align:center;">'
            + '<div style="font-size:16px;font-weight:600;color:#059669;">누락된 필드가 없습니다</div></div>';
    } else {
        cardsHtml = '<div class="rule-summary-container">';
        missingFields.forEach(function(f) {
            var itemCount = f.today_missing_items || 0;
            var rowCount = f.today_null_rows || 0;
            var countClass = '';
            if (itemCount >= 20) countClass = ' critical';
            else if (itemCount >= 10) countClass = ' warning';

            cardsHtml += '<div class="rule-summary-card" onclick="showFieldMissingDetailInline(\'' + escJs(retailer) + '\',\'' + escJs(f.column) + '\')">'
                + '<div class="rule-info">'
                + '<div class="rule-name">' + esc(f.column) + '</div>'
                + '<div class="rule-desc">' + itemCount + ' items | ' + rowCount + '건</div>'
                + '</div>'
                + '<span class="rule-count' + (rowCount === 0 ? ' zero' : countClass) + '">' + rowCount + '건</span>'
                + '</div>';
        });
        cardsHtml += '</div>';
        cardsHtml += '<p style="margin-top:12px;font-size:12px;color:var(--text-secondary);">* 필드명을 클릭하면 해당 필드의 누락 item 데이터를 볼 수 있습니다.</p>';
    }

    var dateScope = '검수일 ' + date + ' · 데이터일 ' + (sourceDate || date) + ' · D-1';
    var html = '<div class="inline-detail">'
        + '<button class="btn-back" onclick="ViewStack.pop()">&#8592; 뒤로가기</button>'
        + '<div class="rule-summary-section">'
        + '<div class="rule-summary-section-header">' + _inlineTitle(titleText) + '</div>'
        + '<div class="field-missing-date-scope">' + esc(dateScope) + '</div>'
        + cardsHtml
        + '</div></div>';

    ViewStack.push(html);
}

// 필드별 누락 상세 보기 (3일치 데이터)
async function viewFieldMissingDetail(retailer, field, date) {
    AppModal.setTitle('detail', `${fieldMissingProductLabel(currentFieldMissingPL)} - ${retailer} - ${field} 누락 상세`);
    AppModal.setBody('detail', '<p style="text-align: center; padding: 40px;">데이터를 불러오는 중...</p>');

    try {
        const params = new URLSearchParams({
            date: date,
            product_line: currentFieldMissingPL,
            retailer: retailer,
            field: field
        });

        const data = await fetchAPI(`/layer3/api/field-missing-detail-by-field/?${params}`);

        if (data.status === 'success') {
            renderFieldMissingDetail(data, retailer, field);
        } else {
            AppModal.setBody('detail', `<p style="text-align: center; padding: 40px;">오류: ${esc(data.message || '데이터 로드 실패')}</p>`);
        }
    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p style="text-align: center; padding: 40px;">데이터 로드 실패</p>');
    }
}

// 필드별 누락 상세 렌더링
function renderFieldMissingDetail(data, retailer, field) {
    const items = data.data || [];
    const columns = data.columns || [];

    // 고유 item 목록 추출
    const uniqueItems = [...new Set(items.map(row => row.item).filter(Boolean))];

    // 누락 item 수와 누락 데이터 수 (API에서 반환)
    const missingItemCount = data.missing_item_count || uniqueItems.length;
    const todayNullCount = data.today_null_count || 0;

    // 상단: 뒤로가기 + 정보
    let html = `<div style="margin-bottom: 12px; padding: 12px; background: var(--bg-primary); border-radius: 8px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <button onclick="viewMissingSummary('${escJs(retailer)}', '${escJs(data.inspection_date || data.date)}')" style="padding: 6px 12px; background: #6b7280; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px;">← 뒤로가기</button>
        <span style="color: #6b7280;">|</span>
        <span><strong>필드:</strong> <span style="color: #dc2626;">${esc(field)}</span></span>
        <span><strong>검수일:</strong> ${data.inspection_date || data.date || ''}</span>
        <span><strong>기간:</strong> ${data.prev_dates?.[0] || ''} ~ ${data.date || ''}</span>
        <span><strong>누락 item 수:</strong> <span style="color: #dc2626;">${missingItemCount}개</span></span>
        <span><strong>누락 데이터 수:</strong> <span style="color: #dc2626;">${todayNullCount}건</span></span>
    </div>`;

    // 누락 item 목록 및 조회 쿼리 표시
    if (uniqueItems.length > 0) {
        const itemListDisplay = uniqueItems.join(', ');
        const inClause = uniqueItems.map(item => `'${item}'`).join(', ');
        const productLine = currentFieldMissingPL || 'tv';
        const tableName = data.table_name || (productLine === 'hhp' ? 'hhp_retail_com' : 'tv_retail_com');
        const dateColumn = data.date_column || (productLine === 'tv' ? 'crawl_datetime' : 'crawl_strdatetime');
        const queryDate = data.date || '';

        // API에서 반환한 컬럼 목록 사용 (필수 + 현재필드 + 관련필드)
        const queryColumns = columns.join(', ');
        const query = `SELECT ${queryColumns}
FROM ${tableName}
WHERE account_name = '${retailer}'
  AND item IN (${inClause})
  AND DATE(${dateColumn}::timestamp) >= DATE('${queryDate}') - INTERVAL '2 days'
  AND DATE(${dateColumn}::timestamp) <= DATE('${queryDate}')
ORDER BY item, ${dateColumn} ASC;`;

        html += `
        <div class="query-section">
            <div class="item-list-box">
                <div class="query-box-header">
                    <span class="query-box-title">누락 Item 목록 (${uniqueItems.length}개)</span>
                    <button class="btn-copy" onclick="copyQueryToClipboard(this.parentElement.nextElementSibling)">복사</button>
                </div>
                <div class="item-list-content">${esc(itemListDisplay)}</div>
            </div>
            <div class="query-box">
                <div class="query-box-header">
                    <span class="query-box-title">3일치 조회 쿼리</span>
                    <button class="btn-copy" onclick="copyQueryToClipboard(this.parentElement.nextElementSibling)">복사</button>
                </div>
                <pre class="query-content">${esc(query)}</pre>
            </div>
        </div>`;
    }

    if (items.length === 0) {
        html += '<p style="text-align: center; padding: 40px; color: var(--text-secondary);">누락 데이터가 없습니다.</p>';
        AppModal.setBody('detail', html);
        return;
    }

    // 테이블 (세로 스크롤)
    html += `<div style="flex: 1; overflow-y: auto; overflow-x: auto;">`;
    html += '<table class="detail-table" style="width: 100%; font-size: 13px; border-collapse: collapse;">';

    // 헤더
    html += '<thead><tr>';
    columns.forEach(col => {
        let colLabel = col;
        if (col === 'crawl_datetime') colLabel = '수집시간';
        else if (col === 'product_url') colLabel = 'URL';
        else if (col === 'id') colLabel = 'ID';

        // 검사 대상 필드 강조
        let headerStyle = 'padding: 10px 12px; position: sticky; top: 0; background: #f8f9fa; border-bottom: 2px solid #e5e7eb; text-align: left;';
        if (col === field) {
            headerStyle += ' background: #fef2f2; color: #dc2626; font-weight: 700;';
        }
        html += `<th style="${headerStyle}">${colLabel}</th>`;
    });
    html += '</tr></thead>';

    // 바디 - item별로 배경색 번갈아 (흰색/회색), 대상일 NULL만 빨간 배경
    html += '<tbody>';

    let currentItem = '';
    let itemColorIndex = 0;
    const itemColors = ['#ffffff', '#f3f4f6']; // 흰색, 옅은 회색
    const targetDate = data.date || ''; // 조회 대상일 (예: 2026-01-26)

    items.forEach(row => {
        // item이 바뀌면 색상 인덱스 변경
        if (row.item !== currentItem) {
            currentItem = row.item;
            itemColorIndex = 1 - itemColorIndex; // 0 <-> 1 토글
        }
        const rowBgColor = itemColors[itemColorIndex];

        // 행의 날짜가 대상일인지 확인
        const rowDate = (row.crawl_datetime || row.crawl_strdatetime || '').substring(0, 10);
        const isTargetDate = rowDate === targetDate;

        html += `<tr style="background: ${rowBgColor};">`;
        columns.forEach(col => {
            let val = row[col];
            let style = 'padding: 8px 12px; border-bottom: 1px solid #e5e7eb;';

            // 검사 대상 필드 강조 (대상일 NULL일 때만 빨간 배경)
            if (col === field && (val === null || val === undefined || val === '') && isTargetDate) {
                style += ' background: #fee2e2;';
            }

            if (val === null || val === undefined || val === '') {
                if (isTargetDate) {
                    val = '<span style="color: #dc2626; font-weight: 600;">NULL</span>';
                } else {
                    val = 'NULL';
                }
            } else if (col === 'product_url') {
                val = renderProductUrl(val);
            } else if (col === 'id') {
                style += ' color: #6b7280; font-size: 12px;';
            } else if (typeof val === 'string' && val.length > 80) {
                val = val.substring(0, 80) + '...';
            }

            if (col === 'item') {
                style += ' font-weight: 500;';
            }
            if (col === 'crawl_datetime') {
                style += ' font-size: 12px; color: #6b7280; white-space: nowrap;';
            }

            html += `<td style="${style}">${val}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';

    AppModal.setBody('detail', html);
}

// 누락분 보기 - 상태 관리
let missingItemsState = {
    retailer: '',
    productLine: '',
    date: '',
    offset: 0,
    limit: 100,
    hasMore: true,
    isLoading: false,
    totalCount: 0,
    loadedCount: 0,
    fields: []
};

// 누락분 보기 버튼
async function viewMissingItems(retailer) {
    const date = getSelectedDate();

    // 상태 초기화
    missingItemsState = {
        retailer: retailer,
        productLine: currentFieldMissingPL,
        date: date,
        offset: 0,
        limit: 100,
        hasMore: true,
        isLoading: false,
        totalCount: 0,
        loadedCount: 0,
        fields: []
    };

    AppModal.setTitle('detail', `${fieldMissingProductLabel(currentFieldMissingPL)} - ${retailer} 필드 누락 항목`);
    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    AppModal.open('detail');

    // 첫 데이터 로드
    await loadMissingItems(true);
}

// 누락분 데이터 로드 (무한스크롤용)
async function loadMissingItems(isInitial = false) {
    if (missingItemsState.isLoading || (!isInitial && !missingItemsState.hasMore)) return;

    missingItemsState.isLoading = true;

    try {
        const params = new URLSearchParams({
            date: missingItemsState.date,
            product_line: missingItemsState.productLine,
            retailer: missingItemsState.retailer,
            offset: missingItemsState.offset,
            limit: missingItemsState.limit
        });

        const data = await fetchAPI(`/layer3/api/field-missing-detail-problem/?${params}`);

        if (data.status === 'success') {
            if (isInitial) {
                missingItemsState.fields = data.fields;
                missingItemsState.totalCount = data.total_count || 0;
                renderMissingItemsModalInitial(data);
            } else {
                appendMissingItemsRows(data.data);
            }

            missingItemsState.offset += data.data.length;
            missingItemsState.loadedCount += data.data.length;
            missingItemsState.hasMore = data.has_more;

            // 로드 상태 업데이트
            updateMissingItemsLoadStatus();
        } else {
            if (isInitial) {
                AppModal.setBody('detail', `<p>오류: ${esc(data.message || '데이터 로드 실패')}</p>`);
            }
        }
    } catch (error) {
        console.error('Error:', error);
        if (isInitial) {
            AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
        }
    } finally {
        missingItemsState.isLoading = false;
    }
}

// 로드 상태 업데이트
function updateMissingItemsLoadStatus() {
    const statusEl = document.getElementById('missing-items-load-status');
    if (statusEl) {
        statusEl.innerHTML = `<strong>로드:</strong> ${missingItemsState.loadedCount} / ${missingItemsState.totalCount}건`;
        if (!missingItemsState.hasMore) {
            statusEl.innerHTML += ' (전체 로드 완료)';
        }
    }
}

// 누락분 모달 초기 렌더링
function renderMissingItemsModalInitial(data) {
    const items = data.data || [];

    if (items.length === 0 && missingItemsState.totalCount === 0) {
        AppModal.setBody('detail', `
            <div style="padding: 40px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                <div style="font-size: 16px; font-weight: 600; color: #059669;">누락된 필드가 없습니다</div>
                <div style="font-size: 13px; margin-top: 8px; color: var(--text-secondary);">직전 2일과 비교하여 데이터일에 누락된 항목이 없습니다.</div>
            </div>`);
        return;
    }

    let html = `<div style="margin-bottom: 16px; padding: 12px; background: var(--bg-primary); border-radius: 8px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <span><strong>검사 필드:</strong> ${data.fields?.length || 0}개</span>
        <span><strong>누락 항목:</strong> <span style="color: #dc2626;">${missingItemsState.totalCount}건</span></span>
        <span id="missing-items-load-status"><strong>로드:</strong> ${items.length} / ${missingItemsState.totalCount}건</span>
    </div>`;

    html += `<div id="missing-items-scroll-container" style="flex: 1; overflow-y: auto; max-height: calc(80vh - 150px);">`;
    html += '<table class="detail-table" id="missing-items-table"><thead><tr>';
    html += '<th>Item</th><th>Account</th><th>필드</th><th>직전 값</th><th>데이터일 값</th>';
    html += '</tr></thead><tbody id="missing-items-tbody">';

    items.forEach(row => {
        html += getMissingItemRow(row);
    });

    html += '</tbody></table></div>';

    // 로딩 인디케이터
    html += `<div id="missing-items-loading" style="display: none; text-align: center; padding: 12px; color: #6b7280;">
        <span>데이터 로딩 중...</span>
    </div>`;

    AppModal.setBody('detail', html);

    // 스크롤 이벤트 리스너
    const scrollContainer = document.getElementById('missing-items-scroll-container');
    scrollContainer.addEventListener('scroll', onMissingItemsScroll);
}

// 테이블 행 HTML 생성
function getMissingItemRow(row) {
    const todayStyle = row.today_has_value ? 'color: #059669;' : 'color: #dc2626; font-weight: 600;';
    const todayValue = row.today_has_value ? (row.today_value || '-') : '❌ 없음';
    const newBadge = row.finding_type === 'new'
        ? ' <span style="display:inline-block;margin-left:6px;padding:1px 6px;border-radius:10px;background:#dcfce7;color:#15803d;font-size:11px;font-weight:700;">신규</span>'
        : '';

    return `<tr>
        <td>${esc(row.item || '-')}${newBadge}</td>
        <td>${esc(row.account_name || '-')}</td>
        <td style="font-weight: 500;">${esc(row.field_name || '-')}</td>
        <td>${esc(row.d1_value || '-')}</td>
        <td style="${todayStyle}">${esc(todayValue)}</td>
    </tr>`;
}

// 행 추가 (무한 스크롤)
function appendMissingItemsRows(items) {
    const tbody = document.getElementById('missing-items-tbody');
    if (!tbody) return;

    items.forEach(row => {
        tbody.insertAdjacentHTML('beforeend', getMissingItemRow(row));
    });
}

// 스크롤 이벤트 핸들러
function onMissingItemsScroll(e) {
    const container = e.target;
    const threshold = 200;

    if (container.scrollHeight - container.scrollTop - container.clientHeight < threshold) {
        if (!missingItemsState.isLoading && missingItemsState.hasMore) {
            const loadingEl = document.getElementById('missing-items-loading');
            if (loadingEl) loadingEl.style.display = 'block';

            loadMissingItems(false)
                .then(() => { if (loadingEl) loadingEl.style.display = 'none'; })
                .catch(() => { if (loadingEl) loadingEl.style.display = 'none'; });
        }
    }
}

// 3일치 보기 - 상태 관리
let threeDaysState = {
    retailer: '',
    productLine: '',
    date: '',
    columns: [],
    displayFields: [],
    offset: 0,
    limit: 100,
    hasMore: true,
    isLoading: false,
    totalCount: 0,
    loadedCount: 0
};

// 3일치 보기 버튼
async function view3DaysData(retailer) {
    const date = getSelectedDate();

    // 상태 초기화
    threeDaysState = {
        retailer: retailer,
        productLine: currentFieldMissingPL,
        date: date,
        columns: [],
        displayFields: [],
        offset: 0,
        limit: 100,
        hasMore: true,
        isLoading: false,
        totalCount: 0,
        loadedCount: 0
    };

    AppModal.setTitle('detail', `${fieldMissingProductLabel(currentFieldMissingPL)} - ${retailer} 3일치 데이터`);
    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    AppModal.open('detail');

    // 첫 데이터 로드
    await load3DaysData(true);
}

// 3일치 데이터 로드 (무한스크롤용)
async function load3DaysData(isInitial = false) {
    if (threeDaysState.isLoading || (!isInitial && !threeDaysState.hasMore)) return;

    threeDaysState.isLoading = true;

    try {
        const params = new URLSearchParams({
            date: threeDaysState.date,
            product_line: threeDaysState.productLine,
            retailer: threeDaysState.retailer,
            offset: threeDaysState.offset,
            limit: threeDaysState.limit
        });

        const data = await fetchAPI(`/layer3/api/field-missing-detail-all/?${params}`);

        if (data.status === 'success') {
            if (isInitial) {
                threeDaysState.columns = data.columns;
                threeDaysState.displayFields = data.display_fields;
                threeDaysState.totalCount = data.total_count || 0;
                render3DaysModalInitial(data);
            } else {
                append3DaysRows(data.data);
            }

            threeDaysState.offset += data.fetched_rows;
            threeDaysState.loadedCount += data.fetched_rows;
            threeDaysState.hasMore = data.has_more;

            // 로드 상태 업데이트
            updateLoadStatus();
        } else {
            if (isInitial) {
                AppModal.setBody('detail', `<p>오류: ${esc(data.message || '데이터 로드 실패')}</p>`);
            }
        }
    } catch (error) {
        console.error('Error:', error);
        if (isInitial) {
            AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
        }
    }

    threeDaysState.isLoading = false;
}

// 날짜 변경하여 재조회
async function change3DaysDate() {
    const newDate = document.getElementById('three-days-date-input').value;
    if (!newDate) return;

    threeDaysState.date = newDate;
    threeDaysState.offset = 0;
    threeDaysState.hasMore = true;
    threeDaysState.loadedCount = 0;

    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    await load3DaysData(true);
}

// 3일치 모달 초기 렌더링 (날짜 조회 + 무한스크롤)
function render3DaysModalInitial(data) {
    const items = data.data || [];
    const columns = data.columns || [];
    const displayFields = data.display_fields || [];

    if (items.length === 0 && threeDaysState.totalCount === 0) {
        AppModal.setBody('detail', '<p style="text-align: center; padding: 40px; color: var(--text-secondary);">데이터가 없습니다.</p>');
        return;
    }

    // 상단: 날짜 조회 + 정보
    let html = `<div style="margin-bottom: 12px; padding: 12px; background: var(--bg-primary); border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <label style="font-weight: 500;">조회 날짜:</label>
            <input type="date" id="three-days-date-input" value="${threeDaysState.date}"
                style="padding: 4px 8px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px;">
            <button onclick="change3DaysDate()" style="padding: 4px 12px; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px;">조회</button>
        </div>
        <span style="color: #6b7280;">|</span>
        <span><strong>기간:</strong> ${data.prev_dates?.[0] || ''} ~ ${data.date || ''} (3일)</span>
        <span><strong>필드:</strong> ${displayFields.length}개</span>
        <span id="load-status"><strong>로드:</strong> ${items.length} / ${threeDaysState.totalCount}건</span>
    </div>`;

    // 테이블 컨테이너 (최대 높이 제한으로 세로 스크롤 활성화)
    html += `<div style="display: flex; flex-direction: column; flex: 1; min-height: 0; max-height: calc(80vh - 120px);">`;

    // 테이블 래퍼 (세로 + 가로 스크롤)
    html += `<div id="table-scroll-container" style="flex: 1; overflow-y: auto; overflow-x: auto; max-height: calc(80vh - 150px);">`;
    html += `<div id="table-inner" style="min-width: max-content;">`;
    html += '<table class="detail-table" id="three-days-table" style="min-width: max-content; font-size: 12px; border-collapse: collapse;">';

    // 헤더
    html += '<thead><tr>';
    columns.forEach(col => {
        let colLabel = col;
        if (col === 'crawl_datetime') colLabel = '수집시간';
        else if (col === 'product_url') colLabel = 'URL';
        html += `<th style="white-space: nowrap; padding: 8px 12px; position: sticky; top: 0; background: #f8f9fa; border-bottom: 2px solid #e5e7eb; z-index: 1;">${colLabel}</th>`;
    });
    html += '</tr></thead>';

    // 바디 - item별 배경색 구분
    html += '<tbody id="three-days-tbody">';
    let currentItem = '';
    let itemColorIndex = 0;
    const itemColors = ['#ffffff', '#f3f4f6'];
    items.forEach(row => {
        if (row.item !== currentItem) {
            currentItem = row.item;
            itemColorIndex = 1 - itemColorIndex;
        }
        html += buildRowHtml(row, columns, itemColors[itemColorIndex]);
    });
    // 마지막 item과 colorIndex 저장 (append용)
    threeDaysState.lastItem = currentItem;
    threeDaysState.lastColorIndex = itemColorIndex;
    html += '</tbody></table></div></div>';

    // 하단 고정 가로 스크롤바
    html += `<div id="horizontal-scroll" style="overflow-x: auto; overflow-y: hidden; flex-shrink: 0; border-top: 1px solid #e5e7eb; background: #fafafa;">
        <div id="scroll-spacer" style="height: 1px;"></div>
    </div>`;

    html += '</div>';

    AppModal.setBody('detail', html);

    // 스크롤 이벤트 및 동기화 설정
    setTimeout(() => {
        setupScrollSync();
        setupInfiniteScroll();
    }, 100);
}

// 행 HTML 생성 (배경색 포함)
function buildRowHtml(row, columns, bgColor = '#ffffff') {
    let html = `<tr style="background: ${bgColor};">`;
    columns.forEach(col => {
        let val = row[col];
        let style = 'white-space: nowrap; padding: 6px 10px; max-width: 250px; overflow: hidden; text-overflow: ellipsis; border-bottom: 1px solid #e5e7eb;';

        if (val === null || val === undefined || val === '') {
            val = '<span style="color: #dc2626;">-</span>';
        } else if (col === 'product_url') {
            val = renderProductUrl(val);
        } else if (col === 'id') {
            style += ' color: #6b7280; font-size: 11px;';
            val = esc(String(val));
        } else if (typeof val === 'string' && val.length > 50) {
            val = esc(val.substring(0, 50)) + '...';
        } else {
            val = esc(String(val));
        }

        if (col === 'item') {
            style += ' font-weight: 500;';
        }
        if (col === 'crawl_datetime') {
            style += ' font-size: 11px; color: #6b7280;';
        }

        html += `<td style="${style}">${val}</td>`;
    });
    html += '</tr>';
    return html;
}

// 추가 행 append (item별 배경색 유지)
function append3DaysRows(items) {
    const tbody = document.getElementById('three-days-tbody');
    if (!tbody) return;

    const itemColors = ['#ffffff', '#f3f4f6'];
    let currentItem = threeDaysState.lastItem || '';
    let colorIndex = threeDaysState.lastColorIndex || 0;

    items.forEach(row => {
        if (row.item !== currentItem) {
            currentItem = row.item;
            colorIndex = 1 - colorIndex;
        }
        tbody.insertAdjacentHTML('beforeend', buildRowHtml(row, threeDaysState.columns, itemColors[colorIndex]));
    });

    // 상태 업데이트
    threeDaysState.lastItem = currentItem;
    threeDaysState.lastColorIndex = colorIndex;

    // 스크롤바 너비 업데이트
    const tableInner = document.getElementById('table-inner');
    const scrollSpacer = document.getElementById('scroll-spacer');
    if (tableInner && scrollSpacer) {
        scrollSpacer.style.width = tableInner.scrollWidth + 'px';
    }
}

// 로드 상태 업데이트
function updateLoadStatus() {
    const statusEl = document.getElementById('load-status');
    if (statusEl) {
        let text = `<strong>로드:</strong> ${threeDaysState.loadedCount} / ${threeDaysState.totalCount}건`;
        if (!threeDaysState.hasMore) {
            text += ' (전체)';
        } else if (threeDaysState.isLoading) {
            text += ' <span style="color: #3b82f6;">(로딩중...)</span>';
        }
        statusEl.innerHTML = text;
    }
}

// 가로 스크롤 동기화 설정
function setupScrollSync() {
    const tableInner = document.getElementById('table-inner');
    const scrollSpacer = document.getElementById('scroll-spacer');
    const horizontalScroll = document.getElementById('horizontal-scroll');
    const tableContainer = document.getElementById('table-scroll-container');

    if (tableInner && scrollSpacer && horizontalScroll && tableContainer) {
        scrollSpacer.style.width = tableInner.scrollWidth + 'px';

        tableContainer.style.scrollbarWidth = 'none';
        tableContainer.style.msOverflowStyle = 'none';

        const existingStyle = document.getElementById('hide-horizontal-scrollbar');
        if (!existingStyle) {
            const style = document.createElement('style');
            style.id = 'hide-horizontal-scrollbar';
            style.textContent = '#table-scroll-container::-webkit-scrollbar { height: 0; width: 0; }';
            document.head.appendChild(style);
        }

        horizontalScroll.addEventListener('scroll', function() {
            tableContainer.scrollLeft = this.scrollLeft;
        });

        tableContainer.addEventListener('scroll', function() {
            horizontalScroll.scrollLeft = this.scrollLeft;
        });
    }
}

// 무한스크롤 설정
function setupInfiniteScroll() {
    const tableContainer = document.getElementById('table-scroll-container');
    if (!tableContainer) return;

    tableContainer.addEventListener('scroll', function() {
        const { scrollTop, scrollHeight, clientHeight } = this;

        // 하단 100px 남았을 때 추가 로드
        if (scrollHeight - scrollTop - clientHeight < 100) {
            load3DaysData(false);
        }
    });
}

// 페이지 로드 시 필드 누락 데이터 로드
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(loadAllRetailersMissing, 500);
});

// 리테일러별 필드 목록 (CSV 기반)
const retailerFields = {
    tv: {
        Amazon: ['product_url', 'screen_size', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'number_of_units_purchased_past_month', 'shipping_info', 'available_quantity_for_purchase', 'discount_type', 'sku_popularity', 'retailer_membership_discounts', 'rank_1', 'rank_2', 'summarized_review_content', 'detailed_review_content', 'main_rank', 'bsr_rank'],
        Bestbuy: ['product_url', 'screen_size', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'detailed_review_content', 'main_rank', 'bsr_rank', 'savings', 'offer', 'pick_up_availability', 'shipping_availability', 'delivery_availability', 'estimated_annual_electricity_use', 'retailer_sku_name_similar', 'top_mentions', 'recommendation_intent', 'promotion_type'],
        Walmart: ['product_url', 'screen_size', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'shipping_info', 'available_quantity_for_purchase', 'discount_type', 'sku_popularity', 'retailer_membership_discounts', 'detailed_review_content', 'main_rank', 'bsr_rank', 'savings', 'offer', 'pick_up_availability', 'shipping_availability', 'delivery_availability', 'sku_status', 'inventory_status', 'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts']
    },
    hhp: {
        Amazon: ['product_url', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'main_rank', 'bsr_rank', 'detailed_review_content', 'country', 'product', 'hhp_carrier', 'hhp_storage', 'hhp_color', 'number_of_units_purchased_past_month', 'shipping_info', 'available_quantity_for_purchase', 'discount_type', 'sku_popularity', 'bundle', 'trade_in', 'retailer_membership_discounts', 'rank_1', 'rank_2', 'summarized_review_content'],
        Bestbuy: ['product_url', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'main_rank', 'bsr_rank', 'detailed_review_content', 'country', 'product', 'hhp_carrier', 'hhp_storage', 'hhp_color', 'trade_in', 'savings', 'offer', 'pick_up_availability', 'shipping_availability', 'delivery_availability', 'sku_status', 'promotion_type', 'retailer_sku_name_similar', 'top_mentions', 'recommendation_intent', 'trend_rank'],
        Walmart: ['product_url', 'retailer_sku_name', 'count_of_reviews', 'star_rating', 'count_of_star_ratings', 'final_sku_price', 'original_sku_price', 'main_rank', 'bsr_rank', 'detailed_review_content', 'hhp_carrier', 'hhp_storage', 'hhp_color', 'shipping_info', 'available_quantity_for_purchase', 'discount_type', 'sku_popularity', 'retailer_membership_discounts', 'savings', 'offer', 'pick_up_availability', 'shipping_availability', 'delivery_availability', 'sku_status', 'retailer_sku_name_similar', 'inventory_status', 'number_of_ppl_purchased_yesterday', 'number_of_ppl_added_to_carts']
    }
};

// 필드 목록 로드
function loadFieldList() {
    const productLine = currentFieldMissingPL || 'tv';
    const retailer = document.getElementById('field-missing-retailer').value;
    const fieldSelect = document.getElementById('field-missing-field');

    const fields = retailerFields[productLine]?.[retailer] || [];

    fieldSelect.innerHTML = '<option value="">-- 필드 선택 --</option>';
    fields.forEach(field => {
        fieldSelect.innerHTML += `<option value="${esc(field)}">${esc(field)}</option>`;
    });
}

// 리테일러 변경 시 필드 목록 업데이트
document.getElementById('field-missing-retailer')?.addEventListener('change', loadFieldList);

// 3일치 전체보기
async function showFieldMissing3Days() {
    const date = getSelectedDate();
    const productLine = currentFieldMissingPL || 'tv';
    const retailer = document.getElementById('field-missing-retailer').value;
    const field = document.getElementById('field-missing-field').value;

    if (!field) {
        alert('필드를 선택하세요');
        return;
    }

    AppModal.setTitle('detail', `${field} - 3일치 전체 데이터 (${retailer})`);
    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    AppModal.open('detail');

    try {
        const data = await fetchAPI(`/layer3/api/field-missing-detail-all/?date=${date}&type=${productLine}&retailer=${retailer}&column=${field}`);
        renderFieldMissing3Days(data, field);
    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
    }
}

// 3일치 전체 데이터 렌더링
function renderFieldMissing3Days(data, fieldName) {
    const items = data.data || [];
    if (items.length === 0) {
        AppModal.setBody('detail', '<p>데이터가 없습니다.</p>');
        return;
    }

    let html = `<div style="margin-bottom: 12px; color: var(--text-secondary); font-size: 13px;">총 ${items.length}건 (최대 500건)</div>`;
    html += '<table class="detail-table"><thead><tr>';
    html += '<th>No.</th><th>Item</th><th>Page Type</th><th>수집일시</th><th>' + fieldName + '</th>';
    html += '</tr></thead><tbody>';

    items.forEach((row, idx) => {
        const value = row[fieldName];
        const isEmpty = value === null || value === '' || value === undefined;
        const valueStyle = isEmpty ? 'color: #c62828; font-weight: bold;' : '';
        const displayValue = isEmpty ? '(없음)' : (String(value).length > 50 ? String(value).substring(0, 50) + '...' : value);

        html += '<tr>';
        html += `<td>${idx + 1}</td>`;
        html += `<td>${row.item || '-'}</td>`;
        html += `<td>${row.page_type || '-'}</td>`;
        html += `<td>${row.crawl_datetime || '-'}</td>`;
        html += `<td style="${valueStyle}">${displayValue}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';
    AppModal.setBody('detail', html);
}

// 필드 누락 탐지 데이터 로드
async function loadFieldMissing() {
    const date = getSelectedDate();
    const productLine = currentFieldMissingPL || 'tv';
    const retailer = document.getElementById('field-missing-retailer').value;

    document.getElementById('field-missing-list').innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-secondary);">데이터를 불러오는 중...</div>';

    try {
        const data = await fetchAPI(`/layer3/api/field-missing/?date=${date}&type=${productLine}&retailer=${retailer}`);
        renderFieldMissing(data);
    } catch (error) {
        console.error('Error:', error);
        document.getElementById('field-missing-list').innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-secondary);">데이터 로드 실패</div>';
    }
}

// 필드 누락 탐지 결과 렌더링
function renderFieldMissing(data) {
    // Summary 업데이트
    const totalMissing = data.total_missing_cases || 0;
    const problemFields = data.problem_fields_count || 0;
    document.getElementById('field-missing-total').textContent = totalMissing.toLocaleString();
    document.getElementById('field-missing-fields').textContent = problemFields;

    // 상태 배지 업데이트
    const statusBadge = document.getElementById('field-missing-status');
    if (totalMissing === 0) {
        statusBadge.className = 'status-badge ok';
        statusBadge.textContent = 'OK';
    } else if (totalMissing < 10) {
        statusBadge.className = 'status-badge warning';
        statusBadge.textContent = 'WARNING';
    } else {
        statusBadge.className = 'status-badge critical';
        statusBadge.textContent = 'CRITICAL';
    }

    const missingFields = data.missing_fields || [];

    if (missingFields.length === 0) {
        document.getElementById('field-missing-list').innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-secondary);">필드 누락이 감지되지 않았습니다.</div>';
        return;
    }

    let html = '';
    missingFields.forEach((field, idx) => {
        html += `
            <div class="check-item" style="cursor: pointer;" onclick="showFieldMissingDetail('${escJs(field.retailer)}', '${escJs(field.field_name)}')">
                <div class="check-info">
                    <div class="check-name">
                        ${esc(field.field_name)}
                        <span class="threshold-badge">${esc(field.retailer)}</span>
                    </div>
                    <div class="check-description">직전 2일 값은 있었으나 데이터일에 누락된 케이스</div>
                </div>
                <div class="check-stats">
                    <div class="check-stat">
                        <div class="value" style="color: var(--color-critical);">${field.missing_count || 0}</div>
                        <div class="label">누락 건수</div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn-rules" onclick="event.stopPropagation(); showFieldMissingDetailAll('${escJs(field.retailer)}', '${escJs(field.field_name)}')">전체보기</button>
                        <button class="btn-rules" style="background: #fef3c7; color: #d97706;" onclick="event.stopPropagation(); showFieldMissingDetailProblem('${escJs(field.retailer)}', '${escJs(field.field_name)}')">문제만</button>
                    </div>
                </div>
            </div>
        `;
    });

    document.getElementById('field-missing-list').innerHTML = html;
}

// 필드 누락 상세 - 전체 데이터
async function showFieldMissingDetailAll(retailer, fieldName) {
    const date = getSelectedDate();
    const productLine = currentFieldMissingPL || 'tv';

    AppModal.setTitle('detail', `${fieldName} - 전체 데이터 (${retailer})`);
    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    AppModal.open('detail');

    try {
        const data = await fetchAPI(`/layer3/api/field-missing-detail-all/?date=${date}&type=${productLine}&retailer=${retailer}&field=${fieldName}`);
        renderFieldMissingDetailAll(data, fieldName);
    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
    }
}

// 필드 누락 상세 - 문제 데이터만
async function showFieldMissingDetailProblem(retailer, fieldName) {
    const date = getSelectedDate();
    const productLine = currentFieldMissingPL || 'tv';

    AppModal.setTitle('detail', `${fieldName} - 문제 데이터 (${retailer})`);
    AppModal.setBody('detail', '<p>데이터를 불러오는 중...</p>');
    AppModal.open('detail');

    try {
        const data = await fetchAPI(`/layer3/api/field-missing-detail-problem/?date=${date}&type=${productLine}&retailer=${retailer}&field=${fieldName}`);
        renderFieldMissingDetailProblem(data, fieldName);
    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
    }
}

// 클릭시 기본 동작
function showFieldMissingDetail(retailer, fieldName) {
    if (window.LAYER3 && window.LAYER3.section === 'field_missing') {
        showFieldMissingDetailInline(retailer, fieldName);
    } else {
        showFieldMissingDetailProblem(retailer, fieldName);
    }
}

// 전체 데이터 모달 렌더링
function renderFieldMissingDetailAll(data, fieldName) {
    const items = data.items || [];
    if (items.length === 0) {
        AppModal.setBody('detail', '<p>데이터가 없습니다.</p>');
        return;
    }

    let html = '<table class="detail-table"><thead><tr>';
    html += '<th>No.</th><th>Item</th><th>Retailer</th><th>수집일시</th><th>' + fieldName + '</th>';
    html += '</tr></thead><tbody>';

    items.forEach((row, idx) => {
        const value = row.field_value;
        const isEmpty = value === null || value === '' || value === 'NULL';
        const valueStyle = isEmpty ? 'color: #c62828; font-weight: bold;' : '';
        const displayValue = isEmpty ? '(없음)' : value;

        html += '<tr>';
        html += `<td>${idx + 1}</td>`;
        html += `<td>${row.item || '-'}</td>`;
        html += `<td>${row.account_name || '-'}</td>`;
        html += `<td>${row.crawl_datetime || '-'}</td>`;
        html += `<td style="${valueStyle}">${displayValue}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';
    AppModal.setBody('detail', html);
}

// 문제 데이터 모달 렌더링
function renderFieldMissingDetailProblem(data, fieldName) {
    const items = data.items || [];
    if (items.length === 0) {
        AppModal.setBody('detail', '<p>문제 데이터가 없습니다.</p>');
        return;
    }

    let html = '<table class="detail-table"><thead><tr>';
    html += '<th>No.</th><th>Item</th><th>Retailer</th><th>직전 값</th><th>데이터일 값</th>';
    html += '</tr></thead><tbody>';

    items.forEach((row, idx) => {
        html += '<tr>';
        html += `<td>${idx + 1}</td>`;
        html += `<td>${row.item || '-'}</td>`;
        html += `<td>${row.account_name || '-'}</td>`;
        html += `<td style="color: #2e7d32;">${row.prev_value || '-'}</td>`;
        html += `<td style="color: #c62828; font-weight: bold;">(없음)</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';
    AppModal.setBody('detail', html);
}

// 검증 규칙 데이터
// getValidationRules → common.js로 이동

// onSubitemClick → common.js로 이동

// ============================================================
// 누락필드 인라인 상세 뷰 + 셀 수정 / 정상 처리
// ============================================================

async function showFieldMissingDetailInline(retailer, fieldName) {
    var date = getSelectedDate();
    var productLine = currentFieldMissingPL || 'tv';
    var days = 3;

    try {
        var data = await fetchAPI('/layer3/api/field-missing-detail-by-field/?date=' + date + '&product_line=' + productLine + '&retailer=' + encodeURIComponent(retailer) + '&field=' + encodeURIComponent(fieldName) + '&days=' + days);
        if (data.status !== 'success') {
            showToast(data.message || '데이터 로드 실패', 'error');
            return;
        }
        _fmRenderInlineView(data, retailer, fieldName, productLine, date, days);
    } catch (e) {
        console.error(e);
        showToast('데이터 로드 실패', 'error');
    }
}

function _fmRenderInlineView(data, retailer, fieldName, productLine, date, days) {
    var tableName = data.table_name || (productLine === 'tv' ? 'tv_retail_com' : 'hhp_retail_com');
    var dateCol = data.date_column || (productLine === 'tv' ? 'crawl_datetime' : 'crawl_strdatetime');
    var editableCols = new Set(data.editable_columns || []);
    var normalReviews = data.normal_reviews || {};
    var columns = data.columns || [];
    var rawRows = data.data || [];
    var plDisplay = fieldMissingProductLabel(productLine || 'tv');
    var inspectionDate = data.inspection_date || date;
    var sourceDate = data.source_date || data.date || date;
    var _wn = ['일','월','화','수','목','금','토'][new Date(inspectionDate).getDay()];
    var dateDisplay = '검수일 ' + inspectionDate + '(' + _wn + ') · 데이터일 ' + sourceDate;

    // 컬럼 정의: API가 반환한 전체 컬럼
    var allColumns = [{ key: '_no', label: 'No', width: 50, fixed: true }];
    columns.forEach(function(col) {
        var w = 120;
        if (col === 'id') w = 80;
        else if (col === 'item') w = 140;
        else if (col === dateCol) w = 190;
        else if (col === 'product_url') w = 80;
        allColumns.push({ key: col, label: col, width: w });
    });

    // 기본 표시 컬럼 (default_columns 기반)
    var defaultCols = data.default_columns || columns;
    var defaultColSet = {};
    defaultCols.forEach(function(c) { defaultColSet[c] = true; });
    var defaultVisibleKeys = ['_no'];
    defaultCols.forEach(function(c) { defaultVisibleKeys.push(c); });

    // 데이터 변환
    var tableRows = rawRows.map(function(row, idx) {
        var r = { _no: idx + 1 };
        columns.forEach(function(col) {
            var val = row[col];
            if (col === 'product_url') {
                r[col] = renderProductUrl(val);
            } else {
                r[col] = val !== null && val !== undefined ? String(val) : '-';
            }
        });
        r._rowId = row.id;
        r._rowDate = (row[dateCol] || '').substring(0, 10);
        r._findingType = row.finding_type || '';
        return r;
    });

    // Item 목록 토글
    var missingItems = [];
    var seen = {};
    rawRows.forEach(function(row) {
        var rd = (row[dateCol] || '').substring(0, 10);
        if (rd === sourceDate && !seen[row.item]) {
            var fv = row[fieldName];
            if (fv === null || fv === undefined || fv === '') {
                missingItems.push(row.item);
                seen[row.item] = true;
            }
        }
    });
    var retailerSafe = retailer.replace(/[^a-zA-Z0-9]/g, '');
    var itemListDisplay = missingItems.join(', ');
    var itemQueryHtml = '<div class="item-toggle-section">'
        + '<div class="item-toggle-header" onclick="var c=this.nextElementSibling;c.style.display=c.style.display===\'none\'?\'\':\'none\';this.querySelector(\'.toggle-arrow\').textContent=c.style.display===\'none\'?\'\\u25b8\':\'\\u25be\';">'
        + '<span class="toggle-arrow">▸</span> Item 목록 (' + missingItems.length + '개)'
        + '</div>'
        + '<div class="item-toggle-content" style="display:none;">'
        + '<div class="item-copy-header"><span class="item-copy-title">누락 Item (' + missingItems.length + '개)</span>'
        + '<button class="btn-copy" onclick="copyQueryToClipboard(document.getElementById(\'fm-item-list-' + retailerSafe + '\'))">복사</button></div>'
        + '<div id="fm-item-list-' + retailerSafe + '" class="item-copy-content">' + esc(itemListDisplay) + '</div>'
        + '</div></div>';

    // 컨테이너 HTML
    var containerHtml = '<div class="detail-view-wrapper">'
        + '<div id="fm-detail-item-query">' + itemQueryHtml + '</div>'
        + '<div id="fm-detail-filter-bar"></div>'
        + '<div id="fm-detail-action-bar"></div>'
        + '<div id="fm-detail-table-area"></div>'
        + '<div id="fm-detail-pagination"></div>'
        + '</div>';

    var daysInputHtml = '<div style="display:flex;align-items:center;gap:6px;margin-right:12px;">'
        + '<label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>'
        + '<input type="number" id="fm-detail-days" value="' + days + '" min="1" max="30" style="width:50px;padding:3px 6px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;font-size:12px;text-align:center;" onkeydown="if(event.key===\'Enter\')reloadFmDays()">'
        + '<button onclick="reloadFmDays()" style="padding:3px 10px;font-size:12px;border:1px solid var(--border-color,#e2e8f0);border-radius:4px;background:var(--page-color,#0d9488);color:#fff;cursor:pointer;white-space:nowrap;">조회</button></div>';

    var titleText = fieldName + ' (' + (data.today_null_count || 0) + '건)';
    var subtitleText = plDisplay + ' Retail | ' + retailer;
    var wrapper = '<div class="inline-detail-view">'
        + '<div class="inline-detail-header"><div>'
        + '<div class="inline-detail-title">' + esc(titleText) + '</div>'
        + '<div class="inline-detail-subtitle">' + esc(subtitleText) + '</div>'
        + '</div><div style="display:flex;align-items:center;">' + daysInputHtml + '<div class="inline-detail-date">' + dateDisplay + '</div></div></div>'
        + '<div id="fm-detail-body">' + containerHtml + '</div>'
        + '</div>';

    ViewStack.push('<div class="inline-detail"><button class="btn-back" onclick="ViewStack.pop()">← 뒤로가기</button>' + wrapper + '</div>');

    // 편집 상태 초기화
    fmPendingEdits = {};

    // 전역 상태 저장
    window._fmCurrentRetailer = retailer;
    window._fmCurrentField = fieldName;
    window._fmCurrentPL = productLine;
    window._fmDate = inspectionDate;
    window._fmSourceDate = sourceDate;
    window._fmTableName = tableName;

    // FilterBar 옵션
    var filterCols = [];
    columns.forEach(function(col) {
        if (col !== 'product_url') filterCols.push({ value: col, label: col });
    });

    window._fmDetailState = {
        allData: tableRows,
        filteredData: null,
        allColumns: allColumns,
        visibleKeys: defaultVisibleKeys.slice(),
        editableCols: editableCols,
        normalReviews: normalReviews,
        sortState: [],
        table: null,
        filterBar: null,
        pager: null,
        fieldName: fieldName,
        dateCol: dateCol,
        sourceDate: sourceDate
    };

    window._fmDetailState.filterBar = new FilterBar('#fm-detail-filter-bar', {
        sticky: false,
        padding: '8px 12px',
        controls: [
            { type: 'select', key: 'fmFilterCol', label: '항목', width: 'auto', options: filterCols },
            { type: 'input', key: 'fmFilterVal', placeholder: '검색어 입력...', onEnter: function() { _fmApplyFilter(); } }
        ],
        onSearch: function() { _fmApplyFilter(); },
        onReset: function() { _fmClearFilter(); },
        columnSelector: {
            columns: allColumns.map(function(c) { return { key: c.key, label: c.label }; }),
            fixed: ['_no'],
            defaultVisible: defaultVisibleKeys,
            onUpdate: function(selected) {
                window._fmDetailState.visibleKeys = selected.map(function(c) { return c.key; });
                _fmRebuildTable();
                setTimeout(function() { _fmBindEditEvents(); }, 100);
            }
        },
        right: [
            { type: 'button', label: '정렬 초기화', style: 'outline', size: 'fb', onClick: function() { window._fmDetailState.sortState = []; _fmRebuildTable(); setTimeout(function() { _fmBindEditEvents(); }, 100); } }
        ]
    }).render();

    _fmRebuildTable();
    setTimeout(function() { _fmBindEditEvents(); }, 100);
}

// N일치 재조회
window.reloadFmDays = function() {
    var daysEl = document.getElementById('fm-detail-days');
    var days = daysEl ? parseInt(daysEl.value, 10) : 1;
    if (isNaN(days) || days < 1) days = 1;
    if (days > 30) days = 30;

    var retailer = window._fmCurrentRetailer;
    var fieldName = window._fmCurrentField;
    var productLine = window._fmCurrentPL;
    var date = window._fmDate;

    fetchAPI('/layer3/api/field-missing-detail-by-field/?date=' + date + '&product_line=' + productLine + '&retailer=' + encodeURIComponent(retailer) + '&field=' + encodeURIComponent(fieldName) + '&days=' + days)
        .then(function(data) {
            if (data.status !== 'success') { showToast(data.message || '재조회 실패', 'error'); return; }
            var st = window._fmDetailState;
            var dateCol = st.dateCol;
            var columns = data.columns || [];
            var rawRows = data.data || [];
            var targetDate = data.source_date || data.date || window._fmSourceDate;
            window._fmSourceDate = targetDate;

            var tableRows = rawRows.map(function(row, idx) {
                var r = { _no: idx + 1 };
                columns.forEach(function(col) {
                    var val = row[col];
                    if (col === 'product_url') {
                        r[col] = renderProductUrl(val);
                    } else {
                        r[col] = val !== null && val !== undefined ? String(val) : '-';
                    }
                });
                r._rowId = row.id;
                r._rowDate = (row[dateCol] || '').substring(0, 10);
                r._findingType = row.finding_type || '';
                return r;
            });

            st.allData = tableRows;
            st.filteredData = null;
            st.editableCols = new Set(data.editable_columns || []);
            st.normalReviews = data.normal_reviews || {};
            st.sourceDate = targetDate;
            _fmRebuildTable();
            setTimeout(function() { _fmBindEditEvents(); }, 100);
        })
        .catch(function(e) { console.error(e); showToast('재조회 실패', 'error'); });
};

// CommonTable 재구성
function _fmRebuildTable() {
    var st = window._fmDetailState;
    if (!st) return;

    var colMap = {};
    st.allColumns.forEach(function(c) { colMap[c.key] = c; });
    var visibleCols = st.visibleKeys.map(function(k) { return colMap[k]; }).filter(Boolean);
    st._visibleCols = visibleCols;

    var ctColumns = visibleCols.map(function(c) {
        return { key: c.key, label: c.label, width: c.width, sortable: c.key === 'item', align: c.key === '_no' ? 'center' : undefined };
    });

    var el = document.getElementById('fm-detail-table-area');
    if (!el) return;
    el.innerHTML = '';

    st.table = new CommonTable('#fm-detail-table-area', {
        variant: 'detail', columns: ctColumns, vlines: true, section: true, showTotalCount: true,
        padding: '6px 12px', reorder: true, fixedColumns: ['_no'], multiSort: true,
        pageSize: 100,
        onPageSizeChange: async function(val) {
            if (Object.keys(fmPendingEdits).length > 0) {
                if (!await showConfirm('변경된 값이 있습니다.\n저장하지 않고 이동하시겠습니까?', 'warning', { okText: '이동', cancelText: '취소' })) return;
            }
            _fmResetPendingEdits();
            if (st.pager) st.pager.options.pageSize = val;
            _fmRenderPage(1);
        },
        onSort: function(sortArr) { st.sortState = sortArr; _fmSortAndRender(); }
    }).render();

    var pageSize = 100;
    st.pager = new Pagination('#fm-detail-pagination', {
        pageSize: pageSize, showInfo: true,
        onPageChange: async function(page) {
            if (Object.keys(fmPendingEdits).length > 0) {
                if (!await showConfirm('변경된 값이 있습니다.\n저장하지 않고 이동하시겠습니까?', 'warning', { okText: '이동', cancelText: '취소' })) return;
            }
            _fmResetPendingEdits();
            _fmRenderPage(page);
        }
    });

    // 레이아웃 고정용: review bar를 미리 hidden으로 생성
    var actionBar = document.getElementById('fm-detail-action-bar');
    if (actionBar && !document.getElementById('fm-review-bar')) {
        actionBar.innerHTML = '<div class="null-review-bar" id="fm-review-bar" style="visibility:hidden;">'
            + '<span class="null-review-info">&nbsp;</span>'
            + '<button class="btn-null-normal">확인</button>'
            + '</div>';
    }

    _fmSortAndRender();
}

function _fmSortAndRender() {
    var st = window._fmDetailState;
    if (!st) return;
    var dataArr = st.filteredData || st.allData;

    if (st.sortState && st.sortState.length > 0) {
        dataArr = dataArr.slice().sort(function(a, b) {
            for (var i = 0; i < st.sortState.length; i++) {
                var s = st.sortState[i];
                var va = a[s.key] || '', vb = b[s.key] || '';
                var cmp = String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: 'base' });
                if (cmp !== 0) return s.dir === 'asc' ? cmp : -cmp;
            }
            return 0;
        });
    }
    st._sortedData = dataArr;
    _fmRenderPage(1);
}

function _fmRenderPage(page) {
    var st = window._fmDetailState;
    if (!st || !st.table) return;

    var dataArr = st._sortedData || st.allData;
    var pageSize = (st.table && st.table.getPageSize) ? st.table.getPageSize() : 100;
    if (st.pager) st.pager.options.pageSize = pageSize;
    var start = (page - 1) * pageSize;
    var pageData = dataArr.slice(start, start + pageSize);
    pageData.forEach(function(r, i) { r._no = start + i + 1; });

    var visibleCols = st._visibleCols || st.allColumns;
    var targetDate = st.sourceDate || window._fmSourceDate || '';
    var targetField = st.fieldName || '';

    // item 컬럼 rowspan 계산
    var itemSpanMap = {};  // index -> rowspan count
    var itemSkipSet = {};  // index -> true (skip item td)
    var hasItemCol = visibleCols.some(function(c) { return c.key === 'item'; });
    if (hasItemCol) {
        var i = 0;
        while (i < pageData.length) {
            var curItem = pageData[i].item;
            var spanCount = 1;
            while (i + spanCount < pageData.length && pageData[i + spanCount].item === curItem) {
                itemSkipSet[i + spanCount] = true;
                spanCount++;
            }
            if (spanCount > 1) itemSpanMap[i] = spanCount;
            i += spanCount;
        }
    }

    st.table.renderBody(pageData, function(row, rowIdx) {
        var tr = '<tr>';
        var rowId = row._rowId;
        var isTargetDate = row._rowDate === targetDate;
        visibleCols.forEach(function(c) {
            // item 컬럼 rowspan 처리
            if (c.key === 'item') {
                if (itemSkipSet[rowIdx]) return; // 이미 rowspan으로 병합됨
                var span = itemSpanMap[rowIdx];
                var spanAttr = span ? ' rowspan="' + span + '"' : '';
                var val = row[c.key];
                var displayVal = val !== null && val !== undefined ? String(val) : '-';
                var findingBadge = row._findingType === 'new'
                    ? ' <span style="display:inline-block;margin-left:6px;padding:1px 6px;border-radius:10px;background:#dcfce7;color:#15803d;font-size:11px;font-weight:700;">신규</span>'
                    : '';
                tr += '<td' + spanAttr + ' style="vertical-align:middle;">' + esc(displayVal) + findingBadge + '</td>';
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
                // 누락필드 특유: 타겟 날짜 NULL 셀 빨간 배경
                var isNull = displayVal === '-' || displayVal === '';
                var cellStyle = (isNull && c.key === targetField) ? ' style="background:#fee2e2;"' : '';
                tr += '<td data-editable="true" data-row-id="' + rowId + '" data-col="' + esc(c.key) + '" data-original="' + esc(displayVal === '-' ? '' : displayVal) + '"' + cellStyle + '>' + esc(displayVal) + '</td>';
            } else if (isTargetDate && rowId) {
                var isNull2 = displayVal === '-' || displayVal === '';
                var cellStyle2 = (isNull2 && c.key === targetField) ? ' style="background:#fee2e2;"' : '';
                tr += '<td data-row-id="' + rowId + '" data-col="' + esc(c.key) + '"' + cellStyle2 + '>' + esc(displayVal) + '</td>';
            } else {
                tr += '<td>' + esc(displayVal) + '</td>';
            }
        });
        tr += '</tr>';
        return tr;
    });

    if (st.pager) st.pager.render(dataArr.length, page);
    var countEl = document.querySelector('#fm-detail-table-area .ct-count');
    if (countEl) {
        var suffix = st.filteredData ? ' (필터 적용)' : '';
        countEl.innerHTML = '총 <strong>' + dataArr.length.toLocaleString() + '</strong>건' + suffix;
    }

    // 편집 이벤트 재바인딩 (테이블 재생성 후 필요)
    setTimeout(function() { _fmBindEditEvents(); }, 50);
}

// 필터
function _fmApplyFilter() {
    var st = window._fmDetailState;
    if (!st) return;
    var colEl = document.getElementById('fmFilterCol');
    var valEl = document.getElementById('fmFilterVal');
    if (!colEl || !valEl) return;
    var col = colEl.value, keyword = (valEl.value || '').trim().toLowerCase();
    if (!keyword) { _fmClearFilter(); return; }
    st.filteredData = st.allData.filter(function(r) { return String(r[col] || '').toLowerCase().indexOf(keyword) >= 0; });
    _fmSortAndRender();
}
function _fmClearFilter() {
    var st = window._fmDetailState;
    if (!st) return;
    st.filteredData = null;
    var valEl = document.getElementById('fmFilterVal');
    if (valEl) valEl.value = '';
    _fmSortAndRender();
}

// ============================================================
// 누락필드 셀 수정 / 정상 처리
// ============================================================
var fmPendingEdits = {};

function _fmBindEditEvents() {
    var container = document.getElementById('fm-detail-table-area');
    if (!container) return;
    var tableEl = container.querySelector('table');
    if (!tableEl) return;
    if (tableEl._fmEditBound) return;
    tableEl._fmEditBound = true;

    // 클릭: 셀 선택 / 정상처리 바
    tableEl.addEventListener('click', function(e) {
        var td = e.target.closest('td[data-editable]');
        var normalTd = !td ? e.target.closest('td.cell-normal') : null;
        var reviewTd = (!td && !normalTd) ? e.target.closest('td[data-row-id]') : null;
        var prev = tableEl.querySelector('.cell-selected');
        if (prev) prev.classList.remove('cell-selected');
        _fmHideReviewBar();
        // 현재 보고 있는 필드와 다른 컬럼은 정상처리 불가
        var targetTd = td || reviewTd;
        var colMatch = true;
        if (targetTd && window._fmCurrentField) {
            var clickedCol = targetTd.getAttribute('data-col');
            if (clickedCol && clickedCol !== window._fmCurrentField) colMatch = false;
        }
        if (td) {
            td.classList.add('cell-selected');
            window._fmSelectedCell = td;
            if (colMatch) _fmShowReviewBar(td, 'normal');
        } else if (normalTd) {
            window._fmSelectedCell = null;
            // cell-normal은 무시 (정상처리 완료된 셀)
        } else if (reviewTd) {
            reviewTd.classList.add('cell-selected');
            window._fmSelectedCell = null;
            if (colMatch) _fmShowReviewBar(reviewTd, 'normal');
        } else {
            window._fmSelectedCell = null;
        }
    });

    // 테이블 외부 클릭
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#fm-detail-table-area') && !e.target.closest('#fm-review-bar')) {
            var sel = tableEl.querySelector('.cell-selected');
            if (sel) sel.classList.remove('cell-selected');
            window._fmSelectedCell = null;
            _fmHideReviewBar();
        }
    });

    // 더블클릭: 직접 입력
    tableEl.addEventListener('dblclick', function(e) {
        var td = e.target.closest('td[data-editable]');
        if (!td) return;
        if (td.querySelector('.cell-edit-overlay')) return;
        var currentVal = td.textContent.trim();
        if (currentVal === '-') currentVal = '';
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'cell-edit-overlay';
        input.value = currentVal;
        input.style.width = td.offsetWidth + 'px';
        input.style.height = td.offsetHeight + 'px';
        input.style.position = 'absolute';
        input.style.left = td.offsetLeft + 'px';
        input.style.top = td.offsetTop + 'px';
        input.style.zIndex = '100';
        td.style.position = 'relative';
        td.appendChild(input);
        input.focus();
        input.select();
        var committed = false;
        function commit() {
            if (committed) return;
            committed = true;
            var newVal = input.value.trim();
            input.remove();
            _fmApplyEdit(td, newVal);
        }
        input.addEventListener('blur', commit);
        input.addEventListener('keydown', function(ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
            else if (ev.key === 'Escape') { committed = true; input.remove(); }
        });
    });

    // Ctrl+V 붙여넣기
    tableEl.addEventListener('paste', function(e) {
        var td = e.target.closest('td[data-editable]');
        if (!td) return;
        if (td.querySelector('.cell-edit-overlay')) return;
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text').trim();
        _fmApplyEdit(td, text);
    });
}

function _fmApplyEdit(td, newVal) {
    var rowId = td.getAttribute('data-row-id');
    var col = td.getAttribute('data-col');
    if (!rowId || !col) return;
    var key = rowId + '_' + col;
    var original = td.getAttribute('data-original') || '';
    if (original === '-') original = '';
    // 값이 변경되지 않았으면 무시
    if (newVal.trim() === original) {
        delete fmPendingEdits[key];
        td.classList.remove('cell-pending');
        _fmUpdateSaveButton();
        return;
    }
    if (!fmPendingEdits[key]) {
        fmPendingEdits[key] = { rowId: rowId, col: col, original: original };
    }
    fmPendingEdits[key].newVal = newVal;
    td.textContent = newVal || '-';
    td.classList.add('cell-pending');
    _fmUpdateSaveButton();
}

function _fmUpdateSaveButton() {
    var bar = document.getElementById('fm-detail-action-bar');
    if (!bar) return;
    var count = Object.keys(fmPendingEdits).length;
    if (count === 0) {
        bar.innerHTML = '<div class="null-review-bar" id="fm-review-bar" style="visibility:hidden;">'
            + '<span class="null-review-info">&nbsp;</span>'
            + '<button class="btn-null-normal">확인</button></div>';
        return;
    }
    bar.innerHTML = '<div class="detail-edit-actions">'
        + '<span class="edit-actions-info">' + count + '건 변경됨</span>'
        + '<div style="display:flex;gap:8px;">'
        + '<button class="btn-cancel-edits" onclick="_fmCancelAllEdits()">취소</button>'
        + '<button class="btn-save-edits" onclick="_fmSaveAllEdits()">저장</button>'
        + '</div></div>';
}

function _fmResetPendingEdits() {
    fmPendingEdits = {};
    _fmUpdateSaveButton();
}

window._fmCancelAllEdits = function() {
    Object.keys(fmPendingEdits).forEach(function(key) {
        var edit = fmPendingEdits[key];
        var tds = document.querySelectorAll('td[data-row-id="' + edit.rowId + '"][data-col="' + edit.col + '"]');
        tds.forEach(function(td) { var orig = td.getAttribute('data-original') || ''; td.textContent = orig || '-'; td.classList.remove('cell-pending'); });
    });
    fmPendingEdits = {};
    _fmUpdateSaveButton();
};

window._fmSaveAllEdits = function() {
    var edits = Object.values(fmPendingEdits);
    if (edits.length === 0) return;
    _fmShowMemoDialog(function(memo) {
        var promises = edits.map(function(edit) {
            return fetch('/dx/layer3/api/update-cell/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({
                    table_name: window._fmTableName,
                    row_id: parseInt(edit.rowId),
                    column_name: edit.col,
                    new_value: edit.newVal,
                    crawl_date: window._fmDate,
                    memo: memo,
                    correction_type: 'field_missing'
                })
            }).then(function(r) { return r.json(); });
        });
        Promise.all(promises).then(function(results) {
            console.log('fm save results:', results);
            var failedResults = results.filter(function(r) { return !r.success; });
            if (failedResults.length > 0) console.warn('fm save failures:', failedResults);
            var successCount = results.filter(function(r) { return r.success; }).length;
            showToast(successCount + '건 저장 완료', 'success');
            document.querySelectorAll('td.cell-pending').forEach(function(td) {
                td.setAttribute('data-original', td.textContent.trim() === '-' ? '' : td.textContent.trim());
                td.classList.remove('cell-pending'); td.classList.add('cell-saved');
            });
            fmPendingEdits = {};
            _fmUpdateSaveButton();
            setTimeout(function() { document.querySelectorAll('td.cell-saved').forEach(function(td) { td.classList.remove('cell-saved'); }); }, 2000);
        }).catch(function(e) { console.error(e); showToast('저장 실패', 'error'); });
    });
};

function _fmShowMemoDialog(callback) {
    var overlay = document.createElement('div');
    overlay.className = 'memo-dialog-overlay';
    overlay.innerHTML = '<div class="memo-dialog">'
        + '<div class="memo-dialog-title">수정 메모</div>'
        + '<div class="memo-dialog-field"><textarea class="memo-dialog-input" id="fm-memo-input" rows="3" placeholder="수정 사유를 입력하세요 (선택)"></textarea></div>'
        + '<div class="memo-dialog-buttons">'
        + '<button class="memo-dialog-cancel" id="fm-memo-cancel">취소</button>'
        + '<button class="memo-dialog-confirm" id="fm-memo-confirm">저장</button>'
        + '</div></div>';
    document.body.appendChild(overlay);
    requestAnimationFrame(function() { overlay.classList.add('show'); });
    document.getElementById('fm-memo-cancel').onclick = function() { overlay.remove(); };
    document.getElementById('fm-memo-confirm').onclick = function() {
        var memo = document.getElementById('fm-memo-input').value.trim();
        overlay.remove();
        callback(memo);
    };
}

// 정상처리 바
function _fmShowReviewBar(td, mode) {
    _fmHideReviewBar();
    var bar = document.getElementById('fm-detail-action-bar');
    if (!bar) return;
    if (Object.keys(fmPendingEdits).length > 0) return;
    var rowId = td.getAttribute('data-row-id');
    var col = td.getAttribute('data-col');
    if (!rowId) return;

    var reviewBar = document.getElementById('fm-review-bar');
    if (!reviewBar) {
        var html = '<div class="null-review-bar" id="fm-review-bar">'
            + '<span class="null-review-info"></span>'
            + '<button class="btn-null-normal">확인</button>'
            + '</div>';
        bar.innerHTML = html;
        reviewBar = document.getElementById('fm-review-bar');
    }
    reviewBar.querySelector('.null-review-info').textContent = col + ' (ID: ' + rowId + ')';
    reviewBar.querySelector('.btn-null-normal').onclick = function() { _fmShowReviewDialog(rowId, col); };
    reviewBar.style.visibility = 'visible';
}

function _fmHideReviewBar() {
    var bar = document.getElementById('fm-review-bar');
    if (bar) bar.style.visibility = 'hidden';
}

window._fmShowReviewDialog = function(rowId, col) {
    _showReviewDialog('field_missing', function(reason, memo) {
        _fmSubmitReview(rowId, col, 'normal', reason, memo, '');
    });
};

window._fmSubmitReview = function(rowId, col, status, reason, memo, normalKey) {
    fetch('/dx/layer3/api/review/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
            table_name: window._fmTableName,
            record_id: parseInt(rowId),
            column_name: col,
            status: status,
            reason: reason || '',
            memo: memo || '',
            crawl_date: window._fmDate,
            retailer: window._fmCurrentRetailer || '',
            correction_type: 'field_missing'
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) { showToast(data.error || '처리 실패', 'error'); return; }
        var st = window._fmDetailState;
        var nk = rowId + '_' + col;
        st.normalReviews[nk] = { reason: reason, memo: memo, created_id: '' };
        showToast('확인 처리 완료', 'success');
        _fmHideReviewBar();
        _fmRenderPage(st.pager ? st.pager.currentPage || 1 : 1);
        setTimeout(function() { _fmBindEditEvents(); }, 100);
    })
    .catch(function(e) { console.error(e); showToast('처리 실패', 'error'); });
};

