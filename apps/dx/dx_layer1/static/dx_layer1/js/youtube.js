// ============================================================
// YouTube Render Functions
// ============================================================
function getYoutubeCardStyle(status) {
    const styles = {
        'OK': { border: '#4CAF50', bg: '#f0fff0', left: '#4CAF50' },
        'WARNING': { border: '#FF9800', bg: '#fff8e1', left: '#FF9800' },
        'CRITICAL': { border: '#f44336', bg: '#ffebee', left: '#f44336' },
        'PENDING': { border: '#9e9e9e', bg: '#f5f5f5', left: '#9e9e9e' },
        'COLLECTING': { border: '#2196F3', bg: '#e3f2fd', left: '#2196F3' }
    };
    return styles[status] || styles['PENDING'];
}

function renderYoutubeStatCard(catName, typeKey, typeLabel, typeDataType, value, status, extraInfo) {
    const statusClass = getStatusClass(status);
    let statsHtml = '';

    if (extraInfo) {
        // 로그: count/expected, rate%, 상태배지
        statsHtml = '<span class="sentiment-retailer-count">' + extraInfo.count + '/' + extraInfo.expected + '</span>' +
            '<span class="sentiment-retailer-rate ' + statusClass + '">' + extraInfo.rate + '%</span>' +
            getStatusBadge(status);
    } else {
        // 비디오/댓글: 숫자, 상태배지
        statsHtml = '<span class="sentiment-retailer-count">' + (value || 0).toLocaleString() + '</span>' +
            getStatusBadge(status);
    }

    var detailUrl = '/dx/layer1/youtube/?category=' + encodeURIComponent(catName) +
        '&data_type=' + encodeURIComponent(typeDataType) +
        '&date=' + getSelectedDate();

    return '<a class="sentiment-retailer-item ' + statusClass + '" ' +
        'href="' + detailUrl + '" ' +
        'style="cursor: pointer; text-decoration: none; color: inherit;" ' +
        'title="클릭하여 ' + catName + ' ' + typeLabel + ' 데이터 보기">' +
        '<span class="sentiment-retailer-name">' + typeLabel + '</span>' +
        '<div class="sentiment-retailer-stats">' +
            statsHtml +
        '</div>' +
    '</a>';
}

function getYoutubeItemStatus(type, value, logStatus) {
    if (type === 'log') {
        return logStatus;
    } else if (type === 'video') {
        return value >= 30 ? 'OK' : 'CRITICAL';
    } else if (type === 'comment') {
        return value >= 1000 ? 'OK' : 'CRITICAL';
    }
    return 'PENDING';
}

function renderYoutubeColumn(cat) {
    // 각 항목별 상태 계산
    const logStatus = cat.status;
    const videoStatus = getYoutubeItemStatus('video', cat.video_count, logStatus);
    const commentStatus = getYoutubeItemStatus('comment', cat.comment_count, logStatus);

    // 전체 상태: 로그, 비디오, 댓글 모두 정상이면 정상
    const allOk = logStatus === 'OK' && videoStatus === 'OK' && commentStatus === 'OK';
    const overallStatus = allOk ? 'OK' : 'CRITICAL';
    const overallStatusClass = getStatusClass(overallStatus);

    // 로그는 상태 표시 포함
    const logExtraInfo = {
        count: cat.log_count.toLocaleString(),
        expected: (cat.expected || 0).toLocaleString(),
        rate: cat.rate || 0
    };

    const retailersHtml =
        renderYoutubeStatCard(cat.name, 'log_count', '로그', 'logs', cat.log_count, logStatus, logExtraInfo) +
        renderYoutubeStatCard(cat.name, 'video_count', '비디오', 'videos', cat.video_count, videoStatus, null) +
        renderYoutubeStatCard(cat.name, 'comment_count', '댓글', 'comments', cat.comment_count, commentStatus, null);

    return '<div class="sentiment-column">' +
        '<div class="sentiment-column-header">' +
            '<span class="sentiment-column-title">' + cat.name + '</span>' +
            '<div class="sentiment-column-stats">' +
                getStatusBadge(overallStatus) +
            '</div>' +
        '</div>' +
        '<div class="sentiment-retailer-list">' +
            retailersHtml +
        '</div>' +
    '</div>';
}

