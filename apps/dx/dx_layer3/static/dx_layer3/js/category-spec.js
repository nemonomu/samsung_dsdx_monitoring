// 카테고리별 특성 데이터 날짜 변경 시 재로드
async function reloadCategorySpecData(date, displayName, title) {
    const inline = isCatSpecInline();
    const bodyEl = inline ? document.querySelector('.inline-detail-body') : AppModal.getBody('detail');
    if (bodyEl) bodyEl.innerHTML = '<p style="text-align:center;">데이터를 불러오는 중...</p>';

    try {
        const data = await fetchAPI(`/layer3/api/category-spec-detail/?date=${date}&display_name=${encodeURIComponent(displayName)}&mode=summary`);

        if (data.error) {
            if (bodyEl) bodyEl.innerHTML = `<p style="color: red;">오류: ${esc(data.error)}</p>`;
            return;
        }

        // 공통 렌더링 (모달/인라인 모두 처리)
        renderCatSpecSummaryContent(title, data);

    } catch (error) {
        console.error('Error:', error);
        if (bodyEl) bodyEl.innerHTML = '<p style="color: red;">데이터 로드 실패</p>';
    }
}

// 카테고리별 특성 규칙별 상세 데이터 로드
let masterTableDetailState = {
    data: null, displayName: '', ruleId: '', date: '', ruleName: '', currentRetailer: 'all', currentPage: 1,
    filterProduct: 'all',   // 'all' | 'product' | 'non_product'
    filterChecked: 'all'    // 'all' | 'checked' | 'unchecked'
};
const SPEC_PAGE_SIZE = 20;
// is_product / is_checked 변경 추적: Map<mst_id, { is_product?, is_checked?, table }>
let specPendingChanges = new Map();
let specOriginalValues = new Map();  // Map<mst_id, { is_product, is_checked }>

async function loadCategorySpecRuleDetail(displayName, ruleId, date, ruleName) {
    const inline = isCatSpecInline();

    if (inline) {
        ViewStack.push(`
            <div class="inline-detail">
                <button class="btn-back" onclick="specCancelAndBack()">← 뒤로가기</button>
                <div class="inline-detail-title">${ruleName}</div>
                <div class="inline-detail-body"><p style="text-align:center;">데이터를 불러오는 중...</p></div>
            </div>
        `);
    } else {
        AppModal.setTitle('detail', ruleName);
        AppModal.setBody('detail', '<p style="text-align:center;">데이터를 불러오는 중...</p>');
    }

    try {
        const data = await fetchAPI(`/layer3/api/category-spec-detail/?date=${date}&display_name=${encodeURIComponent(displayName)}&rule_id=${ruleId}`);

        if (data.error) {
            const errTarget = inline ? document.querySelector('.inline-detail-body') : AppModal.getBody('detail');
            if (errTarget) errTarget.innerHTML = `<p style="color: red;">오류: ${esc(data.error)}</p>`;
            return;
        }

        // 리테일러별 탭으로 표시
        masterTableDetailState = { data, displayName, ruleId, date, ruleName, currentRetailer: 'all', currentPage: 1, filterProduct: 'all', filterChecked: 'all' };
        renderCategorySpecDetail(data, ruleName, 'all');

    } catch (error) {
        console.error('Error:', error);
        AppModal.setBody('detail', '<p style="color: red;">데이터 로드 실패</p>');
    }
}

