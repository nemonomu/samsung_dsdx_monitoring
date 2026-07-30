// Layer 2: 형식/NULL 검수 (DX 데이터 품질 모니터링)
let dxData = null;
let currentFocusTable = null;  // 현재 보고 있는 테이블 이름 (날짜 변경 시 유지용)

// ==================== 칼럼 설정 레지스트리 ====================
const DETAIL_COLUMNS = {
    // --- NULL 필드 상세 (flat) ---
    null_retail_fallback: [
        { key: 'null_fields', label: 'NULL 필드', width: 150 },
        { key: 'id', label: 'ID', width: 80 },
        { key: 'item', label: 'Item', width: 200 },
        { key: 'crawl_datetime', label: '수집일', width: 120 },
        { key: 'product_url', label: 'URL', width: 80 },
    ],
    null_youtube: [
        { key: 'null_fields', label: 'NULL 필드', width: 150 },
        { key: 'comment_id', label: 'COMMENT_ID', width: 180 },
        { key: 'video_id', label: 'VIDEO_ID', width: 150 },
        { key: 'crawl_datetime', label: '수집일', width: 120 },
    ],
    null_market: [
        { key: 'null_fields', label: 'NULL 필드', width: 80 },
        { key: 'id', label: 'ID', width: 80 },
        { key: 'item', label: 'Item', width: 200 },
        { key: 'crawl_datetime', label: '수집일', width: 120 },
    ],
    // --- 중복 검증 (rowspan) ---
    dup_youtube_logs: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'keyword', label: 'Keyword', width: 150 },
            { key: 'category', label: 'Category', width: 100 },
            { key: 'reason', label: '중복사유', width: 180 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 80 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_youtube_comments: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'video_id', label: 'Video ID', width: 120 },
            { key: 'comment_id', label: 'Comment ID', width: 140 },
            { key: 'reason', label: '중복사유', width: 150 },
        ],
        detail: [
            { key: 'comment_text_display', label: '댓글 내용', width: 300 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_youtube_videos: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'video_id', label: 'Video ID', width: 120 },
            { key: 'keyword', label: 'Keyword', width: 100 },
            { key: 'reason', label: '중복사유', width: 180 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 80 },
            { key: 'title', label: '제목', width: 200 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_market_trend: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'keyword', label: 'Keyword', width: 150 },
            { key: 'reason', label: '중복사유', width: 180 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 80 },
            { key: 'total_article_number', label: 'Article수', width: 100 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_market_product: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'batch_id', label: 'Batch ID', width: 100 },
            { key: 'samsung_series_name', label: 'Samsung Series', width: 150 },
            { key: 'comp_brand', label: 'Comp Brand', width: 100 },
            { key: 'comp_series_name', label: 'Comp Series', width: 150 },
            { key: 'reason', label: '중복사유', width: 150 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 60 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_market_event: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'batch_id', label: 'Batch ID', width: 100 },
            { key: 'comp_brand', label: 'Comp Brand', width: 100 },
            { key: 'comp_sku_name', label: 'Comp SKU', width: 150 },
            { key: 'reason', label: '중복사유', width: 150 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 60 },
            { key: 'created_at', label: '수집시각', width: 140 },
        ]
    },
    dup_default: {
        group: [
            { key: '_no', label: 'No', width: 50, align: 'center' },
            { key: 'item', label: 'Item', width: 150 },
            { key: 'period', label: '시간대', width: 100 },
            { key: 'reason', label: '중복사유', width: 150 },
        ],
        detail: [
            { key: 'id', label: 'ID', width: 80 },
            { key: 'page_type', label: 'Page Type', width: 100 },
            { key: 'crawl_datetime', label: '수집시각', width: 140 },
            { key: '_rank', label: 'Rank', width: 80 },
            { key: 'product_url', label: 'URL', width: 80 },
        ]
    },
};

// ==================== 상세 뷰 공통 함수 ====================
// 상세 뷰 상태
var detailViewState = {
    table: null,
    filterBar: null,
    pager: null,
    allData: [],
    filteredData: null,
    columns: [],
    type: null,
    tableParam: null,
    sortColumns: [],
    originalData: null
};

function getColumnConfig(type, tableParam) {
    if (type === 'duplicate') {
        var key = 'dup_' + tableParam;
        return DETAIL_COLUMNS[key] || DETAIL_COLUMNS.dup_default;
    }
    // null
    if (tableParam === 'youtube') return DETAIL_COLUMNS.null_youtube;
    if (tableParam.startsWith('market_')) return DETAIL_COLUMNS.null_market;
    return DETAIL_COLUMNS.null_retail_fallback;
}

function getAllColumns(config) {
    if (Array.isArray(config)) return config;
    var cols = [];
    if (config.group) cols = cols.concat(config.group);
    if (config.detail) cols = cols.concat(config.detail);
    if (config.trailing) cols = cols.concat(config.trailing);
    return cols;
}

function flattenRecords(type, records, tableParam) {
    var flat = [];
    var groupNum = 0;
    records.forEach(function(record) {
        var children;
        if (type === 'duplicate') {
            children = record.records || [];
            if (children.length === 0) return;
        } else {
            flat.push(record);
            return;
        }
        groupNum++;
        children.forEach(function(child, childIdx) {
            flat.push(Object.assign({}, child, {
                _parent: record,
                _isGroupFirst: childIdx === 0,
                _isGroupLast: childIdx === children.length - 1,
                _groupSize: children.length,
                _groupNumber: groupNum
            }));
        });
    });
    return flat;
}

function _editableAttr(row, key) {
    if (!isInlineMode()) return '';
    if (!detailViewState.editableCols || !detailViewState.editableCols.has(key)) return '';
    var rowId = row.id || (row._parent && row._parent.id);
    if (!rowId) return '';
    // 다일치 조회 시 조회 날짜 데이터만 수정 가능
    if ((modalState.days || 1) > 1 && detailViewState.crawlDate) {
        var dateCol = detailViewState.dateColumn || (modalState.nullFieldsData && modalState.nullFieldsData.date_column) || 'crawl_datetime';
        var recDate = (row[dateCol] || '').substring(0, 10);
        if (recDate !== detailViewState.crawlDate) return '';
    }
    return ' data-editable="true" data-row-id="' + rowId + '" data-col="' + esc(key) + '"';
}

