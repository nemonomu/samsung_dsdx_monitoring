function fallbackCopy(text, onSuccess, onError) {
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
        if (onSuccess) onSuccess();
    } catch (err) {
        console.error('복사 실패:', err);
        if (onError) onError(err);
    }
    document.body.removeChild(textArea);
}

function copyToClipboard(element) {
    const text = element.textContent;
    function showSuccess() {
        element.style.background = '#c8e6c9';
        element.setAttribute('data-copied', 'true');
        setTimeout(() => {
            element.style.background = '#e3f2fd';
            element.removeAttribute('data-copied');
        }, 1000);
    }
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(showSuccess).catch(err => {
            console.error('복사 실패:', err);
            fallbackCopy(text, showSuccess);
        });
    } else {
        fallbackCopy(text, showSuccess);
    }
}

function formatSQL(sql) {
    if (!sql) return sql;
    let formatted = sql.replace(/\s+/g, ' ').trim();
    const keywords = ['SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'ORDER BY', 'GROUP BY', 'HAVING', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'LIMIT', 'OFFSET'];
    keywords.forEach(kw => {
        const regex = new RegExp(`\\s+(${kw})\\s+`, 'gi');
        formatted = formatted.replace(regex, `\n${kw} `);
    });
    formatted = formatted.replace(/\nAND /gi, '\n    AND ');
    formatted = formatted.replace(/\nOR /gi, '\n    OR ');
    return formatted;
}

function copyQueryToClipboard(element, preserveRaw) {
    const text = element.textContent;
    const clipboardSQL = preserveRaw === true ? text : formatSQL(text);
    function showSuccess() {
        let btn = element.previousElementSibling?.querySelector?.('.btn-copy');
        if (!btn) btn = element.previousElementSibling?.querySelector?.('.btn-copy-query');
        if (!btn && element.nextElementSibling?.classList?.contains('btn-copy-query')) {
            btn = element.nextElementSibling;
        }
        if (btn) {
            const originalText = btn.textContent;
            const originalBg = btn.style.background;
            btn.textContent = '복사됨!';
            btn.style.background = '#22c55e';
            setTimeout(() => {
                btn.textContent = originalText;
                btn.style.background = originalBg || '#3b82f6';
            }, 1500);
        }
    }
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(clipboardSQL).then(showSuccess).catch(err => {
            console.error('복사 실패:', err);
            fallbackCopy(clipboardSQL, showSuccess);
        });
    } else {
        fallbackCopy(clipboardSQL, showSuccess);
    }
}

let currentData = null;
let layer3StatsRequestId = 0;

// 기존 API/규칙 식별자는 유지하고 화면 표시명만 통일한다.
function getLayer3DisplayName(checkName, detailCode) {
    if (
        checkName === 'TV 논리적 일관성'
        || (detailCode === 'tv' && (checkName === 'TV Retail' || checkName === 'SEA Retail'))
    ) {
        return 'SEA Retail';
    }
    return checkName;
}

// product_url 렌더링 헬퍼: 아이콘(링크) + URL 텍스트(잘림)
function renderProductUrl(url) {
    var safe = safeUrl(url);
    if (!safe) return '-';
    return '<span style="display:flex;align-items:center;gap:4px;min-width:0;">'
        + '<a href="' + esc(safe) + '" target="_blank" style="flex-shrink:0;display:flex;color:#2563eb;">' + AppButton.getIcon('external') + '</a>'
        + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;color:#374151;" title="' + esc(safe) + '">' + esc(safe) + '</span></span>';
}

// ViewStack — 모달 대신 인라인 콘텐츠 교체
const ViewStack = {
    stack: [],
    getContainer() {
        return document.getElementById('categories-container') || document.getElementById('field-missing-section');
    },
    push(html, title) {
        const container = this.getContainer();
        if (!container) return;
        this.stack.push({
            html: container.innerHTML,
            scrollTop: window.scrollY,
            title: AppModal.getTitle('detail')
        });
        container.innerHTML = html;
        window.scrollTo(0, 0);
        // 하위 뷰 진입 시 category-section 배경/보더 제거 (필터바는 유지)
        if (container.classList.contains('category-section')) {
            container.style.background = 'none';
            container.style.border = 'none';
        }
    },
    pop() {
        if (this.stack.length === 0) return false;
        const state = this.stack.pop();
        const container = this.getContainer();
        if (container) {
            container.innerHTML = state.html;
            window.scrollTo(0, state.scrollTop);
        }
        // 최상위로 돌아오면 category-section 스타일 복원
        if (this.stack.length === 0) {
            if (container && container.classList.contains('category-section')) {
                container.style.background = '';
                container.style.border = '';
            }
        }
        return true;
    },
    reset(html) {
        this.stack = [];
        const container = this.getContainer();
        if (container) container.innerHTML = html;
    },
    depth() { return this.stack.length; }
};

// 카테고리별 특성 인라인 모드 판별
function isCatSpecInline() {
    return (window.LAYER3 && window.LAYER3.section) === 'category_spec';
}

// 크로스 필드 검증 인라인 모드 판별
function isCrossFieldInline() {
    return (window.LAYER3 && window.LAYER3.section) === 'cross_field';
}

// 인라인 상세 타이틀 HTML (제목 + 날짜)
function _inlineTitle(title) {
    var dateVal = getSelectedDate();
    var dateDisplay = '';
    if (dateVal) {
        var d = new Date(dateVal + 'T00:00:00');
        var weekdays = ['일', '월', '화', '수', '목', '금', '토'];
        dateDisplay = dateVal + '(' + weekdays[d.getDay()] + ')';
    }
    return '<span>' + title + '</span>' + (dateDisplay ? '<span class="inline-detail-date">' + dateDisplay + '</span>' : '');
}

// 초기화
document.addEventListener('DOMContentLoaded', function() {
    initFilterBar();
    checkBackupStatus();
    loadData();
});

function formatBackupPendingCounts(data) {
    return `SEA TV: ${Number(data.tv_count || 0).toLocaleString()}, ` +
        `SEA REF: ${Number(data.sea_ref_count || 0).toLocaleString()}, ` +
        `SEA LDY: ${Number(data.sea_ldy_count || 0).toLocaleString()}, ` +
        `TSE TV: ${Number(data.tse_tv_count || 0).toLocaleString()}, ` +
        `TSE REF: ${Number(data.tse_ref_count || 0).toLocaleString()}, ` +
        `TSE LDY: ${Number(data.tse_ldy_count || 0).toLocaleString()}`;
}

