(function () {
    const expanded = new Map();
    const labels = {OK: '정상', REVIEW: '확인 필요', CRITICAL: '미수집',
        PENDING: '적재 예정', COLLECTING: '수집 대기', ERROR: '조회 실패'};
    function badge(status) {
        const styles = {OK: 'ok', REVIEW: 'warning', CRITICAL: 'critical',
            PENDING: 'pending', COLLECTING: 'collecting', ERROR: 'warning'};
        return '<span class="status-badge ' + (styles[status] || 'warning') + '">' +
            esc(labels[status] || '확인 필요') + '</span>';
    }
    function table(rows) {
        return '<div class="event-master-table"><table class="ct ct-grid"><thead><tr>' +
            '<th>국가</th><th>최근 수집일</th><th>상태</th><th>확인 사항</th></tr></thead><tbody>' +
            rows.map(row => '<tr><td>' + esc(row.country) + '<br><small>' + esc(row.country_code) +
                '</small></td><td>' + esc(row.execution_date || '—') + '</td><td>' + badge(row.status) +
                '</td><td>' + esc(row.status === 'PENDING' ? row.scheduled_date + ' 적재 예정' : (row.issues || []).join(' / ') || '—') +
                (row.issue_count ? ' · ' + Number(row.issue_count).toLocaleString() + '행' : '') + '</td></tr>').join('') +
            '</tbody></table></div>';
    }
    // Preserve native accordion state across asynchronous dashboard repainting.
    document.addEventListener('toggle', function (event) {
        const key = event.target.dataset && event.target.dataset.eventMasterKey;
        if (key && event.target.isConnected) expanded.set(key, event.target.open);
    }, true);
    function details(key, classes, summary, body) {
        return '<details class="' + classes + '" data-event-master-key="' + esc(key) + '"' +
            (expanded.get(key) ? ' open' : '') + '><summary>' + summary + '</summary>' + body + '</details>';
    }
    L1.renderers.event_master = function (check) {
        document.querySelectorAll('details[data-event-master-key]').forEach(element => {
            expanded.set(element.dataset.eventMasterKey, element.open);
        });
        const countries = check.countries || [];
        const attention = countries.filter(row => row.status !== 'OK').concat(check.unexpected || []);
        const normal = countries.filter(row => row.status === 'OK');
        const key = 'event-master-' + check.inspection_date;
        const summary = '<div class="event-master-heading"><div class="event-master-title"><span class="event-master-month">' +
            esc(String(check.execution_date).slice(0, 7).replace('-', '.')) + '</span><div><div class="check-name">Event Master</div>' +
            '<div class="check-description">월간 이벤트 · 국가별 적재 현황</div></div></div><div class="event-master-status"><div class="event-master-count">' +
            (check.actual == null ? '조회 실패' : '<strong>' + Number(check.actual) + '</strong><span> / ' + Number(check.expected) + '개국 수집</span>') +
            '</div>' + badge(check.status) + '<span class="event-master-chevron" aria-hidden="true"></span></div></div>';
        let body = '<div class="event-master-body">';
        if (check.status === 'ERROR') {
            body += '<p role="alert">' + esc(check.description) + '</p>';
        } else {
            body += '<div class="event-master-schedule"><div><span>수집 확인 기간</span><strong>' + esc(check.execution_date) + ' ~ ' + esc(check.execution_end_date) +
                '</strong></div><div><span>수집 일정</span><strong>첫 월요일 00:30 시작 · 화요일까지 확인 <small>KST</small></strong></div></div>';
            body += '<p class="event-master-note' + (check.status === 'OK' ? ' event-master-success' : '') + '">' +
                (check.status === 'PENDING' ? check.scheduled_date + ' 적재 예정입니다. 기존 수집 결과는 유지됩니다.' :
                    check.status === 'OK' ? '대상 ' + Number(check.expected) + '개국의 적재가 모두 확인되었습니다.' :
                    '수집 현황과 확인이 필요한 항목을 아래에서 확인하세요.') + '</p>';
            [['REVIEW', '확인 필요'], ['CRITICAL', '미수집'], ['COLLECTING', '수집 대기'], ['PENDING', '적재 예정']].forEach(([status, label]) => {
                const rows = attention.filter(row => row.status === status);
                if (rows.length) body += '<h4 class="event-master-section-title">' + label + ' <span>' + rows.length + '개국</span></h4>' + table(rows);
            });
            if (normal.length) body += details(key + '-normal', 'event-master-normal',
                '<span>정상 국가 <span class="event-master-total">' + normal.length + '</span></span><span class="event-master-list-action">국가 목록 <span class="event-master-chevron" aria-hidden="true"></span></span>',
                '<ul class="event-master-countries">' + normal.map(row => '<li><span class="event-master-country-code">' + esc(row.country_code) +
                    '</span><div><strong>' + esc(row.country) + '</strong><small>' + esc(row.execution_date) + ' 수집</small></div><span class="event-master-check" aria-label="정상">✓</span></li>').join('') + '</ul>');
        }
        body += '</div>';
        return '<div class="check-item">' + details(key, 'event-master', summary, body) + '</div>';
    };
})();