function getCellHtml(row, col, tableParam) {
    var key = col.key;
    var val;

    // 특수 키 처리
    if (key === '_no') {
        return '<td' + (col.align ? ' style="text-align:' + col.align + ';font-weight:500;"' : '') + '>' + (row._groupNumber || '') + '</td>';
    }
    if (key === '_identifier') {
        val = row._parent ? (row._parent.keyword || row._parent.video_id || row._parent.comment_type || '-') : '-';
        return '<td>' + esc(String(val)) + '</td>';
    }
    if (key === '_rank') {
        val = row.rank !== undefined ? (row.rank || '-') : (row.main_rank || row.bsr_rank || '-');
        return '<td>' + esc(String(val)) + '</td>';
    }

    // _parent에서 값 가져오기 (group 칼럼)
    val = row[key];
    if (val === undefined && row._parent) val = row._parent[key];

    // product_url → 링크 아이콘 + URL 텍스트
    if (key === 'product_url') {
        if (!val) return '<td>-</td>';
        return '<td data-copy-text="' + esc(val) + '" title="' + esc(val) + '">'
            + '<a href="' + esc(val) + '" target="_blank" onclick="event.stopPropagation();" style="color:#2563eb;margin-right:6px;vertical-align:middle;cursor:pointer;">'
            + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
            + '</a>'
            + esc(val)
            + '</td>';
    }

    // null_fields → 배열 join + 하이라이트
    if (key === 'null_fields') {
        var nf = row.null_fields;
        var text = (Array.isArray(nf) ? nf.join(', ') : nf) || '-';
        return '<td class="null-value">' + esc(text) + '</td>';
    }

    // reason 스타일
    if (key === 'reason') {
        return '<td style="color:#dc2626;font-size:12px;">' + esc(String(val || '-')) + '</td>';
    }

    // comment_text_display → word-break
    if (key === 'comment_text_display') {
        return '<td style="white-space:normal;word-break:break-word;">' + esc(String(val || '-')) + '</td>';
    }

    // NULL 필드 하이라이트 (해당 필드가 record의 null_fields에 포함된 경우)
    if (row.null_fields && Array.isArray(row.null_fields) && row.null_fields.includes(key)) {
        var rowId2 = row.id || (row._parent && row._parent.id);
        var nrKey = rowId2 + '_' + key;
        var nr = detailViewState.normalReviews && detailViewState.normalReviews[nrKey];
        if (nr) {
            // 정상 처리된 셀: 회색 + 툴팁
            var nrTip = '정상 처리됨';
            if (nr.reason) nrTip += ' | 이유: ' + nr.reason;
            if (nr.memo) nrTip += ' | 메모: ' + nr.memo;
            if (nr.created_id) nrTip += ' | ' + nr.created_id;
            if (nr.created_at) nrTip += ' (' + nr.created_at + ')';
            return '<td class="cell-normal" data-normal-key="' + esc(nrKey) + '" data-row-id="' + rowId2 + '" data-col="' + esc(key) + '" title="' + esc(nrTip) + '">' + esc(String(val || 'NULL')) + ' <span class="normal-badge">정상</span></td>';
        }
        var editAttr2 = _editableAttr(row, key);
        return '<td class="null-value"' + editAttr2 + ' title="' + esc(String(val || 'NULL')) + '">' + esc(String(val || 'NULL')) + '</td>';
    }

    // 형식 오류 필드 하이라이트 (error_fields에 포함된 경우)
    if (row.error_fields && Array.isArray(row.error_fields) && row.error_fields.includes(key)) {
        var rowId3 = row.id || (row._parent && row._parent.id);
        var nrKey3 = rowId3 + '_' + key;
        var nr3 = detailViewState.normalReviews && detailViewState.normalReviews[nrKey3];
        if (nr3) {
            var nrTip3 = '정상 처리됨';
            if (nr3.reason) nrTip3 += ' | 이유: ' + nr3.reason;
            if (nr3.memo) nrTip3 += ' | 메모: ' + nr3.memo;
            if (nr3.created_id) nrTip3 += ' | ' + nr3.created_id;
            if (nr3.created_at) nrTip3 += ' (' + nr3.created_at + ')';
            return '<td class="cell-normal" data-normal-key="' + esc(nrKey3) + '" data-row-id="' + rowId3 + '" data-col="' + esc(key) + '" title="' + esc(nrTip3) + '">' + esc(String(val || '-')) + ' <span class="normal-badge">정상</span></td>';
        }
        var errDetail = row.error_details && row.error_details[key];
        var errTip = errDetail ? (errDetail.rule + ': ' + errDetail.reason) : '';
        var editAttr3 = _editableAttr(row, key);
        return '<td class="null-value"' + editAttr3 + ' title="' + esc(errTip) + '">' + esc(String(val || '-')) + '</td>';
    }

    var editAttr = _editableAttr(row, key);
    if (val === null || val === undefined || val === '') return '<td' + editAttr + '>-</td>';
    return '<td' + editAttr + ' title="' + esc(String(val)) + '">' + esc(String(val)) + '</td>';
}

function buildDetailContainerHtml(options) {
    var html = '<div class="detail-view-wrapper">';
    if (options.itemQueryHtml) {
        html += '<div id="detail-item-query">' + options.itemQueryHtml + '</div>';
    }
    html += '<div id="detail-filter-bar"></div>';
    html += '<div id="detail-action-bar"></div>';
    html += '<div id="detail-table-area"></div>';
    html += '<div id="detail-pagination"></div>';
    html += '</div>';
    return html;
}

