(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const safe = value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 1});
    const countries = ['SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE'];
    const products = ['TV', 'REF', 'LDY'];
    let data = null, controller = null, requestId = 0;

    function shiftDate(value, days) {
        const date = new Date(value + 'T00:00:00Z');
        date.setUTCDate(date.getUTCDate() + days);
        return date.toISOString().slice(0, 10);
    }

    function weeksNeeded(endDate, days) {
        const weekday = (new Date(endDate + 'T00:00:00Z').getUTCDay() + 6) % 7;
        return Math.ceil((days + 6 - weekday) / 7);
    }

    function setMessage(message, error = false) {
        byId('cs-message').hidden = false;
        byId('cs-message').className = error ? 'cs-message error' : 'cs-message';
        byId('cs-message').textContent = message;
    }

    function selectedDates(endDate, count) {
        return Array.from({length: count}, (_, index) => shiftDate(endDate, index - count + 1));
    }

    function matches(row) {
        return (byId('cs-country').value === 'ALL' || row.country === byId('cs-country').value)
            && (byId('cs-product').value === 'ALL' || row.product === byId('cs-product').value)
            && (!byId('cs-retailer').value || row.retailer === byId('cs-retailer').value);
    }

    function selectedGroups(dates) {
        const groups = new Map();
        for (const week of data.weeks) for (const row of week.rows) {
            if (!matches(row)) continue;
            const key = JSON.stringify([row.country, row.product, row.retailer]);
            if (!groups.has(key)) groups.set(key, {
                country: row.country, product: row.product, retailer: row.retailer, daily: new Map(),
            });
            const group = groups.get(key);
            for (const day of row.daily) {
                if (day.date < dates[0] || day.date > dates.at(-1)) continue;
                if (!group.daily.has(day.date)) group.daily.set(day.date, []);
                group.daily.get(day.date).push(day);
            }
        }
        return [...groups.values()].sort((a, b) =>
            countries.indexOf(a.country) - countries.indexOf(b.country)
            || products.indexOf(a.product) - products.indexOf(b.product)
            || a.retailer.localeCompare(b.retailer));
    }

    function dayResult(entries) {
        if (!entries.length) return {total: null, label: '미집계'};
        const active = entries.filter(day => day.state !== 'not_scheduled');
        if (!active.length) return {total: null, label: '수집 시작 전'};
        if (active.some(day => day.state === 'error')) return {total: null, label: '갱신 실패', kind: 'low'};
        if (active.some(day => day.state === 'pending')) return {total: null, label: '수집 중'};
        if (active.every(day => day.state === 'unknown')) return {total: null, label: '미집계'};
        if (active.some(day => day.state === 'unknown')) return {total: null, label: '부분 집계'};
        if (active.some(day => day.state === 'future')) return {total: null, label: '예정'};
        const sum = metric => {
            const values = active.map(day => day[metric]).filter(value => value != null);
            return values.length ? values.reduce((total, value) => total + value, 0) : null;
        };
        const total = sum('total'), main = sum('main'), bsr = sum('bsr');
        if (total === 0) return {total, main, bsr, label: '미수집', kind: 'low'};
        const alerts = active.flatMap(day => day.alerts || []);
        const low = alerts.some(alert => alert.status === 'VOLUME_LOW');
        const high = alerts.some(alert => alert.status === 'VOLUME_HIGH');
        if (low) return {total, main, bsr, label: '이상', kind: 'low'};
        if (high) return {total, main, bsr, label: '확인 필요', kind: 'high'};
        return {total, main, bsr, label: active.every(day => day.comparison_state === 'ready') ? '' : '비교 이력 부족'};
    }

    function syncRetailers(preferred = byId('cs-retailer').value) {
        if (!data) return;
        const country = byId('cs-country').value, product = byId('cs-product').value;
        const retailers = [...new Set(data.weeks.flatMap(week => week.rows)
            .filter(row => (country === 'ALL' || row.country === country)
                && (product === 'ALL' || row.product === product))
            .map(row => row.retailer))].sort();
        const select = byId('cs-retailer');
        select.innerHTML = '<option value="">전체</option>'
            + retailers.map(retailer => `<option value="${safe(retailer)}">${safe(retailer)}</option>`).join('');
        select.value = retailers.includes(preferred) ? preferred : '';
    }

    function render() {
        if (!data) return;
        const endDate = byId('cs-date').value, dates = selectedDates(endDate, Number(byId('cs-days').value));
        const groups = selectedGroups(dates);
        byId('cs-selection').textContent = [
            byId('cs-country').value === 'ALL' ? '전체 국가' : byId('cs-country').value,
            byId('cs-product').value === 'ALL' ? '전체 제품군' : byId('cs-product').value,
            byId('cs-retailer').value || '전체 리테일러',
            `${dates[0]} ~ ${endDate} · ${groups.length}개 조합`,
        ].join(' · ');
        byId('cs-table-head').innerHTML = '<tr><th scope="col" rowspan="2">리테일러</th><th scope="col" rowspan="2">총수량 하루 평균</th>'
            + dates.map(day => `<th scope="colgroup" colspan="3">${safe(day.slice(5))}</th>`).join('') + '</tr>'
            + '<tr>' + dates.map(() => '<th scope="col">MAIN</th><th scope="col">BSR</th><th scope="col" class="cs-total-heading">총수량</th>').join('') + '</tr>';
        let previousCountry = '', previousProduct = '';
        byId('cs-table-body').innerHTML = groups.map(group => {
            let heading = '';
            if (group.country !== previousCountry) {
                heading += `<tr class="cs-country-row"><th colspan="${dates.length * 3 + 2}">${safe(group.country)}</th></tr>`;
                previousCountry = group.country;
                previousProduct = '';
            }
            if (group.product !== previousProduct) {
                heading += `<tr class="cs-product-row"><th colspan="${dates.length * 3 + 2}">${safe(group.product)}</th></tr>`;
                previousProduct = group.product;
            }
            const results = dates.map(day => dayResult(group.daily.get(day) || []));
            const completed = results.filter(day => day.total != null);
            const average = completed.length
                ? completed.reduce((sum, day) => sum + day.total, 0) / completed.length : null;
            return heading + `<tr class="cs-retailer-row"><th scope="row" class="cs-identity"><strong>${safe(group.retailer)}</strong></th>`
                + `<td class="cs-average"><strong>${number(average)}</strong><small>${completed.length}/${dates.length}일 집계</small></td>`
                + results.map(day => {
                    const title = day.total == null ? day.label
                        : `총 ${number(day.total)} · MAIN ${number(day.main)} · BSR ${number(day.bsr)}${day.label ? ' · ' + day.label : ''}`;
                    if (day.total == null) return `<td class="cs-day-cell cs-unavailable${day.kind ? ' ' + day.kind : ''}" colspan="3" title="${safe(title)}"><strong>—</strong><small>${safe(day.label)}</small></td>`;
                    return `<td class="cs-day-cell">${number(day.main)}</td>`
                        + `<td class="cs-day-cell">${number(day.bsr)}</td>`
                        + `<td class="cs-day-cell cs-total${day.kind ? ' ' + day.kind : ''}" title="${safe(title)}"><strong>${number(day.total)}</strong>${day.label ? `<small>${safe(day.label)}</small>` : ''}</td>`;
                }).join('') + '</tr>';
        }).join('');
        byId('cs-results').hidden = !groups.length;
        if (groups.length) byId('cs-message').hidden = true;
        else setMessage('선택한 조건에 집계된 데이터가 없습니다. 기간이나 필터를 바꿔보세요.');
        const updates = data.weeks.filter(week => week.updated_at).map(week => week.updated_at);
        const updated = updates.length ? updates.sort().at(-1) : data.updated_at;
        byId('cs-updated').textContent = updated
            ? '집계 갱신 ' + new Date(updated).toLocaleString('ko-KR') : '아직 집계되지 않았습니다';
        history.replaceState(null, '', location.pathname + '?' + new URLSearchParams({
            country: byId('cs-country').value, product: byId('cs-product').value,
            retailer: byId('cs-retailer').value, days: byId('cs-days').value, date: endDate,
        }));
    }

    async function load(preferredRetailer = byId('cs-retailer').value) {
        if (!byId('cs-filters').reportValidity()) return;
        if (controller) controller.abort();
        const request = ++requestId;
        controller = new AbortController();
        const activeController = controller;
        const endDate = byId('cs-date').value;
        const params = new URLSearchParams({
            country: 'ALL', product: 'ALL', date: endDate,
            weeks: String(weeksNeeded(endDate, Number(byId('cs-days').value))),
        });
        data = null;
        byId('cs-results').hidden = true;
        setMessage('일별 수집 건수를 불러오는 중입니다.');
        const timeout = setTimeout(() => activeController.abort(), 10000);
        try {
            const response = await fetch('/dx/layer1/api/collection-statistics/?' + params, {signal: activeController.signal});
            const result = await response.json();
            if (request !== requestId) return;
            if (!response.ok || result.error) throw new Error(result.error || '통계를 불러오지 못했습니다.');
            data = result;
            syncRetailers(preferredRetailer);
            render();
        } catch (error) {
            if (request === requestId) setMessage(error.name === 'AbortError' ? '응답이 지연되고 있습니다. 조회를 다시 눌러주세요.' : error.message, true);
        } finally { clearTimeout(timeout); }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const params = new URLSearchParams(location.search);
        for (const key of ['country', 'product', 'days']) {
            const input = byId('cs-' + key), value = params.get(key);
            if (value && [...input.options].some(option => option.value === value)) input.value = value;
        }
        byId('cs-date').value = params.get('date')
            || new Date().toLocaleDateString('en-CA', {timeZone: 'Asia/Seoul'});
        byId('cs-filters').addEventListener('submit', event => { event.preventDefault(); load(); });
        for (const key of ['country', 'product']) byId('cs-' + key).addEventListener('change', () => {
            syncRetailers();
            render();
        });
        byId('cs-retailer').addEventListener('change', render);
        for (const key of ['days', 'date']) byId('cs-' + key).addEventListener('change', () => load());
        load(params.get('retailer') || '');
    });
})();
