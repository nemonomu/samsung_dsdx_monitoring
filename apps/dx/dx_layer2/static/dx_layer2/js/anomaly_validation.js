// ========== 중복 정리 (체크박스 방식) ==========

// 중복 검증 액션 버튼바 (테이블 위)
function _renderDupActionBar() {
    var el = document.getElementById('detail-action-bar');
    if (!el) return;
    new FilterBar('#detail-action-bar', {
        sticky: false,
        padding: '4px 0',
        controls: [],
        right: [
            { type: 'button', label: '최신 제외 전체 선택', style: 'outline', size: 'fb', onClick: function() { _selectExceptLatest(); } },
            { type: 'button', label: '선택 해제', style: 'outline', size: 'fb', onClick: function() { _clearDupChecks(); } },
            { type: 'button', label: '선택 삭제', style: 'danger', size: 'fb', onClick: function() { _doDuplicateCleanup(); } }
        ]
    }).render();
    var fbEl = document.querySelector('#detail-action-bar .fb');
    if (fbEl) {
        fbEl.style.background = 'none';
        fbEl.style.border = 'none';
        fbEl.style.boxShadow = 'none';
        fbEl.style.marginBottom = '8px';
    }
}

// 헤더 체크박스 주입 (전체선택/해제)
function _injectDupCheckboxHeader() {
    var headerCells = document.querySelectorAll('#detail-table-area th');
    for (var i = 0; i < headerCells.length; i++) {
        var th = headerCells[i];
        if (th.textContent.trim() === '' && th.style.width) {
            th.innerHTML = '<input type="checkbox" class="dup-check-all" title="전체 선택/해제">';
            th.querySelector('.dup-check-all').addEventListener('change', function() {
                var checks = document.querySelectorAll('.dup-check');
                var checked = this.checked;
                checks.forEach(function(cb) { cb.checked = checked; });
            });
            break;
        }
    }
}

// 최신 제외 전체 선택 (각 그룹의 마지막 레코드 = 최신 제외)
function _selectExceptLatest() {
    var checks = document.querySelectorAll('.dup-check');
    checks.forEach(function(cb) {
        cb.checked = !cb.hasAttribute('data-group-last');
    });
    // 헤더 체크박스 상태 동기화
    var allCheck = document.querySelector('.dup-check-all');
    if (allCheck) {
        var total = checks.length;
        var checked = document.querySelectorAll('.dup-check:checked').length;
        allCheck.checked = total > 0 && checked === total;
    }
}

// 선택 해제
function _clearDupChecks() {
    document.querySelectorAll('.dup-check').forEach(function(cb) { cb.checked = false; });
    var allCheck = document.querySelector('.dup-check-all');
    if (allCheck) allCheck.checked = false;
}

// 선택 삭제 실행
function _doDuplicateCleanup() {
    var checked = document.querySelectorAll('.dup-check:checked');
    if (checked.length === 0) {
        showToast('삭제할 항목을 선택해주세요.', 'info');
        return;
    }

    var ids = [];
    checked.forEach(function(cb) { ids.push(parseInt(cb.getAttribute('data-id'))); });
    var table = modalState.tableParam;
    var date = getSelectedDate();

    showConfirm(ids.length + '건 삭제하시겠습니까?')
        .then(function(ok) {
            if (!ok) return;
            fetch('/dx/layer2/api/duplicate-cleanup/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ table: table, ids: ids, date: date })
            })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.success) {
                    showToast(res.deleted_count + '건 삭제 완료', 'success');
                    openDetailModal('duplicate', modalState.tableName, modalState.retailer, modalState.count, 1);
                } else {
                    showToast(res.error || '삭제 실패', 'error');
                }
            })
            .catch(function(err) { showToast('요청 오류: ' + err.message, 'error'); });
        });
}

