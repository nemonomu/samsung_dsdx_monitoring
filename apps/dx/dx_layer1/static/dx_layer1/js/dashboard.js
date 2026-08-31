var CHECK_TYPE_URL = {
    retail: '/dx/layer1/retail/',
    sentiment: '/dx/layer1/sentiment/',
    youtube: '/dx/layer1/youtube/',
    market_trend: '/dx/layer1/market-trend/',
    market_demand: '/dx/layer1/market-demand/',
    market_competitor: '/dx/layer1/market-competitor/',
    market_competitor_event: '/dx/layer1/market-competitor-event/',
    market_promotion: '/dx/layer1/market-promotion/'
};

async function loadStats() {
    try {
        const selectedDate = getSelectedDate();

        // 1. 체크 상태 먼저 조회
        let checkData = null;
        try {
            checkData = await loadCheckStatus(selectedDate);
            currentCheckStatus = checkData;
        } catch (e) {
            currentCheckStatus = null;
        }

        const url = selectedDate
            ? `/dx/layer1/api/stats/?date=${selectedDate}`
            : '/dx/layer1/api/stats/';

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        currentStatsData = data;

        // 선택한 검수일 기준 SEA TV/REF/LDY summary를 한 번씩 로딩
        try {
            await loadSeaRetailSummaries(selectedDate);
        } catch (e) {
            currentRetailSummary = null;
            currentNullData = null;
        }

        // Summary stats
        document.getElementById('total-checked').textContent = data.summary.total_checked;
        document.getElementById('total-passed').textContent = data.summary.passed;
        document.getElementById('total-failed').textContent = data.summary.failed;
        updateConfirmedCount();


        // 데일리 / 분석대상일별 분류 (API 응답의 display_group 기반)
        const dailyChecks = data.checks.filter(c => c.display_group === 'daily');
        const periodChecks = data.checks.filter(c => c.display_group === 'periodic');

        // 체크 렌더링 함수 — L1.renderers에서 check_type별 렌더러 참조
        function renderCheck(check, checkIdx) {
            var renderer = L1.renderers[check.check_type];
            if (renderer) {
                return renderer(check, checkIdx);
            }
            return `
                <div class="check-item">
                    <div class="check-main">
                        <div class="check-info">
                            <div class="check-name">${esc(check.name)}</div>
                            <div class="check-description">${esc(check.description || '')}</div>
                        </div>
                        <div class="check-stats">
                            ${getStatusBadge(check.status)}
                        </div>
                    </div>
                </div>
            `;
        }

        // check-item에 data-check-type 속성만 추가 (배지는 addCheckBadges()에서 DOM으로 삽입)
        function wrapWithCheckBadge(checkHtml, checkType) {
            if (!checkType) return checkHtml;
            return checkHtml.replace(
                '<div class="check-item">',
                `<div class="check-item" data-check-type="${checkType}">`
            );
        }

        // 데일리 체크 리스트
        const dailyChecksList = document.getElementById('daily-checks-list');
        if (dailyChecks.length > 0) {
            dailyChecksList.innerHTML = dailyChecks.map((check, idx) => {
                const checkIdx = data.checks.indexOf(check);
                return wrapWithCheckBadge(renderCheck(check, checkIdx), check.check_type);
            }).join('');
        } else {
            dailyChecksList.innerHTML = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터 없음</div></div></div></div>';
        }

        // 분석대상일별 체크 리스트
        const periodChecksList = document.getElementById('period-checks-list');
        if (periodChecks.length > 0) {
            periodChecksList.innerHTML = periodChecks.map((check, idx) => {
                const checkIdx = data.checks.indexOf(check);
                return wrapWithCheckBadge(renderCheck(check, checkIdx), check.check_type);
            }).join('');
        } else {
            periodChecksList.innerHTML = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터 없음</div></div></div></div>';
        }

        // 체크 배지 삽입 (DOM API)
        addCheckBadges();


    } catch (error) {
        console.error('Stats load failed:', error);
        const errorHtml = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터 로드 실패</div><div class="check-description">' + esc(error.message) + '</div></div></div></div>';
        document.getElementById('daily-checks-list').innerHTML = errorHtml;
        document.getElementById('period-checks-list').innerHTML = errorHtml;
    }
}