// 카테고리 특성 상세보기 렌더링 (리테일러별 탭 + is_product 토글)
function renderCategorySpecDetail(data, ruleName, selectedRetailer) {
    const retailerCounts = data.retailer_counts || {};
    const retailerData = data.retailer_data || {};
    const allAnomalies = data.anomalies || [];
    const displayColumns = data.display_columns || [];
    const hasMstId = allAnomalies.some(r => r.mst_id != null);

    // 선택된 리테일러에 따른 데이터 필터링
    let retailerFiltered = [];
    if (selectedRetailer === 'all') {
        retailerFiltered = allAnomalies;
    } else {
        retailerFiltered = retailerData[selectedRetailer] || [];
    }

    // 제품여부 / 확인완료 필터 적용
    const fProduct = masterTableDetailState.filterProduct || 'all';
    const fChecked = masterTableDetailState.filterChecked || 'all';

    const filteredData = retailerFiltered.filter(row => {
        // 변경 대기 중인 행은 저장 전까지 항상 표시
        if (row.mst_id && specPendingChanges.has(row.mst_id)) return true;
        const ip = row.is_product;
        const ic = row.is_checked;
        if (fProduct === 'product' && ip === false) return false;
        if (fProduct === 'non_product' && ip !== false) return false;
        if (fChecked === 'checked' && ic !== true) return false;
        if (fChecked === 'unchecked' && ic === true) return false;
        return true;
    });

    // table key 결정 (tv / hhp)
    const productLine = (data.product_line || '').toUpperCase();
    const tableKey = productLine.includes('HHP') ? 'hhp' : 'tv';

    const inline = isCatSpecInline();
    let html = data.source_date ? `<p class="inline-detail-subtitle">검수일 ${esc(data.date)} · 수집일 ${esc(data.source_date)}${data.offset_days === -1 ? ' · D-1' : ''}</p>` : '';

    // 뒤로가기 버튼 (모달에서만, 인라인은 상위 컨테이너에 있음)
    if (!inline) {
        html += `<button class="btn-back" onclick="backToCategorySpecSummary()">← 뒤로가기</button>`;
    }

    // 리테일러 탭
    const retailers = Object.keys(retailerCounts).sort();
    const totalCount = allAnomalies.length;

    html += `<div class="retailer-tabs" style="display: flex; gap: 8px; margin: 16px 0; flex-wrap: wrap;">`;

    // All 탭
    html += `<button class="retailer-tab" onclick="switchMasterTableRetailer('all')" style="padding: 8px 16px; border: 1px solid #d1d5db; border-radius: 6px; cursor: pointer; font-size: 13px; ${selectedRetailer === 'all' ? 'background: #3b82f6; color: white; border-color: #3b82f6;' : 'background: white; color: #374151;'}">
        All <span style="font-weight: 600;">(${totalCount})</span>
    </button>`;

    // 각 리테일러 탭
    retailers.forEach(retailer => {
        const count = retailerCounts[retailer];
        const isActive = selectedRetailer === retailer;
        html += `<button class="retailer-tab" onclick="switchMasterTableRetailer('${escJs(retailer)}')" style="padding: 8px 16px; border: 1px solid #d1d5db; border-radius: 6px; cursor: pointer; font-size: 13px; ${isActive ? 'background: #3b82f6; color: white; border-color: #3b82f6;' : 'background: white; color: #374151;'}">
            ${esc(retailer)} <span style="font-weight: 600;">(${count})</span>
        </button>`;
    });

    html += `</div>`;

    // 제품여부 / 확인완료 필터 (인라인=섹션 페이지에서만)
    if (hasMstId && inline) {
        // 각 필터별 건수 계산 (리테일러 필터 적용 후 기준)
        let cntProduct = 0, cntNonProduct = 0, cntChecked = 0, cntUnchecked = 0;
        retailerFiltered.forEach(row => {
            const p = row.mst_id && specPendingChanges.has(row.mst_id) ? specPendingChanges.get(row.mst_id) : null;
            const ip = p && 'is_product' in p ? p.is_product : row.is_product;
            const ic = p && 'is_checked' in p ? p.is_checked : row.is_checked;
            if (ip === false) cntNonProduct++; else cntProduct++;
            if (ic === true) cntChecked++; else cntUnchecked++;
        });

        const fbtn = (type, value, label, count) => {
            const current = type === 'product' ? fProduct : fChecked;
            const active = current === value;
            return `<button onclick="specSetFilter('${type}','${value}')" style="padding: 4px 12px; border: 1px solid ${active ? '#6b7280' : '#e5e7eb'}; border-radius: 4px; cursor: pointer; font-size: 12px; background: ${active ? '#374151' : 'white'}; color: ${active ? 'white' : '#6b7280'};">${label} (${count})</button>`;
        };

        html += `<div style="display: flex; gap: 16px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;">`;
        html += `<div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 12px; font-weight: 600; color: #6b7280;">제품여부</span>
            ${fbtn('product', 'all', '전체', retailerFiltered.length)}
            ${fbtn('product', 'product', '제품', cntProduct)}
            ${fbtn('product', 'non_product', '비제품', cntNonProduct)}
        </div>`;
        html += `<span style="width: 1px; height: 20px; background: #e5e7eb;"></span>`;
        html += `<div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 12px; font-weight: 600; color: #6b7280;">확인완료</span>
            ${fbtn('checked', 'all', '전체', retailerFiltered.length)}
            ${fbtn('checked', 'checked', '확인완료', cntChecked)}
            ${fbtn('checked', 'unchecked', '미확인', cntUnchecked)}
        </div>`;
        html += `</div>`;
    }

    // Item 목록 추출 (중복 제거)
    const items = [...new Set(filteredData.map(row => row.item).filter(item => item))];

    if (items.length > 0) {
        const tableName = data.table_name || (tableKey === 'hhp' ? 'hhp_item_mst' : 'tv_item_mst');
        const inClauseWithQuotes = items.map(item => `'${item}'`).join(', ');
        const itemListDisplay = items.join(', ');

        let retailerCondition = '';
        if (selectedRetailer !== 'all') {
            retailerCondition = `\n  AND account_name = '${selectedRetailer}'`;
        }

        let selectColumns = 'id, account_name, item, is_product, product_url';
        if (displayColumns.length > 0) {
            selectColumns = displayColumns.map(col => col.key).join(', ');
        }

        const query = `SELECT ${selectColumns}
FROM ${tableName}
WHERE item IN (${inClauseWithQuotes})${retailerCondition}
ORDER BY account_name, item;`;

        html += `
        <div class="query-section">
            <div class="item-list-box">
                <div class="query-box-header">
                    <span class="query-box-title">Item 목록 (${items.length}개)</span>
                    <button class="btn-copy" onclick="copyQueryToClipboard(document.getElementById('spec-item-list'))">복사</button>
                </div>
                <div id="spec-item-list" class="item-list-content">${esc(itemListDisplay)}</div>
            </div>
            <div class="query-box">
                <div class="query-box-header">
                    <span class="query-box-title">조회 쿼리</span>
                    <button class="btn-copy" onclick="copyQueryToClipboard(document.getElementById('spec-query-box'))">복사</button>
                </div>
                <pre id="spec-query-box" class="query-content">${esc(query)}</pre>
            </div>
        </div>`;
    }

    // 데이터 테이블
    if (filteredData.length === 0) {
        html += '<p>해당 리테일러에 대한 이상치 데이터가 없습니다.</p>';
    } else {
        // 변경 건수 저장 바 (인라인=섹션 페이지에서만)
        const pendingCount = specPendingChanges.size;
        if (pendingCount > 0 && inline) {
            html += `
            <div id="spec-save-bar" style="background: #fefce8; border: 2px solid #eab308; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-radius: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #854d0e;">${pendingCount}건 변경됨</span>
                <div style="display: flex; gap: 8px;">
                    ${AppButton.html('취소', 'specCancelChanges', { style: 'cancel', size: 'sm' })}
                    ${AppButton.html('저장', 'specSaveChanges', { style: 'save', size: 'sm' })}
                </div>
            </div>`;
        }
        html += '<div class="table-scroll-container"><table class="detail-table"><thead><tr>';
        html += '<th>No.</th>';

        // display_columns가 없으면 데이터 키에서 자동 생성 (mst_id, is_product, is_checked 제외)
        const hiddenKeys = ['id', 'mst_id', 'is_product', 'is_checked'];
        const cols = displayColumns.length > 0 ? displayColumns
            : Object.keys(filteredData[0] || {}).filter(k => !hiddenKeys.includes(k)).map(k => ({ key: k, label: k }));

        cols.forEach(col => {
            html += `<th>${esc(col.label)}</th>`;
        });
        // is_product / is_checked 토글 컬럼 (인라인=섹션 페이지에서만)
        if (hasMstId && inline) {
            html += '<th style="text-align: center; min-width: 70px; white-space: nowrap;">제품여부</th>';
            html += '<th style="text-align: center; min-width: 70px; white-space: nowrap;">확인완료</th>';
        }
        html += '</tr></thead><tbody>';

        // 페이지네이션 계산
        const totalRows = filteredData.length;
        const totalPages = Math.ceil(totalRows / SPEC_PAGE_SIZE);
        const currentPage = masterTableDetailState.currentPage || 1;
        const startIdx = (currentPage - 1) * SPEC_PAGE_SIZE;
        const endIdx = Math.min(startIdx + SPEC_PAGE_SIZE, totalRows);
        const pageData = filteredData.slice(startIdx, endIdx);

        pageData.forEach((row, idx) => {
            const mstId = row.mst_id;
            const pending = mstId && specPendingChanges.has(mstId) ? specPendingChanges.get(mstId) : null;
            const isProduct = pending && 'is_product' in pending ? pending.is_product : row.is_product;
            const isChecked = pending && 'is_checked' in pending ? pending.is_checked : row.is_checked;
            const isNonProduct = isProduct === false;
            let rowStyle = '';
            if (pending) rowStyle = 'background: #fefce8;';
            else if (isNonProduct) rowStyle = 'opacity: 0.45;';

            html += `<tr style="${rowStyle}">`;
            html += `<td>${startIdx + idx + 1}</td>`;
            cols.forEach(col => {
                const value = row[col.key];
                if (col.key.toLowerCase().includes('url') && value) {
                    html += `<td style="max-width:250px;">${renderProductUrl(value)}</td>`;
                } else {
                    html += `<td>${value !== null && value !== undefined ? esc(String(value)) : '-'}</td>`;
                }
            });
            // is_product + is_checked 토글 (인라인=섹션 페이지에서만)
            if (hasMstId && inline) {
                if (mstId) {
                    if (!specOriginalValues.has(mstId)) {
                        specOriginalValues.set(mstId, { is_product: row.is_product, is_checked: row.is_checked });
                    }
                    const prodChecked = isProduct ? 'checked' : '';
                    const chkChecked = isChecked ? 'checked' : '';
                    html += `<td style="text-align: center;">
                        <input type="checkbox" ${prodChecked} onchange="toggleSpecField(${mstId}, 'is_product', this.checked, '${tableKey}')"
                            style="width: 16px; height: 16px; cursor: pointer; accent-color: #7c3aed;">
                    </td>`;
                    html += `<td style="text-align: center;">
                        <input type="checkbox" ${chkChecked} onchange="toggleSpecField(${mstId}, 'is_checked', this.checked, '${tableKey}')"
                            style="width: 16px; height: 16px; cursor: pointer; accent-color: #059669;">
                    </td>`;
                } else {
                    html += '<td style="text-align: center; color: #9ca3af;" title="마스터 미등록">-</td>';
                    html += '<td style="text-align: center; color: #9ca3af;" title="마스터 미등록">-</td>';
                }
            }
            html += '</tr>';
        });

        html += '</tbody></table></div>';

        // 페이지네이션 컨테이너
        html += `<div id="spec-pagination-container"></div>`;
    }

    // 건수 계산: 리테일러 필터 기준 (제품여부/확인완료 필터 적용 전)
    const displayTotal = retailerFiltered.length;
    let nonProductCount = 0;
    let checkedCount = 0;
    retailerFiltered.forEach(r => {
        const p = r.mst_id && specPendingChanges.has(r.mst_id) ? specPendingChanges.get(r.mst_id) : null;
        const ip = p && 'is_product' in p ? p.is_product : r.is_product;
        const ic = p && 'is_checked' in p ? p.is_checked : r.is_checked;
        if (ip === false) nonProductCount++;
        else if (ic === true) checkedCount++;
    });
    const excludeCount = nonProductCount + checkedCount;
    const activeCount = displayTotal - excludeCount;
    const retailerLabel = selectedRetailer === 'all' ? '전체' : selectedRetailer;
    let countLabel = `${displayTotal}건`;
    if (excludeCount > 0) {
        const parts = [];
        if (nonProductCount > 0) parts.push(`비제품 ${nonProductCount}`);
        if (checkedCount > 0) parts.push(`확인완료 ${checkedCount}`);
        countLabel = `${activeCount}건 (${parts.join(', ')}건 제외)`;
    }
    const hasFilter = fProduct !== 'all' || fChecked !== 'all';
    const filterLabel = hasFilter ? ` [필터: ${filteredData.length}건]` : '';
    const titleText = `${ruleName} - ${retailerLabel} ${countLabel}${filterLabel}`;
    if (inline) {
        const titleEl = document.querySelector('.inline-detail-title');
        const bodyEl = document.querySelector('.inline-detail-body');
        if (titleEl) titleEl.innerHTML = _inlineTitle(titleText);
        if (bodyEl) bodyEl.innerHTML = html;
    } else {
        AppModal.setTitle('detail', titleText);
        AppModal.setBody('detail', html);
    }

    // 페이지네이션 바인딩
    const paginationEl = document.getElementById('spec-pagination-container');
    if (paginationEl && filteredData.length > SPEC_PAGE_SIZE) {
        new Pagination(paginationEl, {
            pageSize: SPEC_PAGE_SIZE,
            onPageChange: (page) => specGoToPage(page)
        }).render(filteredData.length, masterTableDetailState.currentPage || 1);
    }
}