async function checkBackupStatus() {
    const date = getSelectedDate();
    if (!date) return;
    try {
        const res = await fetch(`/dx/layer1/retail/api/backup-status/?date=${encodeURIComponent(date)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success || data.pending_count === 0) return;
        const counts = formatBackupPendingCounts(data);

        if (!data.has_backup) {
            const goBackup = await showConfirm(`${date} 미백업 ${data.pending_count}건 (${counts})\n백업 후 검수를 진행해주세요.`, 'warning', { okText: 'Layer 1 이동', cancelText: '계속 조회' });
            if (goBackup) window.location.href = '/dx/layer1/';
        } else {
            const goBackup = await showConfirm(`추가 수집 데이터 ${data.pending_count}건 미백업 (${counts})\n백업 후 검수를 진행해주세요.`, 'warning', { okText: 'Layer 1 이동', cancelText: '계속 조회' });
            if (goBackup) window.location.href = '/dx/layer1/';
        }
    } catch (e) { /* 백업 상태 조회 실패 시 무시 */ }
}


// 섹션 → 카테고리명 매핑
const SECTION_CATEGORY_MAP = {
    'time_series': '시계열 이상치',
    'cross_field': '크로스 필드 검증',
    'category_spec': '카테고리별 특성'
};

function createLayer3StatsState(date) {
    return {
        timestamp: null,
        date: date,
        layer: 3,
        name: '이상치/특수 케이스 검수',
        product_line: 'ALL',
        checks: [],
        summary: {
            total_checked: 0,
            passed: 0,
            failed: 0,
            pass_rate: 0,
            status: 'OK'
        }
    };
}

function refreshLayer3Summary(data) {
    const checks = (data.checks || []).filter(function(check) {
        return !check.load_error;
    });
    const totalChecked = checks.reduce(function(sum, check) {
        return sum + Number(check.checked || 0);
    }, 0);
    const totalFailed = checks.reduce(function(sum, check) {
        return sum + Number(check.failed || 0);
    }, 0);
    const passed = totalChecked - totalFailed;
    data.summary = {
        total_checked: totalChecked,
        passed: passed,
        failed: totalFailed,
        pass_rate: totalChecked > 0 ? Math.round((passed / totalChecked) * 10000) / 100 : 0,
        status: totalFailed === 0 ? 'OK' : 'WARNING'
    };
}

function sortLayer3Checks(checks) {
    const categoryOrder = {
        '시계열 이상치': 0,
        '크로스 필드 검증': 1,
        '카테고리별 특성': 2
    };
    checks.sort(function(left, right) {
        return (categoryOrder[left.category] ?? 99) - (categoryOrder[right.category] ?? 99);
    });
}

function mergeLayer3Stats(target, source, section) {
    const category = SECTION_CATEGORY_MAP[section];
    target.checks = target.checks.filter(function(check) {
        return check.category !== category;
    });
    target.checks = target.checks.concat(source.checks || []);

    sortLayer3Checks(target.checks);
    target.timestamp = source.timestamp || target.timestamp;
    refreshLayer3Summary(target);
}

function markLayer3SectionError(target, section) {
    const category = SECTION_CATEGORY_MAP[section];
    target.checks = target.checks.filter(function(check) {
        return check.category !== category;
    });
    target.checks.push({
        category: category,
        name: '데이터 로딩 실패',
        description: '해당 검사만 응답하지 않았습니다. 다른 검사 결과는 정상적으로 표시됩니다.',
        checked: 0,
        passed: 0,
        failed: 0,
        status: 'ERROR',
        load_error: true
    });
    sortLayer3Checks(target.checks);
    refreshLayer3Summary(target);
}

// 데이터 로드
async function loadData() {
    checkBackupStatus();
    const date = getSelectedDate();
    const section = (window.LAYER3 && window.LAYER3.section) || 'dashboard';
    const requestId = ++layer3StatsRequestId;

    // 인라인 상세보기 중이면 현재 보고 있는 항목 저장 (날짜 변경 후 복원용)
    let reopenDetail = null;
    if (section === 'category_spec' && ViewStack.depth() > 0 && window.categorySpecTitle) {
        reopenDetail = window.categorySpecTitle;
    }
    ViewStack.stack = [];  // ViewStack 초기화

    const catContainer = document.getElementById('categories-container');

    // focus 파라미터 확인 (사이드바에서 직접 진입 시)
    const urlParams = new URLSearchParams(window.location.search);
    const focusParam = urlParams.get('focus');
    const detailCodeParam = urlParams.get('detail_code') || '';

    // focus가 있으면 stats 건너뛰고 바로 상세 로드
    if (focusParam) {
        // 사이드바 하위메뉴 active 동기화
        var expGroup = document.querySelector('.sidebar-group.expanded');
        if (expGroup) {
            expGroup.querySelectorAll('.sidebar-subitem').forEach(function(item) {
                const itemName = item.dataset.itemName || item.textContent.trim();
                const itemDetailCode = item.dataset.detailCode || '';
                item.classList.toggle(
                    'active',
                    itemName === focusParam
                        || (detailCodeParam && itemDetailCode === detailCodeParam)
                );
            });
        }

        if (section === 'field_missing') {
            // 필드 누락은 stats 필요 (탭 전환)
            if (catContainer) catContainer.innerHTML = '<div class="loading">데이터를 불러오는 중...</div>';
            try {
                const sectionParam = `&section=${section}`;
                const data = await fetchAPI(`/layer3/api/stats/?date=${date}&type=all${sectionParam}`);
                currentData = data;
                renderData(data);
                loadAllRetailersMissing();
                switchFieldMissingTab(detailCodeParam || focusParam.toLowerCase());
            } catch (error) {
                console.error('Error:', error);
                if (catContainer) catContainer.innerHTML = '<div class="loading">데이터 로드 실패</div>';
            }
        } else if (section === 'time_series' && SECTION_CATEGORY_MAP[section]) {
            // 시계열 이상치: 사이드메뉴에서는 페이지 내 렌더링
            loadTimeSeriesPage(date, focusParam, detailCodeParam);
        } else if (SECTION_CATEGORY_MAP[section]) {
            showDetail(SECTION_CATEGORY_MAP[section], focusParam, detailCodeParam);
        }

        // focus 파라미터 제거 (뒤로가기 시 중복 방지)
        urlParams.delete('focus');
        const cleanUrl = urlParams.toString() ? `${window.location.pathname}?${urlParams}` : window.location.pathname;
        history.replaceState(null, '', cleanUrl);
        return;
    }

    if (catContainer) {
        catContainer.innerHTML = '<div class="loading">데이터를 불러오는 중...</div>';
    }

    // 필드 누락 캐시 초기화 (조회 시 항상 새로운 데이터 로드)
    if (typeof retailerMissingCache !== 'undefined') retailerMissingCache = {};

    // 대시보드는 검사 세 개를 독립 요청한다. 시계열 쿼리 하나가
    // 느려도 크로스 필드/카테고리 결과와 필드 누락은 먼저 표시된다.
    if (section === 'dashboard') {
        loadAllRetailersMissing();
        const state = createLayer3StatsState(date);
        currentData = state;
        const sections = ['time_series', 'cross_field', 'category_spec'];

        await Promise.allSettled(sections.map(async function(statsSection) {
            try {
                const data = await fetchAPI(
                    `/layer3/api/stats/?date=${encodeURIComponent(date)}&type=all&section=${statsSection}`
                );
                if (requestId !== layer3StatsRequestId) return;
                mergeLayer3Stats(state, data, statsSection);
            } catch (error) {
                if (requestId !== layer3StatsRequestId) return;
                console.error(`Layer3 ${statsSection} Error:`, error);
                markLayer3SectionError(state, statsSection);
            }
            if (requestId === layer3StatsRequestId) {
                currentData = state;
                renderData(state);
            }
        }));
        return;
    }

    try {
        const sectionParam = `&section=${section}`;
        const data = await fetchAPI(`/layer3/api/stats/?date=${date}&type=all${sectionParam}`);
        if (requestId !== layer3StatsRequestId) return;
        currentData = data;
        renderData(data);

        // 필드 누락 데이터 로드
        if (section === 'field_missing') {
            loadAllRetailersMissing();
        }

        // 인라인 상세보기 복원 (날짜 변경 시 같은 화면 유지)
        if (reopenDetail) {
            showDetail('카테고리별 특성', reopenDetail);
        }
    } catch (error) {
        if (requestId !== layer3StatsRequestId) return;
        console.error('Error:', error);
        if (catContainer) catContainer.innerHTML = '<div class="loading">데이터 로드 실패</div>';
    }
}


// 데이터 렌더링
function renderData(data) {
    const section = (window.LAYER3 && window.LAYER3.section) || 'dashboard';
    const filterCategory = SECTION_CATEGORY_MAP[section] || null;

    // Summary 업데이트 (대시보드에서만 표시)
    if (!filterCategory) {
        const elChecked = document.getElementById('total-checked');
        const elPassed = document.getElementById('total-passed');
        const elFailed = document.getElementById('total-failed');
        const elRate = document.getElementById('pass-rate');
        if (elChecked) elChecked.textContent = (data.summary.total_checked || 0).toLocaleString();
        if (elPassed) elPassed.textContent = (data.summary.passed || 0).toLocaleString();
        if (elFailed) elFailed.textContent = (data.summary.failed || 0).toLocaleString();
        if (elRate) elRate.textContent = (data.summary.pass_rate || 0) + '%';
    }

    // 카테고리별 그룹화
    const categories = {};
    (data.checks || []).forEach(check => {
        const cat = check.category || '기타';
        // 섹션 페이지에서는 해당 카테고리만 표시
        if (filterCategory && cat !== filterCategory) return;
        if (!categories[cat]) {
            categories[cat] = [];
        }
        categories[cat].push(check);
    });

    // 카테고리 아이콘 및 색상 매핑
    const categoryConfig = {
        '시계열 이상치': { icon: '📈', class: 'time-series' },
        '크로스 필드 검증': { icon: '🔗', class: 'cross-field' },
        '카테고리별 특성': { icon: '📊', class: 'category-spec' }
    };

    // 검증 규칙이 있는 체크 항목들 (크로스 필드 검증 항목)
    const crossfieldChecksWithRules = ['TV 논리적 일관성', 'HHP 논리적 일관성', 'TV Sentiment↔리뷰 일관성', 'HHP Sentiment↔리뷰 일관성'];

    // 상태 표시 텍스트 변환
    const statusText = (status) => {
        if (status === 'REVIEW_NEEDED') return '확인 필요';
        return status;
    };

    let html = '';

    Object.entries(categories).forEach(([categoryName, checks], catIdx) => {
        const config = categoryConfig[categoryName] || { icon: '📋', class: 'time-series' };
        const totalChecked = checks.reduce((sum, c) => sum + (c.checked || 0), 0);
        const totalFailed = checks.reduce((sum, c) => sum + (c.failed || 0), 0);
        const totalReviewNeeded = checks.reduce((sum, c) => sum + (c.review_needed || 0), 0);
        const hasReviewNeeded = totalReviewNeeded > 0 || checks.some(c => c.status === 'REVIEW_NEEDED');
        const hasLoadError = checks.some(c => c.load_error || c.status === 'ERROR');
        const catStatus = hasLoadError
            ? 'critical'
            : (totalFailed > 0
                ? (totalFailed < 10 ? 'warning' : 'critical')
                : (hasReviewNeeded ? 'review_needed' : 'ok'));

        if (filterCategory) {
            // 섹션 페이지: 카테고리 헤더 없이 체크 항목만 표시
            html += `<div class="category-section"><div class="category-content" id="cat-content-${catIdx}" style="display:block;">`;
        } else {
            // 대시보드: 카테고리 헤더 + 접기/펼치기
            html += `
            <div class="category-section">
                <div class="category-header" onclick="toggleCategory(${catIdx})">
                    <div class="category-title">
                        <div class="category-icon ${config.class}">${config.icon}</div>
                        <span>${esc(categoryName)}</span>
                        <span class="toggle-icon" id="cat-toggle-${catIdx}">▶</span>
                    </div>
                    <div class="category-summary">
                        <div class="category-stat">
                            <div class="value">${totalChecked.toLocaleString()}</div>
                            <div class="label">검사</div>
                        </div>
                        <div class="category-stat">
                            <div class="value" style="color: var(--color-critical);">${totalFailed.toLocaleString()}</div>
                            <div class="label">이상치</div>
                        </div>
                        ${totalReviewNeeded > 0 ? `<div class="category-stat">
                            <div class="value review-needed-value">${totalReviewNeeded.toLocaleString()}</div>
                            <div class="label">확인 필요</div>
                        </div>` : ''}
                        <span class="status-badge ${catStatus}">${statusText(catStatus.toUpperCase())}</span>
                    </div>
                </div>
                <div class="category-content" id="cat-content-${catIdx}">
            `;
        }

        const renderCheckItem = (check, childLabel) => {
            const status = (check.status || 'OK').toLowerCase();
            const reviewNeeded = check.review_needed || 0;
            const displayName = getLayer3DisplayName(check.name, check.detail_code || '');
            const renderedDisplayName = childLabel || displayName;
            // 카테고리별 특성은 모두 검증 규칙 버튼 표시, 크로스 필드는 특정 항목만
            const hasRules = categoryName === '카테고리별 특성'
                || crossfieldChecksWithRules.includes(check.name)
                || /^SEA (REF|LDY) 논리적 일관성$/.test(check.name || '')
                || /^SIEL (TV|REF|LDY) 논리적 일관성$/.test(check.name || '')
                || /^TSE (TV|REF|LDY) 논리적 일관성$/.test(check.name || '');
            const rulesBtn = hasRules ? `<button class="btn-rules" onclick="event.stopPropagation(); showRulesModal('${escJs(check.name)}')">검증 규칙</button>` : '';

            let rowClass = check.load_error ? 'check-item' : 'check-item clickable-row';
            if (childLabel) rowClass += ' crossfield-region-child';
            const rowAction = check.load_error ? '' : `onclick="showDetail('${escJs(categoryName)}', '${escJs(check.name)}', '${escJs(check.detail_code || '')}')"`;

            return `
                <div class="${rowClass}" ${rowAction}>
                    <div class="check-info">
                        <div class="check-name">
                            ${renderCountryFlagLabel(renderedDisplayName)}
                            ${check.threshold ? `<span class="threshold-badge">${esc(String(check.threshold))}</span>` : ''}
                            ${rulesBtn}
                        </div>
                        <div class="check-description">${esc(check.description || '')}</div>
                    </div>
                    <div class="check-stats">
                        <div class="check-stat">
                            <div class="value">${(check.checked || 0).toLocaleString()}</div>
                            <div class="label">검사</div>
                        </div>
                        <div class="check-stat">
                            <div class="value" style="color: var(--color-ok);">${(check.passed || 0).toLocaleString()}</div>
                            <div class="label">정상</div>
                        </div>
                        <div class="check-stat">
                            <div class="value" style="color: var(--color-critical);">${(check.failed || 0).toLocaleString()}</div>
                            <div class="label">이상치</div>
                        </div>
                        ${reviewNeeded > 0 ? `<div class="check-stat">
                            <div class="value review-needed-value">${reviewNeeded.toLocaleString()}</div>
                            <div class="label">확인 필요</div>
                        </div>` : ''}
                        <span class="status-badge ${status}">${statusText(status.toUpperCase())}</span>
                    </div>
                </div>
            `;
        };

        if (categoryName === '크로스 필드 검증') {
            const regionGroups = { sea: [], siel: [], tse: [] };
            const standaloneChecks = [];
            checks.forEach(check => {
                const detailCode = String(check.detail_code || '').toLowerCase();
                const checkName = String(check.name || '');
                if (
                    detailCode === 'sea_ref'
                    || detailCode === 'sea_ldy'
                    || (
                        detailCode === 'tv'
                        && (checkName === 'SEA Retail' || checkName === 'TV 논리적 일관성')
                    )
                ) {
                    regionGroups.sea.push(check);
                } else if (/^siel_(tv|ref|ldy)$/.test(detailCode)) {
                    regionGroups.siel.push(check);
                } else if (/^tse_(tv|ref|ldy)$/.test(detailCode)) {
                    regionGroups.tse.push(check);
                } else {
                    standaloneChecks.push(check);
                }
            });

            [
                { key: 'sea', title: 'SEA Retail', description: 'SEA TV/REF/LDY 크로스필드 검증' },
                { key: 'siel', title: 'SIEL Retail', description: 'SIEL TV/REF/LDY 크로스필드 검증' },
                { key: 'tse', title: 'TSE Retail', description: 'TSE TV/REF/LDY 크로스필드 검증' },
            ].forEach(region => {
                const groupChecks = regionGroups[region.key];
                if (groupChecks.length === 0) return;

                const groupChecked = groupChecks.reduce((sum, check) => sum + (check.checked || 0), 0);
                const groupPassed = groupChecks.reduce((sum, check) => sum + (check.passed || 0), 0);
                const groupFailed = groupChecks.reduce((sum, check) => sum + (check.failed || 0), 0);
                const groupReviewNeeded = groupChecks.reduce((sum, check) => sum + (check.review_needed || 0), 0);
                const groupHasReview = groupReviewNeeded > 0 || groupChecks.some(check => check.status === 'REVIEW_NEEDED');
                const groupHasError = groupChecks.some(check => check.load_error || check.status === 'ERROR');
                const groupStatus = groupHasError
                    ? 'critical'
                    : (groupFailed > 0
                        ? (groupFailed < 10 ? 'warning' : 'critical')
                        : (groupHasReview ? 'review_needed' : 'ok'));
                const groupId = `crossfield-region-${catIdx}-${region.key}`;

                html += `
                    <div class="crossfield-region-group">
                        <button type="button" class="crossfield-region-header"
                                aria-expanded="false" aria-controls="${groupId}"
                                onclick="toggleCrossfieldRegion('${groupId}', this)">
                            <div class="crossfield-region-title">
                                <span class="crossfield-region-arrow">▶</span>
                                <div>
                                    <div class="crossfield-region-name">${renderCountryFlagLabel(region.title)}</div>
                                    <div class="check-description">${region.description}</div>
                                </div>
                            </div>
                            <div class="check-stats">
                                <div class="check-stat">
                                    <div class="value">${groupChecked.toLocaleString()}</div>
                                    <div class="label">검사</div>
                                </div>
                                <div class="check-stat">
                                    <div class="value" style="color: var(--color-ok);">${groupPassed.toLocaleString()}</div>
                                    <div class="label">정상</div>
                                </div>
                                <div class="check-stat">
                                    <div class="value" style="color: var(--color-critical);">${groupFailed.toLocaleString()}</div>
                                    <div class="label">이상치</div>
                                </div>
                                ${groupReviewNeeded > 0 ? `<div class="check-stat">
                                    <div class="value review-needed-value">${groupReviewNeeded.toLocaleString()}</div>
                                    <div class="label">확인 필요</div>
                                </div>` : ''}
                                <span class="status-badge ${groupStatus}">${statusText(groupStatus.toUpperCase())}</span>
                            </div>
                        </button>
                        <div class="crossfield-region-children" id="${groupId}">
                            ${groupChecks.map(check => {
                                const detailCode = String(check.detail_code || '').toLowerCase();
                                const label = detailCode === 'tv' || detailCode === 'siel_tv' || detailCode === 'tse_tv'
                                    ? 'TV'
                                    : (detailCode === 'sea_ref' || detailCode === 'siel_ref' || detailCode === 'tse_ref' ? 'REF' : 'LDY');
                                return renderCheckItem(check, label);
                            }).join('')}
                        </div>
                    </div>`;
            });

            standaloneChecks.forEach(check => {
                html += renderCheckItem(check, '');
            });
        } else {
            checks.forEach(check => {
                html += renderCheckItem(check, '');
            });
        }

        html += `
                </div>
            </div>
        `;
    });

    if (Object.keys(categories).length === 0) {
        html = '<div class="loading">해당 조건의 데이터가 없습니다.</div>';
    }

    const catContainer = document.getElementById('categories-container');
    if (catContainer) {
        catContainer.innerHTML = html;
        // 섹션 페이지에서는 카테고리를 자동 펼침
        if (filterCategory) {
            catContainer.querySelectorAll('.category-content').forEach(el => el.classList.add('show'));
            catContainer.querySelectorAll('.toggle-icon').forEach(el => el.classList.add('expanded'));
        }
    }

}

// 카테고리 토글
function toggleCategory(idx) {
    const content = document.getElementById(`cat-content-${idx}`);
    const toggle = document.getElementById(`cat-toggle-${idx}`);

    if (content.classList.contains('show')) {
        content.classList.remove('show');
        toggle.classList.remove('expanded');
    } else {
        content.classList.add('show');
        toggle.classList.add('expanded');
    }
}

// 상세 정보 표시
async function showDetail(category, checkName, detailCode) {
    const date = getSelectedDate();
    const section = (window.LAYER3 && window.LAYER3.section) || 'dashboard';

    // 시계열 섹션 페이지에서는 모달 대신 페이지 내 렌더링
    if (section === 'time_series' && category === '시계열 이상치') {
        loadTimeSeriesPage(date, checkName, detailCode);
        return;
    }

    // 사이드바 하위메뉴 active 동기화
    var expGroup = document.querySelector('.sidebar-group.expanded');
    if (expGroup) {
        expGroup.querySelectorAll('.sidebar-subitem').forEach(function(item) {
            const itemName = item.dataset.itemName || item.textContent.trim();
            const itemDetailCode = item.dataset.detailCode || '';
            item.classList.toggle(
                'active',
                itemName === checkName
                    || (detailCode && itemDetailCode === detailCode)
            );
        });
    }

    let apiUrl = '';
    let title = getLayer3DisplayName(checkName, detailCode);

    // API URL 결정
    if (category === '시계열 이상치') {
        let itemType = checkName.includes('HHP') ? 'hhp' : 'tv';
        if (detailCode) {
            apiUrl = `/layer3/api/time-series-detail/?date=${date}&detail_code=${encodeURIComponent(detailCode)}`;
        } else if (checkName.includes('리뷰')) {
            apiUrl = `/layer3/api/review-change-detail/?date=${date}&type=${itemType}`;
        } else {
            let code = '';
            if (checkName.includes('HHP') && checkName.includes('중앙값')) code = 'hhp_price_median';
            else if (checkName.includes('HHP') && checkName.includes('/mo')) code = 'hhp_price_format';
            else if (checkName.includes('TV') && checkName.includes('중앙값')) code = 'tv_price_median';
            if (code) apiUrl = `/layer3/api/time-series-detail/?date=${date}&detail_code=${code}`;
        }
    } else if (category === '크로스 필드 검증') {
        if (checkName.includes('Sentiment')) {
            // Sentiment↔리뷰 일관성 검증
            const type = checkName.includes('TV') ? 'tv' : 'hhp';
            apiUrl = `/layer3/api/sentiment-cross-detail/?date=${date}&type=${type}`;
        } else if (checkName.includes('Comp Product')) {
            // Comp Product 자사/경쟁사 구분
            apiUrl = `/layer3/api/comp-product-cross-detail/?date=${date}`;
        } else {
            // TV/HHP 논리적 일관성
            let type = 'hhp';
            if (detailCode === 'tv') type = 'tv';
            else if (detailCode === 'sea_ref' || checkName.includes('SEA REF')) type = 'sea_ref';
            else if (detailCode === 'sea_ldy' || checkName.includes('SEA LDY')) type = 'sea_ldy';
            else if (detailCode === 'siel_tv' || checkName.includes('SIEL TV')) type = 'siel_tv';
            else if (detailCode === 'siel_ref' || checkName.includes('SIEL REF')) type = 'siel_ref';
            else if (detailCode === 'siel_ldy' || checkName.includes('SIEL LDY')) type = 'siel_ldy';
            else if (detailCode === 'tse_tv' || checkName.includes('TSE TV')) type = 'tse_tv';
            else if (detailCode === 'tse_ref' || checkName.includes('TSE REF')) type = 'tse_ref';
            else if (detailCode === 'tse_ldy' || checkName.includes('TSE LDY')) type = 'tse_ldy';
            else if (checkName.includes('TV')) type = 'tv';
            apiUrl = `/layer3/api/cross-field-detail/?date=${date}&type=${type}`;
        }

        // 크로스 필드 섹션 페이지 → 인라인 표시
        if (isCrossFieldInline() && apiUrl) {
            ViewStack.push(`
                <div class="inline-detail">
                    <div class="inline-detail-body"><div class="loading">데이터를 불러오는 중...</div></div>
                </div>
            `);
            try {
                const data = await fetchAPI(apiUrl);
                renderCrossfieldSummaryContent(title, category, data);
            } catch (error) {
                console.error('Error:', error);
                const body = document.querySelector('.inline-detail-body');
                if (body) body.innerHTML = '<p>데이터 로드 실패</p>';
            }
            return;
        }
    } else if (category === '카테고리별 특성') {
        // display_name을 그대로 전달하여 동적 처리
        apiUrl = `/layer3/api/category-spec-detail/?date=${date}&display_name=${encodeURIComponent(checkName)}&mode=summary`;

        // 카테고리별 특성 섹션 페이지 → 인라인 표시
        if (isCatSpecInline()) {
            ViewStack.push(`
                <div class="inline-detail">
                    <div class="inline-detail-body"><div class="loading">데이터를 불러오는 중...</div></div>
                </div>
            `);
            try {
                const data = await fetchAPI(apiUrl);
                renderCatSpecSummaryContent(title, data);
            } catch (error) {
                console.error('Error:', error);
                const body = document.querySelector('.inline-detail-body');
                if (body) body.innerHTML = '<p>데이터 로드 실패</p>';
            }
            return;
        }
    }

    if (!apiUrl) {
        AppModal.setTitle('detail', title);
        AppModal.setBody('detail', '<p>상세 조회 API가 구현되지 않았습니다.</p>');
        AppModal.open('detail');
        return;
    }

    try {
        const data = await fetchAPI(apiUrl);
        renderDetailModal(title, category, data);
    } catch (error) {
        console.error('Error:', error);
        AppModal.setTitle('detail', title);
        AppModal.setBody('detail', '<p>데이터 로드 실패</p>');
        AppModal.open('detail');
    }
}

// 상세 모달 렌더링
function renderDetailModal(title, category, data) {
    AppModal.setTitle('detail', title + ` (${data.total_anomalies || data.anomaly_items || data.total_changes || data.total_duplicates || 0}건)`);

    let html = '';

    if (category === '시계열 이상치') {
        const items = data.items || [];
        if (items.length === 0) {
            html = '<p>이상치 데이터가 없습니다.</p>';
        } else {
            html = '<div id="ts-detail-table"></div>';
        }
    } else if (category === '크로스 필드 검증') {
        // Sentiment 검증인 경우 기존 방식 유지
        if (title.includes('Sentiment')) {
            const anomalies = data.anomalies || [];
            if (anomalies.length === 0) {
                html = '<p>논리 오류 데이터가 없습니다.</p>';
            } else {
                const hasRetailComId = anomalies.some(row => row.retail_com_id);
                html = '<div class="table-scroll-container"><table class="detail-table"><thead><tr>';
                html += '<th>No.</th>';
                if (hasRetailComId) {
                    html += '<th>ID</th>';
                }
                html += '<th>Item</th><th>Retailer</th><th>Page Type</th><th>오류 내용</th>';
                html += '</tr></thead><tbody>';

                anomalies.forEach((row, idx) => {
                    const errorHtml = (row.errors || []).map(e => `<li>${esc(e.error)}</li>`).join('');
                    html += '<tr>';
                    html += `<td>${idx + 1}</td>`;
                    if (hasRetailComId) {
                        html += `<td>${esc(String(row.retail_com_id || '-'))}</td>`;
                    }
                    html += `<td>${esc(row.item || '-')}</td>`;
                    html += `<td>${esc(row.account_name || '-')}</td>`;
                    html += `<td>${esc(row.page_type || '-')}</td>`;
                    html += `<td><ul class="error-list">${errorHtml}</ul></td>`;
                    html += '</tr>';
                });
                html += '</tbody></table></div>';
            }
        } else {
            // TV/HHP 논리적 일관성 - 공통 함수로 위임 (모달/인라인 모두 처리)
            renderCrossfieldSummaryContent(title, category, data);
            return;
        }
    } else if (category === '카테고리별 특성') {
        // 공통 함수로 위임 (모달/인라인 모두 처리)
        renderCatSpecSummaryContent(title, data);
        return;
    } else {
        html = '<p>상세 데이터를 표시할 수 없습니다.</p>';
    }

    AppModal.setBody('detail', html);
    AppModal.open('detail');

    // 시계열 이상치: CommonTable 렌더링
    if (category === '시계열 이상치' && data.items && data.items.length > 0) {
        var container = document.getElementById('ts-detail-table');
        if (container) {
            var columns = [
                { key: 'id', label: 'id', width: 80 },
                { key: 'item', label: 'Item', width: 160 },
                { key: 'account_name', label: 'Retailer', width: 100 },
                { key: 'final_sku_price', label: '가격', width: 120 },
                { key: 'crawl_datetime', label: '수집시간', width: 160 },
                { key: 'product_url', label: 'URL', width: 200 }
            ];
            var table = new CommonTable(container, {
                variant: 'detail',
                columns: columns,
                resize: true,
                vlines: true,
                showTotalCount: true
            });
            table.render();
            table.renderBody(data.items, function(row, idx) {
                var html = '<tr>';
                html += '<td>' + esc(String(row.id || '-')) + '</td>';
                html += '<td>' + esc(row.item || '-') + '</td>';
                html += '<td>' + esc(row.account_name || '-') + '</td>';
                html += '<td>' + esc(row.final_sku_price || '-') + '</td>';
                html += '<td>' + esc(row.crawl_datetime || '-') + '</td>';
                if (row.product_url) {
                    html += '<td><a href="' + esc(row.product_url) + '" target="_blank" style="color:var(--page-color);text-decoration:none;">'
                        + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
                        + esc(row.product_url) + '</a></td>';
                } else {
                    html += '<td>-</td>';
                }
                html += '</tr>';
                return html;
            });
        }
    }
}

function getCrossfieldCountLabel(data) {
    const anomalyCount = Number(data?.total_anomalies || 0);
    const reviewCount = Number(data?.total_review_needed || 0);
    if (reviewCount > 0) {
        return `이상 ${anomalyCount.toLocaleString()}건 · 확인 필요 ${reviewCount.toLocaleString()}건`;
    }
    return `${anomalyCount.toLocaleString()}건`;
}

function renderCrossfieldReviewTypes(summary) {
    const entries = Object.entries(summary || {}).filter(([, count]) => Number(count) > 0);
    if (entries.length === 0) return '';
    return `<div class="review-type-summary">${entries.map(([label, count]) => `
        <span class="review-type-chip">${esc(label)} <strong>${Number(count).toLocaleString()}건</strong></span>
    `).join('')}</div>`;
}

// 크로스필드 요약 렌더링 (모달 / 인라인 공용)
function renderCrossfieldSummaryContent(title, _category, data) {
    const inline = isCrossFieldInline();
    const ruleSummary = data.rule_summary || [];
    const isCanonicalProductLine = /^(SEA_|SIEL_|TSE_)/.test(
        String(data.product_line || '').toUpperCase()
    );

    // 현재 상태 저장 (뒤로가기용)
    window.crossfieldSummaryData = data;
    window.crossfieldTitle = title;
    window.crossfieldProductLine = data.product_line;

    const titleText = title + ` (${getCrossfieldCountLabel(data)})`;

    // 날짜 선택 UI (인라인은 상단 필터바 사용)
    let html = '';
    if (!inline) {
        html += `<div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
            <label style="font-weight: 500;">조회 날짜:</label>
            <input type="date" id="crossfield-date-picker" value="${data.date}"
                style="padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px;"
                onchange="reloadCrossfieldData(this.value, '${escJs(data.product_line)}', '${escJs(title)}')">
        </div>`;
    }

    html += '<div class="crossfield-summary-toolbar">';
    if (data.source_date && data.source_date !== data.date) {
        html += `<div class="inline-detail-subtitle">검수일 ${esc(data.date)} · 데이터일 ${esc(data.source_date)} · D-1</div>`;
    }
    html += '<button type="button" class="btn-crossfield-guide" onclick="showCrossfieldGuide()">검수 기준 안내</button>';
    html += '</div>';

    if (ruleSummary.length === 0) {
        html += '<p>논리 오류 데이터가 없습니다.</p>';
    } else {
        // 플레이스홀더 치환용 정보
        const tableName = data.table_name || '';
        const dateCol = data.date_col || '';
        const noReviewTexts = data.no_review_texts || '';
        const targetDate = data.source_date || data.date || '';

        html += '<div class="rule-summary-section">';
        if (inline) html += `<div class="rule-summary-section-header">${_inlineTitle(titleText)}</div>`;
        html += '<div class="rule-summary-container">';
        ruleSummary.forEach((rule, idx) => {
            const fieldDisplay = rule.field2 ? `${rule.field1} ↔ ${rule.field2}` : rule.field1;
            const queryId = `crossfield-query-${idx}`;
            const displayQuery = isCanonicalProductLine
                ? (rule.query || '쿼리 없음')
                : replaceCrossfieldQueryPlaceholders(
                    rule.query, tableName, dateCol, noReviewTexts, targetDate
                );
            const detailTitle = `${fieldDisplay} (${rule.error_message})`;
            const errorCount = Number(rule.error_count || 0);
            const reviewCount = Number(rule.review_count || 0);
            const countBadges = errorCount === 0 && reviewCount === 0
                ? '<span class="rule-count zero">0건</span>'
                : `${errorCount > 0 ? `<span class="rule-count">이상 ${errorCount.toLocaleString()}건</span>` : ''}
                   ${reviewCount > 0 ? `<span class="rule-count review-needed">확인 필요 ${reviewCount.toLocaleString()}건</span>` : ''}`;
            html += `
                <div class="rule-summary-card-wrapper">
                    <div class="rule-summary-card" data-rule-id="${esc(String(rule.rule_id))}" onclick="loadCrossfieldRuleDetail('${escJs(data.product_line.toLowerCase())}', '${escJs(rule.rule_id)}', '${escJs(data.date)}', '${escJs(detailTitle)}')">
                        <div class="rule-info">
                            <div class="rule-name">
                                ${esc(fieldDisplay)}
                                <button class="btn-show-query" onclick="event.stopPropagation(); toggleCrossfieldQuery('${escJs(queryId)}')" title="검증 쿼리 보기">SQL</button>
                            </div>
                            <div class="rule-desc">${esc(rule.error_message)}</div>
                            ${renderCrossfieldReviewTypes(rule.review_type_summary)}
                        </div>
                        <div class="rule-count-group">${countBadges}</div>
                    </div>
                    <div id="${queryId}" class="crossfield-query-box" style="display: none;">
                        <pre>${esc(displayQuery)}</pre>
                        <button class="btn-copy-query" onclick="copyQueryToClipboard(this.previousElementSibling, ${isCanonicalProductLine})">복사</button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        html += '</div>';
    }

    if (inline) {
        const detailEl = document.querySelector('.inline-detail');
        if (detailEl) {
            detailEl.innerHTML = html;
        }
    } else {
        AppModal.setTitle('detail', titleText);
        AppModal.setBody('detail', html);
        AppModal.open('detail');
    }
}

function toggleCrossfieldRegion(groupId, trigger) {
    const children = document.getElementById(groupId);
    if (!children || !trigger) return;
    const expanded = children.classList.toggle('show');
    trigger.setAttribute('aria-expanded', String(expanded));
    const arrow = trigger.querySelector('.crossfield-region-arrow');
    if (arrow) arrow.classList.toggle('expanded', expanded);
}

function showCrossfieldGuide() {
    const data = window.crossfieldSummaryData || {};
    const productLine = String(data.product_line || '').toUpperCase();
    if (/^(SEA_REF|SEA_LDY)$/.test(productLine)) {
        showSeaCrossfieldGuide();
        return;
    }
    showGenericCrossfieldGuide(data, window.crossfieldTitle || data.label || productLine);
}

function showGenericCrossfieldGuide(data, title) {
    const rules = Array.isArray(data.rule_summary) ? data.rule_summary : [];
    const inspectionDate = data.inspection_date || data.date || '-';
    const sourceDate = data.source_date || data.date || '-';
    const datePolicy = inspectionDate !== sourceDate ? '검수일 D → 데이터일 D-1' : '검수일 D → 데이터일 D';
    const targetName = title || data.label || data.product_line || '크로스필드';
    let ruleItems = '<li><p>등록된 검수 규칙 설명이 없습니다.</p></li>';

    if (rules.length) {
        ruleItems = rules.map(rule => {
            const fieldDisplay = rule.field2
                ? `${rule.field1 || '-'} ↔ ${rule.field2}`
                : (rule.field1 || rule.detail_code || '-');
            const ruleName = rule.detail_name || fieldDisplay;
            return `<li>
                <strong>${esc(ruleName)}</strong>
                <code>${esc(fieldDisplay)}</code>
                <p>${esc(rule.error_message || '등록된 검수 조건을 확인합니다.')}</p>
            </li>`;
        }).join('');
    }

    const html = `
        <div class="sea-crossfield-guide">
            <div class="sea-guide-scope">
                <div class="sea-guide-scope-title">현재 화면에 적용된 검수 기준</div>
                <div class="sea-guide-scope-items">
                    <span>${esc(targetName)}</span>
                    <span>${esc(datePolicy)}</span>
                    <span>현재 등록된 규칙 ${rules.length}개</span>
                    <span>새 대상도 등록 규칙을 자동 표시</span>
                </div>
            </div>
            <div class="sea-guide-grid single">
                <section class="sea-guide-card">
                    <div class="sea-guide-card-header">
                        <h3>${esc(targetName)}</h3><span>${rules.length}개</span>
                    </div>
                    <ol class="sea-guide-rule-list">${ruleItems}</ol>
                </section>
            </div>
        </div>`;
    AppModal.setTitle('crossfield-guide', `${targetName} 검수 기준 안내`);
    AppModal.setBody('crossfield-guide', html);
    AppModal.open('crossfield-guide');
}

function showSeaCrossfieldGuide() {
    const html = `
        <div class="sea-crossfield-guide">
            <div class="sea-guide-scope">
                <div class="sea-guide-scope-title">먼저 확인할 조회 범위</div>
                <div class="sea-guide-scope-items">
                    <span>SEA REF·LDY 동일 적용</span>
                    <span>검수일 D → 데이터일 D-1</span>
                    <span>리테일러별 최신 MAIN batch의 MAIN+BSR</span>
                    <span>NULL·형식 오류는 Layer2에서 확인</span>
                </div>
            </div>
            <div class="sea-guide-grid">
                <section class="sea-guide-card">
                    <div class="sea-guide-card-header">
                        <h3>Bestbuy</h3><span>7개</span>
                    </div>
                    <ol class="sea-guide-rule-list">
                        <li><strong>리뷰 수 일치</strong><code>count_of_reviews = count_of_star_ratings</code></li>
                        <li><strong>별점 0과 별점 수 0 일치</strong><p>한쪽만 0이면 이상입니다. 둘 다 0이거나 둘 다 양수이면 정상입니다.</p></li>
                        <li><strong>페이지 유형과 순위 일치</strong><p>MAIN이면 <code>main_rank</code>, BSR이면 <code>bsr_rank</code>가 있어야 합니다.</p></li>
                        <li><strong>최종가·원가 관계</strong><code>final_sku_price &gt; original_sku_price → 이상</code></li>
                        <li><strong>90% 이상 할인</strong><code>(원가-최종가)/원가 &gt;= 90% → 이상</code></li>
                        <li><strong>리뷰본문 개수</strong><p>리뷰 수가 20개 이하면 해당 수까지, 20개 이상이면 <code>review20</code>까지 있어야 합니다.</p></li>
                        <li><strong>추천 의향 형식</strong><p>리뷰가 있으면 <code>NN% would recommend to a friend</code>, 0~100% 범위여야 합니다. 리뷰가 0이면 값도 비어 있어야 합니다.</p></li>
                    </ol>
                </section>
                <section class="sea-guide-card">
                    <div class="sea-guide-card-header">
                        <h3>Lowes</h3><span>9개</span>
                    </div>
                    <ol class="sea-guide-rule-list">
                        <li><strong>리뷰 수 일치</strong><code>count_of_reviews = count_of_star_ratings</code></li>
                        <li><strong>별점 0과 별점 수 0 일치</strong><p>한쪽만 0이면 이상입니다. 둘 다 0이거나 둘 다 양수이면 정상입니다.</p></li>
                        <li><strong>최종가·원가 관계</strong><code>final_sku_price &gt;= original_sku_price → 이상</code></li>
                        <li>
                            <strong>리뷰 수·본문 확인</strong>
                            <p>사이트 특성상 이상치로 집계하지 않고 파란색 <b>확인 필요</b>로 표시합니다.</p>
                            <code>리뷰 수 있음·본문 없음 / 리뷰 수 0·본문 있음 / reviewN이 리뷰 수보다 큼 / 리뷰 수 20 이상·review20 없음</code>
                        </li>
                        <li><strong>savings 누락</strong><p>최종가와 원가가 있는데 <code>savings</code>가 없으면 이상입니다.</p></li>
                        <li><strong>원가 누락</strong><p>최종가와 <code>savings</code>가 있는데 원가가 없으면 이상입니다.</p></li>
                        <li><strong>할인 금액 일치</strong><code>original_sku_price - final_sku_price &lt;&gt; savings → 이상</code></li>
                        <li><strong>최종가 누락</strong><p>최종가가 없는데 원가 또는 <code>savings</code>가 있으면 이상입니다.</p></li>
                        <li><strong>추천 의향 형식</strong><p>리뷰가 있으면 <code>NN% Recommend this product</code>, 0~100% 범위여야 합니다. 리뷰가 0이면 값도 비어 있어야 합니다.</p></li>
                    </ol>
                </section>
            </div>
        </div>`;
    AppModal.setTitle('crossfield-guide', 'SEA REF/LDY 크로스필드 검수 기준');
    AppModal.setBody('crossfield-guide', html);
    AppModal.open('crossfield-guide');
}

// 카테고리별 특성 요약 렌더링 (모달 / 인라인 공용)
function renderCatSpecSummaryContent(title, data) {
    window.categorySpecSummaryData = data;
    window.categorySpecTitle = title;
    window.categorySpecDisplayName = title;

    const ruleSummary = data.rule_summary || [];
    const titleText = title + ` (${data.total_anomalies || 0}건)`;
    const inline = isCatSpecInline();

    // 날짜 선택기: 모달에서만 표시 (인라인은 상단 필터바 사용)
    let html = '';
    if (!inline) {
        html += `<div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
            <label style="font-weight: 500;">조회 날짜:</label>
            <input type="date" id="category-spec-date-picker" value="${data.date}"
                style="padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px;"
                onchange="reloadCategorySpecData(this.value, '${escJs(title)}', '${escJs(title)}')">
        </div>`;
    }

    if (ruleSummary.length === 0) {
        html += '<p>범위 이탈 데이터가 없습니다.</p>';
    } else {
        html += '<div class="rule-summary-section">';
        if (isCatSpecInline()) html += `<div class="rule-summary-section-header">${_inlineTitle(titleText)}</div>`;
        html += '<div class="rule-summary-container">';
        ruleSummary.forEach(rule => {
            html += `
                <div class="rule-summary-card" onclick="loadCategorySpecRuleDetail('${escJs(title)}', '${escJs(rule.rule_id)}', '${escJs(data.date)}', '${escJs(rule.detail_name)}')">
                    <div class="rule-info">
                        <div class="rule-name">${esc(rule.detail_name)}</div>
                        <div class="rule-desc">${esc(rule.error_message)}</div>
                    </div>
                    <div class="rule-count${rule.error_count === 0 ? ' zero' : ''}">${rule.error_count}건</div>
                </div>
            `;
        });
        html += '</div>';
        html += '</div>';
    }

    if (isCatSpecInline()) {
        const detailEl = document.querySelector('.inline-detail');
        if (detailEl) {
            detailEl.innerHTML = html;
        }
    } else {
        AppModal.setTitle('detail', titleText);
        AppModal.setBody('detail', html);
        AppModal.open('detail');
    }
}

// 모달 닫기
function closeModal() {
    AppModal.close('detail');
}

// 크로스필드 쿼리 플레이스홀더 치환
function replaceCrossfieldQueryPlaceholders(query, tableName, dateCol, noReviewTexts, targetDate) {
    if (!query) return '쿼리 없음';
    let result = query;
    result = result.replace(/\{table\}/g, tableName || 'table_name');
    result = result.replace(/\{date_col\}/g, dateCol || 'crawl_datetime');
    result = result.replace(/\{no_review_texts\}/g, noReviewTexts || "'No customer reviews', 'Not yet reviewed', 'No ratings yet'");
    result = result.replace(/%s/g, `'${targetDate}'`);
    return result;
}

// 크로스필드 검증 쿼리 토글
function toggleCrossfieldQuery(queryId) {
    const queryBox = document.getElementById(queryId);
    if (queryBox) {
        queryBox.style.display = queryBox.style.display === 'none' ? 'block' : 'none';
    }
}

// 크로스필드 데이터 날짜 변경 시 재로드
async function reloadCrossfieldData(date, productLine, title) {
    const inline = isCrossFieldInline();
    const bodyEl = inline ? document.querySelector('.inline-detail-body') : AppModal.getBody('detail');
    if (bodyEl) bodyEl.innerHTML = '<p style="text-align:center;">데이터를 불러오는 중...</p>';

    try {
        const data = await fetchAPI(`/layer3/api/cross-field-detail/?date=${date}&type=${productLine.toLowerCase()}`);

        if (data.error) {
            if (bodyEl) bodyEl.innerHTML = `<p style="color: red;">오류: ${esc(data.error)}</p>`;
            return;
        }

        // 공통 렌더링 (모달/인라인 모두 처리)
        renderCrossfieldSummaryContent(title, '크로스 필드 검증', data);

    } catch (error) {
        console.error('Error:', error);
        if (bodyEl) bodyEl.innerHTML = '<p style="color: red;">데이터 로드 실패</p>';
    }
}

// 크로스필드 검증 유형별 상세 데이터 로드
async function loadCrossfieldRuleDetail(productLine, ruleId, date, ruleName) {
    const inline = isCrossFieldInline();
    const historyDays = getDefaultCrossfieldHistoryDays(productLine);

    if (inline) {
        ViewStack.push(`
            <div class="inline-detail">
                <div class="inline-detail-body"><div class="loading">데이터를 불러오는 중...</div></div>
            </div>
        `);
    } else {
        AppModal.setTitle('detail', ruleName);
        AppModal.setBody('detail', '<p style="text-align:center;">데이터를 불러오는 중...</p>');
    }

    try {
        const data = await fetchAPI(`/layer3/api/cross-field-detail/?date=${date}&type=${productLine}&rule_id=${ruleId}&days=${historyDays}`);

        if (data.error) {
            const errHtml = `<p style="color: red;">오류: ${esc(data.error)}</p>`;
            if (inline) {
                const body = document.querySelector('.inline-detail-body');
                if (body) body.innerHTML = errHtml;
            } else {
                AppModal.setBody('detail', errHtml);
            }
            return;
        }

        let html = '';

        // 뒤로가기 버튼 (모달에서만, 인라인은 상위 컨테이너에 있음)
        if (!inline) {
            html += `<button class="btn-back" onclick="backToCrossfieldSummary()">← 뒤로가기</button>`;
        }

        const anomalies = data.anomalies || [];
        const retailerSummary = data.retailer_summary || {};
        if (anomalies.length === 0) {
            html += '<p>해당 검증 유형에 대한 이상 또는 확인 필요 데이터가 없습니다.</p>';
        } else {
            // 리테일러별 rows 그룹핑 (건수 계산은 백엔드 retailer_summary 사용)
            const retailerData = {};
            anomalies.forEach(row => {
                const retailer = row.account_name || 'Unknown';
                if (!retailerData[retailer]) {
                    retailerData[retailer] = { rows: [] };
                }
                retailerData[retailer].rows.push(row);
            });

            // 전역에 저장 (리테일러 클릭 시 사용)
            window.crossfieldRetailerData = retailerData;
            window.crossfieldRetailerSummary = retailerSummary;
            window.crossfieldAnomalies = anomalies;
            window.crossfieldProductLine = productLine;
            window.crossfieldDate = date;
            window.crossfieldSourceDate = data.source_date || date;
            window.crossfieldOffsetDays = Number(data.offset_days || 0);
            window.crossfieldRuleName = ruleName;
            window.crossfieldRuleId = ruleId;
            window.crossfieldSelectFields = data.select_fields || '';
            window.crossfieldValidationType = data.validation_type || '';
            window.crossfieldTableName = data.table_name || '';
            window.crossfieldDateCol = data.date_col || 'crawl_datetime';
            window.crossfieldEditableCols = new Set(data.editable_columns || []);
            window.crossfieldNormalReviews = data.normal_reviews || {};
            window.crossfieldRetailerColumns = data.retailer_columns || {};
            window.crossfieldDisplayQuery = data.query || '';
            window.crossfieldDisplayQueries = data.queries || {};
            window.crossfieldDays = data.days || historyDays;
            window.crossfieldPendingEdits = {};

            // 건수는 백엔드 계산값 사용
            const titleText = `${ruleName} (${getCrossfieldCountLabel(data)})`;

            // 리테일러 목록 (rule-summary-card 스타일)
            html += '<div class="rule-summary-section">';
            if (inline) html += `<div class="rule-summary-section-header">${_inlineTitle(titleText)}</div>`;
            html += '<div class="rule-summary-container">';
            Object.keys(retailerSummary).sort().forEach(retailer => {
                const info = retailerSummary[retailer];
                const anomalyCount = Number(info.count || 0);
                const reviewCount = Number(info.review_count || 0);
                if (anomalyCount === 0 && reviewCount === 0) return;
                const retailerCounts = `${anomalyCount > 0 ? `<span class="rule-count">이상 ${anomalyCount.toLocaleString()}건</span>` : ''}
                    ${reviewCount > 0 ? `<span class="rule-count review-needed">확인 필요 ${reviewCount.toLocaleString()}건</span>` : ''}`;
                html += `
                    <div class="rule-summary-card" data-retailer="${esc(retailer)}" onclick="showRetailerDetail('${escJs(retailer)}')">
                        <div class="rule-info">
                            <div class="rule-name">${esc(retailer)}</div>
                            <div class="rule-desc">${info.items.length} items</div>
                            ${renderCrossfieldReviewTypes(info.review_type_summary)}
                        </div>
                        <div class="rule-count-group">${retailerCounts}</div>
                    </div>
                `;
            });
            html += '</div>';
            html += '</div>';
        }
        if (inline) {
            const detailEl = document.querySelector('.inline-detail');
            if (detailEl) {
                detailEl.innerHTML = `<button class="btn-back" onclick="ViewStack.pop()">← 뒤로가기</button>` + html;
            }
        } else {
            AppModal.setTitle('detail', ruleName + ' (' + getCrossfieldCountLabel(data) + ')');
            AppModal.setBody('detail', html);
        }

    } catch (error) {
        console.error('Error:', error);
        const errHtml = '<p style="color: red;">데이터 로드 실패</p>';
        if (inline) {
            const detailEl = document.querySelector('.inline-detail');
            if (detailEl) detailEl.innerHTML = errHtml;
        } else {
            AppModal.setBody('detail', errHtml);
        }
    }
}

// HTTP 환경용 폴백 복사 함수
function _showReviewDialog(checkType, callback) {
    fetch('/dx/layer3/api/review-reasons/?check_type=' + encodeURIComponent(checkType))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var reasons = (data.reasons || []).map(function(r) { return typeof r === 'object' ? r.text : r; });
            var overlay = document.createElement('div');
            overlay.className = 'memo-dialog-overlay';
            var reasonOpts = '<option value="">-- 선택 --</option>';
            reasons.forEach(function(r) { reasonOpts += '<option value="' + esc(r) + '">' + esc(r) + '</option>'; });
            var hideReason = reasons.length === 0;
            var memoRequired = checkType === 'cross_field'
                && /^SIEL_/.test(String(window.crossfieldProductLine || '').toUpperCase());
            overlay.innerHTML = '<div class="memo-dialog">'
                + '<div class="memo-dialog-title">확인</div>'
                + '<div class="memo-dialog-field"' + (hideReason ? ' style="display:none"' : '') + '><label class="memo-dialog-label">이유 <span style="color:#dc2626;">*</span></label>'
                + '<select class="memo-dialog-select" id="review-reason-select">' + reasonOpts + '</select></div>'
                + '<div class="memo-dialog-field"><label class="memo-dialog-label">메모' + (memoRequired ? ' <span style="color:#dc2626;">*</span>' : '') + '</label>'
                + '<textarea class="memo-dialog-input" id="review-memo" placeholder="' + (memoRequired ? '확인 메모 입력 (필수)' : '메모 입력 (선택사항)') + '" rows="3"></textarea></div>'
                + '<div class="memo-dialog-buttons">'
                + '<button class="memo-dialog-cancel">취소</button>'
                + '<button class="memo-dialog-confirm">확인</button>'
                + '</div></div>';
            document.body.appendChild(overlay);
            requestAnimationFrame(function() { overlay.classList.add('show'); });

            function closeDlg() {
                overlay.classList.remove('show');
                setTimeout(function() { overlay.remove(); }, 200);
            }
            overlay.querySelector('.memo-dialog-cancel').onclick = closeDlg;
            overlay.querySelector('.memo-dialog-confirm').onclick = function() {
                var reason = hideReason ? '' : document.getElementById('review-reason-select').value;
                var memo = document.getElementById('review-memo').value.trim();
                if (!hideReason && !reason) { showToast('이유를 선택해주세요', 'warning'); return; }
                if (memoRequired && !memo) { showToast('SIEL 확인 메모를 입력해주세요', 'warning'); return; }
                closeDlg();
                callback(reason, memo);
            };
            overlay.addEventListener('click', function(e) {
                if (e.target === overlay) closeDlg();
            });
        })
        .catch(function() {
            showToast('이유 목록 로딩 실패', 'error');
        });
}

