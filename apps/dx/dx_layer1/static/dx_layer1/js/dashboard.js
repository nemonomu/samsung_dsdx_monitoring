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

var layer1StatsRequestId = 0;
var liveCollectionPoll = null;
var ddayCollectionTimer = null;
const dailyPreviewKey = 'dx-layer1-normal-preview-v1';
const dailyPreviewLifetime = 5 * 60 * 1000;

function takeDailyPreview(date, display) {
    try {
        const saved = sessionStorage.getItem(dailyPreviewKey);
        sessionStorage.removeItem(dailyPreviewKey);
        if (!display || !saved) return '';
        const {user, day, confirmedAt, cards} = JSON.parse(saved);
        const age = Date.now() - confirmedAt;
        if (!user || user !== window.LAYER1?.userId || day !== date
            || !Number.isFinite(confirmedAt) || age < 0 || age >= dailyPreviewLifetime
            || !Array.isArray(cards) || cards.length > 20) return '';
        const time = new Intl.DateTimeFormat('ko-KR', {
            timeZone:'Asia/Seoul', hour:'2-digit', minute:'2-digit', hourCycle:'h23'
        }).format(confirmedAt);
        return cards.filter(card => card && typeof card.name === 'string' && card.name.length <= 100)
            .map(card => '<div class="check-item" data-confirmed-preview><div class="check-main">'
                + '<div class="check-info"><div class="check-name">' + esc(card.name) + '</div>'
                + '<div class="check-description">마지막 정상 확인 · ' + time + ' KST · 재조회 중</div></div>'
                + (Number.isSafeInteger(card.count) && card.count >= 0 ? '<div class="check-stats"><div class="check-stat">'
                    + '<div class="value">' + card.count.toLocaleString('ko-KR') + '</div><div class="label">이전 확인 수집량</div></div></div>' : '')
                + '</div></div>').join('');
    } catch (_) {
        return '';
    }
}

function saveDailyPreview(data, day, volume, reviewsReady) {
    const user = window.LAYER1?.userId;
    if (!user || data.error || data._dailyError) return;
    const countries = L1.liveCollection?.countries || {};
    const cards = data.checks.filter(check => check.display_group === 'daily' && check.is_target_date
        && check.status === 'OK' && !needsDailyRead(check))
        .filter(check => {
            const country = countries[check.check_type];
            if (!country) return true;
            if (!reviewsReady || volume?.inspection_date !== day || volume.policy_version !== 4
                || !volume.snapshots?.some(snapshot => snapshot.country === country && snapshot.available)) return false;
            return check.check_type !== 'retail' || check.categories.every(category => currentRetailSummary?.[category.product_line]);
        }).map(check => ({name:check.name, count:Number.isSafeInteger(check.actual) ? check.actual : null}));
    if (!cards.length) return;
    try {
        sessionStorage.setItem(dailyPreviewKey, JSON.stringify({user, day, confirmedAt:Date.now(), cards}));
    } catch (_) {}
}

function needsDailyRead(check) {
    if (check.display_group !== 'daily') return false;
    if (check.status === 'ERROR' || check.error || check.batch_count_error) return true;
    const rows = check._reviewRows || [];
    if (!rows.length) return check.status !== 'OK';
    const operating = L1.collectionVolume.operatingRows(rows);
    return operating.some(row => row.refresh_error || Number(row.batch_count || 0) >= 2
        || (row.status !== 'OK' && !L1.retailReview.reviewed(row)) || L1.retailReview.rejected(row));
}

