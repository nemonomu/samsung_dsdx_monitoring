// ============================================================
// Layer1 Common Utilities
// ============================================================
var L1 = (function() {

    // TV/HHP 카테고리 정렬 순서
    var sortOrder = ['TV', 'HHP'];

    /**
     * 시간 헤더 HTML 생성 (US/KST, DST 라벨)
     * @param {Object} options
     * @param {string} options.usTime - US(NY) 시간 (예: '04:00', '2026-01-06 01:00')
     * @param {string} options.krTime - KST 시간 (예: '2026-01-05 18:00')
     * @param {string} [options.krTimeEnd] - KST 종료 시간 (Retail 오후용)
     * @param {boolean} [options.isDst] - DST 여부
     * @param {string} [options.detailLink] - 추가 설명 링크/텍스트
     * @param {string} [options.label] - 시간 라벨 (기본: '수집 시간')
     * @returns {string} HTML 문자열
     */
    function buildTimeHeader(options) {
        var usTime = options.usTime || '';
        var krTime = options.krTime || '';
        var isDst = options.isDst || false;
        var label = options.label || '수집 시간';
        var kstLabel = isDst ? 'KST(DST)' : 'KST';

        var timeSpans = '<span class="utc">US(NY) ' + usTime + '</span>' +
            '<span class="kst">' + kstLabel + ' ' + krTime + '</span>';

        // krTimeEnd가 있으면 Retail 스타일 (오전/오후 가로 배치)
        if (options.krTimeEnd) {
            if (!options.label) label = '서버별 시간';
            var usTimeAm = usTime;
            var usTimePm = options.usTimePm || '';
            timeSpans = '<span class="utc">[오전] US(NY) ' + usTimeAm + ' ' + kstLabel + ' ' + krTime + '</span>' +
                '<span class="utc">[오후] US(NY) ' + usTimePm + ' ' + kstLabel + ' ' + options.krTimeEnd + '</span>';
        }

        var detailHtml = '';
        if (options.detailLink) {
            detailHtml = '<span style="margin-left: 12px; font-size: 12px; color: var(--text-secondary);">' + options.detailLink + '</span>';
        }

        // krTimeEnd가 있으면 flex-direction: row 스타일 적용
        var timeStyle = options.krTimeEnd
            ? ' style="display: flex; flex-direction: row; align-items: center; gap: 24px;"'
            : '';

        return '<div class="time-slot-item" style="margin-bottom: 16px;">' +
            '<div class="time-slot-header" style="cursor: default;">' +
                '<div class="time-slot-info">' +
                    '<span class="time-slot-name">' + label + '</span>' +
                    '<span class="time-slot-time"' + timeStyle + '>' +
                        timeSpans +
                    '</span>' +
                    detailHtml +
                '</div>' +
            '</div>' +
        '</div>';
    }

    /**
     * TV/HHP 순서로 카테고리 배열 정렬
     * @param {Array} categories - 카테고리 객체 배열
     * @param {string} [nameKey] - 카테고리 이름 키 (기본: 'name', market 계열은 'category')
     * @returns {Array} 정렬된 새 배열
     */
    function sortCategories(categories, nameKey) {
        var key = nameKey || 'name';
        return [].concat(categories).sort(function(a, b) {
            var aIdx = sortOrder.indexOf(a[key]);
            var bIdx = sortOrder.indexOf(b[key]);
            if (aIdx === -1 && bIdx === -1) return 0;
            if (aIdx === -1) return 1;
            if (bIdx === -1) return -1;
            return aIdx - bIdx;
        });
    }

    /**
     * 에러 메시지 렌더링
     * @param {string} containerId - 컨테이너 요소 ID
     * @param {string} message - 에러 메시지
     */
    function renderError(containerId, message) {
        var container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '<div class="check-item"><div class="check-main">' +
                '<div class="check-info">' +
                    '<div class="check-name">데이터 로드 실패</div>' +
                    '<div class="check-description">' + esc(message) + '</div>' +
                '</div></div></div>';
        }
    }

    /**
     * window.onload 공통 초기화
     * @param {Object} options
     * @param {Array} [options.modals] - 생성할 모달 목록 [{name, style}]
     * @param {Object} [options.filterBarOptions] - initFilterBar에 전달할 옵션
     * @param {Function} [options.onLoad] - 초기화 후 호출할 함수
     */
    function initLayer1Page(options) {
        options = options || {};

        window.onload = function() {
            // 모달 생성
            if (options.modals && options.modals.length > 0) {
                options.modals.forEach(function(modal) {
                    AppModal.create(modal.name, { style: modal.style });
                });
            }

            // URL date 파라미터가 있으면 FilterBar 날짜로 설정
            var urlDate = new URLSearchParams(window.location.search).get('date');
            if (urlDate) localStorage.setItem('monitoringSelectedDate', urlDate);

            // FilterBar 초기화
            initFilterBar(options.filterBarOptions);

            // 데이터 로딩
            if (typeof loadAllData === 'function') {
                loadAllData();
            }

            // 추가 초기화 콜백
            if (typeof options.onLoad === 'function') {
                options.onLoad();
            }
        };
    }

    var renderers = {};

    return {
        sortOrder: sortOrder,
        buildTimeHeader: buildTimeHeader,
        sortCategories: sortCategories,
        renderError: renderError,
        initLayer1Page: initLayer1Page,
        renderers: renderers
    };

})();

