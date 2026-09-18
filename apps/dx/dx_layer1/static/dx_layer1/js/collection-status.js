var ddayCollectionRequestId = 0;

async function loadDdayCollection(selectedDate) {
    const requestId = ++ddayCollectionRequestId;
    const container = document.getElementById('dday-collection-list');
    const dateLabel = document.getElementById('dday-collection-date');
    if (!container) return;
    dateLabel.textContent = '수집 대상일: ' + selectedDate + ' · 시각은 한국시간(KST)';
    container.innerHTML = '<div class="check-item">수집 현황을 불러오는 중...</div>';
    try {
        const response = await fetch('/dx/layer1/api/collection-status/?date=' + encodeURIComponent(selectedDate));
        if (!response.ok) throw new Error('collection status unavailable');
        const data = await response.json();
        if (requestId !== ddayCollectionRequestId) return;
        const labels = { scheduled: '수집 예정', waiting: '수집 대기', received: '수집 확인', error: '조회 실패' };
        container.innerHTML = data.retailers.map(function(row) {
            const scheduled = String(row.scheduled_at || '').slice(0, 16).replace('T', ' ');
            const color = row.status === 'received' ? '#059669' : '#64748b';
            return '<div class="check-item"><div class="check-main">' +
                '<div class="check-info"><div class="check-name">SEA ' + esc(row.retailer) + ' ' + esc(row.product) + '</div>' +
                '<div class="check-description">수집 예정: ' + esc(scheduled) + ' KST</div>' +
                '<div class="check-description">마지막 수집: ' + esc(row.last_collected_at || '-') +
                (row.last_collected_at ? ' KST' : '') + '</div></div>' +
                '<div class="check-stats"><span>' + (row.count === null ? '-' : Number(row.count).toLocaleString() + '건') +
                '</span><span style="color:' + color + ';margin-left:16px;">' + esc(labels[row.status] || '조회 실패') +
                '</span></div></div></div>';
        }).join('');
    } catch (error) {
        if (requestId !== ddayCollectionRequestId) return;
        container.innerHTML = '<div class="check-item">수집 현황 조회 실패 · 다시 조회해 주세요.</div>';
    }
}