function loadAllData() {
    loadStats();
}

// 수요증감율 부족 키워드 모달
var demandMissingDataState = {
    category: 'all',
    data: []
};

function openDemandMissingModal(category) {
    var currentDate = getSelectedDate();
    demandMissingDataState.category = category;

    AppModal.setTitle('demandMissing', '수요증감율 부족 키워드 - ' + category);
    AppModal.setBody('demandMissing',
        '<div class="raw-modal-header-sub">' +
            '<div class="raw-data-modal-subtitle" id="demandMissingModalSubtitle">' + currentDate + '</div>' +
            '<div class="raw-modal-actions"></div>' +
        '</div>' +
        '<div class="raw-data-table-wrapper" style="padding: 0 20px 20px;" id="demandMissingTableWrapper"><div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div></div>'
    );
    AppModal.open('demandMissing');

    loadDemandMissingData();
}

function closeDemandMissingModal() {
    AppModal.close('demandMissing');
}

function loadDemandMissingData() {
    var wrapperEl = document.getElementById('demandMissingTableWrapper');
    var currentDate = getSelectedDate();

    wrapperEl.innerHTML = '<div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div>';

    var url = '/dx/layer1/market-demand/api/missing/?category=' + encodeURIComponent(demandMissingDataState.category) +
              '&date=' + encodeURIComponent(currentDate);

    fetch(url)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.error) {
                wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(data.error) + '</div>';
                return;
            }

            demandMissingDataState.data = data.missing_keywords || [];

            // 요약 정보 표시
            var summaryHtml = '';
            if (data.summary) {
                var summaryParts = [];
                for (var cat in data.summary) {
                    var s = data.summary[cat];
                    summaryParts.push(cat + ': ' + s.missing + '/' + s.total + '건 부족');
                }
                summaryHtml = summaryParts.length > 0 ? ' (' + summaryParts.join(', ') + ')' : '';
            }
            if (demandMissingDataState.data.length === 0) {
                wrapperEl.innerHTML = '<div class="raw-data-empty">부족한 키워드가 없습니다</div>';
                return;
            }

            demandMissingDataState.summaryHtml = summaryHtml;
            renderDemandMissingTable();
        })
        .catch(function(error) {
            wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(error.message) + '</div>';
        });
}

function renderDemandMissingTable() {
    var wrapperEl = document.getElementById('demandMissingTableWrapper');
    var summaryHtml = demandMissingDataState.summaryHtml || '';
    wrapperEl.innerHTML = '';

    var table = new CommonTable(wrapperEl, {
        columns: [
            { key: '_no', label: 'No', width: 50 },
            { key: 'category', label: '카테고리', width: 80 },
            { key: 'product_name', label: '제품명' },
            { key: 'event_name', label: '이벤트명' },
            { key: 'event_date', label: '이벤트일자', width: 120 }
        ],
        showTotalCount: true,
        countFormat: function(count) {
            return '총 <strong>' + count.toLocaleString() + '</strong>건 부족' + summaryHtml;
        }
    });
    table.render();
    table.renderBody(demandMissingDataState.data, function(item, idx) {
        return '<tr>' +
            '<td style="text-align:center;">' + (idx + 1) + '</td>' +
            '<td>' + esc(item.category || '') + '</td>' +
            '<td>' + esc(item.product_name || '') + '</td>' +
            '<td>' + esc(item.event_name || '') + '</td>' +
            '<td>' + esc(item.event_date || '') + '</td>' +
            '</tr>';
    });
}


// 백업 실행
function formatBackupCounts(data) {
    return [
        'SEA TV: ' + Number(data.tv_count || 0).toLocaleString() + '건',
        'SEA REF: ' + Number(data.sea_ref_count || 0).toLocaleString() + '건',
        'SEA LDY: ' + Number(data.sea_ldy_count || 0).toLocaleString() + '건',
        'TSE TV: ' + Number(data.tse_tv_count || 0).toLocaleString() + '건',
        'TSE REF: ' + Number(data.tse_ref_count || 0).toLocaleString() + '건',
        'TSE LDY: ' + Number(data.tse_ldy_count || 0).toLocaleString() + '건'
    ].join('\n');
}

