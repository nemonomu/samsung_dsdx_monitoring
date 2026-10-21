(function () {
    'use strict';
    const form = document.getElementById('cca-filters');
    if (!form) return;
    const c = window.ColumnComparison;
    const catalog = JSON.parse(document.getElementById('cca-catalog').textContent);
    const country = document.getElementById('cca-country');
    const product = document.getElementById('cca-product');
    const startDay = document.getElementById('cca-start-date');
    const endDay = document.getElementById('cca-end-date');
    const search = document.getElementById('cca-search');
    const progress = document.getElementById('cca-progress');
    const loading = document.getElementById('cca-loading');
    const progressBar = document.getElementById('cca-progress-bar');
    const progressCount = document.getElementById('cca-progress-count');
    const sidebarLink = document.querySelector('.sidebar-menu a[href="/dx/layer1/column-alerts/"]');
    const sidebarLoading = document.createElement('span');
    sidebarLoading.className = 'cca-sidebar-loading';
    sidebarLoading.setAttribute('role', 'status');
    sidebarLoading.setAttribute('aria-label', '컬럼 수집 상태 조회 중');
    sidebarLoading.title = '컬럼 수집 상태를 확인하고 있습니다.';
    sidebarLoading.hidden = true;
    if (sidebarLink) sidebarLink.appendChild(sidebarLoading);
    const comparisonDate = document.getElementById('cca-comparison-date');
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul'}).format(new Date());
    const params = new URLSearchParams(location.search);
    [...new Set(catalog.map(s => s.country))].forEach(value => country.add(new Option(value, value)));
    country.value = [...country.options].some(o => o.value === params.get('country')) ? params.get('country') : '';
    product.value = ['', 'TV', 'REF', 'LDY', 'LDY_DRYER'].includes(params.get('product')) ? params.get('product') : '';
    function validDay(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '') || value > today) return false;
        const parsed = new Date(value + 'T00:00:00Z');
        return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
    }
    // Existing dashboard links with ?date= still open a single inspection day.
    const legacyDay = validDay(params.get('date')) ? params.get('date') : today;
    startDay.max = endDay.max = today;
    startDay.value = validDay(params.get('start_date')) ? params.get('start_date') : legacyDay;
    endDay.value = validDay(params.get('end_date')) ? params.get('end_date') : startDay.value;
    function validateRange() {
        endDay.setCustomValidity(startDay.value > endDay.value ? '검수 종료일은 시작일과 같거나 이후여야 합니다.' : '');
    }
    let rows = [], status = 'alerts', page = 1, controller, finished = false;
    const pageSize = 50;
    function sidebar(state, count = 0, label = '') {
        window.setSidebarIssueBadge(sidebarLink, state === 'complete' ? count : 0);
        sidebarLoading.hidden = state !== 'loading';
        const badge = sidebarLink && sidebarLink.querySelector('.sidebar-issue-badge');
        if (badge) {
            badge.title = label;
            badge.setAttribute('aria-label', label);
        }
    }
    function render() {
        document.getElementById('cca-status-filters').innerHTML = c.tabs(rows, status, true);
        const term = search.value.trim().toLocaleLowerCase();
        const visible = rows.filter(row => c.matches(row, status) && `${row.country} ${row.product} ${row.retailer} ${row.column}`.toLocaleLowerCase().includes(term))
            .sort((a, b) => b.inspection_date.localeCompare(a.inspection_date) || c.rank(a) - c.rank(b) || (a.ratio ?? Infinity) - (b.ratio ?? Infinity) || `${a.country}${a.product}${a.retailer}${a.column}`.localeCompare(`${b.country}${b.product}${b.retailer}${b.column}`));
        const pages = Math.max(1, Math.ceil(visible.length / pageSize));
        page = Math.min(page, pages);
        const slice = visible.slice((page - 1) * pageSize, page * pageSize);
        document.getElementById('cca-body').innerHTML = slice.map(row => `<tr><th scope="row"><strong>${c.esc(row.retailer)}</strong><small>${c.esc(row.country)} · ${c.esc(row.product)} · 데이터일 ${c.esc(row.comparison_date)} · 기준 이력 ${row.history_days}일</small></th><td>${c.esc(row.inspection_date)}</td><td class="cca-column">${c.esc(row.column)}${row.status === 'uncollected' ? ` <button type="button" class="ccs-link" data-collection-sql="${rows.indexOf(row)}">조회 SQL</button>` : ''}</td><td>${c.badge(row)}</td><td>${c.number(row.baseline)}</td><td class="ccs-target ${c.esc(row.status)}"><strong>${c.number(row.current)}</strong></td><td class="ccs-verdict ${c.esc(row.status)}">${c.ratio(row)}</td><td class="ccs-verdict ${c.esc(row.status)}">${c.delta(row)}</td>${window.ColumnCheckLinks ? window.ColumnCheckLinks.cells(row, rows.indexOf(row)) : '<td colspan="2">링크 확인 중…</td>'}</tr>`).join('') || `<tr><td colspan="10">${finished ? '조회된 결과 중 해당 조건의 항목이 없습니다.' : loading.hidden ? '선택한 조건으로 조회해주세요.' : '조회 중입니다. 완료되는 순서대로 표시합니다.'}</td></tr>`;
        document.getElementById('cca-pagination').innerHTML = `<span>${c.number(visible.length)}개 항목 · ${page} / ${pages}페이지</span><button type="button" data-page="${page - 1}" ${page === 1 ? 'disabled' : ''}>이전</button><button type="button" data-page="${page + 1}" ${page === pages ? 'disabled' : ''}>다음</button>`;
    }
    function invalidate() {
        if (controller) controller.abort();
        rows = []; finished = false; page = 1;
        loading.hidden = true;
        sidebar('idle');
        comparisonDate.textContent = '';
        render();
        progress.textContent = '선택한 조건으로 조회해주세요.';
        form.querySelector('button').disabled = false;
    }
    [startDay, endDay].forEach(el => el.addEventListener('input', validateRange));
    [country, product, startDay, endDay].forEach(el => el.addEventListener('change', () => {validateRange(); invalidate();}));
    search.addEventListener('input', () => {page = 1; render();});
    document.getElementById('cca-status-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-status]');
        if (button) {status = button.dataset.status; page = 1; render();}
    });
    document.getElementById('cca-pagination').addEventListener('click', event => {
        const button = event.target.closest('[data-page]');
        if (button && !button.disabled) {page = Number(button.dataset.page); render();}
    });
    document.getElementById('cca-body').addEventListener('click', event => {
        const button = event.target.closest('[data-collection-sql]');
        if (button && window.CollectionIssues) {
            const row = rows[Number(button.dataset.collectionSql)];
            window.CollectionIssues.sql({...row, source_date: row.comparison_date});
        }
    });
    async function load(force = false) {
        validateRange();
        if (!form.reportValidity()) return;
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        rows = []; page = 1; finished = false;
        const selection = {country: country.value, product: product.value, start_date: startDay.value, end_date: endDay.value};
        const period = selection.start_date === selection.end_date ? selection.start_date : `${selection.start_date} ~ ${selection.end_date}`;
        comparisonDate.textContent = '국가별 D-1/D0 · 행의 데이터일 확인';
        history.replaceState(null, '', '?' + new URLSearchParams(selection));
        const targets = catalog.filter(s => (!selection.country || s.country === selection.country) && (!selection.product || s.product === selection.product))
            .flatMap(s => s.retailers.map(retailer => ({country: s.country, product: s.product, retailer})));
        const jobs = [];
        // Calendar iteration only: source-date/D-1 policy stays in the existing API.
        const cursor = new Date(selection.end_date + 'T00:00:00Z');
        while (cursor.toISOString().slice(0, 10) >= selection.start_date) {
            const date = cursor.toISOString().slice(0, 10);
            jobs.push(...targets.map(job => ({...job, date})));
            cursor.setUTCDate(cursor.getUTCDate() - 1);
        }
        let next = 0, completed = 0;
        const failed = [], historyFailed = [];
        form.querySelector('button').disabled = true;
        sidebar('loading');
        function update() {
            finished = completed === jobs.length;
            const abnormal = rows.filter(row => row.status === 'abnormal').length;
            const review = rows.filter(row => row.status === 'review').length;
            const missing = rows.filter(row => row.status === 'uncollected').length;
            loading.hidden = finished;
            progressBar.max = jobs.length || 1;
            progressBar.value = completed;
            progressCount.textContent = `전체 ${jobs.length}개 대상 중 ${completed}개 확인${failed.length ? ` (실패 ${failed.length}개 포함)` : ' 완료'} · ${jobs.length ? Math.round(completed / jobs.length * 100) : 0}%`;
            if (!finished) {
                progress.textContent = `검수일 ${period} · 컬럼별 수집 상태 조회 중`;
            } else if (failed.length) {
                progress.textContent = `검수일 ${period} · ${jobs.length - failed.length}개 대상 확인 · 조회 실패 ${failed.length}개 (${failed.join(', ')}) — 일부 결과입니다. 다시 조회해주세요.`;
                sidebar('incomplete');
            } else {
                progress.textContent = `검수일 ${period} · 전체 ${jobs.length}개 대상 확인 완료 · 이상 ${abnormal}건 · 확인 필요 ${review}건 · 전체 미수집 ${missing}건`;
                sidebar('complete', abnormal + missing, `${period} · 이상 컬럼 ${abnormal}건 · 전체 미수집 ${missing}건`);
            }
            if (finished && historyFailed.length) {
                progress.textContent += ` · 이력 저장 실패 ${historyFailed.length}개 (${historyFailed.join(', ')}) — 현재 조회 결과는 표시했지만 이력 보존은 서버 확인이 필요합니다.`;
            }
            render();
        }
        async function worker() {
            while (next < jobs.length && !current.signal.aborted) {
                const {date, ...job} = jobs[next++];
                try {
                    const data = await window.ColumnAlertCache.load(job, date, {signal: current.signal, force});
                    if (current.signal.aborted) return;
                    if (data.issue_history_error) historyFailed.push(`${date} ${job.country} ${job.product} ${job.retailer}`);
                    const comparisons = data.comparisons.some(row => row.status === 'uncollected')
                        ? [{column: '전체 미수집', status: 'uncollected', current: 0, baseline: null, history_days: 0, ratio: null, delta: null}]
                        : data.comparisons;
                    rows.push(...comparisons.map(row => ({...row, ...job, comparison_date: data.comparison_date, inspection_date: data.inspection_date || date})));
                } catch (error) {
                    if (current.signal.aborted) return;
                    failed.push(`${date} ${job.country} ${job.product} ${job.retailer}`);
                }
                completed++;
                update();
            }
        }
        update();
        await Promise.all([worker(), worker()]);
        if (controller === current) {
            form.querySelector('button').disabled = false;
        }
    }
    form.addEventListener('submit', event => {event.preventDefault(); load(true);});
    if (window.ColumnCheckLinks) window.ColumnCheckLinks.init(render, () => rows);
    load();
})();