function renderYouTubeCheck(check, checkIdx) {
    const hasCategories = check.categories && check.categories.length > 0;
    const statusClass = getStatusClass(check.status);

    const rateDisplay = (check.rate || 0) + '%';
    const isDst = check.is_dst || false;
    const kstLabel = isDst ? 'KST(DST)' : 'KST';

    // US(NY) 시간과 KST 날짜+시간 형식: US(NY) 04:00 KST 2026-01-05 18:00
    const usTime = check.us_time ? check.us_time.split(' ')[1] : '04:00';
    const krTime = check.kr_time || '';

    const timeHeader = '<div class="time-slot-item" style="margin-bottom: 16px;">' +
        '<div class="time-slot-header" style="cursor: default;">' +
            '<div class="time-slot-info">' +
                '<span class="time-slot-name">수집 시간</span>' +
                '<span class="time-slot-time">' +
                    '<span class="utc">US(NY) ' + usTime + '</span>' +
                    '<span class="kst">' + kstLabel + ' ' + krTime + '</span>' +
                '</span>' +
            '</div>' +
        '</div>' +
    '</div>';

    let categoriesHtml = '';
    if (hasCategories) {
        const sortedCategories = L1.sortCategories(check.categories, 'name');

        const columnsContent = '<div class="sentiment-two-column show no-side-padding">' +
            sortedCategories.map(function(cat) {
                return renderYoutubeColumn(cat);
            }).join('') +
        '</div>';

        categoriesHtml = '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            timeHeader +
            columnsContent +
        '</div>';
    } else {
        // 카테고리가 없을 때도 동일한 형식으로 기본 구조 표시
        const defaultCategories = ['HHP'];
        const defaultColumnsHtml = defaultCategories.map(function(catName) {
            return '<div class="sentiment-column">' +
                '<div class="sentiment-column-header">' +
                    '<span class="sentiment-column-title">' + catName + '</span>' +
                    '<div class="sentiment-column-stats">' +
                        '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                    '</div>' +
                '</div>' +
                '<div class="sentiment-retailer-list">' +
                    '<div class="sentiment-retailer-item pending">' +
                        '<span class="sentiment-retailer-name">로그</span>' +
                        '<div class="sentiment-retailer-stats">' +
                            '<span class="sentiment-retailer-count">0/0</span>' +
                            '<span class="sentiment-retailer-rate pending">0%</span>' +
                            '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="sentiment-retailer-item pending">' +
                        '<span class="sentiment-retailer-name">비디오</span>' +
                        '<div class="sentiment-retailer-stats">' +
                            '<span class="sentiment-retailer-count">0</span>' +
                            '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="sentiment-retailer-item pending">' +
                        '<span class="sentiment-retailer-name">댓글</span>' +
                        '<div class="sentiment-retailer-stats">' +
                            '<span class="sentiment-retailer-count">0</span>' +
                            '<span class="status-badge pending"><span class="status-dot"></span>대기중</span>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }).join('');

        categoriesHtml = '<div class="time-slots-container" id="time-slots-' + checkIdx + '">' +
            timeHeader +
            '<div class="sentiment-two-column show no-side-padding">' +
                defaultColumnsHtml +
            '</div>' +
        '</div>';
    }

    return '<div class="check-item">' +
        '<div class="check-main" onclick="toggleTimeSlots(this, ' + checkIdx + ')">' +
            '<div class="check-info">' +
                '<div class="check-name">' +
                    '<span class="toggle-icon">▶</span>' +
                    check.name +
                '</div>' +
                '<div class="check-description">' + check.description + '</div>' +
            '</div>' +
            '<div class="check-criteria">' +
                '<span class="criteria-item ok">정상: 100%+</span>' +
                '<span class="criteria-item critical">심각: 100% 미만</span>' +
            '</div>' +
            '<div class="check-stats">' +
                '<div class="check-stat">' +
                    '<div class="value ' + statusClass + '">' + rateDisplay + '</div>' +
                    '<div class="label">수집률</div>' +
                '</div>' +
                getStatusBadge(check.status) +
            '</div>' +
        '</div>' +
        categoriesHtml +
    '</div>';
}

// ============================================================
// Raw Data View
// ============================================================

var rawView = new RawDataView({
    apiUrl: '/dx/layer1/youtube/api/raw-data/',
    backUrl: '/dx/layer1/youtube/',
    title: function(p) {
        var typeLabel = {'logs': '로그', 'videos': '비디오', 'comments': '댓글'}[p.data_type] || '로그';
        return 'YouTube - ' + p.category + ' - ' + typeLabel;
    },
    urlParams: ['category', 'data_type'],
    extraControls: function(params) {
        return [{
            type: 'select',
            key: 'dataType',
            label: '데이터 유형',
            width: 'auto',
            default: params.data_type || 'logs',
            options: [
                { value: 'logs', label: '수집 로그' },
                { value: 'videos', label: '비디오' },
                { value: 'comments', label: '댓글' }
            ],
            onChange: function(val) {
                rawView.params.data_type = val;
                document.getElementById('raw-data-title').textContent = rawView.titleFn(rawView.params);
                rawView.load();
            }
        }];
    }
});

// ============================================================
// Section Data Loading
// ============================================================
async function loadSectionData() {
    if (rawView.checkUrlAndShow()) return;

    try {
        var selectedDate = getSelectedDate();
        try { currentCheckStatus = await loadCheckStatus(selectedDate); }
        catch (e) { currentCheckStatus = null; }

        var response = await fetch('/dx/layer1/api/stats/?date=' + selectedDate + '&check_type=youtube');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        var data = await response.json();
        currentStatsData = data;

        var check = data.checks ? data.checks.find(function(c) { return c.check_type === 'youtube'; }) : null;
        var checkIdx = check ? data.checks.indexOf(check) : 0;
        if (!check) check = { name: 'Consumer (YouTube)', description: '데이터 없음', check_type: 'youtube', status: 'PENDING', categories: [], rate: 0 };

        var container = document.getElementById('section-content');
        var html = renderYouTubeCheck(check, checkIdx);
        html = html.replace('<div class="check-item">', '<div class="check-item" data-check-type="youtube">');
        container.innerHTML = html;
        addCheckBadges();
        expandSectionContent();
    } catch (error) {
        console.error('Load failed:', error);
        L1.renderError('section-content', error.message);
    }
}

function loadAllData() { loadSectionData(); }

L1.initLayer1Page();

L1.renderers.youtube = renderYouTubeCheck;