async function loadStats(refresh = false, reentry = false) {
    liveCollectionPoll?.stop();
    clearTimeout(ddayCollectionTimer);
    const requestId = ++layer1StatsRequestId;
    const selectedDate = getSelectedDate();
    const preview = takeDailyPreview(selectedDate, reentry && !refresh);
    for (const id of ['total-checked', 'total-passed', 'total-failed', 'total-confirmed']) {
        const counter = document.getElementById(id);
        if (counter) counter.textContent = '—';
    }
    for (const id of ['daily-checks-list', 'period-checks-list']) {
        const list = document.getElementById(id);
        if (list) list.innerHTML = (id === 'daily-checks-list' ? preview : '')
            + '<div class="check-item"><div class="check-main" role="status">검증 데이터를 조회 중입니다.</div></div>';
    }
    const periodSection = document.getElementById('period-checks-section');
    if (periodSection) periodSection.hidden = false;
    resetDdayCollection();
    if (typeof ColumnAlertSummary !== 'undefined') ColumnAlertSummary.reset();
    function readScope(scope) {
        const params = new URLSearchParams({dashboard:'1', dashboard_scope:scope, date:selectedDate});
        if (refresh) params.set('refresh', '1');
        return fetch('/dx/layer1/api/stats/?' + params, {cache:'no-store'});
    }
    const initial = window.layer1InitialStats;
    delete window.layer1InitialStats;
    const statsRequest = !refresh && initial?.date === selectedDate ? initial.response
        : readScope('daily');
    const active = () => requestId === layer1StatsRequestId && getSelectedDate() === selectedDate;
    function scheduleDday() {
        if (!active() || selectedDate !== getLayer1SeoulDate(0)) return;
        ddayCollectionTimer = setTimeout(() => {
            if (!active() || selectedDate !== getLayer1SeoulDate(0)) return;
            if (document.hidden || L1.liveCollection?.isInspecting()) return scheduleDday();
            updateDday(true);
        }, 60000);
    }
    async function updateDday(background) {
        const needsRead = await loadDdayCollection(selectedDate, {refresh: refresh && !background, background});
        if (needsRead !== false) scheduleDday();
    }
    let data = null;
    let volume = null;
    let capturePreview = false;
    let reviewsReady = false;
    const liveSnapshots = new Map();
    currentCheckStatus = null;
    resetSeaRetailSummaries();
    currentStatsData = null;
    const render = function() {
        if (active() && data) {
            const latestVolume = liveSnapshots.size ? {inspection_date:selectedDate, policy_version:4,
                snapshots:[...(volume?.snapshots || []).filter(snapshot => !liveSnapshots.has(snapshot.country)),
                    ...liveSnapshots.values()]} : volume;
            if (L1.collectionVolume) L1.collectionVolume.decorate(
                data, latestVolume, selectedDate, currentRetailSummary, !data._retailPending);
            renderLayer1Stats(data);
            if (capturePreview) {
                capturePreview = false;
                saveDailyPreview(data, selectedDate, volume, reviewsReady);
            }
        }
    };
    let renderQueued = false;
    function scheduleRender() {
        if (!active() || !data || renderQueued) return;
        if (typeof requestAnimationFrame !== 'function') return render();
        renderQueued = true;
        requestAnimationFrame(() => {
            renderQueued = false;
            if (!active() || !data) return;
            if (L1.liveCollection) L1.liveCollection.preserveView(render);
            else render();
        });
    }
    async function checkedPayload(request) {
        const response = await request;
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (payload.target_date !== selectedDate) throw new Error('검증 데이터의 날짜가 일치하지 않습니다.');
        if (!Array.isArray(payload.checks) || !payload.summary || (payload.error && !payload.checks.length)) {
            throw new Error('검증 데이터를 조회하지 못했습니다.');
        }
        return payload;
    }
    try {
        data = await checkedPayload(statsRequest);
    } catch (error) {
        console.error('Daily stats load failed:', error);
        data = {summary:{}, checks:[], _dailyError:error.message};
    }
    if (!active()) return;
    data._periodicPending = true;
    data._retailPending = true;
    data._checkStatusPending = true;
    currentStatsData = data;
    render();
    if (!document.hidden && typeof requestAnimationFrame === 'function') {
        // The task between these frames gives the daily cards a chance to paint.
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }
    if (!active()) return;

    const periodicRequest = checkedPayload(readScope('periodic')).then(payload => {
        if (!active()) return;
        data.checks.push(...payload.checks);
        const {summary} = data;
        for (const name of ['total_checked', 'total_completed', 'passed', 'failed']) {
            summary[name] = (summary[name] || 0) + (payload.summary[name] || 0);
        }
        const statuses = [summary.status, payload.summary.status];
        summary.status = ['ERROR','CRITICAL','REVIEW'].find(status => statuses.includes(status)) || 'OK';
        summary.pass_rate = summary.total_checked ? Math.round(summary.passed * 1000 / summary.total_checked) / 10 : 0;
        if (payload.error) data._periodicError = '일부 검증 데이터를 조회하지 못했습니다.';
    }).catch(error => {
        if (active()) data._periodicError = error.message;
    }).finally(() => {
        data._periodicPending = false;
        scheduleRender();
    });

    const ddayRequest = updateDday(false);
    const statusRequest = loadCheckStatus(selectedDate, refresh).then(status => {
        if (!active() || !status || status.success === false) return;
        currentCheckStatus = status;
        data._checkStatusPending = false;
        if (!data._periodicPending && !data._dailyError && !data._periodicError && !data.error) updateConfirmedCount();
        addCheckBadges();
    }).catch(function() {});
    const retailRequest = Promise.allSettled([
        L1.collectionVolume?.load(selectedDate),
        L1.retailReview?.load(selectedDate),
        loadSeaRetailSummaries(selectedDate, refresh)
    ]).then(([result, review]) => {
        if (!active()) return;
        if (result.status === 'fulfilled') volume = result.value;
        reviewsReady = review.status === 'fulfilled' && review.value === true;
        capturePreview = true;
        data._retailPending = false;
        scheduleRender();
    });
    const columnRequest = typeof ColumnAlertSummary !== 'undefined'
        ? ColumnAlertSummary.load(selectedDate, true, refresh) : null;
    if (!data._dailyError) {
        if (L1.liveCollection) {
            liveCollectionPoll = L1.liveCollection.poll(() => {
                if (!active()) return null;
                const types = data.checks.filter(needsDailyRead).map(check => check.check_type);
                return {date:selectedDate,
                    countries:types.map(type => L1.liveCollection.countries[type]).filter(Boolean),
                    checkTypes:types.filter(type => !L1.liveCollection.countries[type])};
            }, snapshot => {
                if (!active()) return;
                if (snapshot.country) {
                    liveSnapshots.set(snapshot.country, snapshot);
                    L1.liveCollection.applyDashboard(data, snapshot);
                } else {
                    const index = data.checks.findIndex(check => check.check_type === snapshot.checkType);
                    if (index >= 0) data.checks[index] = snapshot.check || {...data.checks[index], status:'ERROR'};
                }
            }, () => {
                scheduleRender();
            });
        }
    }
    await Promise.allSettled([statusRequest, periodicRequest, retailRequest, ddayRequest, columnRequest]);
}