function renderDetailWithTable(options) {
    var config = options.config;
    var data = options.data;
    var tableParam = options.tableParam || '';
    var type = options.type || 'null';
    var selectCols = options.selectCols || null;
    var editableCols = options.editableCols || [];
    var actualTable = options.actualTable || '';
    var crawlDate = options.crawlDate || '';
    var normalReviews = options.normalReviews || {};
    var dateColumn = options.dateColumn || '';
    var isRowspan = !Array.isArray(config);
    var defaultCols = getAllColumns(config);

    detailViewState.type = type;
    detailViewState.tableParam = tableParam;
    detailViewState.editableCols = new Set(editableCols);
    detailViewState.normalReviews = normalReviews;
    detailViewState.actualTable = actualTable;
    detailViewState.crawlDate = crawlDate;
    detailViewState.dateColumn = dateColumn;

    // flat 데이터 생성
    var flatData;
    if (isRowspan) {
        flatData = flattenRecords(type, data, tableParam);
    } else {
        flatData = data;
    }
    detailViewState.allData = flatData;
    detailViewState.originalData = flatData.slice();
    detailViewState.filteredData = null;
    detailViewState.sortColumns = [];

    // 전체 컬럼 목록 구성
    var defaultKeySet = {};
    defaultCols.forEach(function(c) { defaultKeySet[c.key] = c; });

    var allColumns = [];
    var defaultVisibleKeys = [];

    // 기본 표시 컬럼 키 수집
    defaultCols.forEach(function(c) { defaultVisibleKeys.push(c.key); });

    if (isRowspan) {
        // rowspan 모드(중복 검증): group + detail 원래 순서 유지 (헤더와 데이터 셀 순서 일치 필수)
        defaultCols.forEach(function(c) { allColumns.push(c); });
    } else {
        // flat 모드: id → 디폴트 컬럼 순서 → 나머지 asc 정렬
        // 1) id를 맨 앞에
        if (defaultKeySet['id']) {
            allColumns.push(defaultKeySet['id']);
        }

        // 2) 나머지 디폴트 컬럼 (id, null_fields 제외) 정해진 순서대로
        defaultCols.forEach(function(c) {
            if (c.key === 'id' || c.key === 'null_fields') return;
            allColumns.push(c);
        });
    }

    // selectCols(백엔드)에 있지만 defaultCols에 없는 추가 컬럼 → asc 정렬
    if (selectCols && selectCols.length > 0) {
        var extraCols = [];
        selectCols.forEach(function(key) {
            if (key === 'null_fields' || key === '_no') return;
            if (defaultKeySet[key]) return;
            extraCols.push({
                key: key,
                label: key,
                width: 120
            });
        });
        extraCols.sort(function(a, b) { return a.key.localeCompare(b.key); });
        extraCols.forEach(function(c) { allColumns.push(c); });
    }

    // FilterBar (섹션 페이지에서만 표시, 대시보드 모달에서는 숨김)
    if (isInlineMode()) {
        var visibleKeys = defaultVisibleKeys.filter(function(k) { return k !== 'null_fields'; });
        var filterCols = visibleKeys.map(function(key) {
            var col = defaultKeySet[key];
            return { value: key, label: col ? col.label : key };
        });
        var fbOptions = {
            sticky: false,
            padding: '8px 12px',
            controls: [
                { type: 'select', key: 'filterCol', label: '항목', width: 'auto', options: filterCols },
                { type: 'input', key: 'filterVal', placeholder: '검색어 입력...', onEnter: function() { applyDetailFilter(); } }
            ],
            onSearch: function() { applyDetailFilter(); },
            onReset: function() { clearDetailFilter(); },
            columnSelector: {
                columns: allColumns,
                fixed: ['id'],
                defaultVisible: defaultVisibleKeys,
                onUpdate: function() { _rebuildDetailTable(); }
            }
        };
        fbOptions.right = [
            { type: 'button', label: '정렬 초기화', style: 'outline', size: 'fb', onClick: function() { resetDetailSort(); } }
        ];
        detailViewState.filterBar = new FilterBar('#detail-filter-bar', fbOptions).render();
        detailViewState.columns = detailViewState.filterBar.getVisibleColumns();
    } else {
        detailViewState.filterBar = null;
        detailViewState.columns = defaultCols;
    }

    // CommonTable 생성
    _buildDetailTable();

    // 중복 검증: 액션 버튼바
    if (isRowspan && type === 'duplicate') {
        _renderDupActionBar();
    }

    // Pagination
    var pageSize = detailViewState.pageSize || 15;
    detailViewState.pager = new Pagination('#detail-pagination', {
        pageSize: pageSize,
        showInfo: true,
        padding: '0',
        margin: '0',
        border: 'none',
        onPageChange: function(page) {
            _resetPendingEdits();
            detailRenderPage(page);
        }
    });

    // 첫 페이지 렌더
    detailRenderPage(1);
}

// 컬럼 선택 변경 시 테이블 재생성
function _rebuildDetailTable() {
    if (!detailViewState.filterBar) return;
    detailViewState.columns = detailViewState.filterBar.getVisibleColumns();
    _buildDetailTable();

    // FilterBar select 옵션 갱신 (현재 visible 컬럼만)
    var sel = document.getElementById('filterCol');
    if (sel) {
        sel.innerHTML = '';
        detailViewState.columns.forEach(function(c) {
            if (c.key === 'null_fields') return;
            var opt = document.createElement('option');
            opt.value = c.key;
            opt.textContent = c.label;
            sel.appendChild(opt);
        });
    }

    var currentPage = detailViewState.pager ? detailViewState.pager.getCurrentPage() : 1;
    detailRenderPage(currentPage);
}

