(function () {
    'use strict';
    const labels = {abnormal: '이상', review: '확인 필요', normal: '정상', pending: '수집 중', uncollected: '미수집', insufficient: '비교 이력 부족', no_baseline: '기준값 0 · 비교 불가'};
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 1});
    const comparable = row => ['abnormal', 'review', 'normal'].includes(row.status);
    const badge = row => `<span class="ccs-badge ${esc(row.status)}">${esc(labels[row.status] || '비교 불가')}</span>`;
    const ratio = row => {
        if (!comparable(row)) return '—';
        const rounded = Number(row.ratio.toFixed(2));
        // A rounded 60% must not contradict a normal (>60%) verdict.
        if ((rounded === 30 || rounded === 60) && row.ratio > rounded) return rounded + '% 초과';
        return row.ratio.toLocaleString('ko-KR', {maximumFractionDigits: 2}) + '%';
    };
    const delta = row => comparable(row) ? (row.delta > 0 ? '+' : row.delta < 0 ? '−' : '') + number(Math.abs(row.delta)) + '건' : '—';
    const group = row => comparable(row) ? row.status : 'unavailable';
    const rank = row => ({abnormal: 0, review: 1, uncollected: 2, insufficient: 3, no_baseline: 4, pending: 5, normal: 6}[row.status] ?? 7);
    const detail = (data, column) => '/dx/layer1/column-statistics/?' + new URLSearchParams({country: data.country, product: data.product, retailer: data.retailer, date: data.comparison_date, days: '7', column});
    function tabs(rows, selected, alerts) {
        const choices = alerts ? [['alerts', '알림'], ['abnormal', '이상'], ['review', '확인 필요'], ['unavailable', '대기·비교 불가']] : [['all', '전체'], ['abnormal', '이상'], ['review', '확인 필요'], ['normal', '정상'], ['unavailable', '대기·비교 불가']];
        return choices.map(([value, label]) => {
            const count = rows.filter(row => matches(row, value)).length;
            return `<button type="button" class="ccs-filter ${value === selected ? 'active' : ''}" data-status="${value}" aria-pressed="${value === selected}">${label} <strong>${number(count)}</strong></button>`;
        }).join('');
    }
    function matches(row, status) {
        return status === 'all' || (status === 'alerts' ? ['abnormal', 'review'].includes(row.status) : group(row) === status);
    }
    window.ColumnComparison = {labels, esc, number, badge, ratio, delta, group, rank, detail, tabs, matches};
})();
