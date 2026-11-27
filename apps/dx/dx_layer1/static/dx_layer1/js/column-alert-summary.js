(function () {
    'use strict';
    // The alert page already runs this same bounded query and owns its progress UI.
    if (window.LAYER1.section === 'column_alerts') return;
    const source = document.getElementById('l1-column-alert-catalog');
    if (!source) return;
    const jobs = JSON.parse(source.textContent).flatMap(s => s.retailers.map(retailer => ({country:s.country, product:s.product, retailer})));
    const countries = new Map();
    if (window.LAYER1.section === 'dashboard') {
        for (const job of jobs) {
            if (!countries.has(job.country)) countries.set(job.country, []);
            countries.get(job.country).push(job);
        }
    }
    const tasks = countries.size ? [...countries.values()].sort((a, b) => b.length - a.length)
        : jobs.map(job => [job]);
    const scopeKey = ({product, retailer}) => JSON.stringify([product, retailer]);
    const menu = document.querySelector('.sidebar-menu a[href^="/dx/layer1/column-alerts/"]');
    const link = document.getElementById('l1-column-alert-link');
    const total = document.getElementById('l1-column-alert-total');
    const breakdown = document.getElementById('l1-column-alert-breakdown');
    const historyNotice = document.getElementById('l1-column-alert-history');
    const historyDetail = document.getElementById('l1-column-alert-history-detail');
    const spinner = document.createElement('span');
    spinner.className = 'l1-column-alert-spinner';
    spinner.setAttribute('role', 'status');
    spinner.setAttribute('aria-label', '컬럼 수집 상태 조회 중');
    spinner.hidden = true;
    if (menu) menu.appendChild(spinner);
    let controller, selectedDate, pending;
    const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Seoul'}).format(new Date());

    function clear() {
        window.setSidebarIssueBadge(menu, 0);
        if (total) { total.textContent = '조회 중'; total.classList.add('is-loading'); }
        if (breakdown) breakdown.textContent = '이상·확인 필요 항목을 확인하고 있습니다.';
        if (historyNotice) historyNotice.hidden = true;
        if (historyDetail) historyDetail.textContent = '';
    }
    function load(date, force = false, refresh = false) {
        if (window.CollectionIssues) window.CollectionIssues.load({date});
        if (!force && selectedDate === date) return pending;
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        selectedDate = date;
        clear();
        const href = '/dx/layer1/column-alerts/?' + new URLSearchParams({date});
        if (menu) { menu.href = href; menu.title = `${date} 기준 · 전체 국가·제품군의 컬럼 수집 상태`; }
        if (link) { link.href = href; link.removeAttribute('aria-disabled'); }
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date > today()) {
            spinner.hidden = true;
            if (total) total.textContent = '조회 대기';
            if (breakdown) breakdown.textContent = '오늘까지의 데이터만 조회할 수 있습니다.';
            if (link) { link.removeAttribute('href'); link.setAttribute('aria-disabled', 'true'); }
            return Promise.resolve();
        }
        spinner.hidden = false;
        let next = 0, completed = 0, failures = 0, abnormal = 0, review = 0, missing = 0;
        const historyFailures = [];
        function consume(job, data) {
            if (!data || data.error || !Array.isArray(data.comparisons)) {
                failures++;
            } else {
                if (data.issue_history_error) {
                    const diagnostic = data.issue_history_diagnostic || {};
                    historyFailures.push(`${job.country} · ${job.product} · ${job.retailer}: ${diagnostic.error || '이력 저장 오류'} ${diagnostic.action || '다시 조회해 주세요.'}`);
                }
                abnormal += data.comparisons.filter(row => row.status === 'abnormal' && !row.review?.active).length;
                review += data.comparisons.filter(row => row.status === 'review' && !row.review?.active).length;
                missing += data.comparisons.some(row => row.status === 'uncollected') ? 1 : 0;
            }
            completed++;
        }
        async function readCountry(country) {
            const query = new URLSearchParams({country, date, dashboard:'1'});
            if (refresh) query.set('refresh', '1');
            const response = await fetch('/dx/layer1/api/column-statistics/overview/?' + query,
                {signal:current.signal, cache:'no-store'});
            if (!response.ok) throw new Error('Column overview unavailable');
            const data = await response.json();
            if (data.country !== country || data.inspection_date !== date || !Array.isArray(data.rows)) {
                throw new Error('Unexpected column overview');
            }
            return new Map(data.rows.map(row => [scopeKey(row), row]));
        }
        async function worker() {
            while (next < tasks.length && !current.signal.aborted) {
                const batch = tasks[next++];
                const job = batch[0];
                try {
                    if (countries.size) {
                        const rows = await readCountry(job.country);
                        if (current.signal.aborted) return;
                        batch.forEach(scope => consume(scope, rows.get(scopeKey(scope))));
                    } else {
                        const data = await window.ColumnAlertCache.load(job, date, {signal:current.signal, force, refresh});
                        if (current.signal.aborted) return;
                        consume(job, data);
                    }
                } catch (_) {
                    if (current.signal.aborted) return;
                    failures += batch.length;
                    completed += batch.length;
                }
                spinner.title = `${date} · 전체 ${jobs.length}개 대상 중 ${completed}개 조회`;
                if (breakdown) breakdown.textContent = `전체 ${jobs.length}개 대상 중 ${completed}개 조회 중`;
            }
        }
        pending = Promise.all([worker(), worker()]).then(() => {
            if (current.signal.aborted) return;
            if (window.CollectionIssues) window.CollectionIssues.load({date}, true);
            spinner.hidden = true;
            if (historyFailures.length && historyNotice && historyDetail) {
                historyNotice.hidden = false;
                historyDetail.textContent = `${historyFailures.length}개 대상 · 조회된 통계는 표시됩니다. ${historyFailures.join(' / ')}`;
            }
            if (failures || !jobs.length) {
                if (total) { total.textContent = '일부 조회 실패'; }
                if (breakdown) breakdown.textContent = `${jobs.length - failures}/${jobs.length}개 대상 조회 완료 · 조회된 이상 ${abnormal}건 · 확인 필요 ${review}건 · 전체 미수집 ${missing}건. 전체 건수는 아직 확정할 수 없습니다.`;
                if (menu) menu.title = `${date} · 컬럼 수집 상태 조회 실패 · 메뉴에서 다시 확인해주세요.`;
                return;
            }
            window.setSidebarIssueBadge(menu, abnormal + missing);
            const badge = menu && menu.querySelector('.sidebar-issue-badge');
            if (badge) {
                badge.title = `${date} · 전체 국가·제품군 · 이상 컬럼 ${abnormal}건 · 전체 미수집 ${missing}건`;
                badge.setAttribute('aria-label', badge.title);
            }
            if (total) { total.textContent = (abnormal + review + missing).toLocaleString('ko-KR'); total.classList.remove('is-loading'); }
            if (breakdown) breakdown.innerHTML = `<span class="l1-column-alert-abnormal">이상 ${abnormal.toLocaleString('ko-KR')}</span><span class="l1-column-alert-review">확인 필요 ${review.toLocaleString('ko-KR')}</span><span>전체 미수집 ${missing}</span>`;
        });
        return pending;
    }
    window.ColumnAlertSummary = {load};
    // Statistics pages have their own date form instead of the common FilterBar.
    document.addEventListener('column-review-saved', () => {if (selectedDate) load(selectedDate, true);});
    document.addEventListener('DOMContentLoaded', () => {
        for (const prefix of ['cs', 'ccs']) {
            const form = document.getElementById(prefix + '-filters');
            const date = document.getElementById(prefix + '-date');
            if (!form || !date) continue;
            load(date.value || today());
            form.addEventListener('submit', () => { if (form.reportValidity()) load(date.value, true); });
        }
    });
})();