function _buildDetailTable() {
    var visibleCols = detailViewState.columns;
    var config = getColumnConfig(detailViewState.type, detailViewState.tableParam);
    var isRowspan = !Array.isArray(config);
    // No 컬럼을 항상 맨 앞에 추가 (컬럼 선택과 무관)
    var isDuplicate = detailViewState.type === 'duplicate';
    var ctColumns = [];
    if (isDuplicate) {
        ctColumns.push({ key: '_chk', label: '', width: 40, sortable: false, align: 'center' });
    }
    ctColumns.push({ key: '_no', label: 'No', width: 50, sortable: false, align: 'center' });
    visibleCols.forEach(function(col) {
        if (col.key === '_no') return;
        ctColumns.push({ key: col.key, label: col.label, width: col.width, sortable: !isRowspan && col.key === 'item', align: col.align });
    });
    document.getElementById('detail-table-area').innerHTML = '';
    detailViewState.table = new CommonTable('#detail-table-area', {
        variant: 'detail',
        columns: ctColumns,
        vlines: true,
        rounded: true,
        showTotalCount: true,
        padding: '6px 12px',
        reorder: true,
        fixedColumns: ['_no'],
        multiSort: !isRowspan,
        pageSize: detailViewState.pageSize || 15,
        onPageSizeChange: function(val) {
            detailViewState.pageSize = val;
            if (detailViewState.pager) detailViewState.pager.options.pageSize = val;
            detailRenderPage(1);
        },
        onSort: !isRowspan ? function(sortCols) { handleDetailSort(sortCols); } : undefined,
        onReorder: function(newColumns) {
            // No 컬럼 제외한 순서로 detailViewState.columns 갱신
            var cols = [];
            newColumns.forEach(function(c) {
                if (c.key === '_no') return;
                cols.push(c);
            });
            detailViewState.columns = cols;
            // FilterBar 컬럼 선택 드롭다운 순서 동기화
            if (detailViewState.filterBar && detailViewState.filterBar.reorderColumns) {
                detailViewState.filterBar.reorderColumns(cols.map(function(c) { return c.key; }));
            }
            // 항목 드롭다운 갱신
            var sel = document.getElementById('filterCol');
            if (sel) {
                sel.innerHTML = '';
                cols.forEach(function(c) {
                    if (c.key === 'null_fields') return;
                    var opt = document.createElement('option');
                    opt.value = c.key;
                    opt.textContent = c.label;
                    sel.appendChild(opt);
                });
            }
            // rowspan 사용 시 DOM 재정렬이 셀 수 불일치로 깨지므로 테이블 재생성
            if (detailViewState.type === 'null') {
                setTimeout(function() {
                    _buildDetailTable();
                    var currentPage = detailViewState.pager ? detailViewState.pager.getCurrentPage() : 1;
                    detailRenderPage(currentPage);
                }, 0);
            }
        }
    });
    detailViewState.table.render();
    if (isDuplicate) _injectDupCheckboxHeader();

    // 정렬 상태 복원
    if (!isRowspan && detailViewState.sortColumns.length > 0) {
        detailViewState.table.setSortColumns(detailViewState.sortColumns.map(function(s) {
            return { key: s.key, order: s.direction };
        }));
    }

    // 인라인 편집 (섹션 페이지, editable 셀만)
    // - 클릭: 셀 선택 (Ctrl+V 붙여넣기 가능)
    // - 더블클릭: 직접 입력 모드
    if (isInlineMode() && detailViewState.editableCols && detailViewState.editableCols.size > 0) {
        detailViewState.pendingEdits = {};
        detailViewState.selectedCell = null;

        var tableEl = detailViewState.table.getTable();

        // 클릭: 셀 선택 (editable 셀) 또는 null/normal 셀 액션 바
        tableEl.addEventListener('click', function(e) {
            var td = e.target.closest('td[data-editable]');
            var nullTd = !td ? e.target.closest('td.null-value, td.cell-normal') : null;
            var prev = tableEl.querySelector('.cell-selected');
            if (prev) prev.classList.remove('cell-selected');
            _hideNullReviewBar();
            if (td) {
                td.classList.add('cell-selected');
                detailViewState.selectedCell = td;
                // null-value이면서 아직 수정하지 않은 셀만 정상 처리 바 표시
                if (td.classList.contains('null-value') && !td.classList.contains('cell-pending')) {
                    _showNullReviewBar(td, 'normal');
                }
            } else if (nullTd) {
                detailViewState.selectedCell = null;
                // cell-normal은 무시 (정상처리 완료된 셀)
            } else {
                detailViewState.selectedCell = null;
            }
        });

        // 테이블 외부 클릭 시 선택 해제
        document.addEventListener('click', function(e) {
            if (!e.target.closest('#detail-table-area table') && !e.target.closest('#null-review-bar')) {
                var sel = tableEl.querySelector('.cell-selected');
                if (sel) sel.classList.remove('cell-selected');
                detailViewState.selectedCell = null;
                _hideNullReviewBar();
            }
        });

        // Ctrl+V 붙여넣기
        document.addEventListener('paste', function(e) {
            var td = detailViewState.selectedCell;
            if (!td || !td.dataset.editable || document.querySelector('.cell-edit-overlay')) return;
            e.preventDefault();
            var pastedText = (e.clipboardData || window.clipboardData).getData('text').trim();
            _applyEdit(td, pastedText);
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
                _applyEdit(td, newVal);
            }

            input.addEventListener('keydown', function(ev) {
                if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
                if (ev.key === 'Escape') { committed = true; input.remove(); }
            });
            input.addEventListener('blur', commit);
        });
    }
}

function _applyEdit(td, newVal) {
    var rowId = td.dataset.rowId;
    var colName = td.dataset.col;
    var oldText = td.textContent.trim();
    if (oldText === '-') oldText = '';
    if (newVal === oldText) return;
    _hideNullReviewBar();
    td.textContent = newVal || '-';
    td.classList.remove('null-value');
    td.classList.add('cell-pending');
    var editKey = rowId + '_' + colName;
    var prev = detailViewState.pendingEdits[editKey];
    detailViewState.pendingEdits[editKey] = {
        table_name: detailViewState.actualTable,
        row_id: parseInt(rowId),
        column_name: colName,
        new_value: newVal,
        _oldValue: prev ? prev._oldValue : oldText,
        crawl_date: detailViewState.crawlDate || '',
        td: td
    };
    _updateDetailData(rowId, colName, newVal);
    _updateSaveButton();
}

function _updateSaveButton() {
    var countEl = document.querySelector('#detail-table-area .ct-count');
    if (!countEl) return;
    var wrap = document.getElementById('detail-edit-actions');
    var count = Object.keys(detailViewState.pendingEdits || {}).length;
    if (count === 0) {
        if (wrap) wrap.remove();
        return;
    }
    if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'detail-edit-actions';
        wrap.className = 'detail-edit-actions';
        var infoSpan = document.createElement('span');
        infoSpan.id = 'edit-actions-info';
        infoSpan.className = 'edit-actions-info';
        var btnGroup = document.createElement('div');
        btnGroup.style.cssText = 'display:flex;gap:8px;';
        var btnCancel = document.createElement('button');
        btnCancel.className = 'btn-cancel-edits';
        btnCancel.textContent = '취소';
        btnCancel.addEventListener('click', _cancelAllEdits);
        var btnSave = document.createElement('button');
        btnSave.id = 'btn-save-edits';
        btnSave.className = 'btn-save-edits';
        btnSave.addEventListener('click', _saveAllEdits);
        btnGroup.appendChild(btnCancel);
        btnGroup.appendChild(btnSave);
        wrap.appendChild(infoSpan);
        wrap.appendChild(btnGroup);
        var tableEl = document.querySelector('#detail-table-area table');
        if (tableEl) {
            tableEl.parentNode.insertBefore(wrap, tableEl);
        } else {
            countEl.parentNode.insertBefore(wrap, countEl);
        }
    }
    document.getElementById('edit-actions-info').textContent = count + '건 변경됨';
    document.getElementById('btn-save-edits').textContent = '저장';
}