// Extracted from base_layer1.html
// ============================================================
// Sidebar subitem click
// ============================================================
function onSubitemClick(groupKey, itemName) {
    var urls = {
        'Retail': '/dx/layer1/retail/',
        'Retail 감성분석': '/dx/layer1/sentiment/',
        'YouTube': '/dx/layer1/youtube/',
        'Market Trend': '/dx/layer1/market-trend/',
        'Market 수요증감율': '/dx/layer1/market-demand/',
        'Market Competitor': '/dx/layer1/market-competitor/',
        'Market Competitor Event': '/dx/layer1/market-competitor-event/',
        'Market Promotion': '/dx/layer1/market-promotion/',
    };
    var macroMap = {
        '자본 스톡(실질, PPP)': 'macro_capital_stock',
        '민간부문 순 이자수입': 'macro_net_interest',
        '잠재적 산출량': 'macro_potential_gdp',
        '명목 GDP(PPP) 1인당': 'macro_gdp_ppp_nominal',
        '실질 GDP(PPP) 1인당': 'macro_gdp_ppp_real',
        '가처분소득(실질, PPP)': 'macro_disposable_income_real',
        '소비자 물가 지수': 'macro_cpi',
        '가처분소득(명목, LCU)': 'macro_disposable_income_nominal',
        '가계부문 금융부채': 'macro_household_debt',
        '소매 가격 지수': 'macro_rpi',
    };
    var date = document.getElementById('target-date') ?
               document.getElementById('target-date').value : '';
    var url = urls[itemName];
    if (url) {
        window.location.href = url + (date ? '?date=' + date : '');
        return;
    }
    var macroType = macroMap[itemName];
    if (macroType) {
        window.location.href = '/dx/layer1/macro/?check_type=' + macroType + (date ? '&date=' + date : '');
    }
}

// ============================================================
// Common state
// ============================================================
var currentStatsData = null;
var currentCheckStatus = null;
var currentNullData = null;
var currentRetailSummary = null;

// ============================================================
// Common utility functions
// ============================================================
function getStatusBadge(status) {
    var statusMap = {
        'OK': { class: 'ok', text: '정상' },
        'WARNING': { class: 'warning', text: '주의' },
        'CRITICAL': { class: 'critical', text: '심각' },
        'PENDING': { class: 'pending', text: '대기중' },
        'COLLECTING': { class: 'collecting', text: '수집중' },
        'ANALYZING': { class: 'collecting', text: '분석중' }
    };
    var s = statusMap[status] || { class: 'ok', text: status };
    return '<span class="status-badge ' + s.class + '"><span class="status-dot"></span>' + s.text + '</span>';
}