// is_product / is_checked 토글 (통합)
function toggleSpecField(mstId, field, value, tableKey) {
    const original = specOriginalValues.get(mstId) || {};
    const pending = specPendingChanges.get(mstId) || { table: tableKey };
    pending[field] = value;
    pending.table = tableKey;

    // 제품여부 변경 시 확인완료 자동 연동
    if (field === 'is_product') {
        if (value === original.is_product) {
            // 원래 값으로 돌아오면 is_checked도 원복
            delete pending.is_checked;
        } else {
            pending.is_checked = true;
        }
    }

    // 모든 필드가 원본과 같으면 pending에서 제거
    const allSame = Object.keys(original).every(k => {
        if (!(k in pending)) return true;
        return pending[k] === original[k];
    });
    if (allSame) {
        specPendingChanges.delete(mstId);
    } else {
        specPendingChanges.set(mstId, pending);
    }

    if (isCatSpecInline()) {
        const scrollY = window.scrollY;
        renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);
        window.scrollTo(0, scrollY);
    } else {
        const modalBody = AppModal.getBody('detail');
        const scrollTop = modalBody.scrollTop;
        renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);
        modalBody.scrollTop = scrollTop;
    }
}

// 하위 호환 (기존 호출 유지)
function toggleSpecIsProduct(mstId, isProduct, tableKey) {
    toggleSpecField(mstId, 'is_product', isProduct, tableKey);
}

