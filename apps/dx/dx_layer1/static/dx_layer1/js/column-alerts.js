(function () {
    'use strict';
    const form = document.getElementById('cca-filters');
    if (!form) return;
    const c = window.ColumnComparison;
    const catalog = JSON.parse(document.getElementById('cca-catalog').textContent);
    const country = document.getElementById('cca-country');
    const product = document.getElementById('cca-product');
    const day = document.getElementById('cca-date');
    const search = document.getElementById('cca-search');
    const progress = document.getElementById('cca-progress');
    const comparisonDate = document.getElementById('cca-comparison-date');
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul'}).format(new Date());
    const params = new URLSearchParams(location.search);
    [...new Set(catalog.map(s => s.country))].forEach(value => country.add(new Option(value, value)));
    country.value = [...country.options].some(o => o.value === params.get('country')) ? params.get('country') : '';
    product.value = ['', 'TV', 'REF', 'LDY'].includes(params.get('product')) ? params.get('product') : '';
    day.max = today;
    day.value = /^\d{4}-\d{2}-\d{2}$/.test(params.get('date') || '') && params.get('date') <= today ? params.get('date') : today;
    let rows = [], status = 'alerts', page = 1, controller, finished = false;
    const pageSize = 50;
    function render() {
        document.getElementById('cca-status-filters').innerHTML = c.tabs(rows, status, true);
        const term = search.value.trim().toLocaleLowerCase();
        const visible = rows.filter(row => c.matches(row, status) && `${row.country} ${row.product} ${row.retailer} ${row.column}`.toLocaleLowerCase().includes(term))
            .sort((a, b) => c.rank(a) - c.rank(b) || (a.ratio ?? Infinity) - (b.ratio ?? Infinity) || `${a.country}${a.product}${a.retailer}${a.column}`.localeCompare(`${b.country}${b.product}${b.retailer}${b.column}`));
        const pages = Math.max(1, Math.ceil(visible.length / pageSize));
        page = Math.min(page, pages);
        const slice = visible.slice((page - 1) * pageSize, page * pageSize);
        document.getElementById('cca-body').innerHTML = slice.map(row => `<tr><th scope="row"><strong>${c.esc(row.retailer)}</strong><small>${c.esc(row.country)} · ${c.esc(row.product)} · 기준 이력 ${row.history_days}일</small></th><td class="cca-column">${c.esc(row.column)}</td><td>${c.badge(row)}</td><td>${c.number(row.baseline)}</td><td class="ccs-target ${c.esc(row.status)}"><strong>${c.number(row.current)}</strong></td><td class="ccs-verdict ${c.esc(row.status)}">${c.ratio(row)}</td><td class="ccs-verdict ${c.esc(row.status)}">${c.delta(row)}</td><td><a class="ccs-link" href="${c.esc(c.detail(row, row.column))}">보기</a></td></tr>`).join('') || `<tr><td colspan="8">${finished ? '조회된 결과 중 해당 조건의 항목이 없습니다.' : '조회 중입니다. 완료되는 순서대로 표시합니다.'}</td></tr>`;
        document.getElementById('cca-pagination').innerHTML = `<span>${c.number(visible.length)}개 항목 · ${page} / ${pages}페이지</span><button type="button" data-page="${page - 1}" ${page === 1 ? 'disabled' : ''}>이전</button><button type="button" data-page="${page + 1}" ${page === pages ? 'disabled' : ''}>다음</button>`;
    }
    function invalidate() {
        if (controller) controller.abort();
        rows = []; finished = false; page = 1;
        comparisonDate.textContent = '';
        render();
        progress.textContent = '선택한 조건으로 조회해주세요.';
        form.querySelector('button').disabled = false;
    }
    [country, product, day].forEach(el => el.addEventListener('change', invalidate));
    search.addEventListener('input', () => {page = 1; render();});
    document.getElementById('cca-status-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-status]');
        if (button) {status = button.dataset.status; page = 1; render();}
    });
    document.getElementById('cca-pagination').addEventListener('click', event => {
        const button = event.target.closest('[data-page]');
        if (button && !button.disabled) {page = Number(button.dataset.page); render();}
    });
    async function load() {
        if (!form.reportValidity()) return;
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        rows = []; page = 1; finished = false;
        const selection = {country: country.value, product: product.value, date: day.value};
        comparisonDate.textContent = selection.date;
        history.replaceState(null, '', '?' + new URLSearchParams(selection));
        const jobs = catalog.filter(s => (!selection.country || s.country === selection.country) && (!selection.product || s.product === selection.product))
            .flatMap(s => s.retailers.map(retailer => ({country: s.country, product: s.product, retailer})));
        let next = 0, completed = 0;
        const failed = [];
        form.querySelector('button').disabled = true;
        function update() {
            finished = completed === jobs.length;
            progress.textContent = `${selection.date} · ${completed} / ${jobs.length}개 조합 조회${finished ? ' 완료' : ' 중'}${failed.length ? ` · 조회 실패 ${failed.length}개 (${failed.join(', ')}) — 다시 조회해주세요.` : ''}${finished && !failed.length ? ' · 이상 → 확인 필요 순서' : ''}`;
            render();
        }
        async function worker() {
            while (next < jobs.length && !current.signal.aborted) {
                const job = jobs[next++];
                try {
                    const query = new URLSearchParams({...job, date: selection.date, days: '5'});
                    const response = await fetch('/dx/layer1/api/column-statistics/?' + query, {signal: current.signal});
                    if (!response.ok) throw new Error('Query failed');
                    const data = await response.json();
                    if (current.signal.aborted) return;
                    rows.push(...data.comparisons.map(row => ({...row, ...job, comparison_date: data.comparison_date})));
                } catch (error) {
                    if (current.signal.aborted) return;
                    failed.push(`${job.country} ${job.product} ${job.retailer}`);
                }
                completed++;
                update();
            }
        }
        update();
        await Promise.all([worker(), worker()]);
        if (controller === current) form.querySelector('button').disabled = false;
    }
    form.addEventListener('submit', event => {event.preventDefault(); load();});
    load();
})();
