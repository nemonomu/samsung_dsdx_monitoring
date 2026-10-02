/* ================================================================
 *  DS Layer4 – report.js
 *  보고서 테이블 렌더링, 현황 테이블, 이상치 관리, 메모 저장, 마감/취소
 * ================================================================ */

function renderReportTable(data) {
    const content = document.getElementById('reportContent');
    const actions = document.getElementById('reportActions');

    if (data.daily_reports.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <line x1="16" y1="13" x2="8" y2="13"/>
                    <line x1="16" y1="17" x2="8" y2="17"/>
                </svg>
                <h3>저장된 보고서가 없습니다</h3>
                <p>검수 페이지에서 리테일러별로 저장을 먼저 진행해주세요.</p>
            </div>
        `;
        actions.innerHTML = '';
        return;
    }

    renderStatusTable(data);
}

// 현황 탭 렌더링 (체크박스로 선택 후 저장)
function renderStatusTable(data) {
    const content = document.getElementById('reportContent');

    // 리테일러별 원인 건수 (서버에서 계산된 데이터 사용)
    const causeSummaryByRetailer = data.cause_summary || {};
    const anomaliesByRetailer = new Map();
    (data.anomalies || []).forEach(anomaly => {
        if (!anomaliesByRetailer.has(anomaly.retailer)) anomaliesByRetailer.set(anomaly.retailer, []);
        anomaliesByRetailer.get(anomaly.retailer).push(anomaly);
    });

    let html = `
        <table class="report-table" id="statusTable">
            <thead>
                <tr>
                    ${isClosed ? '' : '<th class="text-center" style="width: 40px;"><input type="checkbox" id="statusSelectAll" class="memo-checkbox" onchange="toggleStatusSelectAll()"></th>'}
                    <th>리테일러</th>
                    <th class="text-center">총 건수</th>
                    <th class="text-center">이상치</th>
                    <th class="text-center">캡쳐</th>
                    <th style="min-width: 300px;">메모</th>
                    <th class="text-center">상세</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.daily_reports.forEach((report, idx) => {
        const anomalies = anomaliesByRetailer.get(report.retailer) || [];
        const missingCauseCount = anomalies.filter(row => !normalizeReportCause(row.cause)).length;
        const escMemo = (report.memo || '').replace(/"/g, '&quot;');
        // 원인별 현황 텍스트 생성
        const causeCounts = causeSummaryByRetailer[report.retailer] || {};
        const causeSummary = Object.entries(causeCounts)
            .map(([cause, count]) => `${cause}(${count}건)`)
            .join(', ') || '';
        const escCauseSummary = causeSummary.replace(/"/g, '&quot;');

        html += `
            <tr class="retailer-row" data-retailer="${esc(report.retailer)}">
                ${isClosed ? '' : `
                <td class="text-center">
                    <input type="checkbox" id="statusCheck_${report.id}" class="memo-checkbox status-checkbox" onchange="toggleStatusInput(${report.id})" data-cause-summary="${escCauseSummary}">
                </td>
                `}
                <td class="report-retailer-cell" onclick="openReportRetailerDetail(${Number(report.id)})">
                    <button type="button" class="report-retailer-toggle" aria-expanded="false" aria-controls="anomalyDetails${idx}">
                        <svg class="expand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>
                        <strong>${esc(report.retailer)}</strong>
                    </button>
                </td>
                <td class="text-center">${report.total_count?.toLocaleString() || 0}</td>
                <td class="text-center" style="color: ${report.anomaly_total > 0 ? '#dc2626' : '#16a34a'}; font-weight: 600;">
                    ${report.anomaly_total || 0}
                </td>
                <td class="text-center">
                    ${renderCaptureButton(report)}
                </td>
                <td>
                    <input type="text" id="statusMemo_${report.id}" class="inline-input" value="${escMemo}" placeholder="메모 입력" disabled data-original="${escMemo}">
                </td>
                <td class="text-center">
                    ${AppButton.iconHtml('info', "showStatusDetail('" + report.retailer + "', '" + (report.created_id || '-') + "', '" + (report.created_at || '-') + "')", { size: 'sm', bg: '#6b7280', title: '상세보기' })}
                </td>
            </tr>
            <tr class="anomaly-details" id="anomalyDetails${idx}">
                <td colspan="${isClosed ? 6 : 7}">
                    <div class="anomaly-list">
                        ${missingCauseCount ? `<div style="margin-bottom:12px;"><span class="missing-cause-badge">원인 미선택 ${missingCauseCount}건</span></div>` : ''}
                        ${renderAnomalyItems(anomalies, report.retailer)}
                    </div>
                </td>
            </tr>
        `;
    });

    html += '</tbody></table>';

    content.innerHTML = html;

    // 저장 버튼 (마감 전에만, 별도 영역에 렌더링)
    const actions = document.getElementById('reportActions');
    if (!isClosed && data.daily_reports.length > 0) {
        actions.innerHTML = `<button class="app-btn app-btn-md app-btn-primary" style="min-width:80px;" onclick="saveStatusMemos()">저장</button>`;
    } else {
        actions.innerHTML = '';
    }

    // 컬럼 리사이즈 적용
    const table = content.querySelector('.report-table');
    if (table) enableColumnResize(table);
    restoreExpandedAccordions();
}

function getCheckedStatusMemo(checkbox, memoInput) {
    const causeSummary = checkbox?.dataset?.causeSummary || '';
    return causeSummary || memoInput?.dataset?.original || '';
}

// 현황 전체 선택/해제
function toggleStatusSelectAll() {
    const selectAll = document.getElementById('statusSelectAll');
    const checkboxes = document.querySelectorAll('.status-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = selectAll.checked;
        const id = cb.id.replace('statusCheck_', '');
        const memoInput = document.getElementById(`statusMemo_${id}`);
        if (memoInput) {
            memoInput.disabled = !selectAll.checked;
            if (selectAll.checked) {
                memoInput.value = getCheckedStatusMemo(cb, memoInput);
            } else {
                memoInput.value = memoInput.dataset.original || '';
            }
        }
    });
}

// 현황 개별 체크박스 토글
function toggleStatusInput(dailyId) {
    const checkbox = document.getElementById(`statusCheck_${dailyId}`);
    const memoInput = document.getElementById(`statusMemo_${dailyId}`);
    if (checkbox && memoInput) {
        memoInput.disabled = !checkbox.checked;
        if (checkbox.checked) {
            memoInput.value = getCheckedStatusMemo(checkbox, memoInput);
            memoInput.focus();
        } else {
            memoInput.value = memoInput.dataset.original || '';
        }
    }
    updateStatusSelectAllState();
}

// 전체 선택 체크박스 상태 동기화
function updateStatusSelectAllState() {
    const selectAll = document.getElementById('statusSelectAll');
    const checkboxes = document.querySelectorAll('.status-checkbox');
    if (!selectAll || checkboxes.length === 0) return;
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    const someChecked = Array.from(checkboxes).some(cb => cb.checked);
    selectAll.checked = allChecked;
    selectAll.indeterminate = someChecked && !allChecked;
}

function renderCauseHistory(anomaly) {
    const history = anomaly.cause_history;
    if (!history || history.status === 'none' || history.status === 'unrecorded') {
        return `<div class="cause-history cause-history-empty">${normalizeReportCause(anomaly.cause)
            ? '원인 적용 출처 미기록 · 확인 가능한 과거 기록 없음'
            : '적용 가능한 과거 기록 없음 · 확인 필요'}</div>`;
    }
    if (history.status === 'manual') {
        return `<div class="cause-history"><div class="cause-history-header">
            <span class="cause-history-badge">이번 검수에서 직접 입력</span>
            <span class="cause-history-meta">${esc(history.applied_at || '')} · ${esc(history.applied_by || '-')}</span>
        </div></div>`;
    }
    const source = history.source;
    if (!source) return '<div class="cause-history cause-history-empty">원인 적용 출처 미기록</div>';
    const value = raw => raw == null || String(raw).trim() === ''
        ? '<span class="null-value">NULL</span>' : esc(String(raw));
    const label = history.status === 'automatic' ? '과거 원인 자동 적용' : '과거 동일 조건 기록';
    return `<div class="cause-history">
        <div class="cause-history-header">
            <span class="cause-history-badge">${label}</span>
            <span class="cause-history-meta">${esc(source.crawl_date || '-')} · 기록자 ${esc(source.updated_id || source.created_id || '-')}</span>
        </div>
        <dl class="cause-history-fields">
            <div><dt>SKU</dt><dd>${value(source.retailersku)}</dd></div>
            <div class="cause-history-title"><dt>제목</dt><dd>${value(source.title)}</dd></div>
            <div><dt>가격</dt><dd>${value(source.retailprice)}</dd></div>
            <div><dt>Ships From</dt><dd>${value(source.ships_from)}</dd></div>
            <div><dt>Sold By</dt><dd>${value(source.sold_by)}</dd></div>
        </dl>
        <div class="cause-history-footer">
            <div class="cause-history-reason"><span>당시 원인</span><strong>${value(source.cause)}</strong></div>
            ${source.screenshot_id ? `<button type="button" class="cause-history-screenshot" onclick="showCauseHistoryScreenshot(${Number(anomaly.id)})">📷 과거 캡처 보기</button>` : '<span class="cause-history-note">과거 캡처 없음</span>'}
        </div>
    </div>`;
}

function renderAnomalyItems(anomalies, retailer) {
    if (anomalies.length === 0) {
        return '<div style="text-align: center; color: var(--text-secondary); padding: 20px;">저장된 이상치가 없습니다.</div>';
    }

    const escRetailer = retailer.replace(/'/g, "\\'");
    const safeRetailerId = retailer.replace(/[^a-zA-Z0-9]/g, '_');
    // 조회/저장 후 렌더링할 때만 정렬한다. 입력 중에는 행을 이동하지 않는다.
    const sortedAnomalies = [...anomalies].sort((a, b) =>
        Number(Boolean(normalizeReportCause(a.cause))) - Number(Boolean(normalizeReportCause(b.cause)))
    );
    const anomalyIds = sortedAnomalies.map(a => a.id);

    let html = `
        <table class="anomaly-table" data-retailer="${retailer}" data-anomaly-ids="${anomalyIds.join(',')}">
            <thead>
                <tr>
                    ${isClosed ? '' : `<th style="width: 35px;"><input type="checkbox" id="anomalySelectAll_${safeRetailerId}" class="memo-checkbox" onchange="toggleAnomalySelectAll('${escRetailer}', '${safeRetailerId}')"></th>`}
                    <th style="width: 100px;">SKU</th>
                    <th style="width: 150px;">제목</th>
                    <th style="width: 80px;">가격</th>
                    <th style="width: 100px;">Ships From</th>
                    <th style="width: 100px;">Sold By</th>
                    <th style="width: 45px;">URL</th>
                    <th style="width: 60px;">스크린샷</th>
                    <th style="width: 200px;">
                        <div>원인</div>
                        ${!isClosed ? `<select id="bulkCause_${safeRetailerId}" class="inline-select" style="width: 100%; margin-top: 4px; display: none;" onchange="applyBulkCause(this, '${safeRetailerId}')">
                            <option value="" disabled selected>일괄 적용</option>
                            <option value="__clear__">해제</option>
                            ${(causeOptions[retailer] || []).map(opt => '<option value="' + opt + '">' + opt + '</option>').join('')}
                        </select>` : ''}
                    </th>
                    <th>원인 적용 이력</th>
                </tr>
            </thead>
            <tbody>
    `;

    sortedAnomalies.forEach(a => {
        const missingCause = !normalizeReportCause(a.cause);
        const escTitle = (a.title || '(제목 없음)').replace(/"/g, '&quot;');
        const escShipsFrom = (a.ships_from || 'NULL').replace(/"/g, '&quot;');
        const escSoldBy = (a.sold_by || 'NULL').replace(/"/g, '&quot;');
        html += `
            <tr class="${missingCause ? 'missing-cause-row' : ''}">
                ${isClosed ? '' : `
                <td class="text-center">
                    <input type="checkbox" id="anomalyCheck_${a.id}" class="memo-checkbox anomaly-checkbox anomaly-checkbox-${safeRetailerId}" onchange="toggleAnomalyInput(${a.id}, '${safeRetailerId}')">
                </td>
                `}
                <td class="text-center">${a.retailersku || '-'}</td>
                <td class="title-cell" title="${escTitle}">${a.title || '(제목 없음)'}</td>
                <td class="${!a.retailprice ? 'null-value' : ''}">${a.retailprice || 'NULL'}</td>
                <td class="overflow-cell ${!a.ships_from ? 'null-value' : ''}" title="${escShipsFrom}">${a.ships_from || 'NULL'}</td>
                <td class="overflow-cell ${!a.sold_by ? 'null-value' : ''}" title="${escSoldBy}">${a.sold_by || 'NULL'}</td>
                <td class="text-center">
                    ${a.producturl ? AppButton.iconHtml('copy', `copyProductUrl('${a.producturl.replace(/'/g, "\\'")}', this)`, { style: 'ghost', title: '링크 복사' }) : '-'}
                </td>
                <td class="text-center">
                    ${a.screenshot_id
                        ? AppButton.iconHtml('📷', `showScreenshot(${a.screenshot_id}, ${a.id})`, { style: 'ghost', title: '스크린샷 보기' })
                        : (!isClosed ? AppButton.iconHtml('📤', `triggerUpload(${a.id})`, { style: 'ghost', title: '수동 업로드' }) : '-')
                    }
                </td>
                <td>
                    <select id="cause_${a.id}" class="inline-select" ${isClosed ? 'disabled' : 'disabled'}>
                        ${getCauseOptionsHtml(a.retailer, a.cause)}
                    </select>
                    ${missingCause ? '<span class="missing-cause-hint">원인 미선택 · 확인 필요</span>' : ''}
                </td>
                <td>
                    ${renderCauseHistory(a)}
                </td>
            </tr>
        `;
    });

    html += '</tbody></table>';

    // 저장 버튼 추가 (마감 전에만)
    if (!isClosed) {
        html += `
            <div style="text-align: right; margin-top: 12px;">
                ${AppButton.html('저장', `saveCheckedAnomalies('${escRetailer}')`, { style: 'teal', size: 'sm', padding: '8px 16px' })}
            </div>
        `;
    }
    return html;
}

// 전체 이상치 테이블 렌더링
function renderAllAnomaliesTable(data) {
    const content = document.getElementById('reportContent');

    if (data.anomalies.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <h3>이상치가 없습니다</h3>
                <p>저장된 이상치 데이터가 없습니다.</p>
            </div>
        `;
        return;
    }

    let html = `
        <table class="all-anomaly-table">
            <thead>
                <tr>
                    <th style="width: 45px;">ID</th>
                    <th style="width: 100px;">리테일러</th>
                    <th style="width: 150px;">제목</th>
                    <th style="width: 80px;">가격</th>
                    <th style="width: 100px;">Ships From</th>
                    <th style="width: 100px;">Sold By</th>
                    <th style="width: 50px;">이미지</th>
                    <th style="width: 200px;">원인</th>
                    <th>원인 적용 이력</th>
                    ${isClosed ? '' : '<th style="width: 60px;">관리</th>'}
                </tr>
            </thead>
            <tbody>
    `;

    data.anomalies.forEach(a => {
        const escTitle = (a.title || '(제목 없음)').replace(/"/g, '&quot;');
        const escShipsFrom = (a.ships_from || 'NULL').replace(/"/g, '&quot;');
        const escSoldBy = (a.sold_by || 'NULL').replace(/"/g, '&quot;');
        html += `
            <tr>
                <td class="text-center">${a.id}</td>
                <td><span class="retailer-badge">${a.retailer}</span></td>
                <td class="title-cell" title="${escTitle}">${a.title || '<span class="null-value">(제목 없음)</span>'}</td>
                <td class="${!a.retailprice ? 'null-value' : ''}">${a.retailprice || 'NULL'}</td>
                <td class="overflow-cell ${!a.ships_from ? 'null-value' : ''}" title="${escShipsFrom}">${a.ships_from || 'NULL'}</td>
                <td class="overflow-cell ${!a.sold_by ? 'null-value' : ''}" title="${escSoldBy}">${a.sold_by || 'NULL'}</td>
                <td class="text-center ${!a.imageurl ? 'null-value' : ''}">
                    ${a.imageurl ? `<a href="${a.imageurl}" target="_blank" style="color: #2563eb;">보기</a>` : 'NULL'}
                </td>
                <td>
                    <select id="cause_all_${a.id}" class="inline-select" ${isClosed ? 'disabled' : ''}>
                        ${getCauseOptionsHtml(a.retailer, a.cause)}
                    </select>
                </td>
                <td>
                    ${renderCauseHistory(a)}
                </td>
                ${isClosed ? '' : `
                <td class="text-center">
                    ${AppButton.html('저장', `saveAnomalyAll(${a.id})`, { style: 'teal', size: 'sm', padding: '8px 16px' })}
                </td>
                `}
            </tr>
        `;
    });

    html += '</tbody></table>';
    content.innerHTML = html;

    // 컬럼 리사이즈 적용
    const table = content.querySelector('.all-anomaly-table');
    if (table) enableColumnResize(table);
}

// 전체 뷰에서 저장
async function saveAnomalyAll(anomalyId) {
    if (isClosed) return;

    const cause = document.getElementById(`cause_all_${anomalyId}`).value;

    // 원인 필수 입력 검증
    if (!cause) {
        showToast('원인을 입력하여 주세요.', 'warning');
        document.getElementById(`cause_all_${anomalyId}`).focus();
        return;
    }

    try {
        const response = await fetch('/ds/layer4/api/update/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                anomaly_id: anomalyId,
                cause: cause,
                user_id: currentUserId
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast('저장되었습니다.');
            // 요약 업데이트
            loadReportList();
        } else {
            showToast(result.error || '저장 실패');
        }
    } catch (error) {
        console.error('Save error:', error);
        showToast('저장 중 오류 발생');
    }
}

function toggleAnomalies(idx, retailer) {
    const row = document.querySelectorAll('.retailer-row')[idx];
    const details = document.getElementById(`anomalyDetails${idx}`);

    if (!row || !details) return;
    const expanded = !expandedRetailers.has(retailer);
    row.classList.toggle('expanded', expanded);
    details.classList.toggle('show', expanded);
    row.querySelector('.report-retailer-toggle').setAttribute('aria-expanded', String(expanded));

    // 펼쳐진 상태 추적
    if (expanded) {
        expandedRetailers.add(retailer);
        // 컬럼 리사이즈 적용 (최초 1회)
        const table = details.querySelector('.anomaly-table');
        if (table && !table.dataset.resizeApplied) {
            enableColumnResize(table);
            table.dataset.resizeApplied = 'true';
        }
    } else {
        expandedRetailers.delete(retailer);
    }
}

// 펼쳐진 아코디언 복원
function restoreExpandedAccordions() {
    if (expandedRetailers.size === 0) return;

    const rows = document.querySelectorAll('.retailer-row');
    rows.forEach((row, idx) => {
        const retailer = row.dataset.retailer;
        if (retailer && expandedRetailers.has(retailer)) {
            const details = document.getElementById(`anomalyDetails${idx}`);
            if (details) {
                row.classList.add('expanded');
                details.classList.add('show');
                row.querySelector('.report-retailer-toggle').setAttribute('aria-expanded', 'true');
                // 컬럼 리사이즈 적용
                const table = details.querySelector('.anomaly-table');
                if (table && !table.dataset.resizeApplied) {
                    enableColumnResize(table);
                    table.dataset.resizeApplied = 'true';
                }
            }
        }
    });
}

// 현황 탭: 체크된 메모만 저장
async function saveStatusMemos() {
    if (isClosed) return;

    // 체크된 항목의 메모만 수집
    const memos = [];
    document.querySelectorAll('.status-checkbox:checked').forEach(checkbox => {
        const dailyId = checkbox.id.replace('statusCheck_', '');
        const memoInput = document.getElementById(`statusMemo_${dailyId}`);
        if (memoInput) {
            memos.push({
                daily_id: parseInt(dailyId),
                memo: memoInput.value
            });
        }
    });

    if (memos.length === 0) {
        showToast('저장할 항목을 선택해주세요.', 'warning');
        return;
    }

    try {
        const response = await fetch('/ds/layer4/api/daily-update/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                memos: memos,
                user_id: currentUserId
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message || '저장되었습니다.');
            // 체크박스 해제 및 입력 비활성화, 원본값 업데이트
            memos.forEach(m => {
                const checkbox = document.getElementById(`statusCheck_${m.daily_id}`);
                const input = document.getElementById(`statusMemo_${m.daily_id}`);
                if (checkbox) checkbox.checked = false;
                if (input) {
                    input.disabled = true;
                    input.dataset.original = input.value;
                }
            });
            // 전체 선택 체크박스 상태 업데이트
            updateStatusSelectAllState();
        } else {
            showToast(result.error || '저장 실패', 'error');
        }
    } catch (error) {
        console.error('Save status memos error:', error);
        showToast('저장 중 오류 발생', 'error');
    }
}

// 헤더 원인 드롭다운 표시/숨김
function toggleBulkCause(safeRetailerId) {
    const bulkCause = document.getElementById(`bulkCause_${safeRetailerId}`);
    if (!bulkCause) return;
    const hasChecked = document.querySelectorAll(`.anomaly-checkbox-${safeRetailerId}:checked`).length > 0;
    bulkCause.style.display = hasChecked ? '' : 'none';
}

// 헤더 원인 드롭다운 → 체크된 행 일괄 적용
function applyBulkCause(selectEl, safeRetailerId) {
    const value = selectEl.value === '__clear__' ? '' : selectEl.value;
    const checkboxes = document.querySelectorAll(`.anomaly-checkbox-${safeRetailerId}:checked`);
    checkboxes.forEach(cb => {
        const anomalyId = cb.id.replace('anomalyCheck_', '');
        const causeEl = document.getElementById(`cause_${anomalyId}`);
        if (causeEl) causeEl.value = value;
    });
    selectEl.selectedIndex = 0;
}

// 이상치 전체 선택/해제 (리테일러별)
function toggleAnomalySelectAll(retailer, safeRetailerId) {
    const selectAll = document.getElementById(`anomalySelectAll_${safeRetailerId}`);
    const checkboxes = document.querySelectorAll(`.anomaly-checkbox-${safeRetailerId}`);
    checkboxes.forEach(cb => {
        cb.checked = selectAll.checked;
        const anomalyId = cb.id.replace('anomalyCheck_', '');
        const causeSelect = document.getElementById(`cause_${anomalyId}`);
        if (causeSelect) causeSelect.disabled = !selectAll.checked;
    });
    toggleBulkCause(safeRetailerId);
}

// 이상치 체크박스 토글 시 원인/메모 입력 활성화/비활성화
function toggleAnomalyInput(anomalyId, safeRetailerId) {
    const checkbox = document.getElementById(`anomalyCheck_${anomalyId}`);
    const causeSelect = document.getElementById(`cause_${anomalyId}`);
    if (checkbox) {
        if (causeSelect) causeSelect.disabled = !checkbox.checked;
        if (checkbox.checked && causeSelect) causeSelect.focus();
    }
    toggleBulkCause(safeRetailerId);
    // 전체 선택 체크박스 상태 업데이트
    if (safeRetailerId) {
        updateAnomalySelectAllState(safeRetailerId);
    }
}

// 이상치 전체 선택 체크박스 상태 동기화
function updateAnomalySelectAllState(safeRetailerId) {
    const selectAll = document.getElementById(`anomalySelectAll_${safeRetailerId}`);
    const checkboxes = document.querySelectorAll(`.anomaly-checkbox-${safeRetailerId}`);
    if (!selectAll || checkboxes.length === 0) return;
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    const someChecked = Array.from(checkboxes).some(cb => cb.checked);
    selectAll.checked = allChecked;
    selectAll.indeterminate = someChecked && !allChecked;
}

// 체크된 이상치만 저장
async function saveCheckedAnomalies(retailer) {
    if (isClosed) return;

    // 해당 리테일러의 anomaly 테이블 찾기
    const table = document.querySelector(`.anomaly-table[data-retailer="${retailer}"]`);
    if (!table) {
        showToast('저장할 데이터를 찾을 수 없습니다.', 'error');
        return;
    }

    // 체크된 행의 데이터만 수집
    const updates = [];
    let missingCauseId = null;
    table.querySelectorAll('.anomaly-checkbox:checked').forEach(checkbox => {
        const anomalyId = parseInt(checkbox.id.replace('anomalyCheck_', ''));
        const causeEl = document.getElementById(`cause_${anomalyId}`);
        if (causeEl) {
            // 원인 필수 입력 검증
            if (!causeEl.value && !missingCauseId) {
                missingCauseId = anomalyId;
            }
            updates.push({
                anomaly_id: anomalyId,
                cause: causeEl.value
            });
        }
    });

    if (updates.length === 0) {
        showToast('저장할 항목을 선택해주세요.', 'warning');
        return;
    }

    // 원인 미입력 항목이 있으면 저장 중단
    if (missingCauseId) {
        showToast('원인을 입력하여 주세요.', 'warning');
        document.getElementById(`cause_${missingCauseId}`).focus();
        return;
    }

    try {
        const response = await fetch('/ds/layer4/api/update/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                updates: updates,
                user_id: currentUserId
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message || '저장되었습니다.');
            // 체크박스 해제 및 입력 비활성화
            const safeRetailerId = retailer.replace(/[^a-zA-Z0-9]/g, '_');
            table.querySelectorAll('.anomaly-checkbox:checked').forEach(checkbox => {
                checkbox.checked = false;
                const anomalyId = checkbox.id.replace('anomalyCheck_', '');
                const causeEl = document.getElementById(`cause_${anomalyId}`);
                if (causeEl) causeEl.disabled = true;
            });
            // 전체 선택 체크박스 상태 업데이트
            updateAnomalySelectAllState(safeRetailerId);
            // 요약 업데이트
            loadReportList();
        } else {
            showToast(result.error || '저장 실패', 'error');
        }
    } catch (error) {
        console.error('Save checked anomalies error:', error);
        showToast('저장 중 오류 발생', 'error');
    }
}

// 일괄현황 저장
// 파일용량 저장
async function saveFileInfo() {
    const date = document.getElementById('targetDate').value;
    const confirmed = await showConfirm('파일용량을 저장하시겠습니까?', 'info');
    if (!confirmed) return;

    const saveFileInfoBtn = document.getElementById('saveFileInfoBtn');
    if (saveFileInfoBtn) saveFileInfoBtn.disabled = true;

    try {
        const response = await fetch('/ds/layer4/api/save-file-info/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                crawl_date: date,
                user_id: currentUserId
            })
        });

        const result = await response.json();
        if (saveFileInfoBtn) saveFileInfoBtn.disabled = false;

        if (result.success) {
            showToast(result.message || '파일 정보 저장 완료');
            
            if (currentReportView === 'file') {
                loadFileTab();
            } else {
                loadReportList();
            }
        } else {
            showToast(result.error || '저장 실패', 'error');
            if (saveFileInfoBtn) saveFileInfoBtn.disabled = false;
        }
    } catch (error) {
        console.error('Save file info error:', error);
        showToast('저장 중 오류 발생', 'error');
        if (saveFileInfoBtn) saveFileInfoBtn.disabled = false;
    }
}

let reportOutputDate = null;
let reportOutputData = null;
let reportClosing = false;

async function closeReport() {
    if (reportClosing || isClosed) return;
    const date = reportOutputDate;
    if (!date || date !== document.getElementById('targetDate').value || !reportOutputData) {
        showToast('보고서 출력을 다시 열어주세요.', 'warning');
        return;
    }
    const rawContent = document.getElementById('reportOutputContent').innerHTML;
    if (!rawContent.trim()) return;
    const content = rawContent.replace(/<h2[^>]*>.*?<\/h2>/i, '').replace(/<h3 /g, '<br><h3 ');
    const totalRetailers = reportOutputData.total_retailers || 0;
    const savedCount = reportOutputData.daily_reports.length;
    const fileSavedCount = reportOutputData.daily_reports.filter(r => r.file_size > 0).length;

    // 현황 저장 완료 체크 (전체 리테일러)
    if (!totalRetailers || savedCount < totalRetailers) {
        showToast(`현황 저장이 완료되지 않았습니다. (${savedCount}/${totalRetailers})`, 'warning');
        return;
    }

    // 이상치 있는 리테일러 메모 체크
    const noMemoRetailers = reportOutputData.daily_reports
        .filter(r => r.anomaly_total > 0 && !r.memo?.trim());
    if (noMemoRetailers.length > 0) {
        const names = noMemoRetailers.map(r => r.retailer).join(', ');
        showToast(`이상치 있는 리테일러에 메모를 작성해주세요.\n(${names})`, 'warning');
        return;
    }

    const btn = document.getElementById('closeReportBtn');
    reportClosing = true;
    btn.disabled = true;
    try {
        const confirmed = await showConfirm(`${date} 날짜를 마감하시겠습니까?\n\n현황 저장: ${savedCount}/${totalRetailers}개\n파일용량 저장: ${fileSavedCount}/${totalRetailers}개\n\n보고서를 자동 저장하고 링크를 복사합니다.\n마감 후 수정이 필요한 경우 마감 취소가 필요합니다.`, 'warning');
        if (!confirmed) return;
        btn.textContent = '마감 중...';
        const response = await fetch('/ds/layer4/api/close/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                crawl_date: date,
                content: content
            })
        });

        const result = await response.json();
        if (!result.success) {
            showToast(result.error || '마감 실패', 'error');
            return;
        }
        isClosed = true;
        document.getElementById('reportOutputOverlay').classList.remove('show');
        const notice = document.getElementById('reportLinkNotice');
        const link = new URL(result.document_url, window.location.origin).href;
        document.getElementById('closedReportLink').value = link;
        notice.dataset.date = date;
        notice.classList.remove('hidden');
        try {
            await copyReportLink(link);
            showToast('마감되었습니다. 보고서 링크가 복사되었습니다.', 'success');
        } catch (error) {
            showToast('마감되었습니다. 링크를 복사해주세요.', 'warning');
        }
        await loadReportList();
    } catch (error) {
        console.error('Close error:', error);
        showToast('마감 결과를 확인하지 못했습니다. 새로 조회하여 마감 상태를 확인해주세요.', 'error');
    } finally {
        reportClosing = false;
        btn.disabled = isClosed;
        btn.textContent = isClosed ? '마감 완료' : '마감';
    }
}

// 복사 실패를 성공으로 표시하지 않도록 execCommand의 반환값도 확인한다.
async function copyReportLink(link) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(link);
            return;
        } catch (error) { /* HTTP/권한 제한 환경에서는 선택 복사 시도 */ }
    }
    const input = document.getElementById('closedReportLink');
    input.focus();
    input.select();
    if (!document.execCommand('copy')) throw new Error('Clipboard copy failed');
}