function getStatusClass(status) {
    return status ? status.toLowerCase() : 'pending';
}

function getRetailerStatusClass(status) {
    var classMap = { 'OK': 'ok', 'WARNING': 'warning', 'CRITICAL': 'critical', 'PENDING': 'pending', 'COLLECTING': 'collecting' };
    return classMap[status] || 'ok';
}

function formatLocalDate(date) {
    var yyyy = date.getFullYear();
    var mm = String(date.getMonth() + 1).padStart(2, '0');
    var dd = String(date.getDate()).padStart(2, '0');
    return yyyy + '-' + mm + '-' + dd;
}

// ============================================================
// FilterBar
// ============================================================
var filterBar;

function getSelectedDate() {
    return filterBar.getDate();
}

function initFilterBar(options) {
    var saved = localStorage.getItem('monitoringSelectedDate');
    var yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    var defaultDate = saved || formatLocalDate(yesterday);
    var today = formatLocalDate(new Date());

    function onDateChange() {
        localStorage.setItem('monitoringSelectedDate', filterBar.getDate());
    }

    var config = {
        sticky: true,
        controls: [
            { type: 'date', key: 'targetDate', label: '조회 날짜', value: defaultDate, max: today, showWeekday: true },
            { type: 'button', label: '조회', style: 'primary', onClick: function() {
                if (filterBar.getDate() > today) { showToast('오늘 이후 날짜로는 조회할 수 없습니다.', 'warning'); filterBar.setDate(today); return; }
                onDateChange(); loadAllData();
            } },
            { type: 'button', label: '전날', style: 'outline', onClick: function() { filterBar.prevDay(); onDateChange(); loadAllData(); } },
            { type: 'button', label: '다음날', style: 'outline', onClick: function() {
                var before = filterBar.getDate();
                filterBar.nextDay();
                if (filterBar.getDate() === before) { showToast('오늘 이후 날짜로는 조회할 수 없습니다.', 'warning'); return; }
                onDateChange(); loadAllData();
            } }
        ]
    };

    if (options && options.right) {
        config.right = options.right;
    }

    filterBar = new FilterBar('#filter-bar-container', config).render();
}