function formatBackupDates(data) {
    var sourceDates = data.source_dates || {};
    return [
        '검수일(inspection_date): ' + (data.inspection_date || ''),
        'SEA source_date - TV: ' + (sourceDates.sea_tv || '') +
            ', REF: ' + (sourceDates.sea_ref || '') +
            ', LDY: ' + (sourceDates.sea_ldy || ''),
        'TSE source_date - TV: ' + (sourceDates.tse_tv || '') +
            ', REF: ' + (sourceDates.tse_ref || '') +
            ', LDY: ' + (sourceDates.tse_ldy || '')
    ].join('\n');
}

function runBackup() {
    var btn = document.getElementById('btn-backup');
    var targetDate = getSelectedDate();
    btn.disabled = true;
    btn.textContent = '확인 중...';

    // 1. 먼저 백업 대상 건수 조회 (GET)
    fetch('/dx/layer1/retail/api/backup/?date=' + encodeURIComponent(targetDate))
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function(res) {
            btn.disabled = false;
            btn.textContent = '백업 실행';

            if (!res.success) {
                showToast('건수 조회 실패: ' + res.error, 'error');
                return;
            }

            // 2. 건수 표시 및 확인 팝업
            var msg = formatBackupDates(res) + '\n백업 대상\n' +
                formatBackupCounts(res) + '\n백업을 진행하시겠습니까?';
            showConfirm(msg).then(function(confirmed) {
                if (!confirmed) return;

                // 3. 백업 실행 (POST)
                btn.disabled = true;
                btn.textContent = '백업 중...';

                fetch('/dx/layer1/retail/api/backup/?date=' + encodeURIComponent(targetDate), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    }
                })
                .then(function(r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(function(result) {
                    btn.disabled = false;
                    btn.textContent = '백업 실행';

                    if (result.success) {
                        showToast(result.message, 'success');
                    } else {
                        showToast('백업 실패: ' + result.error, 'error');
                    }
                })
                .catch(function(err) {
                    btn.disabled = false;
                    btn.textContent = '백업 실행';
                    showToast('백업 오류: ' + err, 'error');
                });
            });
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = '백업 실행';
            showToast('건수 조회 오류: ' + err, 'error');
        });
}



// Market Competitor 부족 키워드 모달
var compMissingDataState = { category: 'all', data: [] };
function openCompMissingModal(category) {
    var currentDate = getSelectedDate();
    compMissingDataState.category = category;
    AppModal.setTitle('compMissing', 'Market Competitor 부족 키워드 - ' + category);
    AppModal.setBody('compMissing', '<div class="raw-modal-header-sub"><div class="raw-data-modal-subtitle" id="compMissingModalSubtitle">' + currentDate + '</div></div><div class="raw-data-table-wrapper" style="padding: 0 20px 20px;" id="compMissingTableWrapper"><div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div></div>');
    AppModal.open('compMissing');
    loadCompMissingData();
}
function loadCompMissingData() {
    var wrapperEl = document.getElementById('compMissingTableWrapper');
    var currentDate = getSelectedDate();
    wrapperEl.innerHTML = '<div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div>';
    fetch('/dx/layer1/market-competitor/api/missing/?category=' + encodeURIComponent(compMissingDataState.category) + '&date=' + encodeURIComponent(currentDate))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(data.error) + '</div>'; return; }
            compMissingDataState.data = data.missing_keywords || [];
            if (compMissingDataState.data.length === 0) { wrapperEl.innerHTML = '<div class="raw-data-empty">부족한 기워드가 없습니다</div>'; return; }
            renderCompMissingTable(data.summary || {});
        }).catch(function(e) { wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(e.message) + '</div>'; });
}
function renderCompMissingTable(summary) {
    var wrapperEl = document.getElementById('compMissingTableWrapper');
    var summaryHtml = '';
    var parts = [];
    for (var cat in summary) { parts.push(cat + ': ' + summary[cat].missing + '/' + summary[cat].total + '건 부족'); }
    if (parts.length > 0) summaryHtml = ' (' + parts.join(', ') + ')';

    var table = new CommonTable(wrapperEl, {
        columns: [
            { key: '_no', label: 'No', width: 50 },
            { key: 'category', label: '카테고리', width: 80 },
            { key: 'samsung_series', label: '삼성 시리즈명' },
            { key: 'comp_brand', label: '경쟁사 브랜드' }
        ],
        showTotalCount: true,
        countFormat: function(c) { return '총 <strong>' + c.toLocaleString() + '</strong>건 부족' + summaryHtml; }
    });
    table.render();
    table.renderBody(compMissingDataState.data, function(item, idx) {
        return '<tr><td style="text-align:center;">' + (idx + 1) + '</td><td>' + esc(item.category || '') + '</td><td>' + esc(item.samsung_series || '') + '</td><td>' + esc(item.comp_brand || '') + '</td></tr>';
    });
}