async function copyClosedReportLink() {
    try {
        await copyReportLink(document.getElementById('closedReportLink').value);
        showToast('보고서 링크가 복사되었습니다.', 'success');
    } catch (error) {
        showToast('링크를 선택한 후 Ctrl+C로 복사해주세요.', 'warning');
    }
}

function cancelClose() {
    const date = document.getElementById('targetDate').value;

    // 사유 입력 다이얼로그
    var existing = document.getElementById('confirmOverlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'confirmOverlay';
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.45); z-index:10002; display:flex; justify-content:center; align-items:center;';
    overlay.innerHTML =
        '<div style="background:#fff; border-radius:12px; padding:28px 32px 20px; min-width:360px; max-width:480px; box-shadow:0 12px 40px rgba(0,0,0,0.25); text-align:center;">' +
            '<div style="margin-bottom:12px;"><svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" width="40" height="40"><path d="M12 9v2m0 4h.01M5.07 19H19a2 2 0 0 0 1.75-2.96L13.74 4a2 2 0 0 0-3.5 0L3.32 16.04A2 2 0 0 0 5.07 19z"/></svg></div>' +
            '<div style="font-size:15px; font-weight:500; color:#1a1a1a; line-height:1.5; margin-bottom:16px;">' + date + ' 마감을 취소하시겠습니까?</div>' +
            '<textarea id="cancelMemoInput" placeholder="취소 사유를 입력하세요" style="width:100%; height:80px; border:1px solid #d1d5db; border-radius:8px; padding:10px; font-size:14px; resize:vertical; box-sizing:border-box; margin-bottom:4px;"></textarea>' +
            '<div id="cancelMemoError" style="font-size:13px; color:#ef4444; text-align:left; margin-bottom:12px; display:none;">취소 사유를 입력하세요.</div>' +
            '<div style="display:flex; gap:10px; justify-content:center;">' +
                '<button id="confirmOk" style="padding:9px 28px; border-radius:8px; font-size:14px; font-weight:600; border:none; cursor:pointer; background:#ef4444; color:#fff;">확인</button>' +
                '<button id="confirmCancel" style="padding:9px 28px; border-radius:8px; font-size:14px; font-weight:600; border:none; cursor:pointer; background:#f3f4f6; color:#1a1a1a;">취소</button>' +
            '</div>' +
        '</div>';
    document.body.appendChild(overlay);

    document.getElementById('cancelMemoInput').focus();

    document.getElementById('confirmOk').onclick = async function() {
        var memo = document.getElementById('cancelMemoInput').value.trim();
        if (!memo) {
            document.getElementById('cancelMemoInput').style.borderColor = '#ef4444';
            document.getElementById('cancelMemoError').style.display = 'block';
            document.getElementById('cancelMemoInput').focus();
            return;
        }
        overlay.remove();

        try {
            const response = await fetch('/ds/layer4/api/cancel-close/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({
                    crawl_date: date,
                    user_id: currentUserId,
                    memo: memo
                })
            });

            const result = await response.json();
            if (result.success) {
                showToast('마감 취소 완료');
                loadReportList();
            } else {
                showToast(result.error || '마감 취소 실패');
            }
        } catch (error) {
            console.error('Cancel close error:', error);
            showToast('마감 취소 중 오류 발생');
        }
    };

    document.getElementById('confirmCancel').onclick = function() { overlay.remove(); };
    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
}

