// ==================== DX ====================
function fetchDXStats() {
    const date = getSelectedDate();

    fetch(`/dx/layer2/api/stats/?date=${date}`)
        .then(response => response.json())
        .then(data => {
            dxData = data;
            renderDXSummary(data);
            renderDXValidationTypes(data);
            updateCurrentInfo(data.date);
        })
        .catch(error => {
            console.error('DX Error:', error);
            document.getElementById('dx-validation-container').innerHTML =
                '<div class="loading"><p style="color: var(--color-critical);">DX 데이터 로딩 실패</p></div>';
        });
}

function renderDXSummary(data) {
    const el = document.getElementById('dx-totalIssues');
    if (!el) return;

    const summary = data.summary;

    el.textContent = summary.total_issues.toLocaleString();
    el.className = `value ${summary.overall_status.toLowerCase()}`;

    document.getElementById('dx-nullIssues').textContent = summary.null_issues.toLocaleString();
    document.getElementById('dx-nullIssues').className = `value ${getStatusClass(summary.null_issues)}`;

    document.getElementById('dx-formatIssues').textContent = summary.format_issues.toLocaleString();
    document.getElementById('dx-formatIssues').className = `value ${getStatusClass(summary.format_issues)}`;

    document.getElementById('dx-duplicateIssues').textContent = summary.duplicate_issues.toLocaleString();
    document.getElementById('dx-duplicateIssues').className = `value ${getStatusClass(summary.duplicate_issues)}`;
}

