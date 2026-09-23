(function () {
    'use strict';
    // The alert page already runs this same bounded query and owns its progress UI.
    if (window.LAYER1.section === 'column_alerts') return;
    const source = document.getElementById('l1-column-alert-catalog');
    if (!source) return;
    const jobs = JSON.parse(source.textContent).flatMap(s => s.retailers.map(retailer => ({country:s.country, product:s.product, retailer})));
    const menu = document.querySelector('.sidebar-menu a[href^="/dx/layer1/column-alerts/"]');
    const link = document.getElementById('l1-column-alert-link');
    const total = document.getElementById('l1-column-alert-total');
    const breakdown = document.getElementById('l1-column-alert-breakdown');
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
    }
    function load(date, force = false) {
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
        let next = 0, completed = 0, failures = 0, abnormal = 0, review = 0;
        async function worker() {
            while (next < jobs.length && !current.signal.aborted) {
                const job = jobs[next++];
                try {
                    const data = await window.ColumnAlertCache.load(job, date, {signal:current.signal, force});
                    if (current.signal.aborted) return;
                    abnormal += data.comparisons.filter(row => row.status === 'abnormal').length;
                    review += data.comparisons.filter(row => row.status === 'review').length;
                } catch (_) {
                    if (current.signal.aborted) return;
                    failures++;
                }
                completed++;
                spinner.title = `${date} · 전체 ${jobs.length}개 대상 중 ${completed}개 조회`;
                if (breakdown) breakdown.textContent = `전체 ${jobs.length}개 대상 중 ${completed}개 조회 중`;
            }
        }
        pending = Promise.all([worker(), worker()]).then(() => {
            if (current.signal.aborted) return;
            spinner.hidden = true;
            if (failures || !jobs.length) {
                if (total) total.textContent = '조회 실패';
                if (breakdown) breakdown.textContent = '전체 건수를 확인하지 못했습니다. 눌러서 다시 확인해주세요.';
                if (menu) menu.title = `${date} · 컬럼 수집 상태 조회 실패 · 메뉴에서 다시 확인해주세요.`;
                return;
            }
            window.setSidebarIssueBadge(menu, abnormal);
            const badge = menu && menu.querySelector('.sidebar-issue-badge');
            if (badge) {
                badge.title = `${date} · 전체 국가·제품군 · 이상 컬럼 ${abnormal}건`;
                badge.setAttribute('aria-label', badge.title);
            }
            if (total) { total.textContent = (abnormal + review).toLocaleString('ko-KR'); total.classList.remove('is-loading'); }
            if (breakdown) breakdown.innerHTML = `<span class="l1-column-alert-abnormal">이상 ${abnormal.toLocaleString('ko-KR')}</span> · <span class="l1-column-alert-review">확인 필요 ${review.toLocaleString('ko-KR')}</span>`;
        });
        return pending;
    }
    window.ColumnAlertSummary = {load};
    // Statistics pages have their own date form instead of the common FilterBar.
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