function renderDetailTable(type, data, tableParam) {
    const body = getDetailBody();

    let records;
    if (type === 'duplicate') {
        records = data.results?.duplicates || [];
    } else {
        records = data.records || data.results || [];
    }

    if (records.length === 0) {
        body.innerHTML = '<div class="modal-loading">데이터가 없습니다.</div>';
        return;
    }

    // NULL 타입: 칼럼 동적 생성 (column_names가 있을 경우)
    var config;
    if (type === 'null') {
        var columnNames = data.column_names || [];
        if (columnNames.length > 0) {
            config = [
                { key: 'id', label: 'ID', width: 60 },
                { key: 'null_fields', label: 'NULL 필드', width: 150 },
            ];
            columnNames.forEach(function(col) {
                config.push({ key: col, label: col === 'product_url' ? 'URL' : col, width: 120 });
            });
        } else {
            config = getColumnConfig('null', tableParam);
        }
    } else {
        config = getColumnConfig(type, tableParam);
    }

    // 서버 사이드 페이징 (중복) — 서버에서 받은 데이터 그대로 표시
    var isServerPaging = type === 'duplicate' && modalState.totalPages > 1;

    // 컨테이너 HTML 생성
    var containerHtml = buildDetailContainerHtml({});
    body.innerHTML = containerHtml;
    if (data.readonly) {
        var readOnlyBar = document.getElementById('detail-action-bar');
        if (readOnlyBar) {
            var readOnlyMessage = data.readonly_message
                || 'TSE 중복 검증은 확인 전용이며 자동 삭제하지 않습니다.';
            readOnlyBar.innerHTML = '<div style="padding:8px 12px;margin-bottom:8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;color:#475569;font-size:12px;">'
                + readOnlyMessage + '</div>';
        }
    }

    // 렌더링
    if (isServerPaging) {
        // 서버 사이드 페이징: 전체 데이터를 한 번에 표시, 서버 페이지네이션 별도 표시
        var allCols = getAllColumns(config);
        var allowCleanup = !data.readonly && !isTseDuplicateTable(tableParam);
        var ctColumns = [];
        if (allowCleanup) {
            ctColumns.push({ key: '_chk', label: '', width: 40, sortable: false, align: 'center' });
        }
        allCols.forEach(function(col) {
            ctColumns.push({ key: col.key, label: col.label, width: col.width, sortable: false, align: col.align });
        });

        detailViewState.type = type;
        detailViewState.tableParam = tableParam;
        detailViewState.columns = allCols;
        detailViewState.editableCols = new Set(data.editable_cols || []);
        detailViewState.actualTable = data.actual_table || '';
        detailViewState.crawlDate = data.date || '';

        var flatData = flattenRecords(type, records, tableParam);
        detailViewState.allData = flatData;

        detailViewState.table = new CommonTable('#detail-table-area', {
            variant: 'detail', columns: ctColumns, vlines: true, rounded: true, showTotalCount: true, padding: '10px 12px',
            pageSize: _dupPageSize,
            onPageSizeChange: function(val) {
                _dupPageSize = val;
                goToPage(1);
            }
        });
        detailViewState.table.render();

        // 전체 렌더 (서버에서 이미 페이징됨)
        detailViewState.table.renderBody(flatData, function(row) {
            var tr = '<tr>';
            // 체크박스 (매 행, rowspan 없음)
            if (allowCleanup) {
                tr += '<td style="text-align:center"><input type="checkbox" class="dup-check" data-id="' + row.id + '"' +
                      (row._isGroupLast ? ' data-group-last="1"' : '') + '></td>';
            }
            if (row._isGroupFirst) {
                config.group.forEach(function(col) {
                    var inner = getCellHtml(row, col, tableParam).replace(/^<td[^>]*>/, '').replace(/<\/td>$/, '');
                    tr += '<td rowspan="' + row._groupSize + '"' +
                          (col.align ? ' style="text-align:' + col.align + ';font-weight:500;"' : '') + '>' + inner + '</td>';
                });
            }
            config.detail.forEach(function(col) {
                tr += getCellHtml(row, col, tableParam);
            });
            if (row._isGroupFirst && config.trailing) {
                config.trailing.forEach(function(col) {
                    var inner = getCellHtml(row, col, tableParam).replace(/^<td[^>]*>/, '').replace(/<\/td>$/, '');
                    tr += '<td rowspan="' + row._groupSize + '">' + inner + '</td>';
                });
            }
            return tr + '</tr>';
        });
        if (allowCleanup) {
            _injectDupCheckboxHeader();
            _renderDupActionBar();
        }

        // 서버 사이드 페이지네이션
        var pagerEl = document.getElementById('detail-pagination');
        if (pagerEl) {
            var sp = new Pagination(pagerEl, {
                variant: 'simple',
                pageSize: _dupPageSize,
                showInfo: true,
                onPageChange: function(page) { goToPage(page); }
            });
            sp.render(modalState.totalGroups, modalState.currentPage);
        }

        // 건수 (CommonTable의 ct-count를 전체 건수로 덮어쓰기)
        var countEl = document.querySelector('#detail-table-area .ct-count');
        if (countEl) countEl.innerHTML = '총 <strong>' + modalState.totalGroups.toLocaleString() + '</strong>개 중복 그룹';

        // FilterBar (섹션 페이지에서만 표시)
        if (isInlineMode()) {
            var filterCols = allCols.map(function(c, i) { return { value: String(i), label: c.label }; });
            var serverCols = data.select_cols || null;
            // id → 디폴트 컬럼 순서 → 나머지 asc 정렬
            var defaultKeySet = {};
            allCols.forEach(function(c) { defaultKeySet[c.key] = c; });
            var selectorColumns = [];
            if (defaultKeySet['id']) selectorColumns.push(defaultKeySet['id']);
            allCols.forEach(function(c) {
                if (c.key === 'id' || c.key === 'null_fields') return;
                selectorColumns.push(c);
            });
            if (serverCols && typeof serverCols === 'object' && !Array.isArray(serverCols)) {
                var colKeys = (serverCols.group || []).concat(serverCols.record || []);
                var extraCols = [];
                colKeys.forEach(function(k) {
                    if (!defaultKeySet[k]) {
                        extraCols.push({ key: k, label: k, width: 120 });
                    }
                });
                extraCols.sort(function(a, b) { return a.key.localeCompare(b.key); });
                extraCols.forEach(function(c) { selectorColumns.push(c); });
            }
            var defaultVisibleKeys = allCols.map(function(c) { return c.key; });
            detailViewState.filterBar = new FilterBar('#detail-filter-bar', {
                sticky: false, padding: '8px 12px',
                controls: [
                    { type: 'select', key: 'filterCol', label: '항목', width: 'auto', options: filterCols },
                    { type: 'input', key: 'filterVal', placeholder: '검색어 입력...', onEnter: function() { applyDetailFilter(); } }
                ],
                onSearch: function() { applyDetailFilter(); },
                onReset: function() { clearDetailFilter(); },
                columnSelector: {
                    columns: selectorColumns,
                    fixed: ['id'],
                    defaultVisible: defaultVisibleKeys,
                    onUpdate: function() { /* 서버 페이징에서는 컬럼 변경 시 재렌더 불필요 */ }
                }
            }).render();
        }
    } else {
        // 클라이언트 사이드 페이징 (NULL, 형식, 중복 소량)
        var selectCols = data.select_cols || null;
        // 중복: {group: [...], record: [...]} → flat 배열로 변환
        if (selectCols && typeof selectCols === 'object' && !Array.isArray(selectCols)) {
            selectCols = (selectCols.group || []).concat(selectCols.record || []);
        }
        renderDetailWithTable({
            config: config,
            data: records,
            tableParam: tableParam,
            type: type,
            selectCols: selectCols,
            editableCols: data.editable_cols || [],
            actualTable: data.actual_table || '',
            crawlDate: data.date || '',
            normalReviews: data.normal_reviews || {}
        });
    }
}

