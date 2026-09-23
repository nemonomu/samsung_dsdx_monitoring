var reviewLogState = { period: 'today', page: 1, request: 0, controller: null };

function _reviewLogEscape(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _reviewLogValue(value) {
    return value === null || value === undefined || value === ''
        ? '<span class="review-log-muted">-</span>' : _reviewLogEscape(value);
}

function _reviewLogUrl(value) {
    if (!value) return _reviewLogValue(null);
    try {
        var parsed = new URL(value);
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return _reviewLogValue(value);
        return '<a href="' + _reviewLogEscape(parsed.href)
            + '" target="_blank" rel="noopener noreferrer" title="' + _reviewLogEscape(value)
            + '">상품 페이지 ↗</a>';
    } catch (_) { return _reviewLogValue(value); }
}

function _reviewLogPages(data) {
    var footer = document.getElementById('review-log-pagination');
    if (!footer) return;
    var page = data.page || 1, pages = data.pages || 1, total = data.total || 0;
    if (!total) { footer.innerHTML = ''; return; }
    var size = data.page_size || 50;
    var html = '<span>' + ((page - 1) * size + 1).toLocaleString() + '–'
        + Math.min(page * size, total).toLocaleString() + ' / ' + total.toLocaleString()
        + '건 · 50행씩</span><nav aria-label="확인 이력 페이지">';
    function button(number, label, disabled) {
        return '<button type="button" data-page="' + number + '"'
            + (disabled ? ' disabled' : '') + (number === page ? ' aria-current="page"' : '')
            + '>' + label + '</button>';
    }
    html += button(page - 1, '이전', page === 1);
    var numbers = new Set([1, pages]);
    for (var n = Math.max(1, page - 2); n <= Math.min(pages, page + 2); n++) numbers.add(n);
    var previous = 0;
    Array.from(numbers).sort(function(a, b) { return a - b; }).forEach(function(number) {
        if (previous && number > previous + 1) html += '<span>…</span>';
        html += button(number, number, false);
        previous = number;
    });
    footer.innerHTML = html + button(page + 1, '다음', page === pages) + '</nav>';
}

function _renderNullReviewLogs(data) {
    var body = document.getElementById('review-log-body');
    var heading = document.getElementById('review-log-heading');
    var policy = document.getElementById('review-log-policy');
    if (heading) heading.textContent = 'NULL 확인 이력';
    if (policy) policy.textContent = data.supports_null_auto_review
        ? '수동확인은 확인일, 자동확인은 적용일 기준입니다. 확인 근거에는 원 수동확인의 작성자와 시각을 표시합니다.'
        : '이전 정책의 자동확인은 원 확인일부터 14일 이내에 적용됩니다.';
    var logs = Array.isArray(data.logs) ? data.logs : [];
    var total = data.total === undefined ? logs.length : data.total;
    document.getElementById('review-log-count').textContent = '조회 결과 ' + total.toLocaleString()
        + '건 · 메모 ' + (data.memo_count || 0).toLocaleString() + '건';
    var retailer = document.getElementById('review-log-retailer');
    if (retailer && Array.isArray(data.retailers)) {
        var selected = retailer.value;
        var options = data.retailers.slice();
        if (selected && !options.includes(selected)) options.push(selected);
        retailer.innerHTML = '<option value="">리테일러 전체</option>' + options.map(function(value) {
            return '<option value="' + _reviewLogEscape(value) + '">' + _reviewLogEscape(value) + '</option>';
        }).join('');
        retailer.value = selected;
    }
    reviewLogState.page = data.page || 1;
    _reviewLogPages(data);
    if (!logs.length) {
        body.className = 'review-log-empty';
        body.textContent = '선택한 기간과 검색 조건에 맞는 확인 이력이 없습니다.';
        return;
    }
    var html = '<div class="review-log-scroll" tabindex="0" role="region" aria-label="NULL 확인 이력 표">'
        + '<table class="review-log-table"><thead><tr><th>No</th><th>확인·적용일</th>'
        + '<th>나라</th><th>제품군</th><th>리테일러</th><th>ITEM</th><th>SKU</th><th>ID</th>'
        + '<th>수집시간</th><th>상품명</th><th>URL</th><th>구분</th><th>문제 컬럼</th>'
        + '<th>확인 사유</th><th>메모</th><th>확인 근거</th></tr></thead><tbody>';
    logs.forEach(function(log, index) {
        html += '<tr><td>' + ((reviewLogState.page - 1) * 50 + index + 1) + '</td>'
            + '<td>' + _reviewLogValue(log.applied_date || log.crawl_date) + '</td>'
            + '<td>' + _reviewLogValue(log.country) + '</td><td>' + _reviewLogValue(log.product_line) + '</td>'
            + '<td>' + _reviewLogValue(log.retailer) + '</td><td>' + _reviewLogValue(log.item) + '</td>'
            + '<td>' + _reviewLogValue(log.sku) + '</td><td>' + _reviewLogValue(log.record_id) + '</td>'
            + '<td>' + _reviewLogValue(log.collected_at) + '</td>'
            + '<td class="review-log-product">' + _reviewLogValue(log.retailer_sku_name) + '</td>'
            + '<td>' + _reviewLogUrl(log.product_url) + '</td>'
            + '<td class="' + (log.auto_applied ? 'review-log-auto' : '') + '">'
            + _reviewLogValue(log.application_type || '수동확인') + '</td>'
            + '<td>' + _reviewLogValue(log.column_name) + '</td>'
            + '<td class="review-log-reason">' + _reviewLogValue(log.reason) + '</td>'
            + '<td class="review-log-memo">' + _reviewLogValue(log.memo) + '</td>'
            + '<td class="review-log-evidence">' + _reviewLogValue(log.created_id) + '<br>'
            + _reviewLogValue(log.original_created_at || log.created_at)
            + (log.auto_applied ? '<div class="review-log-muted">원 수동확인 근거 자동 적용</div>' : '')
            + (log.revoked_at ? '<div class="review-log-muted">자동확인 중단: '
                + _reviewLogEscape(log.revoked_at) + '</div>' : '') + '</td></tr>';
    });
    body.className = '';
    body.innerHTML = html + '</tbody></table></div>';
}

async function handleSearch(page, refresh) {
    var form = document.getElementById('review-log-filters');
    if (!form.reportValidity()) return;
    var params = new URLSearchParams(new FormData(form));
    params.set('period', reviewLogState.period);
    params.set('page', typeof page === 'number' ? page : 1);
    if (refresh) params.set('refresh', '1');
    if (reviewLogState.period === 'calendar' && params.get('start_date') > params.get('end_date')) {
        document.getElementById('review-log-feedback').textContent = '시작일은 종료일보다 늦을 수 없습니다.';
        return;
    }
    if (reviewLogState.controller) reviewLogState.controller.abort();
    reviewLogState.controller = new AbortController();
    var request = ++reviewLogState.request;
    var body = document.getElementById('review-log-body');
    document.getElementById('review-log-feedback').textContent = '';
    body.className = 'review-log-empty';
    body.textContent = '확인 이력을 조회하고 있습니다. 전체 기간은 시간이 걸릴 수 있습니다.';
    body.setAttribute('aria-busy', 'true');
    document.getElementById('review-log-pagination').innerHTML = '';
    document.getElementById('review-log-count').textContent = '조회 중…';
    try {
        var response = await fetch('/dx/layer2/api/null-review-logs/?' + params.toString(), {
            signal: reviewLogState.controller.signal
        });
        if (!response.ok) {
            var failure = await response.json().catch(function() { return {}; });
            throw new Error(failure.error || '확인 이력을 조회하지 못했습니다. 다시 조회해 주세요.');
        }
        var data = await response.json();
        if (request !== reviewLogState.request) return;
        if (data.error) throw new Error(data.error);
        _renderNullReviewLogs(data);
    } catch (error) {
        if (request !== reviewLogState.request || error.name === 'AbortError') return;
        body.textContent = error.message || '확인 이력을 조회하지 못했습니다.';
        document.getElementById('review-log-count').textContent = '-';
    } finally {
        if (request === reviewLogState.request) body.setAttribute('aria-busy', 'false');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // A fresh visit opens today, independent of other screens' saved dates.
    var today = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(new Date());
    document.querySelectorAll('#review-log-calendar input').forEach(function(input) {
        input.value = today;
        input.disabled = true;
    });
    document.querySelectorAll('[data-period]').forEach(function(button) {
        button.addEventListener('click', function() {
            reviewLogState.period = button.dataset.period;
            document.querySelectorAll('[data-period]').forEach(function(other) {
                other.setAttribute('aria-pressed', String(other === button));
            });
            var calendar = reviewLogState.period === 'calendar';
            document.getElementById('review-log-calendar').hidden = !calendar;
            document.querySelectorAll('#review-log-calendar input').forEach(function(input) {
                input.disabled = !calendar;
            });
            if (!calendar) handleSearch(1, true);
            else document.getElementById('review-log-start').focus();
        });
    });
    document.getElementById('review-log-filters').addEventListener('submit', function(event) {
        event.preventDefault();
        handleSearch(1, true);
    });
    document.querySelectorAll('#review-log-filters select, #review-log-memo-only').forEach(function(input) {
        input.addEventListener('change', function() { handleSearch(); });
    });
    document.getElementById('review-log-pagination').addEventListener('click', function(event) {
        var button = event.target.closest('button[data-page]');
        if (button && !button.disabled) handleSearch(Number(button.dataset.page));
    });
    handleSearch(1, true);
});