// 변경 취소 후 뒤로가기 (인라인 규칙 상세에서)
function specCancelAndBack() {
    specPendingChanges.clear();
    specOriginalValues.clear();
    ViewStack.pop();
}

// 변경 취소
function specCancelChanges() {
    specPendingChanges.clear();
    specOriginalValues.clear();
    renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);
}

// 변경 저장
async function specSaveChanges() {
    if (specPendingChanges.size === 0) return;

    // table별로 그룹화
    const byTable = {};
    specPendingChanges.forEach((val, mstId) => {
        const t = val.table || 'tv';
        if (!byTable[t]) byTable[t] = [];
        const change = { id: mstId };
        if ('is_product' in val) change.is_product = val.is_product;
        if ('is_checked' in val) change.is_checked = val.is_checked;
        byTable[t].push(change);
    });

    try {
        for (const [tableKey, changes] of Object.entries(byTable)) {
            const res = await fetch('/dx/data/api/item-master/save/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ table: tableKey, changes, user_id: window.LAYER3.username || '' })
            });
            const result = await res.json();
            if (result.error) {
                showToast(result.error, 'error');
                return;
            }
        }

        showToast(`${specPendingChanges.size}건 저장 완료`, 'success');

        // anomalies / retailer_data에 변경 반영
        const applyChanges = (row) => {
            if (!row.mst_id || !specPendingChanges.has(row.mst_id)) return;
            const p = specPendingChanges.get(row.mst_id);
            if ('is_product' in p) row.is_product = p.is_product;
            if ('is_checked' in p) row.is_checked = p.is_checked;
        };
        (masterTableDetailState.data.anomalies || []).forEach(applyChanges);
        const rd = masterTableDetailState.data.retailer_data || {};
        Object.values(rd).forEach(rows => rows.forEach(applyChanges));

        specPendingChanges.clear();
        specOriginalValues.clear();
        renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);

    } catch (e) {
        showToast('저장 실패: ' + e.message, 'error');
    }
}