function renderDXValidationTypes(data) {
    const container = document.getElementById('dx-validation-container');

    // 섹션별 필터링
    const section = (window.LAYER2 && window.LAYER2.section) || 'dashboard';
    const typeMap = { null_validation: 'null', format_validation: 'format', anomaly_validation: 'duplicate' };
    if (typeMap[section] && data.validation_types) {
        data.validation_types = data.validation_types.filter(v => v.type === typeMap[section]);
    }

    if (!data.validation_types || data.validation_types.length === 0) {
        container.innerHTML = '<div class="loading"><p>검증 데이터 없음</p></div>';
        return;
    }

    let html = '';

    if (isInlineMode()) {
        // 섹션 페이지: validation 헤더 없이 테이블 목록만 직접 표시
        // 테이블 클릭 → 인라인 상세 전환
        const vType = data.validation_types[0];
        if (vType && vType.tables) {
            vType.tables.forEach((table, tIdx) => {
                const issueCount = table.total_issues || 0;
                html += `
                    <div class="table-item clickable-table" onclick="showTableDetail(${tIdx})">
                        <div class="table-header">
                            <div class="table-info">
                                <span class="table-name">${table.table_name}</span>
                                <span style="font-size: 12px; color: var(--text-secondary);">
                                    (${(table.total_records || table.total_checked || 0).toLocaleString()}건 검사)
                                </span>
                            </div>
                            <div class="table-stats">
                                <span class="table-count ${table.status.toLowerCase()}">${issueCount.toLocaleString()}건</span>
                                <span class="status-badge ${table.status.toLowerCase()}">${table.status}</span>
                                <span class="toggle-icon">▶</span>
                            </div>
                        </div>
                    </div>
                `;
            });
        }
        // focus 결정: currentFocusTable > URL focus > 첫 번째 테이블
        var focusTarget = currentFocusTable;
        if (!focusTarget) {
            const focus = new URLSearchParams(window.location.search).get('focus');
            if (focus) {
                focusTarget = decodeURIComponent(focus);
            }
        }
        // focus 없으면 첫 번째 테이블
        if (!focusTarget && vType && vType.tables && vType.tables.length > 0) {
            focusTarget = vType.tables[0].table_name;
        }

        if (focusTarget && vType) {
            const idx = vType.tables.findIndex(t => t.table_name === focusTarget);
            if (idx >= 0) {
                // 목록 HTML은 ViewStack에만 저장 (뒤로가기용)
                ViewStack.stack = [{ html: html, scrollTop: 0 }];
                ViewStack._updateBackBtn();
                const table = vType.tables[idx];
                currentFocusTable = table.table_name;
                let detailHtml = `
                    <div class="inline-detail-view">
                        <div class="inline-detail-header">
                            <div>
                                <div class="inline-detail-title">${table.table_name}</div>
                                <div class="inline-detail-subtitle">${(table.total_records || table.total_checked || 0).toLocaleString()}건 검사 | ${table.total_issues}건 오류</div>
                            </div>
                        </div>
                        <div class="inline-detail-body">
                            ${renderDXTableDetail(vType, table)}
                        </div>
                    </div>`;
                container.innerHTML = detailHtml;
            } else {
                container.innerHTML = html;
            }
        } else {
            container.innerHTML = html;
        }
    } else {
        // 대시보드: 기존 validation-section + toggle 구조
        data.validation_types.forEach((vType, vIdx) => {
            html += `
                <div class="validation-section">
                    <div class="validation-header" onclick="toggleValidation(${vIdx})">
                        <div class="validation-title">
                            <span class="validation-icon">${vType.icon}</span>
                            <div>
                                <div class="validation-name">${vType.type_name}</div>
                                <div class="validation-name-en">${vType.type_name_en}</div>
                            </div>
                        </div>
                        <div class="validation-stats">
                            <span class="validation-count ${vType.status.toLowerCase()}">${vType.total_issues.toLocaleString()}건</span>
                            <span class="status-badge ${vType.status.toLowerCase()}">${vType.status}</span>
                            <span class="toggle-icon" id="toggle-dx-v-${vIdx}">▶</span>
                        </div>
                    </div>
                    <div class="tables-container" id="dx-tables-${vIdx}">
                        ${renderDXTables(vType, vIdx)}
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    }
}

// 섹션 페이지: 테이블 클릭 → 리테일러 카드를 인라인으로 표시
function showTableDetail(tableIdx) {
    if (!dxData || !dxData.validation_types) return;
    const vType = dxData.validation_types[0];
    if (!vType || !vType.tables || !vType.tables[tableIdx]) return;
    const table = vType.tables[tableIdx];
    currentFocusTable = table.table_name;
    // URL에 focus 파라미터 반영 (새로고침 시 현재 메뉴 유지)
    const url = new URL(window.location);
    url.searchParams.set('focus', table.table_name);
    history.replaceState(null, '', url);

    let html = `
        <div class="inline-detail-view">
            <div class="inline-detail-header">
                <div>
                    <div class="inline-detail-title">${table.table_name}</div>
                    <div class="inline-detail-subtitle">${(table.total_records || table.total_checked || 0).toLocaleString()}건 검사 | ${table.total_issues}건 오류</div>
                </div>
            </div>
            <div class="inline-detail-body">
    `;

    html += renderDXTableDetail(vType, table);

    html += '</div></div>';
    ViewStack.push(html);
}

function renderDXTables(vType, vIdx) {
    if (!vType.tables || vType.tables.length === 0) {
        return '<p style="padding: 20px; color: var(--text-secondary);">테이블 데이터 없음</p>';
    }

    let html = '';

    vType.tables.forEach((table, tIdx) => {
        html += `
            <div class="table-item">
                <div class="table-header" onclick="toggleTable(${vIdx}, ${tIdx})">
                    <div class="table-info">
                        <span class="table-name">${table.table_name}</span>
                        <span style="font-size: 12px; color: var(--text-secondary);">
                            (${(table.total_records || table.total_checked || 0).toLocaleString()}건 검사)
                        </span>
                    </div>
                    <div class="table-stats">
                        <span class="table-count ${table.status.toLowerCase()}">${table.total_issues.toLocaleString()}건</span>
                        <span class="status-badge ${table.status.toLowerCase()}">${table.status}</span>
                        <span class="toggle-icon" id="toggle-dx-t-${vIdx}-${tIdx}">▶</span>
                    </div>
                </div>
                <div class="detail-container" id="dx-detail-${vIdx}-${tIdx}">
                    ${renderDXTableDetail(vType, table)}
                </div>
            </div>
        `;
    });

    return html;
}

function renderDXTableDetail(vType, table) {
    let html = '';
    const tableName = table.table_name;

    // NULL 검증 - 리테일러별 상세
    if (vType.type === 'null' && table.retailers) {
        const retailerCount = table.retailers.length;
        const gridCols = retailerCount <= 2 ? retailerCount : 3;
        html += `<div class="retailer-grid" style="grid-template-columns: repeat(${gridCols}, 1fr)">`;
        table.retailers.forEach(retailer => {
            const hasIssue = (retailer.total_null_count || 0) > 0;
            const totalCount = retailer.total || 0;
            const nullCount = retailer.total_null_count || 0;

            const fieldsJson = JSON.stringify(retailer.fields_detail || {}).replace(/'/g, '&#39;');
            html += `
                <div class="retailer-card ${(retailer.status || 'ok').toLowerCase()}">
                    <div class="retailer-card-main"
                         data-fields='${fieldsJson}'
                         onclick="openDetailModal('null', '${tableName}', '${retailer.retailer}', ${nullCount}, 1, this.dataset.fields)"
                         ${!hasIssue ? 'style="cursor: default;"' : 'style="cursor: pointer;"'}>
                        <div class="retailer-header">
                            <span class="retailer-name">${retailer.retailer}</span>
                            <span class="retailer-issue-count ${(retailer.status || 'ok').toLowerCase()}">${nullCount}건</span>
                        </div>
                        <div class="retailer-detail">
                            총 ${totalCount.toLocaleString()}건 중 필수값 NULL 레코드
                        </div>
                        <div class="retailer-fields">
                            ${renderNullFieldsDetail(retailer.fields_detail)}
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
    }

    // 형식 검증 - 리테일러별
    if (vType.type === 'format' && table.retailers) {
        const retailerCount = table.retailers.length;
        const gridCols = retailerCount <= 2 ? retailerCount : 3;
        html += `<div class="retailer-grid" style="grid-template-columns: repeat(${gridCols}, 1fr)">`;
        table.retailers.forEach(retailer => {
            const hasIssue = (retailer.issue_count || 0) > 0;
            const totalCount = retailer.total || 0;
            const issueCount = retailer.issue_count || 0;
            html += `
                <div class="retailer-card ${(retailer.status || 'ok').toLowerCase()}">
                    <div class="retailer-header">
                        <span class="retailer-name">${retailer.retailer}</span>
                        <span class="retailer-issue-count ${(retailer.status || 'ok').toLowerCase()}">${issueCount}건</span>
                    </div>
                    <div class="retailer-detail">
                        총 ${totalCount.toLocaleString()}건 중 형식 오류 레코드
                    </div>
                    <div class="retailer-actions">
                        <button class="btn-rule" onclick="event.stopPropagation(); openRuleModal('${tableName}', '${retailer.retailer}')">검증규칙</button>
                        ${hasIssue ? `<button class="btn-detail" onclick="event.stopPropagation(); openDetailModal('format', '${tableName}', '${retailer.retailer}', ${issueCount})">상세보기</button>` : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
    }

    // 중복 검증 - 리테일러별 중복
    if (vType.type === 'duplicate' && table.retailers) {
        const isYouTube = table.table === 'youtube';
        const isMarket = table.table === 'market';
        const retailerCount = table.retailers.length;
        const gridCols = retailerCount <= 2 ? retailerCount : 3;
        html += `<div class="retailer-grid" style="grid-template-columns: repeat(${gridCols}, 1fr)">`;
        table.retailers.forEach(retailer => {
            const dupGroups = retailer.duplicate_groups || 0;
            const hasIssue = dupGroups > 0;
            let detailTableName = tableName;
            if (isYouTube) {
                if (retailer.retailer === 'Logs') detailTableName = 'YouTube Logs';
                else if (retailer.retailer === 'Videos') detailTableName = 'YouTube Videos';
                else detailTableName = 'YouTube Comments';
            }
            let detailText = '중복 그룹 수';
            if (isYouTube && retailer.retailer === 'Logs') {
                detailText = 'keyword + category 중복';
            } else if (isYouTube && retailer.retailer === 'Videos') {
                detailText = 'video_id + keyword 중복';
            } else if (isYouTube && retailer.retailer === 'Comments') {
                detailText = 'video_id + comment_id 중복';
            } else if (isMarket && retailer.retailer === 'Trend') {
                detailText = 'keyword 중복';
            } else if (isMarket && retailer.retailer === 'Product') {
                detailText = 'batch_id + samsung_series + comp_brand + comp_series 중복';
            } else if (isMarket && retailer.retailer === 'Event') {
                detailText = 'batch_id + comp_brand + comp_sku 중복';
            }
            html += `
                <div class="retailer-card ${(retailer.status || 'ok').toLowerCase()}"
                     onclick="openDetailModal('duplicate', '${detailTableName}', '${retailer.retailer}', ${dupGroups})"
                     ${!hasIssue ? 'style="cursor: default;"' : ''}>
                    <div class="retailer-header">
                        <span class="retailer-name">${retailer.retailer}</span>
                        <span class="retailer-issue-count ${(retailer.status || 'ok').toLowerCase()}">${dupGroups}건</span>
                    </div>
                    <div class="retailer-detail">${detailText}</div>
                </div>
            `;
        });
        html += '</div>';
    }

    if (!html) {
        html = '<p style="padding: 20px; color: var(--text-secondary);">상세 데이터 없음</p>';
    }

    return html;
}

// ==================== 공통 함수 ====================
function getStatusClass(count) {
    if (count === 0) return 'ok';
    if (count <= 10) return 'warning';
    return 'critical';
}

function renderNullFieldsDetail(fieldsDetail) {
    if (!fieldsDetail) return '';
    return Object.entries(fieldsDetail).map(([field, count]) => {
        const safeCount = count || 0;
        const hasIssue = safeCount > 0;
        return `<span class="field-badge ${hasIssue ? 'has-issue' : 'ok'}">${field}: ${safeCount}</span>`;
    }).join('');
}

function toggleValidation(vIdx) {
    const container = document.getElementById(`dx-tables-${vIdx}`);
    const icon = document.getElementById(`toggle-dx-v-${vIdx}`);

    if (container.classList.contains('show')) {
        container.classList.remove('show');
        icon.classList.remove('expanded');
    } else {
        container.classList.add('show');
        icon.classList.add('expanded');
    }
}

function toggleTable(vIdx, tIdx) {
    const container = document.getElementById(`dx-detail-${vIdx}-${tIdx}`);
    const icon = document.getElementById(`toggle-dx-t-${vIdx}-${tIdx}`);

    if (container.classList.contains('show')) {
        container.classList.remove('show');
        icon.classList.remove('expanded');
    } else {
        container.classList.add('show');
        icon.classList.add('expanded');
    }
}

function updateCurrentInfo(date) {
    const el = document.getElementById('current-info');
    if (!el) return;

    const today = new Date().toISOString().split('T')[0];
    const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];

    let badgeClass = 'past';
    let badgeText = '';
    if (date === today) {
        badgeClass = 'today';
        badgeText = 'TODAY';
    } else if (date === yesterday) {
        badgeClass = 'yesterday';
        badgeText = 'D-1';
    } else {
        const diffDays = Math.floor((new Date(today) - new Date(date)) / 86400000);
        badgeText = `D-${diffDays}`;
    }
    el.innerHTML = `<strong>${date}</strong> DX 검증 현황 <span class="date-badge ${badgeClass}">${badgeText}</span>`;
}