// showToast는 ui.js에서 로드

// 상세보기 모달 표시
function showStatusDetail(retailer, createdId, createdAt) {
    document.getElementById('detailModalTitle').textContent = `${retailer} 상세 정보`;
    document.getElementById('detailCreatedId').textContent = createdId;
    document.getElementById('detailCreatedAt').textContent = createdAt;
    document.getElementById('detailModalOverlay').classList.add('show');
}

// 상세보기 모달 닫기
function closeDetailModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('detailModalOverlay').classList.remove('show');
}


// ── 보고서 출력/저장 ──────────────────────────────

// 보고서 출력 모달 열기
async function openReportOutput() {
    if (reportClosing) return;
    const date = document.getElementById('targetDate').value;
    reportOutputDate = null;
    reportOutputData = null;
    let detailData;
    // 날짜 변경이나 파일 탭에서 열어도 전체 최신 현황으로 미리보기를 만든다.
    try {
        const response = await fetch(`/ds/layer4/api/report-list/?date=${date}&view=detail`);
        detailData = await response.json();
        if (!response.ok || !detailData.success) throw new Error('Report load failed');
        if (!detailData.daily_reports.length) {
            showToast('출력할 보고서가 없습니다.', 'warning');
            return;
        }
    } catch (e) {
        showToast('보고서를 불러오지 못했습니다. 다시 시도해주세요.', 'error');
        return;
    }

    // 파일 용량 7일 히스토리 조회
    let fileSizeHistory = null;
    try {
        const response = await fetch(`/ds/layer4/api/file-size-history/?end_date=${date}&days=7`);
        if (response.ok) {
            fileSizeHistory = await response.json();
        }
    } catch (e) {
        console.error('파일 용량 히스토리 조회 실패:', e);
    }

    // 표시용 HTML 생성
    if (date !== document.getElementById('targetDate').value) return;
    reportData = detailData;
    isClosed = detailData.is_closed;
    reportOutputDate = date;
    reportOutputData = detailData;
    updateCloseButton(detailData);
    const html = generateReportContent(fileSizeHistory);
    document.getElementById('reportOutputContent').innerHTML = html;
    document.getElementById('reportOutputOverlay').classList.add('show');
}