function _resetPendingEdits() {
    var edits = detailViewState.pendingEdits;
    if (!edits) return;
    Object.keys(edits).forEach(function(k) {
        var edit = edits[k];
        _updateDetailData(edit.row_id, edit.column_name, edit._oldValue);
    });
    detailViewState.pendingEdits = {};
    var wrap = document.getElementById('detail-edit-actions');
    if (wrap) wrap.remove();
}

function _cancelAllEdits() {
    var edits = detailViewState.pendingEdits;
    if (!edits) return;
    Object.keys(edits).forEach(function(k) {
        var edit = edits[k];
        if (edit.td) {
            edit.td.classList.remove('cell-pending');
            // 원래 값 복원
            var origVal = edit._oldValue;
            edit.td.textContent = (origVal === null || origVal === undefined || origVal === '') ? '-' : origVal;
            _updateDetailData(edit.row_id, edit.column_name, origVal);
        }
    });
    detailViewState.pendingEdits = {};
    _updateSaveButton();
}

function _saveAllEdits() {
    var edits = detailViewState.pendingEdits;
    if (!edits) return;
    var keys = Object.keys(edits);
    if (keys.length === 0) return;

    _showMemoDialog(function(memo) {
        _doSaveEdits(memo);
    }, '수정 메모', '수정 사유 입력 (선택사항)');
}

function _doSaveEdits(memo) {
    var edits = detailViewState.pendingEdits;
    if (!edits) return;
    var keys = Object.keys(edits);
    if (keys.length === 0) return;

    var btn = document.getElementById('btn-save-edits');
    if (btn) { btn.disabled = true; btn.textContent = '저장 중...'; }

    var requests = keys.map(function(k) {
        var edit = edits[k];
        return fetch('/dx/layer2/api/update-cell/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                table_name: edit.table_name,
                row_id: edit.row_id,
                column_name: edit.column_name,
                new_value: edit.new_value,
                crawl_date: edit.crawl_date,
                correction_type: detailViewState.type || 'null',
                memo: memo || ''
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
        results.forEach(function(r) {
            var edit = edits[r.key];
            if (r.success) {
                successCount++;
                if (edit.td) {
                    edit.td.classList.remove('cell-pending');
                    edit.td.classList.add('cell-saved');
                    setTimeout(function() { edit.td.classList.remove('cell-saved'); }, 1500);
                }
                delete edits[r.key];
            } else {
                failCount++;
            }
        });
        if (successCount > 0) showToast(successCount + '건 저장 완료', 'success');
        if (failCount > 0) showToast(failCount + '건 저장 실패', 'error');
        _updateSaveButton();
    });
}

function _updateDetailData(rowId, colName, newVal) {
    var id = parseInt(rowId);
    if (detailViewState.allData) {
        detailViewState.allData.forEach(function(row) {
            if (row.id === id || (row._parent && row._parent.id === id)) {
                var target = row[colName] !== undefined ? row : (row._parent || row);
                target[colName] = newVal === '' ? null : newVal;
            }
        });
    }
}

// ==================== NULL 정상 처리 ====================
function _showNullReviewBar(td, mode) {
    _hideNullReviewBar();
    var bar = document.createElement('div');
    bar.id = 'null-review-bar';
    bar.className = 'null-review-bar';
    var colName = td.dataset.col || '';
    var rowId = td.dataset.rowId || '';
    var errLabel = detailViewState.type === 'format' ? '형식 오류' : 'NULL 오류';
    var infoText = colName + ' (ID: ' + rowId + ') — ' + errLabel;
    var info = document.createElement('span');
    info.className = 'null-review-info';
    info.textContent = infoText;
    var btn = document.createElement('button');
    btn.className = 'btn-null-normal';
    btn.textContent = '확인';
    btn.addEventListener('click', function() {
        _showReviewDialog(function(reason, memo) {
            _submitNullReview(td, 'normal', memo, reason);
        });
    });
    bar.appendChild(info);
    bar.appendChild(btn);
    var tableEl = document.querySelector('#detail-table-area table');
    if (tableEl) tableEl.parentNode.insertBefore(bar, tableEl);
}

function _hideNullReviewBar() {
    var bar = document.getElementById('null-review-bar');
    if (bar) bar.remove();
}

// 정상 처리 다이얼로그 (이유 선택 필수 + 메모 선택)
function _showReviewDialog(callback) {
    var overlay = document.createElement('div');
    overlay.className = 'memo-dialog-overlay';
    overlay.innerHTML = '<div class="memo-dialog">'
        + '<div class="memo-dialog-title">확인</div>'
        + '<div class="memo-dialog-field"><label class="memo-dialog-label">이유 <span style="color:#dc2626;">*</span></label>'
        + '<select class="memo-dialog-select" id="review-reason-select"><option value="">불러오는 중...</option></select></div>'
        + '<div class="memo-dialog-field"><label class="memo-dialog-label">메모</label>'
        + '<textarea class="memo-dialog-input" placeholder="메모 입력 (선택사항)" rows="3"></textarea></div>'
        + '<div class="memo-dialog-buttons">'
        + '<button class="memo-dialog-cancel">취소</button>'
        + '<button class="memo-dialog-confirm">확인</button>'
        + '</div></div>';
    document.body.appendChild(overlay);
    setTimeout(function() { overlay.classList.add('show'); }, 10);

    // 이유 목록 조회
    var checkType = (detailViewState.type === 'null') ? 'null_check' : (detailViewState.type + '_check');
    fetch('/dx/layer2/api/review-reasons/?check_type=' + encodeURIComponent(checkType))
        .then(function(r) { return r.json(); })
        .then(function(res) {
            var sel = document.getElementById('review-reason-select');
            if (!sel) return;
            var reasons = res.reasons || [];
            if (reasons.length === 0) {
                // 사유 목록이 비어있으면 select 영역 숨김 (메모만 사용)
                var reasonField = sel.closest('.memo-dialog-field');
                if (reasonField) reasonField.style.display = 'none';
            } else {
                sel.innerHTML = '<option value="">-- 선택 --</option>';
                reasons.forEach(function(r) {
                    var opt = document.createElement('option');
                    opt.value = r.text;
                    opt.textContent = r.text;
                    sel.appendChild(opt);
                });
            }
        })
        .catch(function() {
            var sel = document.getElementById('review-reason-select');
            if (sel) sel.innerHTML = '<option value="">로딩 실패</option>';
        });

    var textarea = overlay.querySelector('.memo-dialog-input');
    function closeDlg() {
        overlay.classList.remove('show');
        setTimeout(function() { overlay.remove(); }, 200);
    }
    overlay.querySelector('.memo-dialog-cancel').addEventListener('click', closeDlg);
    overlay.querySelector('.memo-dialog-confirm').addEventListener('click', function() {
        var selEl = document.getElementById('review-reason-select');
        var reasonField = selEl ? selEl.closest('.memo-dialog-field') : null;
        var reasonHidden = reasonField && reasonField.style.display === 'none';
        var reason = reasonHidden ? '' : (selEl ? selEl.value : '');
        var memo = textarea.value.trim();
        if (!reasonHidden && !reason) { showToast('이유를 선택해주세요', 'error'); return; }
        closeDlg();
        callback(reason, memo);
    });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeDlg();
    });
}