async function showRulesModal(checkName) {
    AppModal.setTitle('detail', getLayer3DisplayName(checkName, '') + ' - 검증 규칙');
    AppModal.setBody('detail', '<p style="text-align:center;">로딩 중...</p>');
    AppModal.open('detail');

    // 크로스필드 규칙 체크 (Sentiment, 논리적 일관성)
    const crossfieldChecks = ['TV 논리적 일관성', 'HHP 논리적 일관성', 'TV Sentiment↔리뷰 일관성', 'HHP Sentiment↔리뷰 일관성'];
    const isSeaCrossfield = /^SEA (REF|LDY) 논리적 일관성$/.test(checkName || '');
    const isSielCrossfield = /^SIEL (TV|REF|LDY) 논리적 일관성$/.test(checkName || '');
    const isTseCrossfield = /^TSE (TV|REF|LDY) 논리적 일관성$/.test(checkName || '');
    const isCrossfield = crossfieldChecks.includes(checkName) || isSeaCrossfield || isSielCrossfield || isTseCrossfield;

    // checkName에서 category 추출
    let category = 'all';
    let apiUrl = '';

    if (isCrossfield) {
        // 크로스필드 규칙
        if (checkName.includes('SEA REF')) {
            category = 'sea_ref_retail';
        } else if (checkName.includes('SEA LDY')) {
            category = 'sea_ldy_retail';
        } else if (checkName.includes('SIEL TV')) {
            category = 'siel_tv_retail';
        } else if (checkName.includes('SIEL REF')) {
            category = 'siel_ref_retail';
        } else if (checkName.includes('SIEL LDY')) {
            category = 'siel_ldy_retail';
        } else if (checkName.includes('TSE TV')) {
            category = 'tse_tv_retail';
        } else if (checkName.includes('TSE REF')) {
            category = 'tse_ref_retail';
        } else if (checkName.includes('TSE LDY')) {
            category = 'tse_ldy_retail';
        } else if (checkName.includes('TV') && checkName.includes('Sentiment')) {
            category = 'tv_sentiment';
        } else if (checkName.includes('HHP') && checkName.includes('Sentiment')) {
            category = 'hhp_sentiment';
        } else if (checkName.includes('TV')) {
            category = 'tv_retail';
        } else if (checkName.includes('HHP')) {
            category = 'hhp_retail';
        }
        apiUrl = `/layer3/api/crossfield-rules/?section=${category}`;
    } else {
        // 카테고리별 특성 규칙 (display_name으로 매핑)
        // 먼저 category-rules API에서 모든 규칙을 가져와서 display_name으로 매칭
        apiUrl = `/layer3/api/category-rules/?display_name=${encodeURIComponent(checkName)}`;
    }

    // isCategorySpec 변수 (렌더링용)
    const isCategorySpec = !isCrossfield;

    try {
        const data = await fetchAPI(apiUrl);

        if (data.status === 'success' && data.rules.length > 0) {
            let html = '<ul class="rules-list">';
            data.rules.forEach((rule, idx) => {
                const retailerInfo = rule.retailer && rule.retailer !== 'all' ? ` (${rule.retailer})` : '';
                const thresholdInfo = rule.threshold ? ` [${rule.threshold}]` : '';

                if (isCategorySpec) {
                    // 카테고리별 특성 규칙 표시 - detail_name 사용
                    html += `
                        <li>
                            <div class="rule-number">${idx + 1}</div>
                            <div class="rule-content">
                                <div class="rule-title">${esc(rule.detail_name)}${esc(retailerInfo)}</div>
                                <div class="rule-desc">${esc(rule.error_message)}</div>
                                <div class="rule-example">${esc(rule.error_message)}${thresholdInfo ? ' / 범위: ' + esc(String(rule.threshold)) : ''}</div>
                            </div>
                        </li>
                    `;
                } else {
                    // 크로스필드 규칙 표시
                    html += `
                        <li>
                            <div class="rule-number">${idx + 1}</div>
                            <div class="rule-content">
                                <div class="rule-title">${esc(rule.field1)}${rule.field2 ? ' ↔ ' + esc(rule.field2) : ''}${esc(retailerInfo)}</div>
                                <div class="rule-desc">${esc(rule.error_message)}</div>
                            </div>
                        </li>
                    `;
                }
            });
            html += '</ul>';
            AppModal.setBody('detail', html);
        } else {
            // API 실패 시 기존 하드코딩 데이터 사용 (fallback)
            const rules = getValidationRules(checkName);
            let html = '<ul class="rules-list">';
            rules.forEach((rule, idx) => {
                html += `
                    <li>
                        <div class="rule-number">${idx + 1}</div>
                        <div class="rule-content">
                            <div class="rule-title">${esc(rule.title)}</div>
                            <div class="rule-desc">${esc(rule.description)}</div>
                            ${rule.example ? `<div class="rule-example">${esc(rule.example)}</div>` : ''}
                        </div>
                    </li>
                `;
            });
            html += '</ul>';
            AppModal.setBody('detail', html);
        }
    } catch (error) {
        console.error('Failed to fetch rules:', error);
        // 에러 시 기존 하드코딩 데이터 사용 (fallback)
        const rules = getValidationRules(checkName);
        let html = '<ul class="rules-list">';
        rules.forEach((rule, idx) => {
            html += `
                <li>
                    <div class="rule-number">${idx + 1}</div>
                    <div class="rule-content">
                        <div class="rule-title">${rule.title}</div>
                        <div class="rule-desc">${rule.description}</div>
                        ${rule.example ? `<div class="rule-example">${rule.example}</div>` : ''}
                    </div>
                </li>
            `;
        });
        html += '</ul>';
        AppModal.setBody('detail', html);
    }
}