// ============================================================
// Check Log (검수 확인)
// ============================================================
function flattenCheckToDetails(sectionType, check) {
    var details = [];
    switch (sectionType) {
        case 'retail':
            (check.categories || []).forEach(function(cat) {
                (cat.time_slots || []).forEach(function(slot) {
                    if (slot.status === 'PENDING') return;
                    (slot.retailers || []).forEach(function(ret) {
                        details.push({
                            category: cat.name, time_slot: slot.name,
                            retailer: ret.retailer, item_name: '',
                            expected_count: ret.expected || 0, actual_count: ret.count || 0,
                            rate: ret.expected > 0 ? Math.round((ret.count || 0) / ret.expected * 1000) / 10 : 0,
                            status: ret.status
                        });
                    });
                });
            });
            if (currentNullData) {
                    ['tv'].forEach(function(type) {
                    (currentNullData[type] || []).forEach(function(ret) {
                        ret.time_slots.forEach(function(slot) {
                            var nullCols = slot.null_columns.join(', ');
                            var existing = details.find(function(d) {
                                return d.category === type.toUpperCase() && d.retailer === ret.retailer && d.time_slot === slot.time_slot;
                            });
                            if (existing) {
                                existing.item_name = nullCols;
                                existing.status = 'NULL';
                            } else {
                                details.push({
                                    category: type.toUpperCase(), time_slot: slot.time_slot,
                                    retailer: ret.retailer, item_name: nullCols,
                                    expected_count: 0, actual_count: 0, rate: 0, status: 'NULL'
                                });
                            }
                        });
                    });
                });
            }
            break;
        case 'sentiment':
            (check.categories || []).forEach(function(cat) {
                (cat.time_slots || []).forEach(function(slot) {
                    (slot.retailers || []).forEach(function(ret) {
                        details.push({
                            category: cat.name, time_slot: slot.time,
                            retailer: ret.name, item_name: '',
                            expected_count: ret.target || 0, actual_count: ret.analyzed || 0,
                            rate: ret.rate || 0, status: ret.status
                        });
                    });
                });
            });
            break;
        case 'youtube':
            (check.categories || []).forEach(function(cat) {
                details.push({ category: cat.name, time_slot: '', retailer: '', item_name: 'Log',
                    expected_count: cat.expected || 0, actual_count: cat.log_count || 0,
                    rate: cat.rate || 0, status: cat.status });
                details.push({ category: cat.name, time_slot: '', retailer: '', item_name: 'Video',
                    expected_count: cat.avg_7day || 0, actual_count: cat.video_count || 0,
                    rate: cat.avg_7day > 0 ? Math.round(cat.video_count / cat.avg_7day * 1000) / 10 : 0,
                    status: cat.status });
                details.push({ category: cat.name, time_slot: '', retailer: '', item_name: 'Comment',
                    expected_count: 0, actual_count: cat.comment_count || 0, rate: 0, status: cat.status });
            });
            break;
        case 'tse_retail':
            (check.categories || []).forEach(function(cat) {
                (cat.retailers || []).forEach(function(ret) {
                    details.push({
                        category: cat.category || cat.name,
                        time_slot: check.collection_window || 'RDP 09:00~09:30',
                        retailer: ret.retailer,
                        item_name: ret.batch_id || '',
                        expected_count: ret.expected || 0,
                        actual_count: ret.actual || ret.count || 0,
                        rate: ret.rate || 0,
                        status: ret.status
                    });
                });
            });
            break;
        case 'market_trend':
            (check.categories || []).forEach(function(cat) {
                (cat.items || []).forEach(function(item) {
                    details.push({ category: cat.name, time_slot: '', retailer: '', item_name: item.name,
                        expected_count: item.expected || 0, actual_count: item.collected || 0,
                        rate: item.rate || 0, status: item.status });
                });
            });
            break;
        case 'market_competitor':
        case 'market_competitor_event':
            (check.categories || []).forEach(function(cat) {
                details.push({ category: cat.category, time_slot: '', retailer: '', item_name: 'collected',
                    expected_count: cat.expected || 0, actual_count: cat.collected || 0,
                    rate: cat.rate || 0, status: cat.status });
            });
            break;
        case 'market_demand':
            (check.categories || []).forEach(function(cat) {
                details.push({ category: cat.category, time_slot: '', retailer: '', item_name: '',
                    expected_count: cat.target || 0, actual_count: cat.collected || 0,
                    rate: cat.rate || 0, status: cat.status });
            });
            break;
        case 'market_promotion':
            (check.retailers || []).forEach(function(ret) {
                details.push({ category: '', time_slot: '', retailer: ret.retailer, item_name: '',
                    expected_count: ret.expected || 0, actual_count: ret.collected || 0,
                    rate: ret.rate || 0, status: ret.status });
            });
            break;
    }
    return details;
}

async function loadCheckStatus(dateStr) {
    var response = await fetch('/dx/layer1/api/check/status/?date=' + dateStr);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return await response.json();
}

