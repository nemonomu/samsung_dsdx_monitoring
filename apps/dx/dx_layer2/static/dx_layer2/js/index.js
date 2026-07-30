    function escapeHtml(str) {
        if (!str && str !== 0) return '';
        return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }
    function safeUrl(url) {
        if (!url) return '';
        const s = String(url).trim();
        if (s.startsWith('http://') || s.startsWith('https://')) return escapeHtml(s);
        return '';
    }

    let dxData = null;

    AppModal.create('l2-detail', { style: 'wide', closeOnOverlay: true });
    AppModal.create('l2-rule', { style: 'wide', closeOnOverlay: true });

    document.addEventListener('DOMContentLoaded', function() {
        initDatePicker();
        checkBackupStatus();
        fetchDXStats();
    });

    async function checkBackupStatus() {
        const date = getSelectedDate();
        if (!date) return;
        try {
            const res = await fetch(`/dx/layer1/api/backup-status/?date=${date}`);
            if (!res.ok) return;
            const data = await res.json();
            if (!data.success || data.pending_count === 0) return;

            if (!data.has_backup) {
                const goBackup = await showConfirm(`${date} 미백업 ${data.pending_count}건 (TV: ${data.tv_count}, HHP: ${data.hhp_count})\n백업 후 검수를 진행해주세요.`, 'warning', { okText: 'Layer 1 이동', cancelText: '계속 조회' });
                if (goBackup) window.location.href = '/dx/layer1/';
            } else {
                showToast(`추가 수집 데이터 ${data.pending_count}건 미백업 (TV: ${data.tv_count}, HHP: ${data.hhp_count})`, 'warning', 5000);
            }
        } catch (e) { /* 백업 상태 조회 실패 시 무시 */ }
    }

    // 요일 표시 업데이트
    function updateWeekday() {
        const dateInput = document.getElementById('target-date');
        const weekdayDisplay = document.getElementById('weekday-display');
        if (dateInput.value && weekdayDisplay) {
            const date = new Date(dateInput.value + 'T00:00:00');
            const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
            const weekday = weekdays[date.getDay()];
            const isWeekend = date.getDay() === 0 || date.getDay() === 6;
            weekdayDisplay.textContent = `(${weekday})`;
            weekdayDisplay.style.color = isWeekend ? 'var(--color-critical)' : 'var(--text-secondary)';
        }
    }

    // 로컬 날짜를 YYYY-MM-DD 형식으로 변환
    function formatLocalDate(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function initDatePicker() {
        const dateInput = document.getElementById('target-date');
        const urlParams = new URLSearchParams(window.location.search);
        const urlDate = urlParams.get('date');
        const saved = localStorage.getItem('monitoringSelectedDate');

        if (urlDate) {
            dateInput.value = urlDate;
        } else if (saved) {
            dateInput.value = saved;
        } else {
            const yesterday = new Date();
            yesterday.setDate(yesterday.getDate() - 1);
            dateInput.value = formatLocalDate(yesterday);
        }
        localStorage.setItem('monitoringSelectedDate', dateInput.value);

        const today = new Date();
        dateInput.max = formatLocalDate(today);

        // 날짜 변경 시 요일 업데이트 + localStorage 저장
        dateInput.addEventListener('change', function() {
            updateWeekday();
            localStorage.setItem('monitoringSelectedDate', dateInput.value);
        });
        updateWeekday();
    }

    function setNextDay() {
        const dateInput = document.getElementById('target-date');
        const current = new Date(dateInput.value);
        current.setDate(current.getDate() + 1);
        dateInput.value = formatLocalDate(current);
        localStorage.setItem('monitoringSelectedDate', dateInput.value);
        updateWeekday();
        handleSearch();
    }

    function setPrevDay() {
        const dateInput = document.getElementById('target-date');
        const current = new Date(dateInput.value);
        current.setDate(current.getDate() - 1);
        dateInput.value = formatLocalDate(current);
        localStorage.setItem('monitoringSelectedDate', dateInput.value);
        updateWeekday();
        handleSearch();
    }

    function handleSearch() {
        checkBackupStatus();
        dxData = null;
        document.getElementById('dx-validation-container').innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
                <p>데이터 로딩 중...</p>
            </div>`;
        fetchDXStats();
    }

    function getSelectedDate() {
        return document.getElementById('target-date').value;
    }

    // ==================== DX ====================
    function fetchDXStats() {
        const date = getSelectedDate();

        fetch(`/dx/layer2/api/stats/?date=${date}`)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
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
        const summary = data.summary;

        document.getElementById('dx-totalIssues').textContent = summary.total_issues.toLocaleString();
        document.getElementById('dx-totalIssues').className = `value ${summary.overall_status.toLowerCase()}`;

        document.getElementById('dx-nullIssues').textContent = summary.null_issues.toLocaleString();
        document.getElementById('dx-nullIssues').className = `value ${getStatusClass(summary.null_issues)}`;

        document.getElementById('dx-formatIssues').textContent = summary.format_issues.toLocaleString();
        document.getElementById('dx-formatIssues').className = `value ${getStatusClass(summary.format_issues)}`;

        document.getElementById('dx-duplicateIssues').textContent = summary.duplicate_issues.toLocaleString();
        document.getElementById('dx-duplicateIssues').className = `value ${getStatusClass(summary.duplicate_issues)}`;

    }

    function renderDXValidationTypes(data) {
        const container = document.getElementById('dx-validation-container');

        if (!data.validation_types || data.validation_types.length === 0) {
            container.innerHTML = '<div class="loading"><p>검증 데이터 없음</p></div>';
            return;
        }

        let html = '';

        data.validation_types.forEach((vType, vIdx) => {
            html += `
                <div class="validation-section">
                    <div class="validation-header" onclick="toggleValidation(${vIdx})">
                        <div class="validation-title">
                            <span class="validation-icon">${escapeHtml(vType.icon)}</span>
                            <div>
                                <div class="validation-name">${escapeHtml(vType.type_name)}</div>
                                <div class="validation-name-en">${escapeHtml(vType.type_name_en)}</div>
                            </div>
                        </div>
                        <div class="validation-stats">
                            <span class="validation-count ${escapeHtml(vType.status).toLowerCase()}">${vType.total_issues.toLocaleString()}건</span>
                            <span class="status-badge ${escapeHtml(vType.status).toLowerCase()}">${escapeHtml(vType.status)}</span>
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
                            <span class="table-name">${escapeHtml(table.table_name)}</span>
                            <span style="font-size: 12px; color: var(--text-secondary);">
                                (${(table.total_records || table.total_checked || 0).toLocaleString()}건 검사)
                            </span>
                        </div>
                        <div class="table-stats">
                            <span class="table-count ${escapeHtml(table.status).toLowerCase()}">${table.total_issues.toLocaleString()}건</span>
                            <span class="status-badge ${escapeHtml(table.status).toLowerCase()}">${escapeHtml(table.status)}</span>
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

                html += `
                    <div class="retailer-card ${(retailer.status || 'ok').toLowerCase()}">
                        <div class="retailer-card-main"
                             onclick="openDetailModal('null', '${escapeHtml(tableName)}', '${escapeHtml(retailer.retailer)}', ${nullCount})"
                             ${!hasIssue ? 'style="cursor: default;"' : 'style="cursor: pointer;"'}>
                            <div class="retailer-header">
                                <span class="retailer-name">${escapeHtml(retailer.retailer)}</span>
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

        // 형식 검증 - 리테일러별 (TV/HHP Retail과 YouTube 동일한 형태)
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
                            <span class="retailer-name">${escapeHtml(retailer.retailer)}</span>
                            <span class="retailer-issue-count ${(retailer.status || 'ok').toLowerCase()}">${issueCount}건</span>
                        </div>
                        <div class="retailer-detail">
                            총 ${totalCount.toLocaleString()}건 중 형식 오류 레코드
                        </div>
                        <div class="retailer-actions">
                            <button class="btn-rule" onclick="event.stopPropagation(); openRuleModal('${escapeHtml(tableName)}', '${escapeHtml(retailer.retailer)}')">검증규칙</button>
                            ${hasIssue ? `<button class="btn-detail" onclick="event.stopPropagation(); openDetailModal('format', '${escapeHtml(tableName)}', '${escapeHtml(retailer.retailer)}', ${issueCount})">상세보기</button>` : ''}
                        </div>
                    </div>
                `;
            });
            html += '</div>';
        }

        // 중복 검증 - 리테일러별 중복
        if (vType.type === 'duplicate' && table.retailers) {
            // YouTube인 경우 설명 텍스트 다르게 표시
            const isYouTube = table.table === 'youtube';
            const isMarket = table.table === 'market';
            // 카드 개수에 따라 그리드 컬럼 조절
            const retailerCount = table.retailers.length;
            const gridCols = retailerCount <= 2 ? retailerCount : 3;
            html += `<div class="retailer-grid" style="grid-template-columns: repeat(${gridCols}, 1fr)">`;
            table.retailers.forEach(retailer => {
                const dupGroups = retailer.duplicate_groups || 0;
                const hasIssue = dupGroups > 0;
                // YouTube Logs/Videos/Comments인 경우 적절한 테이블 파라미터로 변환
                let detailTableName = tableName;
                if (isYouTube) {
                    if (retailer.retailer === 'Logs') detailTableName = 'YouTube Logs';
                    else if (retailer.retailer === 'Videos') detailTableName = 'YouTube Videos';
                    else detailTableName = 'YouTube Comments';
                }
                // 설명 텍스트
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
                         onclick="openDetailModal('duplicate', '${escapeHtml(detailTableName)}', '${escapeHtml(retailer.retailer)}', ${dupGroups})"
                         ${!hasIssue ? 'style="cursor: default;"' : ''}>
                        <div class="retailer-header">
                            <span class="retailer-name">${escapeHtml(retailer.retailer)}</span>
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
            return `<span class="field-badge ${hasIssue ? 'has-issue' : 'ok'}">${escapeHtml(field)}: ${safeCount}</span>`;
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
        document.getElementById('current-info').innerHTML = `<strong>${escapeHtml(date)}</strong> DX 검증 현황 <span class="date-badge ${badgeClass}">${escapeHtml(badgeText)}</span>`;
    }

    // ==================== 모달 함수 ====================
    // 페이지네이션 상태 저장
    let modalState = {
        type: null,
        tableName: null,
        tableParam: null,
        retailer: null,
        count: 0,
        currentPage: 1,
        totalPages: 1,
        totalGroups: 0,
        nullFieldsData: null,  // NULL 필드별 데이터 저장
        selectedField: null    // 선택된 NULL 필드
    };

    function openDetailModal(type, tableName, retailer, count, page = 1) {
        if (count === 0) return;

        const typeNames = {
            'null': 'NULL 검증',
            'format': '형식 검증',
            'duplicate': '중복 검증'
        };

        AppModal.setTitle('l2-detail', `${retailer} - ${typeNames[type]} 오류`);
        AppModal.setBody('l2-detail', '<div id="modal-subtitle" style="font-size:13px;color:var(--text-secondary);margin:-8px 0 16px;">' + `${tableName} | ${count}건의 오류 데이터` + '</div><div id="modal-body"><div class="modal-loading">데이터 로딩 중...</div></div>');
        AppModal.open('l2-detail');
        const body = document.getElementById('modal-body');
        document.body.style.overflow = 'hidden';

        // API 호출 - 타입별로 다른 API 사용
        const date = getSelectedDate();
        // tableName에서 table 파라미터 변환
        const tableParam = tableName === 'YouTube' ? 'youtube' :
                           tableName === 'YouTube Logs' ? 'youtube_logs' :
                           tableName === 'YouTube Comments' ? 'youtube_comments' :
                           tableName === 'YouTube Videos' ? 'youtube_videos' :
                           tableName === 'TV Retail' ? 'tv_retail' :
                           tableName === 'HHP Retail' ? 'hhp_retail' :
                           tableName === 'Market' ? 'market' :
                           tableName.toLowerCase().replace(' ', '_');

        // 상태 저장
        modalState = { type, tableName, tableParam, retailer, count, currentPage: page, totalPages: 1, totalGroups: 0, nullFieldsData: null, selectedField: null };

        const encRetailer = encodeURIComponent(retailer);
        let apiUrl;
        if (type === 'null') {
            apiUrl = `/dx/layer2/api/null-detail/?table=${tableParam}&retailer=${encRetailer}&date=${date}`;
        } else if (type === 'format') {
            apiUrl = `/dx/layer2/api/format-detail/?table=${tableParam}&retailer=${encRetailer}&date=${date}`;
        } else if (type === 'duplicate') {
            apiUrl = `/dx/layer2/api/anomaly-detail/?table=${tableParam}&retailer=${encRetailer}&date=${date}&page=${page}&page_size=20`;
        } else {
            apiUrl = `/dx/layer2/api/detail/?type=${type}&table=${tableParam}&retailer=${encRetailer}&date=${date}`;
        }

        fetch(apiUrl)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                // 페이지네이션 정보 저장 (anomaly_detail: results 안에 포함)
                const pgInfo = data.results || data;
                if (pgInfo.total_pages) {
                    modalState.totalPages = pgInfo.total_pages;
                    modalState.totalGroups = pgInfo.total_groups;
                    modalState.currentPage = pgInfo.page || 1;
                }

                // NULL 검증의 경우 항목별 요약을 먼저 표시
                if (type === 'null') {
                    modalState.nullFieldsData = data;
                    renderNullFieldSummary(data, tableParam);
                } else {
                    renderModalTable(type, data, tableParam);
                }
            })
            .catch(error => {
                console.error('Detail Error:', error);
                body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">데이터 로딩 실패</div>';
            });
    }

    // NULL 필드별 요약 표시
    function renderNullFieldSummary(data, tableParam) {
        const body = document.getElementById('modal-body');
        const records = data.records || data.results || [];
        const date = data.date || getSelectedDate();

        // 필드별 건수 집계
        const fieldCounts = {};
        records.forEach(record => {
            const nullFields = record.null_fields || [];
            nullFields.forEach(field => {
                fieldCounts[field] = (fieldCounts[field] || 0) + 1;
            });
        });

        // 전체 데이터 저장
        modalState.nullFieldsData = data;
        modalState.selectedField = null;

        let html = '';

        // 상단 툴바 (날짜만)
        html += `<div class="modal-toolbar">
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="null-modal-date" value="${date}"
                    onchange="reloadNullData(this.value)">
            </div>
        </div>`;

        // 필드별 요약 카드
        const sortedFields = Object.entries(fieldCounts).sort((a, b) => b[1] - a[1]);

        if (sortedFields.length === 0) {
            html += '<p style="text-align: center; color: var(--text-secondary);">NULL 오류 데이터가 없습니다.</p>';
        } else {
            html += '<div class="null-field-summary-container">';
            sortedFields.forEach(([field, count]) => {
                html += `
                    <div class="null-field-card" onclick="showNullFieldDetail('${escapeHtml(field)}')">
                        <div class="null-field-card-name">${escapeHtml(field)}</div>
                        <div class="null-field-card-count">${count}건</div>
                    </div>
                `;
            });
            html += '</div>';
        }

        body.innerHTML = html;
    }

    // NULL 필드별 상세 데이터 표시
    function showNullFieldDetail(fieldName) {
        const body = document.getElementById('modal-body');
        const data = modalState.nullFieldsData;
        const records = data.records || data.results || [];
        const displayConfig = data.display_config || {};
        const queryConfig = data.query_config || {};
        const dateColumn = data.date_column || 'crawl_datetime';
        const tableParam = modalState.tableParam;
        const date = data.date || getSelectedDate();

        // 선택된 필드가 포함된 레코드만 필터링
        const filteredRecords = records.filter(record => {
            const nullFields = record.null_fields || [];
            return nullFields.includes(fieldName);
        });

        modalState.selectedField = fieldName;

        const isRetail = tableParam === 'tv_retail' || tableParam === 'hhp_retail';

        // display_config에서 해당 필드의 표시 칼럼 설정 가져오기
        const fieldConfig = displayConfig[fieldName] || {};
        const selectColumns = fieldConfig.select_columns || [];
        const columnHeaders = fieldConfig.column_headers || {};

        // query_config에서 해당 필드의 쿼리 칼럼 가져오기
        const queryColumns = queryConfig[fieldName] || [];

        // 컬럼별 최대 데이터 길이 계산
        const columnWidths = {};

        // 기본 컬럼들
        columnWidths['NULL 필드'] = calcTextWidth('NULL 필드');

        // 데이터에서 최대 길이 계산
        filteredRecords.forEach(record => {
            // NULL 필드
            const nullFieldsVal = record.null_fields?.join(', ') || '-';
            columnWidths['NULL 필드'] = Math.max(columnWidths['NULL 필드'], calcTextWidth(nullFieldsVal));

            // display_config 기반 동적 컬럼
            selectColumns.forEach(col => {
                const headerName = columnHeaders[col] || col;
                if (!columnWidths[headerName]) {
                    columnWidths[headerName] = calcTextWidth(headerName);
                }
                let val = record[col];
                if (col === 'product_url') {
                    columnWidths[headerName] = Math.max(columnWidths[headerName], calcTextWidth('바로가기'));
                } else {
                    if ((col.includes('_at') || col.includes('datetime')) && val) {
                        val = isRetail ? formatDateTime(val) : formatDateOnly(val);
                    }
                    columnWidths[headerName] = Math.max(columnWidths[headerName], calcTextWidth(String(val || '-')));
                }
            });
        });

        let html = '';

        // 상단 툴바 (뒤로가기 + 날짜)
        html += `<div class="modal-toolbar">
            <button class="btn-back" onclick="backToNullFieldSummary()">← 뒤로가기</button>
            <div class="modal-date-picker">
                <label>조회 날짜:</label>
                <input type="date" id="null-modal-date" value="${date}"
                    onchange="reloadNullData(this.value)">
            </div>
        </div>`;

        // 필드명 표시
        html += `<h4 style="margin-bottom: 12px; font-size: 15px;">${escapeHtml(fieldName)} NULL 오류 (${filteredRecords.length}건)</h4>`;

        if (filteredRecords.length === 0) {
            html += '<p>해당 필드의 NULL 오류 데이터가 없습니다.</p>';
        } else {
            // item 목록 및 쿼리 섹션을 테이블 위에 먼저 표시
            const items = [...new Set(filteredRecords.map(r => r.item).filter(Boolean))].sort();
            const ids = filteredRecords.map(r => r.id).filter(Boolean);

            if (isRetail) {
                // 테이블명 결정
                const tableName = tableParam === 'tv_retail' ? 'tv_retail_com' : 'hhp_retail_com';
                const retailerName = modalState.retailer || '';

                // 쿼리 칼럼 결정 (query_config에서 가져오거나 기본값 사용)
                const queryCols = queryColumns.length > 0 ? queryColumns.join(', ') : '*';

                if (items.length > 0) {
                    // item이 있는 경우: item 기반 쿼리
                    const inClause = items.map(item => `'${item}'`).join(', ');
                    const itemListDisplay = items.join(', ');

                    const query3Days = `SELECT ${queryCols}
FROM ${tableName}
WHERE account_name = '${retailerName}'
  AND item IN (${inClause})
  AND DATE(${dateColumn}::timestamp) >= DATE('${date}') - INTERVAL '2 days'
  AND DATE(${dateColumn}::timestamp) <= DATE('${date}')
ORDER BY item, ${dateColumn} ASC;`;

                    html += `
                        <div class="item-query-section">
                            <div class="item-list-box">
                                <div class="item-copy-header">
                                    <span class="item-copy-title">Item 목록 (${items.length}개)</span>
                                    <button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button>
                                </div>
                                <div class="item-copy-content">${escapeHtml(itemListDisplay)}</div>
                            </div>
                            <div class="query-box">
                                <div class="item-copy-header">
                                    <span class="item-copy-title">3일치 조회 쿼리 (${escapeHtml(date)} 기준)</span>
                                    <button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button>
                                </div>
                                <pre class="query-content">${escapeHtml(query3Days)}</pre>
                            </div>
                        </div>
                    `;
                } else if (ids.length > 0) {
                    // item이 NULL인 경우: ID 기반 쿼리
                    const idInClause = ids.join(', ');
                    const idListDisplay = ids.join(', ');

                    const queryById = `SELECT ${queryCols}
FROM ${tableName}
WHERE id IN (${idInClause});`;

                    html += `
                        <div class="item-query-section">
                            <div class="item-list-box">
                                <div class="item-copy-header">
                                    <span class="item-copy-title">ID 목록 (${ids.length}개)</span>
                                    <button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button>
                                </div>
                                <div class="item-copy-content">${escapeHtml(idListDisplay)}</div>
                            </div>
                            <div class="query-box">
                                <div class="item-copy-header">
                                    <span class="item-copy-title">ID 기반 조회 쿼리</span>
                                    <button class="btn-copy" onclick="copyToClipboard(this.parentElement.nextElementSibling)">복사</button>
                                </div>
                                <pre class="query-content">${escapeHtml(queryById)}</pre>
                            </div>
                        </div>
                    `;
                }
            }

            html += '<div class="modal-table-wrapper"><table class="modal-table"><thead><tr>';

            // 헤더 생성 (display_config 기반)
            if (selectColumns.length > 0) {
                selectColumns.forEach(col => {
                    const headerName = columnHeaders[col] || col;
                    const colWidth = columnWidths[headerName] || 100;
                    html += `<th style="width: ${colWidth}px;">${headerName}<div class="resize-handle"></div></th>`;
                });
            } else {
                // fallback: 기본 칼럼
                html += `<th style="width: ${columnWidths['NULL 필드']}px;">NULL 필드<div class="resize-handle"></div></th>`;
                html += '<th style="width: 80px;">ID<div class="resize-handle"></div></th>';
                html += '<th style="width: 200px;">Item<div class="resize-handle"></div></th>';
                html += '<th style="width: 120px;">수집일<div class="resize-handle"></div></th>';
                html += '<th style="width: 80px;">URL<div class="resize-handle"></div></th>';
            }

            html += '</tr></thead><tbody>';

            filteredRecords.forEach(record => {
                html += '<tr>';

                if (selectColumns.length > 0) {
                    selectColumns.forEach(col => {
                        let val = record[col];
                        if (col === 'product_url') {
                            const href = safeUrl(val);
                            const urlLink = href
                                ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                                : '-';
                            html += `<td>${urlLink}</td>`;
                        } else {
                            if ((col.includes('_at') || col.includes('datetime')) && val) {
                                val = isRetail ? formatDateTime(val) : formatDateOnly(val);
                            }
                            const isNull = record.null_fields?.includes(col);
                            if (isNull) {
                                html += `<td class="null-value" title="${escapeHtml(val) || 'NULL'}">${escapeHtml(val) || 'NULL'}</td>`;
                            } else {
                                html += `<td title="${escapeHtml(val) || '-'}">${escapeHtml(val) || '-'}</td>`;
                            }
                        }
                    });
                } else {
                    // fallback: 기본 칼럼
                    const collectedAt = record.crawl_datetime || record.collected_at;
                    const href = safeUrl(record.product_url);
                    const urlLink = href
                        ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                        : '-';
                    html += `<td class="null-value">${escapeHtml(record.null_fields?.join(', ')) || '-'}</td>`;
                    html += `<td>${escapeHtml(record.id) || '-'}</td>`;
                    html += `<td>${escapeHtml(record.item) || '-'}</td>`;
                    html += `<td>${formatDateTime(collectedAt)}</td>`;
                    html += `<td>${urlLink}</td>`;
                }

                html += '</tr>';
            });

            html += '</tbody></table></div>';
        }

        body.innerHTML = html;
        initColumnResize();
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

        // HTTPS에서는 clipboard API 사용
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(showSuccess).catch(err => {
                console.error('복사 실패:', err);
                fallbackCopy(text, showSuccess);
            });
        } else {
            // HTTP에서는 execCommand 사용
            fallbackCopy(text, showSuccess);
        }
    }

    // HTTP 환경용 폴백 복사 함수
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

    // 텍스트 길이 기반 열 너비 계산
    function calcTextWidth(text) {
        if (!text) return 60;
        const str = String(text);
        const padding = 32;
        const minWidth = 60;
        const maxWidth = 300;

        let width = 0;
        for (const char of str) {
            if (/[가-힣]/.test(char)) {
                width += 14;
            } else if (/[A-Z]/.test(char)) {
                width += 10;
            } else if (char === '_') {
                width += 7;
            } else {
                width += 8;
            }
        }
        width += padding;

        return Math.max(minWidth, Math.min(maxWidth, width));
    }

    // NULL 필드 요약으로 돌아가기
    function backToNullFieldSummary() {
        const data = modalState.nullFieldsData;
        const tableParam = modalState.tableParam;
        renderNullFieldSummary(data, tableParam);
    }

    // NULL 데이터 날짜 변경 시 재로드
    async function reloadNullData(date) {
        const body = document.getElementById('modal-body');
        body.innerHTML = '<div class="modal-loading">데이터를 불러오는 중...</div>';

        const { tableParam, retailer, selectedField } = modalState;

        try {
            const response = await fetch(`/dx/layer2/api/null-detail/?table=${tableParam}&retailer=${encodeURIComponent(retailer)}&date=${date}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            modalState.nullFieldsData = data;

            // 제목 업데이트
            const records = data.records || data.results || [];
            document.getElementById('modal-subtitle').textContent = `${modalState.tableName} | ${records.length}건의 오류 데이터`;

            // 이전에 특정 필드를 보고 있었으면 해당 필드 상세 유지
            if (selectedField) {
                showNullFieldDetail(selectedField);
            } else {
                renderNullFieldSummary(data, tableParam);
            }
        } catch (error) {
            console.error('Error:', error);
            body.innerHTML = '<div class="modal-loading" style="color: var(--color-critical);">데이터 로드 실패</div>';
        }
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

    // 컬럼명 길이에 따라 초기 너비 계산
    function calcColumnWidth(colName) {
        const padding = 40;    // 좌우 패딩 + 여유
        const minWidth = 80;   // 최소 너비
        const maxWidth = 250;  // 최대 너비

        // 글자별 너비 계산
        let width = 0;
        for (const char of colName) {
            if (/[가-힣]/.test(char)) {
                width += 16;  // 한글
            } else if (/[A-Z]/.test(char)) {
                width += 12;  // 대문자
            } else if (char === '_') {
                width += 8;   // 언더스코어
            } else {
                width += 10;  // 소문자, 숫자
            }
        }
        width += padding;

        return Math.max(minWidth, Math.min(maxWidth, width));
    }

    function renderModalTable(type, data, tableParam) {
        const body = document.getElementById('modal-body');
        const retailer = modalState.retailer;  // modalState에서 retailer 가져오기

        // API 응답에서 레코드 배열 찾기 (타입별로 다른 구조)
        let records;
        if (type === 'duplicate') {
            // duplicate는 results.duplicates 구조
            records = data.results?.duplicates || [];
        } else {
            // null, format은 records 또는 results
            records = data.records || data.results || [];
        }

        if (records.length === 0) {
            body.innerHTML = '<div class="modal-loading">데이터가 없습니다.</div>';
            return;
        }

        let html = '<div class="modal-table-wrapper"><table class="modal-table"><thead><tr>';

        // 타입별, 테이블별 컬럼 설정
        // API 응답에서 column_names 가져오기 (CSV 기반)
        const columnNames = data.column_names || [];

        if (type === 'null') {
            // CSV 기반 동적 컬럼 (column_names가 있는 경우 - YouTube, Market, TV/HHP Retail 모두 적용)
            if (columnNames.length > 0) {
                // ID, NULL 필드 먼저
                html += '<th style="width: 60px;">ID<div class="resize-handle"></div></th>';
                html += `<th style="width: ${calcColumnWidth('NULL 필드')}px;">NULL 필드<div class="resize-handle"></div></th>`;
                // CSV에서 가져온 컬럼들 (show_detail=Y인 컬럼)
                columnNames.forEach(col => {
                    // product_url은 링크로 표시하므로 헤더명을 URL로 변경
                    const headerName = col === 'product_url' ? 'URL' : col;
                    const colWidth = calcColumnWidth(headerName);
                    html += `<th style="width: ${colWidth}px;">${headerName}<div class="resize-handle"></div></th>`;
                });
            } else if (tableParam === 'youtube') {
                // 폴백: 기존 하드코딩 (column_names가 없는 경우)
                html += '<th style="width: 25%;">NULL 필드<div class="resize-handle"></div></th><th style="width: 30%;">COMMENT_ID<div class="resize-handle"></div></th><th style="width: 25%;">VIDEO_ID<div class="resize-handle"></div></th><th style="width: 20%;">수집일<div class="resize-handle"></div></th>';
            } else if (tableParam.startsWith('market_')) {
                // 폴백: Market 테이블들 기존 구조
                html += '<th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 150px;">NULL 필드<div class="resize-handle"></div></th><th style="width: 200px;">Item<div class="resize-handle"></div></th><th style="width: 120px;">수집일<div class="resize-handle"></div></th>';
            } else {
                html += '<th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 150px;">NULL 필드<div class="resize-handle"></div></th><th style="width: 200px;">Item<div class="resize-handle"></div></th><th style="width: 120px;">수집일<div class="resize-handle"></div></th><th style="width: 80px;">URL<div class="resize-handle"></div></th>';
            }
        } else if (type === 'format') {
            // YouTube 형식 오류는 다른 컬럼 구조
            if (tableParam === 'youtube') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 120px;">식별자<div class="resize-handle"></div></th><th style="width: 120px;">오류 필드<div class="resize-handle"></div></th><th style="width: 150px;">오류 값<div class="resize-handle"></div></th><th style="width: 120px;">규칙<div class="resize-handle"></div></th><th style="min-width: 150px;">위배 사유<div class="resize-handle"></div></th>';
            } else {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 150px;">Item<div class="resize-handle"></div></th><th style="width: 120px;">오류 필드<div class="resize-handle"></div></th><th style="width: 150px;">오류 값<div class="resize-handle"></div></th><th style="width: 120px;">규칙<div class="resize-handle"></div></th><th style="min-width: 150px;">위배 사유<div class="resize-handle"></div></th><th style="width: 120px;">수집일<div class="resize-handle"></div></th><th style="width: 80px;">URL<div class="resize-handle"></div></th>';
            }
        } else if (type === 'duplicate') {
            if (tableParam === 'youtube_logs') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 150px;">Keyword<div class="resize-handle"></div></th><th style="width: 100px;">Category<div class="resize-handle"></div></th><th style="width: 180px;">중복사유<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else if (tableParam === 'youtube_comments') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 120px;">Video ID<div class="resize-handle"></div></th><th style="width: 140px;">Comment ID<div class="resize-handle"></div></th><th style="width: 150px;">중복사유<div class="resize-handle"></div></th><th style="min-width: 300px;">댓글 내용<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else if (tableParam === 'youtube_videos') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 120px;">Video ID<div class="resize-handle"></div></th><th style="width: 100px;">Keyword<div class="resize-handle"></div></th><th style="width: 180px;">중복사유<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="min-width: 200px;">제목<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else if (tableParam === 'market_trend') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 150px;">Keyword<div class="resize-handle"></div></th><th style="width: 180px;">중복사유<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 100px;">Article수<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else if (tableParam === 'market_product') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 100px;">Batch ID<div class="resize-handle"></div></th><th style="width: 150px;">Samsung Series<div class="resize-handle"></div></th><th style="width: 100px;">Comp Brand<div class="resize-handle"></div></th><th style="width: 150px;">Comp Series<div class="resize-handle"></div></th><th style="width: 150px;">중복사유<div class="resize-handle"></div></th><th style="width: 60px;">ID<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else if (tableParam === 'market_event') {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 100px;">Batch ID<div class="resize-handle"></div></th><th style="width: 100px;">Comp Brand<div class="resize-handle"></div></th><th style="width: 150px;">Comp SKU<div class="resize-handle"></div></th><th style="width: 150px;">중복사유<div class="resize-handle"></div></th><th style="width: 60px;">ID<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th>';
            } else {
                html += '<th style="width: 50px;">No<div class="resize-handle"></div></th><th style="width: 150px;">Item<div class="resize-handle"></div></th><th style="width: 100px;">시간대<div class="resize-handle"></div></th><th style="width: 150px;">중복사유<div class="resize-handle"></div></th><th style="width: 80px;">ID<div class="resize-handle"></div></th><th style="width: 100px;">Page Type<div class="resize-handle"></div></th><th style="width: 140px;">수집시각<div class="resize-handle"></div></th><th style="width: 80px;">Rank<div class="resize-handle"></div></th><th style="width: 80px;">URL<div class="resize-handle"></div></th>';
            }
        }

        html += '</tr></thead><tbody>';

        let rowNumber = 0;  // 형식 오류 순번용
        records.forEach((record, recordIdx) => {
            if (type === 'null') {
                html += '<tr>';
                // crawl_datetime 또는 collected_at 둘 다 지원
                const collectedAt = record.crawl_datetime || record.collected_at;

                // CSV 기반 동적 컬럼 (column_names가 있는 경우 - YouTube, Market, TV/HHP Retail 모두 적용)
                if (columnNames.length > 0) {
                    // ID, NULL 필드 먼저
                    html += `<td>${escapeHtml(record.id) || '-'}</td>`;
                    html += `<td class="null-value">${escapeHtml(record.null_fields?.join(', ')) || '-'}</td>`;
                    // TV/HHP Retail만 오전/오후 표시, 나머지는 날짜만
                    const isRetail = tableParam === 'tv_retail' || tableParam === 'hhp_retail';
                    // CSV에서 가져온 컬럼들 값 표시
                    columnNames.forEach(col => {
                        let val = record[col];
                        // product_url은 링크로 표시
                        if (col === 'product_url') {
                            const href = safeUrl(val);
                            const urlLink = href
                                ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                                : '-';
                            html += `<td>${urlLink}</td>`;
                        } else {
                            // 날짜 형식인지 확인 (published_at, created_at, started_at, crawl_datetime 등)
                            if ((col.includes('_at') || col.includes('datetime')) && val) {
                                // Retail만 오전/오후 표시, 나머지는 날짜만
                                val = isRetail ? formatDateTime(val) : formatDateOnly(val);
                            }
                            // NULL인 필드는 빨간색으로 표시
                            const isNull = record.null_fields?.includes(col);
                            if (isNull) {
                                html += `<td class="null-value" title="${escapeHtml(val) || 'NULL'}">${escapeHtml(val) || 'NULL'}</td>`;
                            } else {
                                html += `<td title="${escapeHtml(val) || '-'}">${escapeHtml(val) || '-'}</td>`;
                            }
                        }
                    });
                } else if (tableParam === 'youtube') {
                    // 폴백: 기존 하드코딩 (column_names가 없는 경우)
                    html += `
                        <td class="null-value">${escapeHtml(record.null_fields?.join(', ')) || '-'}</td>
                        <td title="${escapeHtml(record.comment_id) || '-'}">${escapeHtml(record.comment_id) || '-'}</td>
                        <td title="${escapeHtml(record.video_id) || '-'}">${escapeHtml(record.video_id) || '-'}</td>
                        <td>${formatDateOnly(collectedAt)}</td>
                    `;
                } else if (tableParam.startsWith('market_')) {
                    // 폴백: Market 테이블들 기존 구조
                    html += `
                        <td>${escapeHtml(record.id) || '-'}</td>
                        <td class="null-value">${escapeHtml(record.null_fields?.join(', ')) || '-'}</td>
                        <td>${escapeHtml(record.item) || '-'}</td>
                        <td>${formatDateTime(collectedAt)}</td>
                    `;
                } else {
                    const href = safeUrl(record.product_url);
                    const urlLink = href
                        ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                        : '-';
                    html += `
                        <td>${escapeHtml(record.id) || '-'}</td>
                        <td class="null-value">${escapeHtml(record.null_fields?.join(', ')) || '-'}</td>
                        <td>${escapeHtml(record.item) || '-'}</td>
                        <td>${formatDateTime(collectedAt)}</td>
                        <td>${urlLink}</td>
                    `;
                }
                html += '</tr>';
            } else if (type === 'format') {
                // 형식 오류는 errors 배열의 각 오류마다 별도 행으로 표시 (rowspan 사용)
                const errors = record.errors || [];
                if (errors.length === 0) return;

                rowNumber++;  // 레코드 순번 증가
                const rowspan = errors.length;

                errors.forEach((err, errIdx) => {
                    html += '<tr>';

                    if (tableParam === 'youtube') {
                        const identifier = escapeHtml(record.keyword || record.video_id || record.comment_type) || '-';
                        if (errIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.id)}</td>
                                <td rowspan="${rowspan}">${identifier}</td>
                            `;
                        }
                        html += `
                            <td class="null-value">${escapeHtml(err.field) || '-'}</td>
                            <td>${escapeHtml(err.value) || '-'}</td>
                            <td>${escapeHtml(err.rule) || '-'}</td>
                            <td>${escapeHtml(err.reason) || '-'}</td>
                        `;
                    } else {
                        // TV/HHP Retail 형식 오류
                        const href = safeUrl(record.product_url);
                        const urlLink = href
                            ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                            : '-';
                        const collectedAt = record.crawl_datetime || record.collected_at;
                        if (errIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.id)}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.item) || '-'}</td>
                            `;
                        }
                        html += `
                            <td class="null-value">${escapeHtml(err.field) || '-'}</td>
                            <td>${escapeHtml(err.value) || '-'}</td>
                            <td>${escapeHtml(err.rule) || '-'}</td>
                            <td>${escapeHtml(err.reason) || '-'}</td>
                        `;
                        if (errIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}">${formatDateTime(collectedAt)}</td>
                                <td rowspan="${rowspan}">${urlLink}</td>
                            `;
                        }
                    }

                    html += '</tr>';
                });
            } else if (type === 'duplicate') {
                // 중복 그룹: 각 그룹의 records를 펼쳐서 표시
                rowNumber++;
                const dupRecords = record.records || [];
                const rowspan = dupRecords.length;

                dupRecords.forEach((rec, recIdx) => {
                    html += '<tr>';

                    if (tableParam === 'youtube_logs') {
                        // YouTube Logs 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.keyword) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.category) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else if (tableParam === 'youtube_comments') {
                        // YouTube Comments 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}" title="${escapeHtml(record.video_id)}">${escapeHtml(record.video_id) || '-'}</td>
                                <td rowspan="${rowspan}" title="${escapeHtml(record.comment_id)}">${escapeHtml(record.comment_id) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td style="white-space: normal; word-break: break-word;">${escapeHtml(rec.comment_text_display) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else if (tableParam === 'youtube_videos') {
                        // YouTube Videos 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.video_id) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.keyword) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${escapeHtml(rec.title) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else if (tableParam === 'market_trend') {
                        // Market Trend 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.keyword) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${escapeHtml(rec.total_article_number) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else if (tableParam === 'market_product') {
                        // Market Product 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.batch_id) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.samsung_series_name) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.comp_brand) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.comp_series_name) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else if (tableParam === 'market_event') {
                        // Market Event 중복
                        if (recIdx === 0) {
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.batch_id) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.comp_brand) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.comp_sku_name) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${formatDateTime(rec.created_at)}</td>
                        `;
                    } else {
                        // TV/HHP Retail 중복
                        const href = safeUrl(rec.product_url);
                        const urlLink = href
                            ? `<a href="${href}" target="_blank" style="color: #2563eb;">바로가기</a>`
                            : '-';
                        // HHP는 API에서 page_type별 rank를 계산해서 내려줌, TV는 기존 방식
                        const rank = rec.rank !== undefined ? (escapeHtml(rec.rank) || '-') : (escapeHtml(rec.main_rank) || escapeHtml(rec.bsr_rank) || '-');

                        if (recIdx === 0) {
                            // 첫 행에만 그룹 정보 표시 (item, 시간대, 중복사유)
                            html += `
                                <td rowspan="${rowspan}" style="text-align: center; font-weight: 500;">${rowNumber}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.item) || '-'}</td>
                                <td rowspan="${rowspan}">${escapeHtml(record.period) || '-'}</td>
                                <td rowspan="${rowspan}" style="color: #dc2626; font-size: 12px;">${escapeHtml(record.reason) || '-'}</td>
                            `;
                        }
                        // 개별 레코드 정보 (ID, page_type, 수집시각, rank, URL)
                        html += `
                            <td>${escapeHtml(rec.id) || '-'}</td>
                            <td>${escapeHtml(rec.page_type) || '-'}</td>
                            <td>${formatDateTime(rec.crawl_datetime)}</td>
                            <td>${rank}</td>
                            <td>${urlLink}</td>
                        `;
                    }
                    html += '</tr>';
                });
            }
        });

        html += '</tbody></table></div>';

        // 페이지네이션 UI (YouTube Comments 중복 등 페이지네이션 지원하는 경우)
        if (modalState.totalPages > 1) {
            const { currentPage, totalPages, totalGroups } = modalState;
            html += `
                <div class="modal-pagination">
                    <div class="pagination-info">
                        총 ${totalGroups.toLocaleString()}개 중복 그룹 중 ${records.length}개 표시 (${currentPage}/${totalPages} 페이지)
                    </div>
                    <div class="pagination-buttons">
                        <button class="pagination-btn" onclick="goToPage(1)" ${currentPage === 1 ? 'disabled' : ''}>«</button>
                        <button class="pagination-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>‹</button>
                        <span class="pagination-current">${currentPage} / ${totalPages}</span>
                        <button class="pagination-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>›</button>
                        <button class="pagination-btn" onclick="goToPage(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''}>»</button>
                    </div>
                </div>
            `;
        } else {
            const total = data.total || records.length;
            if (total > records.length) {
                html += `<p style="margin-top: 16px; color: var(--text-secondary); font-size: 13px;">
                    총 ${total.toLocaleString()}건 중 ${records.length}건 표시
                </p>`;
            }
        }

        body.innerHTML = html;

        // 열 크기 조정 기능 초기화
        initColumnResize();
    }

    function closeModal() {
        AppModal.close('l2-detail');

        // 모달 상태 초기화
        modalState.type = null;
        modalState.tableName = null;
        modalState.tableParam = null;
        modalState.retailer = null;
        modalState.count = 0;
        modalState.currentPage = 1;
        modalState.totalPages = 1;
        modalState.totalGroups = 0;
        modalState.nullFieldsData = null;
        modalState.selectedField = null;
    }

    // 검증규칙 모달 (CSV 기반 API 호출)
    async function openRuleModal(tableName, retailer) {
        AppModal.setTitle('l2-rule', `${retailer} - 형식 검증 규칙`);
        AppModal.setBody('l2-rule', '<div style="text-align: center; padding: 20px;">로딩 중...</div>');
        AppModal.open('l2-rule');
        const body = AppModal.getBody('l2-rule');

        // 테이블명 매핑
        const tableNameMap = {
            'TV Retail': 'tv_retail_com',
            'HHP Retail': 'hhp_retail_com',
            'YouTube': 'youtube_videos',
            'Market': 'market_trend'
        };

        // Market 하위 항목은 retailer로 테이블 구분
        const marketRetailerMap = {
            'Trend': 'market_trend',
            'Comp Product': 'market_comp_product',
            'Comp Event': 'market_comp_event',
            'Forecast': 'openai_forecast_results'
        };

        let dbTableName = tableNameMap[tableName] || 'tv_retail_com';
        if (tableName === 'Market' && marketRetailerMap[retailer]) {
            dbTableName = marketRetailerMap[retailer];
        }

        try {
            const response = await fetch(`/layer2/api/format-rules/?table=${encodeURIComponent(dbTableName)}&retailer=${encodeURIComponent(retailer)}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const rules = data.rules || [];

            let html = '<table class="rule-table"><thead><tr>';
            html += '<th>필드명</th><th>검증 규칙</th><th>허용 패턴/값</th>';
            html += '</tr></thead><tbody>';

            if (rules.length === 0) {
                html += '<tr><td colspan="3" style="text-align: center;">등록된 규칙이 없습니다.</td></tr>';
            } else {
                rules.forEach(rule => {
                    html += `<tr>
                        <td class="rule-field">${escapeHtml(rule.field)}</td>
                        <td>${escapeHtml(rule.description)}</td>
                        <td><span class="rule-pattern">${escapeHtml(rule.pattern)}</span></td>
                    </tr>`;
                });
            }

            html += '</tbody></table>';
            body.innerHTML = html;
        } catch (error) {
            console.error('형식 검증 규칙 로드 실패:', error);
            body.innerHTML = '<div style="text-align: center; padding: 20px; color: #dc3545;">규칙 로드 실패</div>';
        }
    }

    function closeRuleModal() {
        AppModal.close('l2-rule');
    }

    // 열 크기 조정 기능
    function initColumnResize() {
        const table = document.querySelector('.modal-table');
        if (!table) return;

        const wrapper = table.closest('.modal-table-wrapper');
        const headers = table.querySelectorAll('th');
        const minColWidth = 80;

        // 테이블 초기 너비를 wrapper 너비로 설정
        const wrapperWidth = wrapper.offsetWidth;
        table.style.width = wrapperWidth + 'px';

        // 각 헤더의 초기 너비를 픽셀로 변환
        headers.forEach(th => {
            const width = th.offsetWidth;
            th.style.width = width + 'px';
        });

        headers.forEach((th, index) => {
            const handle = th.querySelector('.resize-handle');
            if (!handle) return;

            let startX, startWidth, tableStartWidth;

            handle.addEventListener('mousedown', function(e) {
                e.preventDefault();
                startX = e.pageX;
                startWidth = th.offsetWidth;
                tableStartWidth = table.offsetWidth;

                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });

            function onMouseMove(e) {
                const diff = e.pageX - startX;
                const newWidth = Math.max(minColWidth, startWidth + diff);
                const widthDiff = newWidth - startWidth;

                th.style.width = newWidth + 'px';

                // 테이블 전체 너비 조정
                const newTableWidth = tableStartWidth + widthDiff;
                table.style.width = Math.max(wrapperWidth, newTableWidth) + 'px';
            }

            function onMouseUp() {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            }
        });
    }