// 필터 전환
function specSetFilter(type, value) {
    if (type === 'product') masterTableDetailState.filterProduct = value;
    else if (type === 'checked') masterTableDetailState.filterChecked = value;
    masterTableDetailState.currentPage = 1;
    renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);
}

// 리테일러 탭 전환
function switchMasterTableRetailer(retailer) {
    masterTableDetailState.currentRetailer = retailer;
    masterTableDetailState.currentPage = 1;
    renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, retailer);
}

function specGoToPage(page) {
    masterTableDetailState.currentPage = page;
    renderCategorySpecDetail(masterTableDetailState.data, masterTableDetailState.ruleName, masterTableDetailState.currentRetailer);
    // 테이블 상단으로 스크롤
    const tableEl = document.querySelector('.table-scroll-container');
    if (tableEl) tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 카테고리별 특성 규칙 요약으로 돌아가기
function backToCategorySpecSummary() {
    specPendingChanges.clear();
    specOriginalValues.clear();
    if (isCatSpecInline()) {
        ViewStack.pop();
        return;
    }
    if (window.categorySpecSummaryData && window.categorySpecTitle) {
        AppModal.setTitle('detail', window.categorySpecTitle + ` (${window.categorySpecSummaryData.total_anomalies}건)`);
        renderDetailModal(window.categorySpecTitle, '카테고리별 특성', window.categorySpecSummaryData);
    }
}