async function saveCheck(sectionType, step) {
    step = step || 1;
    if (!currentStatsData || !currentStatsData.checks) return;

    var check = currentStatsData.checks.find(function(c) { return c.check_type === sectionType; });
    if (!check) { showToast('해당 섹션 데이터가 없습니다.', 'error'); return; }

    var confirmMsg = step === 2
        ? check.name + ' 검수를 최종 완료하시겠습니까?'
        : check.name + ' 검수를 확인 처리하시겠습니까?';

    var options = step === 1 ? { input: { placeholder: '메모 (선택)' } } : {};
    var result = await showConfirm(confirmMsg, step === 2 ? 'warning' : 'info', options);
    var confirmed = typeof result === 'object' ? result.confirmed : result;
    var memo = typeof result === 'object' ? (result.value || '') : '';
    if (!confirmed) return;

    try {
        // 수요증감율 1차 확인: 부족 키워드 스냅샷 포함
        var keywords = [];
        if (sectionType === 'market_demand' && step === 1) {
            try {
                var missingResp = await fetch('/dx/layer1/market-demand/api/missing/?category=all&date=' + getSelectedDate());
                var missingData = await missingResp.json();
                keywords = missingData.missing_keywords || [];
            } catch (e) { /* 키워드 조회 실패해도 확인은 진행 */ }
        }

        var sectionData = { section: sectionType,
            expected_count: check.expected || check.expected_min || check.target || 0,
            actual_count: check.actual || 0, rate: check.rate || 0, status: check.status,
            details: flattenCheckToDetails(sectionType, check), memo: memo };
        if (keywords.length > 0) sectionData.keywords = keywords;

        var response = await fetch('/dx/layer1/api/check/save/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ date: getSelectedDate(), layer: 1, step: step, sections: [sectionData] })
        });
        var saveData = await response.json();
        if (!response.ok || !saveData.success) { showToast(saveData.error || '저장 중 오류가 발생했습니다.', saveData.level || 'error'); return; }
        showToast(step === 2 ? '완료 처리됨' : '확인 완료', 'success');
        loadAllData();
    } catch (e) { showToast('시스템 오류가 발생했습니다.', 'error'); }
}

async function deleteCheck(sectionType, step) {
    step = step || 0;
    var confirmMsg = step === 2 ? '완료를 취소하시겠습니까?' : '확인을 취소하시겠습니까?';

    var result = await showConfirm(confirmMsg, 'warning', { input: { placeholder: '취소 사유를 입력하세요 (필수)' } });
    if (!result.confirmed) return;
    if (!result.value) { showToast('취소 사유를 입력해주세요.', 'warning'); return; }
    var deleteMemo = result.value;

    try {
        var response = await fetch('/dx/layer1/api/check/delete/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ date: getSelectedDate(), layer: 1, section: sectionType, step: step, delete_memo: deleteMemo })
        });
        var data = await response.json();
        if (!response.ok || !data.success) { showToast(data.error || '취소 중 오류가 발생했습니다.', 'error'); return; }
        showToast(step === 2 ? '완료 취소됨' : '확인 취소됨', 'info');
        loadAllData();
    } catch (e) { showToast('시스템 오류가 발생했습니다.', 'error'); }
}

function updateConfirmedCount() {
    var el = document.getElementById('total-confirmed');
    if (!el) return;
    var targetCount = 0, confirmedCount = 0;
    if (currentStatsData && currentStatsData.checks) {
        var targetChecks = currentStatsData.checks.filter(function(c) { return c.is_target_date !== false; });
        targetCount = targetChecks.length;
        if (currentCheckStatus && currentCheckStatus.sections) {
            targetChecks.forEach(function(c) { if (currentCheckStatus.sections[c.check_type]) confirmedCount++; });
        }
    }
    el.textContent = targetCount > 0 ? confirmedCount + ' / ' + targetCount : '-';
    if (targetCount > 0 && confirmedCount === targetCount) { el.style.color = 'var(--color-ok)'; }
    else if (confirmedCount > 0) { el.style.color = '#f59e0b'; }
    else { el.style.color = ''; }
}