function renderLayer1Stats(data) {
    if (L1.retailReview && !data._retailPending) L1.retailReview.decorate(data, getSelectedDate());
    // Summary stats
    const complete = !data._periodicPending && !data._dailyError && !data._periodicError && !data.error;
    document.getElementById('total-checked').textContent = complete ? data.summary.total_checked : '—';
    document.getElementById('total-passed').textContent = complete && !data._retailPending ? data.summary.passed : '—';
    document.getElementById('total-failed').textContent = complete && !data._retailPending ? data.summary.failed : '—';
    if (complete && !data._checkStatusPending) updateConfirmedCount();
    else document.getElementById('total-confirmed').textContent = '—';


    // 데일리 / 분석대상일별 분류 (API 응답의 display_group 기반)
    const dailyChecks = data.checks.filter(c => c.display_group === 'daily');
    const periodChecks = data.checks.filter(c => c.display_group === 'periodic');
    const periodSection = document.getElementById('period-checks-section');
    if (periodSection) periodSection.hidden = !data._periodicPending && !data._periodicError && !periodChecks.length;

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
                        <div class="check-name">${renderCountryFlagLabel(check.name)}</div>
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
    } else if (!data._dailyError) {
        dailyChecksList.innerHTML = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터 없음</div></div></div></div>';
    } else {
        dailyChecksList.innerHTML = '';
    }

    // 분석대상일별 체크 리스트
    const periodChecksList = document.getElementById('period-checks-list');
    if (periodChecks.length > 0) {
        periodChecksList.innerHTML = periodChecks.map((check, idx) => {
            const checkIdx = data.checks.indexOf(check);
            return wrapWithCheckBadge(renderCheck(check, checkIdx), check.check_type);
        }).join('');
    } else if (data._periodicPending) {
        periodChecksList.innerHTML = '<div class="check-item"><div class="check-main">데이터를 불러오는 중입니다.</div></div>';
    } else if (data._periodicError) {
        periodChecksList.innerHTML = '';
    } else {
        periodChecksList.innerHTML = '<div class="check-item"><div class="check-main"><div class="check-info"><div class="check-name">데이터 없음</div></div></div></div>';
    }

    if (data._dailyError || data.error) dailyChecksList.insertAdjacentHTML('afterbegin',
        '<div role="alert" class="check-description">' + esc(data._dailyError || '일부 검증 데이터를 조회하지 못했습니다.') + '</div>');
    if (data._periodicError) periodChecksList.insertAdjacentHTML('afterbegin',
        '<div role="alert" class="check-description">분석대상일별 조회 실패 · ' + esc(data._periodicError) + '</div>');

    // 체크 배지 삽입 (DOM API)
    addCheckBadges();
}