// 보고서 출력 모달 닫기
function closeReportOutput() {
    if (reportClosing) return;
    document.getElementById('reportOutputOverlay').classList.remove('show');
}

// 보고서 콘텐츠 생성 (HTML 템플릿)
function generateReportContent(fileSizeHistory) {
    const date = document.getElementById('targetDate').value;

    const totalRetailers = reportData.daily_reports.length;
    const rerunCount = reportData.daily_reports.filter(r => r.rerun_count > 0).length;
    const issueRetailers = reportData.daily_reports.filter(r => r.anomaly_total > 0);
    const issueCount = issueRetailers.length;
    const issueDataCount = reportData.total_anomalies;
    const rerunRetailers = reportData.daily_reports.filter(r => r.rerun_count > 0);
    const { anomalyLines, shortfallLines } = buildIssueLines();

    let fileStatusText = '정상';
    let fileStatusClass = 'status-normal';
    if (fileSizeHistory && fileSizeHistory.retailers && fileSizeHistory.retailers.length > 0) {
        const abnormalRetailers = [];
        fileSizeHistory.retailers.forEach(r => {
            const todaySize = r.sizes[r.sizes.length - 1] || 0;
            const avg = r.avg || 0;
            if (avg > 0 && todaySize > 0 && Math.abs(todaySize - avg) > 200) {
                abnormalRetailers.push(r.retailer);
            }
        });
        if (abnormalRetailers.length > 0) {
            fileStatusText = '비정상 (' + abnormalRetailers.join(', ') + ')';
            fileStatusClass = 'status-issue';
        }
    }

    const qualityText = issueCount > 0
        ? `이슈 ${issueCount}건 (${issueDataCount}건 데이터)`
        : '정상';
    const qualityStyle = issueCount > 0 ? 'color:#dc2626;font-weight:600;' : 'color:#16a34a;font-weight:600;';
    const fileStatusStyle = fileStatusClass === 'status-issue' ? 'color:#dc2626;font-weight:600;' : 'color:#16a34a;font-weight:600;';

    const S = {
        h2: 'style="font-size:20px;font-weight:700;text-align:center;padding-bottom:16px;margin-bottom:24px;border-bottom:2px solid #1e293b;"',
        h3: 'style="font-size:15px;font-weight:700;color:#1e293b;margin:24px 0 12px;padding-left:10px;border-left:3px solid #7e6b9b;"',
        table: 'style="width:100%;border-collapse:collapse;margin:8px 0 16px;font-size:13px;"',
        th: 'style="background:#f3f4f6;font-weight:600;padding:8px 12px;border:1px solid #d1d5db;text-align:left;white-space:nowrap;"',
        thR: 'style="background:#f3f4f6;font-weight:600;padding:8px 12px;border:1px solid #d1d5db;text-align:right;white-space:nowrap;"',
        thDate: 'style="background:#e2e8f0;font-weight:600;padding:8px 12px;border:1px solid #d1d5db;text-align:right;white-space:nowrap;"',
        td: 'style="padding:8px 12px;border:1px solid #d1d5db;"',
        tdR: 'style="padding:8px 12px;border:1px solid #d1d5db;text-align:right;"',
        tdLabel: 'style="padding:8px 12px;border:1px solid #d1d5db;font-weight:600;color:#475569;width:120px;white-space:nowrap;"',
        tdHighlight: 'style="padding:8px 12px;border:1px solid #d1d5db;text-align:right;background:#fffde7;"',
        tdAbnormal: 'style="padding:8px 12px;border:1px solid #d1d5db;text-align:right;background:#fee2e2;color:#dc2626;font-weight:600;"',
        tdAvg: 'style="padding:8px 12px;border:1px solid #d1d5db;text-align:right;font-weight:600;"',
        ok: 'style="color:#16a34a;font-weight:600;"',
        warn: 'style="color:#d97706;font-weight:600;"',
        issue: 'style="color:#dc2626;font-weight:600;"',
    };

    let html = '';
    html += `<h2 ${S.h2}>${date} DS 검수 보고서</h2>`;

    html += `<h3 ${S.h3}>요약</h3>`;
    html += `<table ${S.table}>`;
    const lowRetailers = reportData.daily_reports.filter(r => {
        const fc = r.final_batch_count || 0;
        const ex = r.expected_count || fc;
        return ex > 0 && fc < ex;
    });
    const okCount = totalRetailers - lowRetailers.length;
    const collectStatus = lowRetailers.length > 0
        ? `<span ${S.ok}>정상 ${okCount}건</span> / <span ${S.issue}>미달 ${lowRetailers.length}건</span> (${lowRetailers.map(r => r.retailer).join(', ')})`
        : `<span ${S.ok}>정상</span> (${totalRetailers}개 리테일러 100% 완료)`;
    html += `<tr><td ${S.tdLabel}>수집현황</td><td ${S.td}>${collectStatus}</td></tr>`;
    html += `<tr><td ${S.tdLabel}>재실행</td><td ${S.td}>${rerunCount > 0 ? '<span ' + S.warn + '>' + rerunCount + '건</span>' : '0건'}</td></tr>`;
    html += `<tr><td ${S.tdLabel}>데이터 품질</td><td ${S.td}><span style="${qualityStyle}">${qualityText}</span></td></tr>`;
    html += `<tr><td ${S.tdLabel}>파일질라</td><td ${S.td}><span style="${fileStatusStyle}">${fileStatusText}</span></td></tr>`;
    html += `</table>`;

    if (rerunRetailers.length > 0) {
        html += `<h3 ${S.h3}>재실행 현황</h3>`;
        html += `<table ${S.table}><thead><tr><th ${S.th}>리테일러</th><th ${S.th}>재실행 횟수</th></tr></thead><tbody>`;
        rerunRetailers.forEach(r => {
            html += `<tr><td ${S.td}>${r.retailer}</td><td ${S.td}>${r.rerun_count}회</td></tr>`;
        });
        html += `</tbody></table>`;
    }

    if (shortfallLines.length > 0 || anomalyLines.length > 0) {
        html += `<h3 ${S.h3}>이슈 내용</h3>`;
        if (shortfallLines.length > 0) {
            html += `<p style="font-weight:600;margin:8px 0 4px;">수집 미달</p><ul>`;
            shortfallLines.forEach(line => { html += `<li>${line}</li>`; });
            html += `</ul>`;
        }
        if (anomalyLines.length > 0) {
            html += `<p style="font-weight:600;margin:8px 0 4px;">이상치</p><ul>`;
            anomalyLines.forEach(line => { html += `<li>${line}</li>`; });
            html += `</ul>`;
        }
    }

    html += `<h3 ${S.h3}>수집 상세 (${totalRetailers}개 리테일러)</h3>`;
    html += `<table ${S.table}><thead><tr><th ${S.th}>리테일러</th><th ${S.thR}>수집건수</th><th ${S.thR}>예상건수</th><th ${S.thR}>달성률</th></tr></thead><tbody>`;
    reportData.daily_reports.forEach(r => {
        const finalCount = r.final_batch_count || 0;
        const expected = r.expected_count || finalCount;
        const rate = expected > 0 ? Math.round(finalCount / expected * 100) : 100;
        const isLow = rate < 100;
        const trStyle = isLow ? ' style="background:#fee2e2;"' : '';
        html += `<tr${trStyle}>`;
        html += `<td ${S.td}>${r.retailer}</td>`;
        html += `<td ${S.tdR}>${finalCount.toLocaleString()}</td>`;
        html += `<td ${S.tdR}>${expected.toLocaleString()}</td>`;
        html += `<td ${S.tdR}>${isLow ? '<span ' + S.issue + '>' + rate + '%</span>' : rate + '%'}</td>`;
        html += `</tr>`;
    });
    html += `</tbody></table>`;

    html += `<h3 ${S.h3}>특이사항</h3>`;
    if (shortfallLines.length > 0 || anomalyLines.length > 0) {
        if (shortfallLines.length > 0) {
            html += `<p style="font-weight:600;margin:8px 0 4px;">수집 미달</p><ul>`;
            shortfallLines.forEach(line => { html += `<li>${line}</li>`; });
            html += `</ul>`;
        }
        if (anomalyLines.length > 0) {
            html += `<p style="font-weight:600;margin:8px 0 4px;">이상치</p><ul>`;
            anomalyLines.forEach(line => { html += `<li>${line}</li>`; });
            html += `</ul>`;
        }
    } else {
        html += `<p>없음</p>`;
    }

    html += `<h3 ${S.h3}>파일질라 용량 보고</h3>`;
    if (fileSizeHistory && fileSizeHistory.retailers && fileSizeHistory.retailers.length > 0) {
        const dateHeaders = [...fileSizeHistory.dates].reverse().map(d => {
            const parts = d.split('-');
            return parts[1] + '/' + parts[2];
        });

        html += `<table ${S.table}><thead><tr>`;
        html += `<th ${S.th}>리테일러</th><th ${S.thR}>7일 평균</th>`;
        dateHeaders.forEach((d, i) => {
            html += `<th ${i === 0 ? S.thDate : S.thR}>${d}</th>`;
        });
        html += `</tr></thead><tbody>`;

        fileSizeHistory.retailers.forEach(r => {
            const sizes = [...r.sizes].reverse();
            const avg = r.avg || 0;
            html += `<tr>`;
            html += `<td ${S.td}>${r.retailer}</td>`;
            html += `<td ${S.tdAvg}>${avg > 0 ? avg.toLocaleString() : '-'}</td>`;
            sizes.forEach((s, i) => {
                let tdStyle = S.tdR;
                if (i === 0) {
                    const isAbnormal = avg > 0 && s > 0 && Math.abs(s - avg) > 200;
                    tdStyle = isAbnormal ? S.tdAbnormal : S.tdHighlight;
                }
                html += `<td ${tdStyle}>${s > 0 ? s.toLocaleString() : '-'}</td>`;
            });
            html += `</tr>`;
        });
        html += `</tbody></table>`;

        // 파일메모가 있는 리테일러 표시
        const fileMemoReports = (reportData.daily_reports || []).filter(r => r.file_memo && r.file_memo.trim());
        if (fileMemoReports.length > 0) {
            html += `<h3 ${S.h3}>파일 비고</h3><ul>`;
            fileMemoReports.forEach(r => {
                html += `<li>${r.retailer} : ${r.file_memo}</li>`;
            });
            html += `</ul>`;
        }
    } else {
        html += `<p>데이터 없음</p>`;
    }

    return html;
}

