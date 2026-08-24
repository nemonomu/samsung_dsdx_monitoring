function _reviewLogEscape(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _reviewLogValue(value) {
    if (value === null || value === undefined || value === '') {
        return '<span class="review-log-muted">-</span>';
    }
    return _reviewLogEscape(value);
}

function _renderNullReviewLogs(data) {
    var body = document.getElementById('review-log-body');
    var count = document.getElementById('review-log-count');
    var logs = Array.isArray(data.logs) ? data.logs : [];
    count.textContent = logs.length.toLocaleString() + '건';

    if (!logs.length) {
        body.className = 'review-log-empty';
        body.textContent = data.date + ' 처리 이력이 없습니다.';
        return;
    }

    var html = '<div class="review-log-scroll"><table class="review-log-table"><thead><tr>'
        + '<th>검수일</th><th>처리 시각</th><th>처리자</th><th>제품군</th>'
        + '<th>리테일러</th><th>item</th><th>retailer_sku_name</th><th>NULL 컬럼</th>'
        + '<th>처리 사유</th><th>메모</th><th>후속 처리</th>'
        + '</tr></thead><tbody>';
    logs.forEach(function(log) {
        html += '<tr>'
            + '<td>' + _reviewLogValue(log.crawl_date) + '</td>'
            + '<td>' + _reviewLogValue(log.created_at) + '</td>'
            + '<td>' + _reviewLogValue(log.created_id) + '</td>'
            + '<td>' + _reviewLogValue(log.product_line) + '</td>'
            + '<td>' + _reviewLogValue(log.retailer) + '</td>'
            + '<td>' + _reviewLogValue(log.item) + '</td>'
            + '<td>' + _reviewLogValue(log.retailer_sku_name) + '</td>'
            + '<td>' + _reviewLogValue(log.column_name) + '</td>'
            + '<td class="review-log-reason">' + _reviewLogValue(log.reason) + '</td>'
            + '<td>' + _reviewLogValue(log.memo) + '</td>'
            + '<td>' + _reviewLogValue(log.handling) + '</td>'
            + '</tr>';
    });
    body.className = '';
    body.innerHTML = html + '</tbody></table></div>';
}

function handleSearch() {
    var date = getSelectedDate();
    var body = document.getElementById('review-log-body');
    body.className = 'review-log-empty';
    body.textContent = '데이터 로딩 중...';
    fetch('/dx/layer2/api/null-review-logs/?date=' + encodeURIComponent(date))
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.error) throw new Error(data.error);
            _renderNullReviewLogs(data);
        })
        .catch(function(error) {
            body.className = 'review-log-empty';
            body.textContent = error.message || '로그 조회에 실패했습니다.';
            showToast(body.textContent, 'error');
        });
}

document.addEventListener('DOMContentLoaded', function() {
    initFilterBar();
    handleSearch();
});