function loadAllData(refresh = false, reentry = false) {
    return loadStats(refresh, reentry);
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
function formatBackupCount(value) {
    return Number(value || 0).toLocaleString() + '건';
}

function formatBackupSourceDate(sourceDates, keys) {
    var dates = keys.map(function(key) {
        return sourceDates[key] || '-';
    });
    if (dates.every(function(date) { return date === dates[0]; })) {
        return dates[0];
    }
    return keys.map(function(key, index) {
        var label = key.replace(/^[^_]+_/, '').toUpperCase();
        return (label === 'LDY_DRYER' ? 'DRY' : label) + ' ' + dates[index];
    }).join(' · ');
}

function formatBackupPrompt(data) {
    var sourceDates = data.source_dates || {};
    var totalCount = data.total_count;
    if (totalCount === undefined || totalCount === null) {
        totalCount = Number(data.tv_count || 0) +
            Number(data.sea_ref_count || 0) +
            Number(data.sea_ldy_count || 0) +
            Number(data.seda_tv_count || 0) +
            Number(data.seda_ref_count || 0) +
            Number(data.seda_ldy_count || 0) +
            Number(data.siel_tv_count || 0) +
            Number(data.siel_ref_count || 0) +
            Number(data.siel_ldy_count || 0) +
            Number(data.sem_tv_count || 0) +
            Number(data.sem_ref_count || 0) +
            Number(data.sem_ldy_count || 0) +
            Number(data.sem_ldy_dryer_count || 0) +
            Number(data.sea_ldy_dryer_count || 0) +
            Number(data.seg_tv_count || 0) +
            Number(data.seg_ref_count || 0) +
            Number(data.seg_ldy_count || 0) +
            Number(data.seg_ldy_dryer_count || 0) +
            Number(data.tse_tv_count || 0) +
            Number(data.tse_ref_count || 0) +
            Number(data.tse_ldy_count || 0) +
            Number(data.seib_tv_count || 0) +
            Number(data.seib_ref_count || 0) +
            Number(data.seib_ldy_count || 0) +
            Number(data.seib_ldy_dryer_count || 0) +
            Number(data.seuk_tv_count || 0) + Number(data.seuk_ref_count || 0) +
            Number(data.seuk_ldy_count || 0) + Number(data.seuk_ldy_dryer_count || 0);
    }

    return [
        '백업 대상 확인',
        '',
        '검수일  ' + (data.inspection_date || '-'),
        '',
        'SEA · D-1 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['sea_tv', 'sea_ref', 'sea_ldy', 'sea_ldy_dryer']
        ),
        'TV ' + formatBackupCount(data.tv_count) +
            '  ·  REF ' + formatBackupCount(data.sea_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.sea_ldy_count) +
            '  ·  DRY ' + formatBackupCount(data.sea_ldy_dryer_count),
        '',
        'SEDA · D-1 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['seda_tv', 'seda_ref', 'seda_ldy']
        ),
        'TV ' + formatBackupCount(data.seda_tv_count) +
            '  ·  REF ' + formatBackupCount(data.seda_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.seda_ldy_count),
        '',
        'SEM · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['sem_tv', 'sem_ref', 'sem_ldy', 'sem_ldy_dryer']
        ),
        'TV ' + formatBackupCount(data.sem_tv_count) +
            '  ·  REF ' + formatBackupCount(data.sem_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.sem_ldy_count) +
            '  ·  DRY ' + formatBackupCount(data.sem_ldy_dryer_count),
        '',
        'SIEL · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['siel_tv', 'siel_ref', 'siel_ldy']
        ),
        'TV ' + formatBackupCount(data.siel_tv_count) +
            '  ·  REF ' + formatBackupCount(data.siel_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.siel_ldy_count),
        '',
        'SEG · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['seg_tv', 'seg_ref', 'seg_ldy', 'seg_ldy_dryer']
        ),
        'TV ' + formatBackupCount(data.seg_tv_count) +
            '  ·  REF ' + formatBackupCount(data.seg_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.seg_ldy_count) +
            '  ·  DRY ' + formatBackupCount(data.seg_ldy_dryer_count),
        '',
        'TSE · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['tse_tv', 'tse_ref', 'tse_ldy']
        ),
        'TV ' + formatBackupCount(data.tse_tv_count) +
            '  ·  REF ' + formatBackupCount(data.tse_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.tse_ldy_count),
        '',
        'SEIB · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['seib_tv', 'seib_ref', 'seib_ldy', 'seib_ldy_dryer']
        ),
        'TV ' + formatBackupCount(data.seib_tv_count) +
            '  ·  REF ' + formatBackupCount(data.seib_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.seib_ldy_count) +
            '  ·  DRY ' + formatBackupCount(data.seib_ldy_dryer_count),
        'SEUK · D 데이터 · ' + formatBackupSourceDate(
            sourceDates, ['seuk_tv', 'seuk_ref', 'seuk_ldy', 'seuk_ldy_dryer']
        ),
        'TV ' + formatBackupCount(data.seuk_tv_count) +
            '  ·  REF ' + formatBackupCount(data.seuk_ref_count) +
            '  ·  LDY ' + formatBackupCount(data.seuk_ldy_count) +
            '  ·  DRY ' + formatBackupCount(data.seuk_ldy_dryer_count),
        '',
        '총 ' + formatBackupCount(totalCount),
        '',
        '백업을 진행하시겠습니까?'
    ].join('\n');
}