function getCheckBadgeHtml(sectionType) {
    var check = null;
    if (currentStatsData && currentStatsData.checks) {
        check = currentStatsData.checks.find(function(c) { return c.check_type === sectionType; });
    }
    var isFullRate = check && check.rate >= 100 && sectionType !== 'retail';

    if (!currentCheckStatus || !currentCheckStatus.sections) {
        if (isFullRate) {
            return '<button class="btn-check-confirm step2" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 2)" title="완료">완료</button>';
        }
        return '<button class="btn-check-confirm" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 1)" title="1차 확인">확인</button>';
    }
    var sec = currentCheckStatus.sections[sectionType];
    if (!sec) {
        if (isFullRate) {
            return '<button class="btn-check-confirm step2" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 2)" title="완료">완료</button>';
        }
        return '<button class="btn-check-confirm" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 1)" title="1차 확인">확인</button>';
    }

    var timeStr = sec.updated_at
        ? new Date(sec.updated_at).toLocaleString('ko-KR', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'})
        : new Date(sec.created_at).toLocaleString('ko-KR', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
    var who = sec.updated_id || sec.created_id || '';

    if (sec.confirm_step === 2) {
        // 2차 완료됨
        return '<button class="btn-check-confirm completed" onclick="event.stopPropagation(); deleteCheck(\'' + sectionType + '\', 2)" title="' + esc(who) + ' ' + timeStr + '">완료 ✓</button>';
    }
    if (sec.confirm_step === 1) {
        // 1차 확인됨: [취소] + [완료] (retail이거나 rate >= 100이면 완료 가능)
        var cancelBtn = '<button class="btn-check-confirm cancel" onclick="event.stopPropagation(); deleteCheck(\'' + sectionType + '\')" title="확인 취소">취소</button>';
        if (sectionType === 'retail' || isFullRate) {
            return cancelBtn + '<button class="btn-check-confirm checked" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 2)" title="' + esc(who) + ' ' + timeStr + '">완료</button>';
        }
        return cancelBtn + '<button class="btn-check-confirm checked" disabled title="' + esc(who) + ' ' + timeStr + ' (완료율 100% 미달)">확인됨</button>';
    }
    // confirm_step=0 (기존 레거시): 미확인처럼 처리
    if (isFullRate) {
        return '<button class="btn-check-confirm step2" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 2)" title="완료">완료</button>';
    }
    return '<button class="btn-check-confirm" onclick="event.stopPropagation(); saveCheck(\'' + sectionType + '\', 1)" title="1차 확인">확인</button>';
}

function addCheckBadges() {
    document.querySelectorAll('.check-item[data-check-type]').forEach(function(item) {
        var type = item.dataset.checkType;
        var statsDiv = item.querySelector('.check-stats');
        if (!statsDiv) return;
        if (currentStatsData && currentStatsData.checks) {
            var check = currentStatsData.checks.find(function(c) { return c.check_type === type; });
            if (check && check.is_target_date === false) return;
        }
        var badge = document.createElement('span');
        badge.className = 'check-badge-inline';
        badge.innerHTML = getCheckBadgeHtml(type);
        statsDiv.appendChild(badge);
    });
}

// ============================================================
// Toggle functions
// ============================================================
function toggleTimeSlots(element, checkIdx) {
    var container = document.getElementById('time-slots-' + checkIdx);
    var icon = element.querySelector('.toggle-icon');
    if (container) { container.classList.toggle('show'); icon.classList.toggle('expanded'); }
}

function toggleRetailerDetails(element, checkIdx, slotIdx) {
    var container = document.getElementById('retailers-' + checkIdx + '-' + slotIdx);
    var icon = element.querySelector('.toggle-icon-small');
    if (container) { container.classList.toggle('show'); if (icon) icon.classList.toggle('expanded'); }
}

function toggleSentimentCategory(element, checkIdx, catIdx) {
    var container = document.getElementById('sentiment-cat-' + checkIdx + '-' + catIdx);
    var icon = element.querySelector('.toggle-icon-small');
    if (container) { container.classList.toggle('show'); if (icon) icon.classList.toggle('expanded'); }
}

// ============================================================
// Common table helpers
// ============================================================
var DEFAULT_COL_WIDTH = 150;
var MIN_COL_WIDTH = 50;

// escJs: escape for inline JS strings (single quotes)
function escJs(s) { return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

// 섹션 페이지: 토글 없이 모든 콘텐츠 펼침
function expandSectionContent() {
    document.querySelectorAll('.time-slots-container').forEach(function(el) { el.classList.add('show'); });
    document.querySelectorAll('.sentiment-two-column').forEach(function(el) { el.classList.add('show'); });
    document.querySelectorAll('.toggle-icon, .toggle-icon-small').forEach(function(el) { el.remove(); });
    document.querySelectorAll('.check-main[onclick], .sentiment-category-header[onclick]').forEach(function(el) {
        el.removeAttribute('onclick');
        el.style.cursor = 'default';
    });
}