// 수정 저장용 메모 다이얼로그 (이유 없음, 메모 선택)
function _showMemoDialog(callback, title, placeholder) {
    var dlgTitle = title || '수정 메모';
    var dlgPlaceholder = placeholder || '메모 입력 (선택사항)';
    var overlay = document.createElement('div');
    overlay.className = 'memo-dialog-overlay';
    overlay.innerHTML = '<div class="memo-dialog">'
        + '<div class="memo-dialog-title">' + dlgTitle + '</div>'
        + '<textarea class="memo-dialog-input" placeholder="' + dlgPlaceholder + '" rows="3"></textarea>'
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

function _submitNullReview(td, status, memo, reason) {
    var rowId = td.dataset.rowId || (td.dataset.normalKey && td.dataset.normalKey.split('_')[0]);
    var colName = td.dataset.col || (td.dataset.normalKey && td.dataset.normalKey.split('_').slice(1).join('_'));
    if (!rowId || !colName) return;

    fetch('/dx/layer2/api/null-review/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
            table_name: detailViewState.actualTable,
            record_id: parseInt(rowId),
            column_name: colName,
            status: status,
            memo: memo || '',
            reason: reason || '',
            crawl_date: detailViewState.crawlDate || '',
            correction_type: detailViewState.type === 'format' ? 'format' : 'null'
        })
    }).then(function(r) { return r.json(); })
    .then(function(res) {
        if (res.success) {
            _hideNullReviewBar();
            if (status === 'normal') {
                // 정상 처리 → normalReviews에 추가 + 셀 스타일 변경
                var nrKey = rowId + '_' + colName;
                if (!detailViewState.normalReviews) detailViewState.normalReviews = {};
                detailViewState.normalReviews[nrKey] = { memo: memo, reason: '', created_id: '', created_at: '' };
                td.className = 'cell-normal';
                td.dataset.normalKey = nrKey;
                td.removeAttribute('data-editable');
                var badge = td.querySelector('.normal-badge');
                if (!badge) {
                    var span = document.createElement('span');
                    span.className = 'normal-badge';
                    span.textContent = '정상';
                    td.appendChild(span);
                }
                var tip = '정상 처리됨';
                if (memo) tip += ' | 메모: ' + memo;
                td.title = tip;
                showToast('확인 처리 완료', 'success');
            }
        } else {
            showToast(res.error || '처리 실패', 'error');
        }
    }).catch(function() {
        showToast('네트워크 오류', 'error');
    });
}

function handleDetailSort(sortCols) {
    detailViewState.sortColumns = sortCols.map(function(s) {
        return { key: s.key, direction: s.order };
    });

    if (detailViewState.sortColumns.length === 0) {
        detailViewState.allData = detailViewState.originalData.slice();
    } else {
        var cols = detailViewState.sortColumns;
        detailViewState.allData.sort(function(a, b) {
            for (var i = 0; i < cols.length; i++) {
                var key = cols[i].key;
                var dir = cols[i].direction;
                var valA = a[key], valB = b[key];
                var aIsNull = (valA === null || valA === undefined || valA === '');
                var bIsNull = (valB === null || valB === undefined || valB === '');
                if (aIsNull && bIsNull) continue;
                if (aIsNull) return 1;
                if (bIsNull) return -1;
                var numA = parseFloat(valA), numB = parseFloat(valB);
                if (!isNaN(numA) && !isNaN(numB)) {
                    var diff = dir === 'asc' ? numA - numB : numB - numA;
                    if (diff !== 0) return diff;
                    continue;
                }
                var strA = String(valA).toLowerCase(), strB = String(valB).toLowerCase();
                var cmp = dir === 'asc' ? strA.localeCompare(strB) : strB.localeCompare(strA);
                if (cmp !== 0) return cmp;
            }
            return 0;
        });
    }

    if (detailViewState.filteredData) applyDetailFilter();
    detailRenderPage(1);
}

function resetDetailSort() {
    detailViewState.sortColumns = [];
    detailViewState.allData = detailViewState.originalData.slice();
    if (detailViewState.table) detailViewState.table.setSortColumns([]);
    if (detailViewState.filteredData) applyDetailFilter();
    detailRenderPage(1);
}