// null/빈값 체크 헬퍼
function isNullValue(val) {
    if (val === null || val === undefined) return true;
    if (typeof val === 'string') {
        const v = val.trim().toLowerCase();
        return v === '' || v === 'null' || v === 'none' || v === 'n/a';
    }
    return false;
}

// 가격 0원 체크 헬퍼
function isZeroPriceValue(val) {
    if (val === null || val === undefined) return false;
    const v = String(val).trim().toLowerCase();
    return v === '0' || v === '$0' || v === '0원' || v === '₩0' || v === '0.00' || v === '$0.00';
}

function buildIssueLines() {
    const anomalyLines = [];
    const shortfallLines = [];

    const byRetailer = {};
    reportData.anomalies.forEach(a => {
        if (!byRetailer[a.retailer]) byRetailer[a.retailer] = [];
        byRetailer[a.retailer].push(a);
    });

    const dailyMemo = {};
    reportData.daily_reports.forEach(d => {
        if (d.memo) dailyMemo[d.retailer] = d.memo;
    });

    const retailerOrder = reportData.daily_reports.map(d => d.retailer);

    retailerOrder.filter(retailer => byRetailer[retailer]).forEach(retailer => {
        const anomalies = byRetailer[retailer];
        const typeCount = {};

        anomalies.forEach(a => {
            const nullFields = [];
            let isZeroPrice = false;

            if (isZeroPriceValue(a.retailprice)) {
                isZeroPrice = true;
            } else if (isNullValue(a.retailprice)) {
                nullFields.push('retailprice');
            }
            if (isNullValue(a.title)) nullFields.push('title');
            if (isNullValue(a.imageurl)) nullFields.push('imageurl');
            if (isNullValue(a.ships_from)) nullFields.push('ships_from');
            if (isNullValue(a.sold_by)) nullFields.push('sold_by');

            let typeStr = '';
            if (isZeroPrice) {
                typeStr = 'retailprice 0원';
            } else if (nullFields.length > 0) {
                typeStr = nullFields.join(', ') + ' null';
            } else {
                typeStr = a.error_type || 'unknown';
            }
            typeCount[typeStr] = (typeCount[typeStr] || 0) + 1;
        });

        const typeParts = Object.entries(typeCount).map(([t, c]) => `${t} ${c}건`);
        let line = `${retailer}    ${typeParts.join(', ')}`;
        if (dailyMemo[retailer]) {
            line += ` : ${dailyMemo[retailer]}`;
        }
        anomalyLines.push(line);
    });

    reportData.daily_reports.forEach(r => {
        const fc = r.final_batch_count || 0;
        const ex = r.expected_count || fc;
        if (ex > 0 && fc < ex) {
            const rate = Math.round(fc / ex * 100);
            let line = `${r.retailer}    ${fc.toLocaleString()} / ${ex.toLocaleString()} (${rate}%)`;
            if (dailyMemo[r.retailer]) {
                line += ` : ${dailyMemo[r.retailer]}`;
            }
            shortfallLines.push(line);
        }
    });

    return { anomalyLines, shortfallLines };
}

// 보고서 출력 모달 외부 클릭 시 닫기
document.getElementById('reportOutputOverlay').addEventListener('click', function(e) {
    if (e.target === this) {
        closeReportOutput();
    }
});
