(function () {
    'use strict';
    const form = document.getElementById('ccs-filters');
    if (!form) return;
    const catalog = JSON.parse(document.getElementById('ccs-catalog').textContent);
    const controls = Object.fromEntries(['country', 'product', 'retailer', 'days', 'date'].map(k => [k, document.getElementById('ccs-' + k)]));
    const message = document.getElementById('ccs-message');
    const results = document.getElementById('ccs-results');
    const params = new URLSearchParams(location.search);
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul'}).format(new Date());
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const number = value => Number(value).toLocaleString('ko-KR');
    const comparison = window.ColumnComparison;
    let loadedData;
    let selectedStatus = 'all';
    let controller;
    function options(control, values, preferred) {
        control.replaceChildren(...values.map(value => new Option(value, value)));
        control.value = values.includes(preferred) ? preferred : values[0];
    }
    function retailers(preferred) {
        const source = catalog.find(s => s.country === controls.country.value && s.product === controls.product.value);
        options(controls.retailer, source ? source.retailers : [], preferred);
    }
    function products(preferredProduct, preferredRetailer) {
        options(controls.product, catalog.filter(s => s.country === controls.country.value).map(s => s.product), preferredProduct);
        retailers(preferredRetailer);
    }
    options(controls.country, [...new Set(catalog.map(s => s.country))], params.get('country') || 'SEA');
    products(params.get('product') || 'TV', params.get('retailer') || 'Amazon');
    if (['5', '7', '14', '28', '49'].includes(params.get('days'))) controls.days.value = params.get('days');
    controls.date.max = today;
    controls.date.value = /^\d{4}-\d{2}-\d{2}$/.test(params.get('date') || '') && params.get('date') <= today ? params.get('date') : today;
    controls.country.addEventListener('change', () => {products(controls.product.value, controls.retailer.value); invalidate();});
    controls.product.addEventListener('change', () => {retailers(controls.retailer.value); invalidate();});
    ['retailer', 'days', 'date'].forEach(key => controls[key].addEventListener('change', invalidate));
    function invalidate() {
        if (controller) controller.abort();
        results.hidden = true;
        message.hidden = false;
        message.className = 'cs-message';
        message.textContent = '선택한 조건으로 조회해주세요.';
        form.querySelector('button').disabled = false;
    }
    function render(data) {
        loadedData = data;
        document.getElementById('ccs-selection').textContent = `${data.country} · ${data.product} · ${data.retailer} · ${data.dates[0]} ~ ${data.dates[data.dates.length - 1]} · ${data.columns.length}개 항목`;
        document.getElementById('ccs-updated').textContent = '집계 ' + new Date(data.updated_at).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'});
        document.getElementById('ccs-status-filters').innerHTML = comparison.tabs(data.comparisons, selectedStatus, false);
        document.getElementById('ccs-head').innerHTML = '<tr><th scope="col">수집 항목</th><th scope="col">검수 판정</th><th scope="col">평소 기준<small>이전 28일 중앙값</small></th>' + data.dates.map(day => `<th scope="col" class="${day === data.comparison_date ? 'ccs-target' : ''}">${esc(day.slice(5))}<small>${day === data.comparison_date ? '비교일' : '수집 건수'}</small></th>`).join('') + '<th scope="col">기준 대비<small>현재 ÷ 기준</small></th><th scope="col">증감 건수<small>현재 − 기준</small></th></tr>';
        let html = '<tr class="ccs-total"><th scope="row">실제 수집 데이터</th><td colspan="2">전체 건수</td>' + data.daily.map(day => `<td class="${day.date === data.comparison_date ? 'ccs-target' : ''}"><span class="${day.total === 0 ? 'ccs-zero' : ''}">${number(day.total)}</span>${day.total === 0 ? '<small>수집 데이터 없음</small>' : ''}</td>`).join('') + '<td>—</td><td>—</td></tr>';
        const visible = data.comparisons.filter(row => comparison.matches(row, selectedStatus));
        html += visible.map(row => {
            const column = row.column;
            return `<tr data-column="${esc(column)}" class="${column === params.get('column') ? 'ccs-focused' : ''}"><th scope="row">${esc(column)}</th><td>${comparison.badge(row)}</td><td><strong>${comparison.number(row.baseline)}</strong><small>기준 이력 ${row.history_days}일</small></td>` + data.daily.map(day => {
                const target = day.date === data.comparison_date;
                return `<td class="${target ? 'ccs-target ' + esc(row.status) : ''}"><strong class="${day.total && day.counts[column] === 0 ? 'ccs-zero' : ''}">${day.total ? number(day.counts[column]) : '—'}</strong></td>`;
            }).join('') + `<td class="ccs-verdict ${esc(row.status)}">${comparison.ratio(row)}</td><td class="ccs-verdict ${esc(row.status)}">${comparison.delta(row)}</td></tr>`;
        }).join('');
        if (!visible.length) html += `<tr><td colspan="${data.dates.length + 5}">해당 판정의 항목이 없습니다.</td></tr>`;
        document.getElementById('ccs-body').innerHTML = html;
        document.getElementById('ccs-sku-note').hidden = !data.sku_from_master;
        results.hidden = false;
        message.hidden = true;
        const scroll = document.querySelector('.ccs-scroll');
        scroll.scrollLeft = scroll.scrollWidth;
        const focused = document.querySelector('.ccs-focused');
        if (focused) scroll.scrollTop = focused.offsetTop - 65;
    }
    document.getElementById('ccs-status-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-status]');
        if (!button || !loadedData) return;
        selectedStatus = button.dataset.status;
        render(loadedData);
    });
    async function load() {
        if (!form.reportValidity()) return;
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        const query = new URLSearchParams(Object.fromEntries(Object.entries(controls).map(([key, el]) => [key, el.value])));
        history.replaceState(null, '', '?' + query);
        results.hidden = true;
        message.hidden = false;
        message.className = 'cs-message';
        message.textContent = '컬럼별 수집 건수를 불러오는 중입니다.';
        form.querySelector('button').disabled = true;
        try {
            const response = await fetch('/dx/layer1/api/column-statistics/?' + query, {signal: current.signal});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');
            if (!current.signal.aborted) render(data);
        } catch (error) {
            if (current.signal.aborted) return;
            message.className = 'cs-message error';
            message.textContent = error.message || '조회에 실패했습니다.';
        } finally {
            if (controller === current) form.querySelector('button').disabled = false;
        }
    }
    form.addEventListener('submit', event => {event.preventDefault(); load();});
    load();
})();
