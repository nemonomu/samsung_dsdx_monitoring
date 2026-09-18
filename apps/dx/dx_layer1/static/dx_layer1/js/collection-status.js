var ddayCollectionRequestId = 0;

function ddayStatusBadge(status) {
    const styles = {
        scheduled: ['pending', '수집 예정'], waiting: ['collecting', '수집 대기'],
        received: ['ok', '수집 확인'], partial: ['collecting', '일부 수집'],
        error: ['warning', '조회 실패']
    };
    const entry = styles[status] || styles.error;
    return '<span class="status-badge ' + entry[0] + '">' + entry[1] + '</span>';
}

function ddaySummary(rows) {
    const count = rows.reduce((total, row) => total + (Number(row.count) || 0), 0);
    const mainCount = rows.reduce((total, row) => total + (Number(row.main_count) || 0), 0);
    const bsrCount = rows.reduce((total, row) => total + (Number(row.bsr_count) || 0), 0);
    const status = rows.some(row => row.status === 'error') ? 'error'
        : rows.every(row => row.status === 'received') ? 'received'
        : rows.some(row => row.status === 'received') ? 'partial'
        : rows.every(row => row.status === 'scheduled') ? 'scheduled' : 'waiting';
    return { count, mainCount, bsrCount, status };
}

function renderDdayCollection(data) {
    const overall = ddaySummary(data.retailers);
    const categories = ['TV', 'REF', 'LDY'].map(function(product) {
        const rows = data.retailers.filter(row => row.product === product);
        if (!rows.length) return '';
        const summary = ddaySummary(rows);
        const body = rows.map(function(row) {
            const scheduled = String(row.scheduled_at || '').slice(0, 16).replace('T', ' ');
            const batch = row.batch_id ? ' <span class="dday-batch">/ ' + esc(row.batch_id) + '</span>' : '';
            return '<tr aria-label="SEA ' + esc(row.retailer) + ' ' + product + '">' +
                '<td class="rt-name">' + esc(row.retailer) + batch + '</td>' +
                '<td>' + (row.main_count == null ? '-' : Number(row.main_count).toLocaleString()) + '</td>' +
                '<td>' + (row.bsr_count == null ? '-' : Number(row.bsr_count).toLocaleString()) + '</td>' +
                '<td>' + esc(scheduled) + ' KST</td>' +
                '<td>' + esc(row.last_collected_at || '-') + (row.last_collected_at ? ' KST' : '') + '</td>' +
                '<td class="rt-total">' + (row.count === null ? '-' : Number(row.count).toLocaleString()) + '</td>' +
                '<td class="rt-status ct-nc">' + ddayStatusBadge(row.status) + '</td></tr>';
        }).join('');
        return '<details class="sentiment-category-item" open>' +
            '<summary class="sentiment-category-header"><div class="sentiment-category-info">' +
            '<span class="toggle-icon-small">▶</span><span class="sentiment-category-name">' + product + '</span>' +
            '<span class="dday-date">수집 대상일 ' + esc(data.source_date) + ' · D-DAY</span></div>' +
            '<div class="sentiment-category-stats"><span class="sentiment-category-count">' + summary.count.toLocaleString() +
            '건</span>' + ddayStatusBadge(summary.status) + '</div></summary>' +
            '<div class="sentiment-two-column retail-single-column show"><div class="sentiment-column">' +
            '<div class="sentiment-column-header"><span class="sentiment-column-title">일일</span>' +
            '<div class="sentiment-column-stats"><span class="sentiment-column-count">' + summary.count.toLocaleString() +
            '건</span>' + ddayStatusBadge(summary.status) + '</div></div>' +
            '<div class="retail-rank-wrap"><table class="ct ct-grid"><colgroup>' +
            '<col style="width:20%"><col style="width:8%"><col style="width:8%"><col style="width:21%"><col style="width:21%"><col style="width:10%"><col style="width:12%">' +
            '</colgroup><thead><tr><th style="text-align:left">리테일러</th><th>MAIN</th><th>BSR</th><th>수집 예정 시각</th>' +
            '<th>마지막 수집 시각</th><th>총 건수</th><th>수집 상태</th></tr></thead><tbody>' + body +
            '<tr class="rt-sum"><td>' + (summary.status === 'error' ? '확인된 합계' : '합계') +
            '</td><td>' + summary.mainCount.toLocaleString() + '</td><td>' + summary.bsrCount.toLocaleString() +
            '</td><td></td><td></td><td>' + summary.count.toLocaleString() + '</td><td></td></tr>' +
            '</tbody></table></div></div></div></details>';
    }).join('');
    return '<details class="check-item" open><summary class="check-main retail-check-main">' +
        '<div class="check-info"><div class="check-name"><span class="toggle-icon">▶</span> 🇺🇸 SEA Retail</div>' +
        '<div class="check-description" id="dday-collection-date">수집 대상일: ' + esc(data.source_date) +
        ' · 한국시간(KST) 기준</div></div><div class="check-stats"><div class="check-stat">' +
        '<div class="value">' + overall.count.toLocaleString() + '</div><div class="label">' +
        (overall.status === 'error' ? '확인된 수집량' : '총 수집량') + '</div></div>' +
        ddayStatusBadge(overall.status) + '</div></summary>' +
        '<div class="time-slots-container show"><div class="dday-notice">D-1 검수와 별도인 당일 수집 여부 안내입니다.</div>' +
        '<div class="sentiment-categories">' + categories + '</div></div></details>';
}

async function loadDdayCollection(selectedDate) {
    const requestId = ++ddayCollectionRequestId;
    const container = document.getElementById('dday-collection-list');
    if (!container) return;
    container.innerHTML = '<div class="check-item"><div class="check-main">수집 현황을 불러오는 중...</div></div>';
    try {
        const response = await fetch('/dx/layer1/api/collection-status/?date=' + encodeURIComponent(selectedDate));
        if (!response.ok) throw new Error('collection status unavailable');
        const data = await response.json();
        if (requestId !== ddayCollectionRequestId) return;
        container.innerHTML = renderDdayCollection(data);
    } catch (error) {
        if (requestId !== ddayCollectionRequestId) return;
        container.innerHTML = '<div class="check-item"><div class="check-main">수집 현황 조회 실패 · 다시 조회해 주세요.</div></div>';
    }
}