function detailRenderPage(page) {
    var source = detailViewState.filteredData || detailViewState.allData;
    var config = getColumnConfig(detailViewState.type, detailViewState.tableParam);
    var isRowspan = !Array.isArray(config);
    var tableParam = detailViewState.tableParam;
    var visibleCols = detailViewState.columns;
    var pageSize = (detailViewState.table && detailViewState.table.getPageSize)
        ? detailViewState.table.getPageSize()
        : (detailViewState.pager ? detailViewState.pager.getPageSize() : 15);
    if (detailViewState.pager) detailViewState.pager.options.pageSize = pageSize;

    // rowspan인 경우 그룹 단위로 페이징
    var pageData, totalItems, startIdx;
    if (isRowspan) {
        var groups = [];
        var curGroup = [];
        source.forEach(function(row) {
            if (row._isGroupFirst && curGroup.length > 0) {
                groups.push(curGroup);
                curGroup = [];
            }
            curGroup.push(row);
        });
        if (curGroup.length > 0) groups.push(curGroup);

        totalItems = groups.length;
        var startGroup = (page - 1) * pageSize;
        var endGroup = Math.min(startGroup + pageSize, groups.length);
        pageData = [];
        startIdx = startGroup;
        for (var g = startGroup; g < endGroup; g++) {
            pageData = pageData.concat(groups[g]);
        }
    } else {
        totalItems = source.length;
        var start = (page - 1) * pageSize;
        startIdx = start;
        var end = Math.min(start + pageSize, source.length);
        pageData = source.slice(start, end);
    }

    // item rowspan 계산 (flat 모드, null 타입만)
    if (!isRowspan && detailViewState.type === 'null') {
        for (var ri = 0; ri < pageData.length; ri++) {
            var curItem = pageData[ri].item || '';
            var span = 1;
            while (ri + span < pageData.length && (pageData[ri + span].item || '') === curItem) {
                span++;
            }
            if (span > 1) {
                pageData[ri]._itemRowspan = span;
                for (var si = 1; si < span; si++) {
                    pageData[ri + si]._itemRowspan = 0;
                }
                ri += span - 1;
            } else {
                delete pageData[ri]._itemRowspan;
            }
        }
    }

    // renderBody
    var rowNum = startIdx;
    var isDup = detailViewState.type === 'duplicate';
    detailViewState.table.renderBody(pageData, function(row) {
        if (isRowspan) {
            var tr = '<tr>';
            // 중복 검증: 체크박스 (매 행, rowspan 없음)
            if (isDup) {
                tr += '<td style="text-align:center"><input type="checkbox" class="dup-check" data-id="' + row.id + '"' +
                      (row._isGroupLast ? ' data-group-last="1"' : '') + '></td>';
            }
            if (row._isGroupFirst) {
                config.group.forEach(function(col) {
                    tr += '<td rowspan="' + row._groupSize + '"' +
                          (col.align ? ' style="text-align:' + col.align + ';font-weight:500;"' : '') + '>' +
                          getCellHtml(row, col, tableParam).replace(/^<td[^>]*>/, '').replace(/<\/td>$/, '') + '</td>';
                });
            }
            config.detail.forEach(function(col) {
                tr += getCellHtml(row, col, tableParam);
            });
            if (row._isGroupFirst && config.trailing) {
                config.trailing.forEach(function(col) {
                    tr += '<td rowspan="' + row._groupSize + '">' +
                          getCellHtml(row, col, tableParam).replace(/^<td[^>]*>/, '').replace(/<\/td>$/, '') + '</td>';
                });
            }
            return tr + '</tr>';
        } else {
            rowNum++;
            var tr = '<tr>';
            // No 컬럼 (항상 맨 앞)
            tr += '<td style="text-align:center;font-weight:500;">' + rowNum + '</td>';
            visibleCols.forEach(function(col) {
                if (col.key === 'item' && row._itemRowspan !== undefined) {
                    if (row._itemRowspan > 0) {
                        tr += '<td rowspan="' + row._itemRowspan + '">' + esc(String(row.item || '')) + '</td>';
                    }
                } else {
                    tr += getCellHtml(row, col, tableParam);
                }
            });
            return tr + '</tr>';
        }
    });

    // Pagination
    detailViewState.pager.render(totalItems, page);

    // 건수 (CommonTable의 ct-count를 전체 건수로 덮어쓰기)
    var countEl = document.querySelector('#detail-table-area .ct-count');
    if (countEl) {
        var suffix = detailViewState.filteredData ? ' (필터 적용)' : '';
        countEl.innerHTML = '총 <strong>' + totalItems.toLocaleString() + '</strong>건' + suffix;
    }

}

function applyDetailFilter() {
    if (!detailViewState.filterBar) return;
    var colKey = detailViewState.filterBar.getValue('filterCol');
    var keyword = (detailViewState.filterBar.getValue('filterVal') || '').trim().toLowerCase();
    var allCols = detailViewState.columns;
    var config = getColumnConfig(detailViewState.type, detailViewState.tableParam);
    var isRowspan = !Array.isArray(config);
    var col = null;
    for (var i = 0; i < allCols.length; i++) {
        if (allCols[i].key === colKey) { col = allCols[i]; break; }
    }
    if (!col) return;

    var source = detailViewState.allData;
    if (!keyword) {
        detailViewState.filteredData = null;
    } else if (isRowspan) {
        // 그룹 단위 필터: 그룹 내 어느 행이든 매칭 시 전체 그룹 포함
        var groups = [];
        var curGroup = [];
        source.forEach(function(row) {
            if (row._isGroupFirst && curGroup.length > 0) {
                groups.push(curGroup);
                curGroup = [];
            }
            curGroup.push(row);
        });
        if (curGroup.length > 0) groups.push(curGroup);

        var filtered = [];
        groups.forEach(function(group) {
            var match = group.some(function(row) {
                var val = row[col.key];
                if (val === undefined && row._parent) val = row._parent[col.key];
                if (col.key === '_no') val = String(row._groupNumber || '');
                if (col.key === '_identifier') val = row._parent ? (row._parent.keyword || row._parent.video_id || '') : '';
                if (col.key === '_rank') val = row.rank || row.main_rank || row.bsr_rank || '';
                if (col.key === 'null_fields' && Array.isArray(row.null_fields)) val = row.null_fields.join(', ');
                return val !== null && val !== undefined && String(val).toLowerCase().indexOf(keyword) !== -1;
            });
            if (match) filtered = filtered.concat(group);
        });
        detailViewState.filteredData = filtered;
    } else {
        detailViewState.filteredData = source.filter(function(row) {
            var val = row[col.key];
            if (col.key === 'null_fields' && Array.isArray(row.null_fields)) val = row.null_fields.join(', ');
            return val !== null && val !== undefined && String(val).toLowerCase().indexOf(keyword) !== -1;
        });
    }

    detailRenderPage(1);
}

function clearDetailFilter() {
    detailViewState.filteredData = null;
    detailRenderPage(1);
}


// ViewStack — 섹션 페이지에서 모달 대신 인라인 콘텐츠 교체
const ViewStack = {
    stack: [],
    getContainer() { return document.getElementById('dx-validation-container'); },
    push(html) {
        const c = this.getContainer();
        if (!c) return;
        this.stack.push({ html: c.innerHTML, scrollTop: window.scrollY });
        c.innerHTML = html;
        window.scrollTo(0, 0);
        this._updateBackBtn();
    },
    pop() {
        if (this.stack.length === 0) return false;
        const s = this.stack.pop();
        const c = this.getContainer();
        if (c) { c.innerHTML = s.html; window.scrollTo(0, s.scrollTop); }
        this._updateBackBtn();
        return true;
    },
    depth() { return this.stack.length; },
    _updateBackBtn() {
        var el = document.getElementById('viewstack-back-container');
        if (el) el.style.display = this.stack.length > 0 ? '' : 'none';
        var fb = document.getElementById('filter-bar-container');
        if (fb) fb.style.display = this.stack.length > 1 ? 'none' : '';
    }
};