function renderBackupConfirmContent(data) {
    var container = document.getElementById('confirmMsg');
    if (!container) return;

    var sourceDates = data.source_dates || {};
    var totalCount = data.total_count;
    if (totalCount === undefined || totalCount === null) {
        totalCount = Number(data.tv_count || 0) +
            Number(data.sea_ref_count || 0) +
            Number(data.sea_ldy_count || 0) +
            Number(data.seda_tv_count || 0) +
            Number(data.seda_ref_count || 0) +
            Number(data.seda_ldy_count || 0) +
            Number(data.siel_tv_count || 0) +
            Number(data.siel_ref_count || 0) +
            Number(data.siel_ldy_count || 0) +
            Number(data.sem_tv_count || 0) +
            Number(data.sem_ref_count || 0) +
            Number(data.sem_ldy_count || 0) +
            Number(data.sem_ldy_dryer_count || 0) +
            Number(data.sea_ldy_dryer_count || 0) +
            Number(data.seg_tv_count || 0) +
            Number(data.seg_ref_count || 0) +
            Number(data.seg_ldy_count || 0) +
            Number(data.seg_ldy_dryer_count || 0) +
            Number(data.tse_tv_count || 0) +
            Number(data.tse_ref_count || 0) +
            Number(data.tse_ldy_count || 0) +
            Number(data.seib_tv_count || 0) +
            Number(data.seib_ref_count || 0) +
            Number(data.seib_ldy_count || 0) +
            Number(data.seib_ldy_dryer_count || 0) +
            Number(data.seuk_tv_count || 0) + Number(data.seuk_ref_count || 0) +
            Number(data.seuk_ldy_count || 0) + Number(data.seuk_ldy_dryer_count || 0);
    }

    function element(tagName, text, styles) {
        var node = document.createElement(tagName);
        if (text !== undefined && text !== null) node.textContent = text;
        if (styles) node.style.cssText = styles;
        return node;
    }

    function countryCard(country, offsetLabel, sourceDate, counts) {
        var flagCodes = { SEA: 'us', SEDA: 'br', SEM: 'mx', SIEL: 'in', SEG: 'de', TSE: 'th', SEIB: 'es', SEUK: 'gb' };
        var card = element('div', null,
            'border:1px solid #e2e8f0;border-radius:10px;padding:13px 14px;background:#fff;');
        var header = element('div', null,
            'display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:10px;');
        var title = element('strong', null,
            'font-size:15px;color:#0f172a;');
        title.className = 'country-flag-label';
        var flag = element('img');
        flag.className = 'country-flag-icon';
        flag.src = '/static/img/flags/' + flagCodes[country] + '.svg';
        flag.alt = '';
        flag.setAttribute && flag.setAttribute('aria-hidden', 'true');
        title.appendChild(flag);
        title.appendChild(element('span', country));
        var meta = element('div', null,
            'display:flex;align-items:center;gap:7px;font-size:12px;color:#64748b;');
        meta.appendChild(element('span', '데이터일 ' + sourceDate));
        meta.appendChild(element('span', offsetLabel,
            'padding:2px 7px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-weight:700;'));
        header.appendChild(title);
        header.appendChild(meta);
        card.appendChild(header);

        var countGrid = element('div', null,
            'display:grid;grid-template-columns:repeat(' + counts.length + ',minmax(0,1fr));gap:8px;');
        counts.forEach(function(item) {
            var countBox = element('div', null,
                'padding:8px 6px;border-radius:8px;background:#f8fafc;text-align:center;');
            countBox.appendChild(element('div', item.label,
                'font-size:11px;color:#64748b;margin-bottom:2px;'));
            countBox.appendChild(element('strong', formatBackupCount(item.value),
                'font-size:14px;color:#0f172a;'));
            countGrid.appendChild(countBox);
        });
        card.appendChild(countGrid);
        return card;
    }

    container.textContent = '';
    container.style.cssText =
        'font-size:14px;font-weight:400;color:#1a1a1a;line-height:1.45;margin-bottom:20px;text-align:left;';
    if (container.parentElement) {
        container.parentElement.classList.add('backup-confirm-dialog');
    }
    container.appendChild(element('div', '백업 대상 확인',
        'font-size:17px;font-weight:700;color:#0f172a;text-align:center;margin-bottom:13px;'));

    var inspection = element('div', null,
        'display:flex;align-items:center;justify-content:space-between;padding:10px 13px;' +
        'border-radius:9px;background:#f1f5f9;margin-bottom:10px;');
    inspection.appendChild(element('span', '검수일',
        'font-size:12px;color:#64748b;'));
    inspection.appendChild(element('strong', data.inspection_date || '-',
        'font-size:14px;color:#0f172a;'));
    container.appendChild(inspection);

    var cards = element('div');
    cards.className = 'backup-confirm-grid';
    cards.appendChild(countryCard(
        'SEA', 'D-1',
        formatBackupSourceDate(sourceDates, ['sea_tv', 'sea_ref', 'sea_ldy', 'sea_ldy_dryer']),
        [
            { label: 'TV', value: data.tv_count },
            { label: 'REF', value: data.sea_ref_count },
            { label: 'LDY', value: data.sea_ldy_count },
            { label: 'DRY', value: data.sea_ldy_dryer_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SEDA', 'D-1',
        formatBackupSourceDate(sourceDates, ['seda_tv', 'seda_ref', 'seda_ldy']),
        [
            { label: 'TV', value: data.seda_tv_count },
            { label: 'REF', value: data.seda_ref_count },
            { label: 'LDY', value: data.seda_ldy_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SEM', 'D',
        formatBackupSourceDate(sourceDates, ['sem_tv', 'sem_ref', 'sem_ldy', 'sem_ldy_dryer']),
        [
            { label: 'TV', value: data.sem_tv_count },
            { label: 'REF', value: data.sem_ref_count },
            { label: 'LDY', value: data.sem_ldy_count },
            { label: 'DRY', value: data.sem_ldy_dryer_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SIEL', 'D',
        formatBackupSourceDate(sourceDates, ['siel_tv', 'siel_ref', 'siel_ldy']),
        [
            { label: 'TV', value: data.siel_tv_count },
            { label: 'REF', value: data.siel_ref_count },
            { label: 'LDY', value: data.siel_ldy_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SEIB', 'D',
        formatBackupSourceDate(sourceDates, ['seib_tv', 'seib_ref', 'seib_ldy', 'seib_ldy_dryer']),
        [
            { label: 'TV', value: data.seib_tv_count },
            { label: 'REF', value: data.seib_ref_count },
            { label: 'LDY', value: data.seib_ldy_count },
            { label: 'DRY', value: data.seib_ldy_dryer_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SEUK', 'D',
        formatBackupSourceDate(sourceDates, ['seuk_tv', 'seuk_ref', 'seuk_ldy', 'seuk_ldy_dryer']),
        [
            { label: 'TV', value: data.seuk_tv_count },
            { label: 'REF', value: data.seuk_ref_count },
            { label: 'LDY', value: data.seuk_ldy_count },
            { label: 'DRY', value: data.seuk_ldy_dryer_count }
        ]
    ));
    cards.appendChild(countryCard(
        'TSE', 'D',
        formatBackupSourceDate(sourceDates, ['tse_tv', 'tse_ref', 'tse_ldy']),
        [
            { label: 'TV', value: data.tse_tv_count },
            { label: 'REF', value: data.tse_ref_count },
            { label: 'LDY', value: data.tse_ldy_count }
        ]
    ));
    cards.appendChild(countryCard(
        'SEG', 'D',
        formatBackupSourceDate(sourceDates, ['seg_tv', 'seg_ref', 'seg_ldy', 'seg_ldy_dryer']),
        [
            { label: 'TV', value: data.seg_tv_count },
            { label: 'REF', value: data.seg_ref_count },
            { label: 'LDY', value: data.seg_ldy_count },
            { label: 'DRY', value: data.seg_ldy_dryer_count }
        ]
    ));
    container.appendChild(cards);

    var total = element('div', null,
        'display:flex;align-items:center;justify-content:center;gap:7px;margin:13px 0 8px;');
    total.appendChild(element('span', '총 백업 대상',
        'font-size:12px;color:#64748b;'));
    total.appendChild(element('strong', formatBackupCount(totalCount),
        'font-size:18px;color:#2563eb;'));
    container.appendChild(total);
    container.appendChild(element('div', '백업을 진행하시겠습니까?',
        'font-size:13px;color:#475569;text-align:center;'));
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
            var msg = formatBackupPrompt(res);
            var confirmPromise = showConfirm(msg, 'info', {
                okText: '백업 실행',
                cancelText: '취소'
            });
            renderBackupConfirmContent(res);
            confirmPromise.then(function(confirmed) {
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
    loadOnDomReady: true,
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