function getCsrfToken() {
    const name = 'csrftoken';
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// 시계열 이상치: 사이드메뉴 페이지 렌더링

// 사이드메뉴 서브아이템 클릭
function onSubitemClick(parentSection, checkName, detailCode) {
    var date = getSelectedDate();
    var params = [];
    if (date) params.push('date=' + date);
    if (checkName) params.push('focus=' + encodeURIComponent(checkName));
    if (detailCode) params.push('detail_code=' + encodeURIComponent(detailCode));
    var qs = params.length > 0 ? '?' + params.join('&') : '';

    var sectionUrls = {
        time_series: 'time-series',
        cross_field: 'cross-field',
        category_spec: 'category-spec',
        field_missing: 'field-missing'
    };
    var path = sectionUrls[parentSection] || '';
    window.location.href = '/dx/layer3/' + path + '/' + qs;
}

// 검증 규칙 정적 데이터 (showRulesModal fallback)
function getValidationRules(checkName) {
    const rulesData = {
        'TV 논리적 일관성': [
            {
                title: 'star_rating ↔ count_of_star_ratings 일관성',
                description: 'star_rating(별점)이 존재하는데 count_of_star_ratings(리뷰 수)가 NULL 또는 0인 경우 오류로 판정합니다.',
                example: '오류: star_rating=4.5, count_of_star_ratings=NULL'
            },
            {
                title: 'page_type ↔ 순위 필드 일관성',
                description: 'page_type에 따라 해당 순위 필드가 존재해야 합니다. main→main_rank, bsr→bsr_rank, promotion→promotion_position',
                example: '오류: page_type=main, main_rank=NULL / page_type=bsr, bsr_rank=NULL'
            },
            {
                title: 'promotion_position ↔ promotion_type 일관성 (Bestbuy)',
                description: 'promotion_position이 있는데 promotion_type이 NULL인 경우 오류로 판정합니다. 프로모션 페이지에 노출된 상품은 promotion_type이 있어야 합니다.',
                example: '오류: promotion_position=1, promotion_type=NULL'
            },
            {
                title: 'final_sku_price ↔ original_sku_price 비교',
                description: '할인 가격이 원래 가격보다 높은 경우 오류입니다. 월 할부 가격($X/month)은 제외합니다.',
                example: '오류: final=$1,299, original=$999'
            },
            {
                title: '할인율 90% 이상 검증',
                description: '두 가격 필드 간 할인율이 90% 이상인 경우 비정상적인 가격 관계로 판정합니다.',
                example: '오류: final=$99, original=$999 (90% 할인)'
            },
            {
                title: 'count_of_reviews ↔ detailed_review_content 일관성',
                description: '리테일러별 형식으로 검증합니다. Amazon: "N-" 형식, Bestbuy: "|" 구분자 개수, Walmart: "reviewN" 형식',
                example: 'Amazon: 5- / Bestbuy: 구분자 19개=리뷰 20개 / Walmart: review5'
            }
        ],
        'HHP 논리적 일관성': [
            {
                title: 'star_rating ↔ count_of_star_ratings 일관성',
                description: 'star_rating(별점)이 존재하는데 count_of_star_ratings(리뷰 수)가 NULL 또는 0인 경우 오류로 판정합니다.',
                example: '오류: star_rating=4.5, count_of_star_ratings=NULL'
            },
            {
                title: 'page_type ↔ 순위 필드 일관성',
                description: 'page_type에 따라 해당 순위 필드가 존재해야 합니다. main→main_rank, bsr→bsr_rank, trend→trend_rank(Bestbuy)',
                example: '오류: page_type=main, main_rank=NULL / page_type=trend, trend_rank=NULL'
            },
            {
                title: 'promotion_position ↔ promotion_type 일관성 (Bestbuy)',
                description: 'promotion_position이 있는데 promotion_type이 NULL인 경우 오류로 판정합니다. 프로모션 페이지에 노출된 상품은 promotion_type이 있어야 합니다.',
                example: '오류: promotion_position=1, promotion_type=NULL'
            },
            {
                title: 'final_sku_price ↔ original_sku_price 비교',
                description: '할인 가격이 원래 가격보다 높은 경우 오류입니다. 월 할부 가격($X/month)은 제외합니다.',
                example: '오류: final=$1,299, original=$999'
            },
            {
                title: '할인율 90% 이상 검증',
                description: '두 가격 필드 간 할인율이 90% 이상인 경우 비정상적인 가격 관계로 판정합니다.',
                example: '오류: final=$99, original=$999 (90% 할인)'
            },
            {
                title: 'count_of_reviews ↔ detailed_review_content 일관성',
                description: 'HHP는 "reviewN" 형식으로 검증합니다. 리뷰 20개 이상이면 review20, 5개면 review5가 있어야 합니다.',
                example: '오류: count_of_reviews=5, review5=없음 / count_of_reviews=452, review20=없음'
            }
        ]
    };

    return rulesData[checkName] || [];
}