// Market Competitor Event 부족 키워드 모달
var eventMissingDataState = { category: 'all', data: [] };
function openEventMissingModal(category) {
    var currentDate = getSelectedDate();
    eventMissingDataState.category = category;
    AppModal.setTitle('eventMissing', 'Market Competitor Event 부족 키워드 - ' + category);
    AppModal.setBody('eventMissing', '<div class="raw-modal-header-sub"><div class="raw-data-modal-subtitle" id="eventMissingModalSubtitle">' + currentDate + '</div></div><div class="raw-data-table-wrapper" style="padding: 0 20px 20px;" id="eventMissingTableWrapper"><div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div></div>');
    AppModal.open('eventMissing');
    loadEventMissingData();
}
function loadEventMissingData() {
    var wrapperEl = document.getElementById('eventMissingTableWrapper');
    var currentDate = getSelectedDate();
    wrapperEl.innerHTML = '<div class="raw-data-loading"><div class="raw-data-loading-spinner"></div>데이터를 불러오는 중...</div>';
    fetch('/dx/layer1/market-competitor-event/api/missing/?category=' + encodeURIComponent(eventMissingDataState.category) + '&date=' + encodeURIComponent(currentDate))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(data.error) + '</div>'; return; }
            eventMissingDataState.data = data.missing_keywords || [];
            if (eventMissingDataState.data.length === 0) { wrapperEl.innerHTML = '<div class="raw-data-empty">부족한 기워드가 없습니다</div>'; return; }
            renderEventMissingTable(data.summary || {});
        }).catch(function(e) { wrapperEl.innerHTML = '<div class="raw-data-empty">오류: ' + esc(e.message) + '</div>'; });
}
function renderEventMissingTable(summary) {
    var wrapperEl = document.getElementById('eventMissingTableWrapper');
    var summaryHtml = '';
    var parts = [];
    for (var cat in summary) { parts.push(cat + ': ' + summary[cat].missing + '/' + summary[cat].total + '건 부족'); }
    if (parts.length > 0) summaryHtml = ' (' + parts.join(', ') + ')';

    var table = new CommonTable(wrapperEl, {
        columns: [
            { key: '_no', label: 'No', width: 50 },
            { key: 'category', label: '카테고리', width: 80 },
            { key: 'comp_brand', label: '경쟁사 브랜드' },
            { key: 'comp_sku_name', label: '경쟁사 Sku (제품)명' }
        ],
        showTotalCount: true,
        countFormat: function(c) { return '총 <strong>' + c.toLocaleString() + '</strong>건 부족' + summaryHtml; }
    });
    table.render();
    table.renderBody(eventMissingDataState.data, function(item, idx) {
        return '<tr><td style="text-align:center;">' + (idx + 1) + '</td><td>' + esc(item.category || '') + '</td><td>' + esc(item.comp_brand || '') + '</td><td>' + esc(item.comp_sku_name || '') + '</td></tr>';
    });
}

L1.initLayer1Page({
    modals: [
        { name: 'demandMissing', style: 'extra-wide' },
        { name: 'compMissing', style: 'extra-wide' },
        { name: 'eventMissing', style: 'extra-wide' },
        { name: 'columns', style: 'wide' }
    ],
    filterBarOptions: {
        right: [{ type: 'button', label: '백업 실행', style: 'save', onClick: function() { runBackup(); }, id: 'btn-backup' }]
    }
});
