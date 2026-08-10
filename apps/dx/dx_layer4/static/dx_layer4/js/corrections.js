/**
 * Layer 4 검수기록
 */

(function() {
    'use strict';

    var currentPage = 1;

    // focus 파라미터 → 고정 검증유형
    var FOCUS_TO_TYPE = { 'NULL 검수': 'null_check', '형식 검수': 'format_check', '중복 검수': 'duplicate_check', '크로스필드 검수': 'cross_field', '누락필드 검수': 'field_missing' };
    var correctionsFocus = '';
    var correctionsFixedType = '';

    var correctionsFilterBar = null;

    function getActiveType() {
        return correctionsFixedType || 'all';
    }

    function resetFilters() {
        currentPage = 1;
        correctionsTable = null;
        loadCorrections();
    }

    function buildCorrectionsFilterBar() {
        var controls = [];

        // 검색 항목 드롭다운 + 검색어 입력
        var searchOptions = [
            { value: 'category', label: '카테고리' },
            { value: 'retailer', label: '리테일러' },
            { value: 'column_name', label: '컬럼' },
            { value: 'item', label: 'Item' },
            { value: 'record_id', label: 'Record' }
        ];
        if (!correctionsFixedType) {
            searchOptions.unshift({ value: 'correction_type', label: '검증유형' });
        }
        controls.push({
            type: 'select', key: 'filter-search-field', label: '항목',
            options: searchOptions
        });
        controls.push({
            type: 'input', key: 'filter-search-value', placeholder: '검색어 입력...',
            onEnter: resetFilters
        });

        correctionsFilterBar = new FilterBar('#corrections-filter-bar', {
            controls: controls, plain: true, sticky: false,
            onSearch: resetFilters,
            onReset: resetFilters
        }).render();

        updateCancelButton();
    }

    function initCorrectionsFilterBar() {
        var focusParam = new URLSearchParams(window.location.search).get('focus') || '';
        correctionsFocus = focusParam;
        correctionsFixedType = FOCUS_TO_TYPE[focusParam] || '';
        buildCorrectionsFilterBar();
        if (window.CORRECTIONS_IS_ADMIN) {
            addBulkHistoryTab();
        }
        initCorrectionsTabs();
    }

    function addBulkHistoryTab() {
        var tabsContainer = document.getElementById('corrections-tabs');
        if (!tabsContainer) return;
        var tab = document.createElement('button');
        tab.className = 'log-tab';
        tab.dataset.status = 'bulk_history';
        tab.innerHTML = '일괄 이력 <span style="font-size:10px;background:#7c3aed;color:white;border-radius:4px;padding:1px 5px;vertical-align:middle;margin-left:2px;">관리자</span>';
        tabsContainer.appendChild(tab);
    }

    function initCorrectionsTabs() {
        var tabsContainer = document.getElementById('corrections-tabs');
        if (!tabsContainer) return;
        tabsContainer.style.display = 'flex';
        var tabs = tabsContainer.querySelectorAll('.log-tab');
        tabs.forEach(function(tab) {
            tab.addEventListener('click', function() {
                tabs.forEach(function(t) { t.classList.remove('active'); });
                tab.classList.add('active');
                currentPage = 1;
                correctionsTable = null;
                updateCancelButton();

                var isBulk = tab.dataset.status === 'bulk_history';
                document.getElementById('corrections-table-container').style.display = isBulk ? 'none' : '';
                document.getElementById('corrections-pagination').style.display = isBulk ? 'none' : '';
                var bhs = document.getElementById('bulk-history-section');
                if (bhs) bhs.style.display = isBulk ? '' : 'none';

                if (isBulk) {
                    var daysEl = document.getElementById('bulk-history-days');
                    var days = daysEl ? (parseInt(daysEl.value) || 3) : 3;
                    bulkHistoryTable = null;
                    loadBulkHistory(days);
                } else {
                    loadCorrections();
                }
            });
        });
        updateCancelButton();
    }

    function updateCancelButton() {
        var existing = document.getElementById('corr-cancel-btn');
        if (existing) existing.remove();
        var activeTab = document.querySelector('#corrections-tabs .log-tab.active');
        if (!activeTab || activeTab.dataset.status !== 'normal') return;
        var tabsContainer = document.getElementById('corrections-tabs');
        if (!tabsContainer) return;
        var btn = document.createElement('button');
        btn.id = 'corr-cancel-btn';
        btn.className = 'app-btn app-btn-sm app-btn-danger';
        btn.textContent = '취소';
        btn.addEventListener('click', function() { cancelCheckedCorrections(); });
        tabsContainer.appendChild(btn);
    }

    function updateTabCounts(correctedCount, normalCount, revertedCount) {
        var el1 = document.getElementById('tabCorrectedCount');
        var el2 = document.getElementById('tabNormalCount');
        var el3 = document.getElementById('tabRevertedCount');
        if (el1) { el1.textContent = correctedCount; el1.className = 'tab-count ' + (correctedCount > 0 ? 'count-corrected' : 'count-zero'); }
        if (el2) { el2.textContent = normalCount; el2.className = 'tab-count ' + (normalCount > 0 ? 'count-normal' : 'count-zero'); }
        if (el3) { el3.textContent = revertedCount; el3.className = 'tab-count ' + (revertedCount > 0 ? 'count-reverted' : 'count-zero'); }
    }

    function loadCorrections(page) {
        var date = getSelectedDate();
        if (!date) return;

        if (page !== undefined) currentPage = page;
        if (currentPage === 1) correctionsTable = null;

        var type = getActiveType();
        var activeTab = document.querySelector('#corrections-tabs .log-tab.active');
        var status = activeTab ? activeTab.dataset.status : 'corrected';
        var searchField = document.getElementById('filter-search-field') ? document.getElementById('filter-search-field').value : '';
        var searchValue = document.getElementById('filter-search-value') ? document.getElementById('filter-search-value').value.trim() : '';

        var url = '/dx/layer4/api/corrections/?date=' + encodeURIComponent(date)
            + '&type=' + encodeURIComponent(type)
            + '&status=' + encodeURIComponent(status)
            + '&page=' + currentPage
            + '&page_size=50';
        if (searchValue && searchField) {
            url += '&search_field=' + encodeURIComponent(searchField)
                + '&search_value=' + encodeURIComponent(searchValue);
        }

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    showToast(data.error || '조회 실패', 'error');
                    return;
                }
                if (data.status_counts) {
                    updateTabCounts(data.status_counts.corrected || 0, data.status_counts.normal || 0, data.status_counts.reverted || 0);
                }
                renderCorrections(data);
            })
            .catch(function(e) {
                console.error(e);
                showToast('검수기록 조회 중 오류가 발생했습니다.', 'error');
            });
    }

    // window에 노출 (페이지네이션 onclick에서 호출)
    window.loadCorrections = loadCorrections;

    // ── 일괄 이력 조회 ────────────────────────────────

    var bulkHistoryTable = null;
    var bulkHistoryFilterBar = null;
    var bulkHistoryData = null;
    var bulkHistoryCategory = 'tv';

    function isBulkHistoryActive() {
        var activeTab = document.querySelector('#corrections-tabs .log-tab.active');
        return activeTab && activeTab.dataset.status === 'bulk_history';
    }

    function loadBulkHistory(days) {
        var date = getSelectedDate();
        if (!date) return;

        var type = getActiveType();
        var url = '/dx/layer4/api/corrections/bulk-history/'
            + '?date=' + encodeURIComponent(date)
            + '&type=' + encodeURIComponent(type)
            + '&days=' + (days || 3)
            + '&category=' + encodeURIComponent(bulkHistoryCategory);

        var container = document.getElementById('bulk-history-table-container');
        if (container) container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    if (container) container.innerHTML = '<div class="l4-empty-state"><p>' + L4.escapeHtml(data.error || '조회 실패') + '</p></div>';
                    return;
                }
                bulkHistoryData = data;
                renderBulkHistoryFilterBar(days || 3, data);
                renderBulkHistoryTable();
            })
            .catch(function(e) {
                console.error(e);
                if (container) container.innerHTML = '<div class="l4-empty-state"><p>오류가 발생했습니다.</p></div>';
            });
    }

    function renderBulkHistoryFilterBar(days, data) {
        if (bulkHistoryFilterBar) return;

        var COL_WIDTHS = { id: 70, crawl_datetime: 150, account_name: 100, item: 180, product_url: 200 };
        var allCols = (data.columns || []).map(function(c) {
            return { key: c, label: c, width: COL_WIDTHS[c] || 130 };
        });
        var defaultVisible = data.default_visible || [];
        var fixedCols = data.fixed || [];

        var catBtnStyle = 'padding:5px 14px;font-size:13px;font-weight:600;border:1px solid var(--border-color);border-radius:4px;cursor:pointer;background:var(--bg-primary);color:var(--text-secondary);';
        var catBtnActiveStyle = 'padding:5px 14px;font-size:13px;font-weight:600;border:1px solid var(--page-color);border-radius:4px;cursor:pointer;background:var(--page-color);color:white;';

        bulkHistoryFilterBar = new FilterBar('#bulk-history-filter-bar', {
            plain: true, sticky: false,
            controls: [
                {
                    type: 'custom',
                    html: '<div style="display:flex;align-items:center;gap:4px;">'
                        + '<button id="bulk-cat-tv" style="' + (bulkHistoryCategory === 'tv' ? catBtnActiveStyle : catBtnStyle) + '">TV</button>'
                        + '<button id="bulk-cat-tse_tv" style="' + (bulkHistoryCategory === 'tse_tv' ? catBtnActiveStyle : catBtnStyle) + '">TSE TV</button>'
                        + '<button id="bulk-cat-tse_ref" style="' + (bulkHistoryCategory === 'tse_ref' ? catBtnActiveStyle : catBtnStyle) + '">TSE REF</button>'
                        + '<button id="bulk-cat-tse_ldy" style="' + (bulkHistoryCategory === 'tse_ldy' ? catBtnActiveStyle : catBtnStyle) + '">TSE LDY</button>'
                        + '</div>'
                },
                {
                    type: 'custom',
                    html: '<div style="display:flex;align-items:center;gap:6px;">'
                        + '<label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>'
                        + '<input type="number" id="bulk-history-days" value="' + days + '" min="1" max="30"'
                        + ' style="width:50px;padding:8px 6px;border:1px solid var(--border-color);border-radius:4px;font-size:14px;text-align:center;box-sizing:border-box;">'
                        + '</div>'
                }
            ],
            onSearch: function() {
                var val = parseInt(document.getElementById('bulk-history-days').value) || 3;
                bulkHistoryTable = null;
                bulkHistoryFilterBar = null;
                loadBulkHistory(val);
            },
            columnSelector: {
                columns: allCols,
                fixed: fixedCols,
                defaultVisible: defaultVisible,
                onUpdate: function() {
                    bulkHistoryTable = null;
                    renderBulkHistoryTable();
                }
            }
        }).render();

        ['tv', 'tse_tv', 'tse_ref', 'tse_ldy'].forEach(function(cat) {
            var btn = document.getElementById('bulk-cat-' + cat);
            if (!btn) return;
            btn.addEventListener('click', function() {
                if (bulkHistoryCategory === cat) return;
                bulkHistoryCategory = cat;
                bulkHistoryTable = null;
                bulkHistoryFilterBar = null;
                var curDays = parseInt((document.getElementById('bulk-history-days') || {}).value) || 3;
                loadBulkHistory(curDays);
            });
        });

        var daysInput = document.getElementById('bulk-history-days');
        if (daysInput) {
            daysInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    var val = parseInt(daysInput.value) || 3;
                    bulkHistoryTable = null;
                    bulkHistoryFilterBar = null;
                    loadBulkHistory(val);
                }
            });
        }
    }

    function renderBulkHistoryTable() {
        var container = document.getElementById('bulk-history-table-container');
        if (!bulkHistoryData || !container) return;

        var rows = bulkHistoryData.rows || [];
        var correctedMap = bulkHistoryData.corrected_map || {};

        if (rows.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>이력 데이터가 없습니다.</p></div>';
            return;
        }

        var visibleCols = bulkHistoryFilterBar ? bulkHistoryFilterBar.getVisibleColumns() : [];
        if (visibleCols.length === 0) {
            visibleCols = (bulkHistoryData.default_visible || []).map(function(c) { return { key: c, label: c }; });
        }

        container.innerHTML = '';
        bulkHistoryTable = new CommonTable(container, {
            variant: 'detail',
            columns: visibleCols,
            resize: true,
            reorder: true,
            fixedColumns: (bulkHistoryData.fixed || []),
            vlines: true,
            showTotalCount: true,
            padding: '5px 14px',
            onReorder: function(newColumns) {
                if (bulkHistoryFilterBar) {
                    bulkHistoryFilterBar.reorderColumns(newColumns.map(function(c) { return c.key; }));
                }
            }
        });
        bulkHistoryTable.render();

        // item 컬럼 rowspan 계산 (연속된 동일 item끼리 묶기)
        var itemSpans = {}; // rowIndex → span 수 (그룹 첫 행만 존재)
        var itemSkip = {};  // rowIndex → true (그룹 중간/끝 행, td 생략)
        var hasItemCol = visibleCols.some(function(c) { return c.key === 'item'; });
        if (hasItemCol) {
            var si = 0;
            while (si < rows.length) {
                var itemVal = rows[si].item;
                var ei = si + 1;
                while (ei < rows.length && rows[ei].item === itemVal) ei++;
                itemSpans[si] = ei - si;
                for (var k = si + 1; k < ei; k++) itemSkip[k] = true;
                si = ei;
            }
        }

        bulkHistoryTable.renderBody(rows, function(row, idx) {
            var rowId = row.id;
            var correctedCols = correctedMap[rowId] || [];
            var isTarget = correctedCols.length > 0;
            var trStyle = isTarget ? ' style="background:rgba(139,92,246,0.06);"' : '';
            var html = '<tr' + trStyle + '>';
            visibleCols.forEach(function(col) {
                var val = row[col.key];
                var isCorrectedCol = isTarget && correctedCols.indexOf(col.key) >= 0;
                var cellStyle = isCorrectedCol ? 'background:rgba(139,92,246,0.18);font-weight:600;' : '';
                if (col.key === 'item' && hasItemCol) {
                    if (itemSkip[idx]) return; // rowspan 중간 행 — td 생략
                    var span = itemSpans[idx] || 1;
                    html += '<td rowspan="' + span + '" style="vertical-align:middle;' + cellStyle + '">'
                        + L4.escapeHtml(val !== undefined && val !== '' ? String(val) : '-') + '</td>';
                } else if (col.key === 'product_url' && val) {
                    var urlText = L4.escapeHtml(String(val));
                    html += '<td style="' + cellStyle + '"><a href="' + urlText + '" target="_blank" style="color:var(--page-color);text-decoration:none;">'
                        + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
                        + urlText + '</a></td>';
                } else {
                    html += '<td style="' + cellStyle + '">' + L4.escapeHtml(val !== undefined && val !== '' ? String(val) : '-') + '</td>';
                }
            });
            html += '</tr>';
            return html;
        });
    }

    var correctionsTable = null;
    var correctionItems = [];

    function getActiveStatus() {
        var activeTab = document.querySelector('#corrections-tabs .log-tab.active');
        return activeTab ? activeTab.dataset.status : 'corrected';
    }

    function getCorrectionsColumns() {
        var status = getActiveStatus();
        var isNormalTab = status === 'normal';
        var isCorrectedTab = status === 'corrected';
        var cols = [];
        if (isNormalTab) {
            cols.push({ key: '_check', label: '', width: 40, align: 'center' });
        }
        cols.push({ key: 'no', label: 'No.', width: 50, align: 'center' });
        if (!correctionsFixedType) {
            cols.push({ key: 'correction_type', label: '검증유형', width: 90, align: 'center' });
        }
        cols.push(
            { key: 'table_name', label: '카테고리', width: 60 },
            { key: 'retailer', label: '리테일러', width: 90 },
            { key: 'item', label: 'Item', width: 140 }
        );
        // 수정 탭: record_id, 수집시간 표시
        if (isCorrectedTab) {
            cols.push(
                { key: 'record_id', label: 'Record', width: 70, align: 'center' },
                { key: 'crawl_time', label: '수집시간', width: 150 }
            );
        }
        cols.push({ key: 'column_name', label: '컬럼', width: 160 });
        // 수정/취소 탭: 이전값, 변경한 값 표시
        if (!isNormalTab) {
            cols.push(
                { key: 'old_value', label: '이전값', width: 120 },
                { key: 'new_value', label: '변경한 값', width: 120 }
            );
        }
        // 확인 탭: 이유 표시
        if (!isCorrectedTab) {
            cols.push({ key: 'reason', label: '이유' });
        }
        return cols;
    }

    function renderCorrections(data) {
        var container = document.getElementById('corrections-table-container');
        var items = data.items || [];

        if (items.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>검수기록이 없습니다.</p></div>';
            correctionsTable = null;
            renderPagination(0, 0, 0);
            return;
        }

        var startNo = (data.page - 1) * data.page_size;
        var activeTab = document.querySelector('#corrections-tabs .log-tab.active');

        if (!correctionsTable) {
            container.innerHTML = '';
            correctionsTable = new CommonTable(container, {
                variant: 'detail',
                columns: getCorrectionsColumns(),
                resize: true,
                vlines: true,
                showTotalCount: true
            });
            correctionsTable.render();
            if (activeTab && activeTab.dataset.status === 'normal') {
                var firstTh = container.querySelector('thead th');
                if (firstTh) {
                    firstTh.innerHTML = '<input type="checkbox" id="corr-check-all">';
                    document.getElementById('corr-check-all').addEventListener('change', function() {
                        var checks = document.querySelectorAll('.corr-check');
                        var checked = this.checked;
                        checks.forEach(function(cb) { cb.checked = checked; });
                    });
                }
            }
        }

        var CATEGORY_NAME = {
            'tv_retail_com': 'TV',
            'dx_tse.dx_tse_tv_retail_com': 'TSE TV',
            'dx_tse.dx_tse_ref_retail_com': 'TSE REF',
            'dx_tse.dx_tse_ldy_retail_com': 'TSE LDY',
            'youtube_collection_logs': 'YouTube', 'youtube_videos': 'YouTube', 'youtube_comments': 'YouTube',
            'market_trend': 'Market Trend', 'market_comp_product': 'Market', 'market_comp_event': 'Market',
            'openai_forecast_results': '수요증감율'
        };
        var status = getActiveStatus();
        var isNormalTab = status === 'normal';
        var isCorrectedTab = status === 'corrected';
        correctionsTable.renderBody(items, function(item, idx) {
            var categoryName = CATEGORY_NAME[item.table_name] || item.table_name;
            var html = '<tr style="cursor:pointer" data-corr-idx="' + idx + '">';
            if (isNormalTab) {
                html += '<td style="text-align:center"><input type="checkbox" class="corr-check" data-id="' + item.id + '"></td>';
            }
            html += '<td style="text-align:center">' + (startNo + idx + 1) + '</td>';
            if (!correctionsFixedType) {
                var typeName = L4.TYPE_NAMES[item.correction_type] || item.correction_type;
                html += '<td style="text-align:center"><span class="l4-type-badge">' + L4.escapeHtml(typeName) + '</span></td>';
            }
            html += '<td>' + L4.escapeHtml(categoryName) + '</td>'
                + '<td>' + L4.escapeHtml(item.retailer || '-') + '</td>'
                + '<td>' + L4.escapeHtml(item.item || '-') + '</td>';
            if (isCorrectedTab) {
                html += '<td style="text-align:center">' + L4.escapeHtml(String(item.record_id || '-')) + '</td>'
                    + '<td>' + L4.escapeHtml(item.crawl_time || '-') + '</td>';
            }
            html += '<td>' + L4.escapeHtml(item.column_name) + '</td>';
            if (!isNormalTab) {
                html += '<td title="' + L4.escapeHtml(item.old_value || '') + '">' + L4.escapeHtml(item.old_value || '-') + '</td>'
                    + '<td title="' + L4.escapeHtml(item.new_value || '') + '">' + L4.escapeHtml(item.new_value || '-') + '</td>';
            }
            if (!isCorrectedTab) {
                html += '<td>' + L4.escapeHtml(item.reason || '-') + '</td>';
            }
            html += '</tr>';
            return html;
        });

        // 행 클릭 → 상세 모달
        correctionItems = items;
        var tbody = container.querySelector('tbody');
        if (tbody) {
            tbody.addEventListener('click', function(e) {
                if (e.target.tagName === 'INPUT') return;
                var tr = e.target.closest('tr[data-corr-idx]');
                if (!tr) return;
                var idx = parseInt(tr.dataset.corrIdx);
                showCorrectionDetail(items[idx], startNo + idx + 1);
            });
        }

        renderPagination(data.page, data.total_pages, data.total);

        var checkAll = document.getElementById('corr-check-all');
        if (checkAll) checkAll.checked = false;
    }

    function showCorrectionDetail(item, no) {
        var CATEGORY_NAME = {
            'tv_retail_com': 'TV',
            'dx_tse.dx_tse_tv_retail_com': 'TSE TV',
            'dx_tse.dx_tse_ref_retail_com': 'TSE REF',
            'dx_tse.dx_tse_ldy_retail_com': 'TSE LDY',
            'youtube_collection_logs': 'YouTube', 'youtube_videos': 'YouTube', 'youtube_comments': 'YouTube',
            'market_trend': 'Market Trend', 'market_comp_product': 'Market', 'market_comp_event': 'Market',
            'openai_forecast_results': '수요증감율'
        };
        var categoryName = CATEGORY_NAME[item.table_name] || item.table_name;
        var typeName = L4.TYPE_NAMES[item.correction_type] || item.correction_type;
        var statusName = L4.STATUS_NAMES[item.status] || item.status;
        var isCorrected = item.status === 'corrected';

        var rows = [
            ['No.', no],
            ['검증유형', typeName],
            ['카테고리', categoryName],
            ['리테일러', item.retailer || '-'],
            ['Record', item.record_id],
            ['Item', item.item || '-'],
            ['컬럼', item.column_name],
            ['이전값', item.old_value || '-'],
            ['변경한 값', item.new_value || '-'],
            ['상태', '<span class="l4-status ' + item.status + '">' + L4.escapeHtml(statusName) + '</span>'],
            ['이유', item.reason || '-'],
            ['메모', item.memo || '-'],
            [isCorrected ? '수정자' : '확인자', item.created_id || '-'],
            [isCorrected ? '수정일' : '확인일', item.created_at || '-']
        ];
        if (item.rule_name) {
            rows.splice(3, 0, ['검증규칙명', item.rule_name]);
        }
        if (item.status === 'reverted') {
            rows.push(['취소자', item.updated_id || '-']);
            rows.push(['취소일', item.updated_at || '-']);
            if (item.cancel_memo) {
                rows.push(['취소 사유', item.cancel_memo]);
            }
        }

        var html = '<table class="corr-detail-table">';
        for (var i = 0; i < rows.length; i++) {
            var isHtml = rows[i][0] === '상태';
            html += '<tr><th>' + L4.escapeHtml(rows[i][0]) + '</th><td>' + (isHtml ? rows[i][1] : L4.escapeHtml(String(rows[i][1]))) + '</td></tr>';
        }
        html += '</table>';

        // Retail history lookup
        var historyTables = [
            'tv_retail_com',
            'dx_tse.dx_tse_tv_retail_com',
            'dx_tse.dx_tse_ref_retail_com',
            'dx_tse.dx_tse_ldy_retail_com'
        ];
        if (historyTables.indexOf(item.table_name) >= 0 && item.retailer && item.item) {
            html += '<div style="text-align:right;margin-top:12px;">'
                + '<button class="app-btn app-btn-sm app-btn-outline" id="corr-history-btn">이력 조회</button>'
                + '</div>';
        }

        AppModal.setTitle('corr-detail', '검수기록 상세');
        AppModal.setBody('corr-detail', html);
        AppModal.open('corr-detail');

        // 이력 조회 버튼 이벤트
        var historyBtn = document.getElementById('corr-history-btn');
        if (historyBtn) {
            historyBtn.addEventListener('click', function() {
                AppModal.close('corr-detail');
                openCorrectionHistory(item);
            });
        }
    }

    // ── 이력 조회 ──────────────────────────────────

    var historyTable = null;
    var historyFilterBar = null;
    var historyData = null;  // 마지막 조회 결과 보관

    function openCorrectionHistory(item) {
        AppModal.setTitle('corr-history', L4.escapeHtml(item.retailer + ' / ' + item.item) + ' 이력');
        AppModal.setBody('corr-history', '<div id="history-filter-bar"></div><div id="history-table-container"><div class="l4-empty-state"><p>조회 중...</p></div></div>');
        AppModal.open('corr-history');

        historyTable = null;
        historyFilterBar = null;
        historyData = null;
        loadCorrectionHistory(item, 3);
    }

    function loadCorrectionHistory(item, days) {
        var url = '/dx/layer4/api/corrections/history/'
            + '?table_name=' + encodeURIComponent(item.table_name)
            + '&retailer=' + encodeURIComponent(item.retailer)
            + '&item=' + encodeURIComponent(item.item)
            + '&column=' + encodeURIComponent(item.column_name)
            + '&record_id=' + encodeURIComponent(item.record_id || '')
            + '&days=' + days;

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    document.getElementById('history-table-container').innerHTML = '<div class="l4-empty-state"><p>' + L4.escapeHtml(data.error || '조회 실패') + '</p></div>';
                    return;
                }
                historyData = data;
                renderHistoryFilterBar(item, data, days);
                renderHistoryTable();
            })
            .catch(function(e) {
                console.error(e);
                document.getElementById('history-table-container').innerHTML = '<div class="l4-empty-state"><p>시스템 오류가 발생했습니다.</p></div>';
            });
    }

    function renderHistoryFilterBar(item, data, days) {
        if (historyFilterBar) return;

        var allColumns = data.columns || [];
        var defaultVisible = data.default_visible || [];
        var fixedCols = data.fixed || [];
        var columnDefs = allColumns.map(function(c) { return { key: c, label: c }; });

        historyFilterBar = new FilterBar('#history-filter-bar', {
            plain: true, sticky: false,
            controls: [
                {
                    type: 'custom',
                    html: '<div style="display:flex;align-items:center;gap:6px;">'
                        + '<label style="font-size:12px;color:var(--text-secondary);white-space:nowrap;">일수:</label>'
                        + '<input type="number" id="history-days" value="' + days + '" min="1" max="30"'
                        + ' style="width:50px;padding:8px 6px;border:1px solid var(--border-color);border-radius:4px;font-size:14px;text-align:center;box-sizing:border-box;">'
                        + '</div>'
                }
            ],
            onSearch: function() {
                var val = parseInt(document.getElementById('history-days').value) || 3;
                historyTable = null;
                loadCorrectionHistory(item, val);
            },
            columnSelector: {
                columns: columnDefs,
                fixed: fixedCols,
                defaultVisible: defaultVisible,
                onUpdate: function() {
                    historyTable = null;
                    renderHistoryTable();
                }
            }
        }).render();

        // Enter 키로 조회
        var daysInput = document.getElementById('history-days');
        if (daysInput) {
            daysInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    var val = parseInt(daysInput.value) || 3;
                    historyTable = null;
                    loadCorrectionHistory(item, val);
                }
            });
        }
    }

    function renderHistoryTable() {
        var container = document.getElementById('history-table-container');
        if (!historyData) return;

        var rows = historyData.rows || [];
        var recordId = historyData.record_id;

        if (rows.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>이력 데이터가 없습니다.</p></div>';
            return;
        }

        var visibleCols = historyFilterBar ? historyFilterBar.getVisibleColumns() : [];
        if (visibleCols.length === 0) {
            visibleCols = (historyData.default_visible || []).map(function(c) { return { key: c, label: c }; });
        }

        container.innerHTML = '';
        historyTable = new CommonTable(container, {
            variant: 'detail',
            columns: visibleCols,
            resize: true,
            reorder: true,
            fixedColumns: (historyData.fixed || []),
            vlines: true,
            showTotalCount: true,
            onReorder: function(newColumns) {
                if (historyFilterBar) {
                    historyFilterBar.reorderColumns(newColumns.map(function(c) { return c.key; }));
                }
            }
        });
        historyTable.render();

        historyTable.renderBody(rows, function(row) {
            var isTarget = recordId && row.id && parseInt(row.id) === recordId;
            var trStyle = isTarget ? ' style="background:rgba(139,92,246,0.08);"' : '';
            var html = '<tr' + trStyle + '>';
            visibleCols.forEach(function(col) {
                var val = row[col.key];
                if (col.key === 'product_url' && val) {
                    var urlText = L4.escapeHtml(String(val));
                    html += '<td style="max-width:300px;"><a href="' + urlText + '" target="_blank" style="display:inline-flex;align-items:center;gap:4px;color:var(--page-color);text-decoration:none;word-break:break-all;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' + urlText + '</a></td>';
                } else {
                    html += '<td>' + L4.escapeHtml(val !== undefined && val !== '' ? String(val) : '-') + '</td>';
                }
            });
            html += '</tr>';
            return html;
        });
    }

    async function cancelCheckedCorrections() {
        var checked = document.querySelectorAll('.corr-check:checked');
        if (checked.length === 0) {
            showToast('취소할 항목을 선택하세요.', 'warning');
            return;
        }
        var ids = [];
        checked.forEach(function(cb) { ids.push(parseInt(cb.dataset.id)); });

        var result = await showConfirm(ids.length + '건을 정상취소 하시겠습니까?', 'warning', {
            input: { placeholder: '취소 사유 (선택)' }
        });
        if (!result.confirmed) return;

        try {
            var res = await fetch('/dx/layer4/api/corrections/cancel/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ ids: ids, cancel_memo: result.value || '' })
            });
            var data = await res.json();
            if (data.success) {
                showToast(data.cancelled + '건 취소되었습니다.', 'success');
                loadCorrections();
            } else {
                showToast(data.error || '취소 실패', 'error');
            }
        } catch (e) {
            showToast('시스템 오류가 발생했습니다.', 'error');
        }
    }

    function renderPagination(page, totalPages, total) {
        var container = document.getElementById('corrections-pagination');
        if (!container) return;

        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        var html = '<div style="display:flex;justify-content:center;gap:4px;margin-top:16px;">';

        if (page > 1) {
            html += '<button class="app-btn app-btn-sm app-btn-outline" onclick="loadCorrections(1)">&laquo;</button>';
            html += '<button class="app-btn app-btn-sm app-btn-outline" onclick="loadCorrections(' + (page - 1) + ')">&lsaquo;</button>';
        }

        var start = Math.max(1, page - 2);
        var end = Math.min(totalPages, page + 2);

        for (var i = start; i <= end; i++) {
            if (i === page) {
                html += '<button class="app-btn app-btn-sm" style="background:var(--layer-color);color:white;border-color:var(--layer-color);">' + i + '</button>';
            } else {
                html += '<button class="app-btn app-btn-sm app-btn-outline" onclick="loadCorrections(' + i + ')">' + i + '</button>';
            }
        }

        if (page < totalPages) {
            html += '<button class="app-btn app-btn-sm app-btn-outline" onclick="loadCorrections(' + (page + 1) + ')">&rsaquo;</button>';
            html += '<button class="app-btn app-btn-sm app-btn-outline" onclick="loadCorrections(' + totalPages + ')">&raquo;</button>';
        }

        html += '</div>';
        container.innerHTML = html;
    }

    // 핸들러/초기화 등록
    L4._sectionHandler['corrections'] = function() {
        if (isBulkHistoryActive()) {
            bulkHistoryTable = null;
            bulkHistoryFilterBar = null;
            loadBulkHistory(3);
        } else {
            loadCorrections();
        }
    };
    L4._sectionInit['corrections'] = function() {
        initCorrectionsFilterBar();
        AppModal.create('corr-detail', { style: 'compact', closeOnOverlay: true });
        AppModal.create('corr-history', { style: 'wide', closeOnOverlay: true });
    };

})();