function isInlineMode() {
    const s = (window.LAYER2 && window.LAYER2.section) || 'dashboard';
    return s !== 'dashboard';
}

function getDetailBody() {
    return document.getElementById('detail-body') || document.getElementById('modal-body');
}

function getDetailSubtitle() {
    return document.getElementById('detail-subtitle') || (function() {
        var body = AppModal.getBody('l2-detail');
        return body ? body.querySelector('#modal-subtitle') : null;
    })();
}

document.addEventListener('DOMContentLoaded', function() {
    initFilterBar();
    checkBackupStatus();
    fetchDXStats();
});

async function checkBackupStatus() {
    const date = getSelectedDate();
    if (!date) return;
    try {
        const res = await fetch(`/dx/layer1/retail/api/backup-status/?date=${date}`);
        const data = await res.json();
        if (!data.success || data.pending_count === 0) return;

        if (!data.has_backup) {
            const goBackup = await showConfirm(`${date} 미백업 ${data.pending_count}건 (TV: ${data.tv_count}, HHP: ${data.hhp_count})\n백업 후 검수를 진행해주세요.`, 'warning', { okText: 'Layer 1 이동', cancelText: '계속 조회' });
            if (goBackup) window.location.href = '/dx/layer1/';
        } else {
            const goBackup = await showConfirm(`추가 수집 데이터 ${data.pending_count}건 미백업 (TV: ${data.tv_count}, HHP: ${data.hhp_count})\n백업 후 검수를 진행해주세요.`, 'warning', { okText: 'Layer 1 이동', cancelText: '계속 조회' });
            if (goBackup) window.location.href = '/dx/layer1/';
        }
    } catch (e) { /* 백업 상태 조회 실패 시 무시 */ }
}

// 로컬 날짜를 YYYY-MM-DD 형식으로 변환
function formatLocalDate(date) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function handleSearch() {
    checkBackupStatus();
    dxData = null;
    ViewStack.stack = [];
    ViewStack._updateBackBtn();
    document.getElementById('dx-validation-container').innerHTML = `
        <div class="loading">
            <div class="loading-spinner"></div>
            <p>데이터 로딩 중...</p>
        </div>`;
    fetchDXStats();
}


function closeModal() {
    AppModal.close('l2-detail');
}

// 검증규칙 모달
async function openRuleModal(tableName, retailer) {
    AppModal.setTitle('l2-rule', `${retailer} - 형식 검증 규칙`);
    AppModal.setBody('l2-rule', '<div style="text-align: center; padding: 20px;">로딩 중...</div>');
    AppModal.open('l2-rule');
    const body = AppModal.getBody('l2-rule');

    const tableNameMap = {
        'TV Retail': 'tv_retail_com',
        'HHP Retail': 'hhp_retail_com',
        'YouTube': 'youtube_videos',
        'Market': 'market_trend'
    };

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
        const response = await fetch(`/dx/layer2/api/format-rules/?table=${dbTableName}&retailer=${retailer}`);
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
                    <td class="rule-field">${rule.field}</td>
                    <td>${rule.description}</td>
                    <td><span class="rule-pattern">${rule.pattern}</span></td>
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

// ==================== 사이드바 ====================
function onSubitemClick(parentSection, tableName) {
    const section = (window.LAYER2 && window.LAYER2.section) || 'dashboard';
    const date = getSelectedDate();
    const dateParam = date ? `?date=${date}` : '';

    if (section !== parentSection) {
        const sectionUrls = {
            null_validation: 'null',
            format_validation: 'format',
            anomaly_validation: 'anomaly'
        };
        const path = sectionUrls[parentSection] || '';
        const sep = dateParam ? '&' : '?';
        window.location.href = `/dx/layer2/${path}/${dateParam}${sep}focus=${encodeURIComponent(tableName)}`;
        return;
    }

    // 같은 섹션: ViewStack으로 해당 테이블 상세 표시
    showTableDetailByName(tableName);

    // 사이드바 active 갱신
    document.querySelectorAll('.sidebar-subitem').forEach(function(el) {
        el.classList.toggle('active', el.textContent.trim() === tableName);
    });
}

function scrollToTable(tableName) {
    const tableItems = document.querySelectorAll('.table-item');
    for (const tableEl of tableItems) {
        const nameEl = tableEl.querySelector('.table-name');
        if (nameEl && nameEl.textContent.trim() === tableName) {
            // 상위 validation-section 펼침
            const vSection = tableEl.closest('.validation-section');
            if (vSection) {
                const tablesContainer = vSection.querySelector('.tables-container');
                const vIcon = vSection.querySelector('.toggle-icon');
                if (tablesContainer && !tablesContainer.classList.contains('show')) {
                    tablesContainer.classList.add('show');
                    if (vIcon) vIcon.classList.add('expanded');
                }
            }
            // 테이블 상세 펼침
            const detail = tableEl.querySelector('.detail-container');
            const tIcon = tableEl.querySelector('.toggle-icon');
            if (detail && !detail.classList.contains('show')) {
                detail.classList.add('show');
                if (tIcon) tIcon.classList.add('expanded');
            }
            tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
            tableEl.style.outline = '2px solid var(--layer-color)';
            setTimeout(() => { tableEl.style.outline = ''; }, 2000);
            return;
        }
    }
}

// 이름으로 테이블 상세 열기 (사이드바 서브아이템 클릭)
function showTableDetailByName(tableName) {
    if (!dxData || !dxData.validation_types || !dxData.validation_types[0]) return;
    const tables = dxData.validation_types[0].tables || [];
    const idx = tables.findIndex(t => t.table_name === tableName);
    if (idx >= 0) {
        // ViewStack 초기화 후 열기
        while (ViewStack.depth() > 0) ViewStack.pop();
        showTableDetail(idx);
    }
}

function handleFocusParam() {
    var target = currentFocusTable;
    if (!target) {
        const focus = new URLSearchParams(window.location.search).get('focus');
        if (focus) target = decodeURIComponent(focus);
    }

    if (target) {
        if (isInlineMode()) {
            showTableDetailByName(target);
        } else {
            scrollToTable(target);
        }
    }
}
