(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const safe = value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 1});
    const metricName = {total: '총 건수', main: 'MAIN', bsr: 'BSR'};
    let optionsController = null, resultsController = null, optionsRequest = 0, resultsRequest = 0;

    function localToday() {
        return new Date().toLocaleDateString('en-CA', {timeZone: 'Asia/Seoul'});
    }

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

    function dayEntries(result, day) {
        const weekday = (new Date(day + 'T00:00:00Z').getUTCDay() + 6) % 7;
        const monday = shiftDate(day, -weekday);
        const week = result.weeks.find(item => item.start === monday);
        return week ? week.rows.flatMap(row => row.daily.filter(item => item.date === day)
            .map(item => ({...item, slot: row.slot}))) : [];
    }

    function dailyStatus(entries, totals) {
        if (!entries.length) return '<span class="cs-tag">미집계</span>';
        if (entries.every(item => item.state === 'not_scheduled')) return '<span class="cs-tag">수집 시작 전</span>';
        if (entries.some(item => item.state === 'error')) return '<span class="cs-tag low">갱신 실패</span>';
        if (entries.some(item => item.state === 'pending')) return '<span class="cs-tag">수집 중</span>';
        if (entries.some(item => item.state === 'unknown')) return '<span class="cs-tag">부분 집계</span>';
        if (entries.some(item => item.state === 'future')) return '<span class="cs-tag">예정</span>';
        if (totals.total === 0) return '<span class="cs-tag low">미수집</span>';
        const active = entries.filter(item => item.state !== 'not_scheduled');
        const alerts = active.flatMap(item => item.alerts || []);
        const low = alerts.filter(item => item.status === 'VOLUME_LOW');
        const high = alerts.filter(item => item.status === 'VOLUME_HIGH');
        if (low.length || high.length) return [...low, ...high].map(alert =>
            `<span class="cs-tag ${alert.status === 'VOLUME_LOW' ? 'low' : 'high'}">${alert.status === 'VOLUME_LOW' ? '이상' : '확인 필요'} · ${metricName[alert.metric]} ${number(Math.abs(alert.percent))}% ${alert.percent < 0 ? '감소' : '증가'}</span>`).join('');
        const ready = active.every(item => item.comparison_state === 'ready');
        return `<span class="cs-tag ${ready ? 'ok' : ''}">${ready ? '정상' : '비교 이력 부족'}</span>`;
    }

    function render(result, endDate, count) {
        const days = [];
        for (let offset = count - 1; offset >= 0; offset--) {
            const date = shiftDate(endDate, -offset);
            const entries = dayEntries(result, date);
            const active = entries.filter(item => item.state !== 'not_scheduled');
            const complete = active.length > 0 && active.every(item => item.state === 'complete');
            const totals = {};
            for (const metric of ['main', 'bsr', 'total']) {
                const values = complete ? active.map(item => item[metric]).filter(value => value != null) : [];
                totals[metric] = values.length ? values.reduce((sum, value) => sum + value, 0) : null;
            }
            days.push({date, entries, complete, totals});
        }
        const completed = days.filter(day => day.complete && day.totals.total != null);
        const average = completed.length ? completed.reduce((sum, day) => sum + day.totals.total, 0) / completed.length : null;
        byId('cs-summary').innerHTML = [
            ['하루 평균 수집 건수', number(average), `집계 완료 ${completed.length}일 기준 · 0건 포함`],
            ['집계 완료', `${completed.length} / ${count}일`, '선택한 기간의 데이터일 기준'],
        ].map(([label, value, note]) => `<div class="cs-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
        byId('cs-selection').textContent = `${byId('cs-country').value} · ${byId('cs-product').value} · ${byId('cs-retailer').value} · ${shiftDate(endDate, -(count - 1))} ~ ${endDate}`;
        byId('cs-table-body').innerHTML = days.map(day => {
            const slots = day.entries.filter(item => item.state !== 'not_scheduled').map(item => item.slot);
            const slotLabel = [...new Set(slots)].map(slot => slot === 'daily' ? '일일' : slot).join(', ');
            return `<tr><td>${safe(day.date)}</td><td>${safe(slotLabel || '—')}</td><td>${number(day.totals.main)}</td><td>${number(day.totals.bsr)}</td><td class="cs-total">${number(day.totals.total)}</td><td>${dailyStatus(day.entries, day.totals)}</td></tr>`;
        }).join('');
        byId('cs-results').hidden = false;
        byId('cs-message').hidden = true;
        const updates = result.weeks.filter(week => week.rows.length && week.updated_at)
            .map(week => week.updated_at);
        const updated = updates.length ? updates.sort().at(-1) : result.updated_at;
        byId('cs-updated').textContent = updated
            ? '집계 갱신 ' + new Date(updated).toLocaleString('ko-KR')
            : '아직 집계되지 않았습니다';
    }

    async function loadRetailers(preferred = '') {
        const country = byId('cs-country').value, product = byId('cs-product').value;
        const select = byId('cs-retailer');
        if (optionsController) optionsController.abort();
        const request = ++optionsRequest;
        select.disabled = true;
        select.innerHTML = '<option value="">리테일러 선택</option>';
        if (!country || !product) return;
        optionsController = new AbortController();
        const params = new URLSearchParams({country, product, weeks: '8', date: byId('cs-date').value});
        try {
            const response = await fetch('/dx/layer1/api/collection-statistics/?' + params, {signal: optionsController.signal});
            const result = await response.json();
            if (request !== optionsRequest) return;
            if (!response.ok || result.error) throw new Error(result.error || '리테일러 목록을 불러오지 못했습니다.');
            select.innerHTML += result.retailers.map(retailer => `<option value="${safe(retailer)}">${safe(retailer)}</option>`).join('');
            if (result.retailers.includes(preferred)) select.value = preferred;
            select.disabled = false;
            if (!result.retailers.length) setMessage('선택한 국가·제품군에 집계된 리테일러가 없습니다.');
        } catch (error) {
            if (request === optionsRequest && error.name !== 'AbortError') setMessage(error.message, true);
        }
    }

    async function loadResults() {
        const form = byId('cs-filters');
        if (!form.reportValidity()) return;
        if (byId('cs-retailer').disabled || !byId('cs-retailer').value) {
            setMessage('리테일러를 선택한 뒤 조회를 눌러주세요.');
            return;
        }
        if (resultsController) resultsController.abort();
        const request = ++resultsRequest;
        resultsController = new AbortController();
        const activeController = resultsController;
        const endDate = byId('cs-date').value, days = Number(byId('cs-days').value);
        const params = new URLSearchParams({
            country: byId('cs-country').value, product: byId('cs-product').value,
            retailer: byId('cs-retailer').value, date: endDate, weeks: String(weeksNeeded(endDate, days)),
        });
        byId('cs-results').hidden = true;
        setMessage('일별 수집 건수를 불러오는 중입니다.');
        const timeout = setTimeout(() => activeController.abort(), 10000);
        try {
            const response = await fetch('/dx/layer1/api/collection-statistics/?' + params, {signal: activeController.signal});
            const result = await response.json();
            if (request !== resultsRequest) return;
            if (!response.ok || result.error) throw new Error(result.error || '통계를 불러오지 못했습니다.');
            history.replaceState(null, '', location.pathname + '?' + new URLSearchParams({
                country: byId('cs-country').value, product: byId('cs-product').value,
                retailer: byId('cs-retailer').value, days: String(days), date: endDate,
            }));
            render(result, endDate, days);
        } catch (error) {
            if (request === resultsRequest) setMessage(error.name === 'AbortError' ? '응답이 지연되고 있습니다. 조회를 다시 눌러주세요.' : error.message, true);
        } finally { clearTimeout(timeout); }
    }

    document.addEventListener('DOMContentLoaded', async function () {
        const params = new URLSearchParams(location.search);
        const country = params.get('country') || '';
        if ([...byId('cs-country').options].some(option => option.value === country)) byId('cs-country').value = country;
        const product = params.get('product') || '';
        if ([...byId('cs-product').options].some(option => option.value === product)) byId('cs-product').value = product;
        const days = params.get('days') || '5';
        if ([...byId('cs-days').options].some(option => option.value === days)) byId('cs-days').value = days;
        byId('cs-date').value = params.get('date') || shiftDate(localToday(), country === 'SEA' ? -1 : 0);
        byId('cs-filters').addEventListener('submit', event => { event.preventDefault(); loadResults(); });
        for (const key of ['country', 'product']) byId('cs-' + key).addEventListener('change', () => {
            if (resultsController) resultsController.abort();
            resultsRequest++;
            if (key === 'country' && !params.has('date')) byId('cs-date').value = shiftDate(localToday(), byId('cs-country').value === 'SEA' ? -1 : 0);
            byId('cs-results').hidden = true;
            setMessage('리테일러를 선택한 뒤 조회를 눌러주세요.');
            loadRetailers();
        });
        for (const key of ['retailer', 'days', 'date']) byId('cs-' + key).addEventListener('change', () => {
            if (resultsController) resultsController.abort();
            resultsRequest++;
            byId('cs-results').hidden = true;
            setMessage('선택한 조건으로 조회를 눌러주세요.');
            if (key === 'date') loadRetailers(byId('cs-retailer').value);
        });
        if (country && product) {
            await loadRetailers(params.get('retailer') || '');
            if (byId('cs-retailer').value) loadResults();
        }
    });
})();
