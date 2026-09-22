(function () {
    'use strict';
    let data = null, requestId = 0, controller = null;
    const byId = id => document.getElementById(id);
    const safe = value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 1});
    const metricName = {total: '총 건수', main: 'MAIN', bsr: 'BSR'};
    function selectedRows() {
        return (data.weeks || []).flatMap(week => week.rows.map(row => ({...row, week})));
    }
    function stateTag(row) {
        const lows = row.daily.filter(day => day.state === 'complete' && (day.alerts || []).some(alert => alert.status === 'VOLUME_LOW')).length;
        const highs = row.daily.filter(day => day.state === 'complete' && (day.alerts || []).some(alert => alert.status === 'VOLUME_HIGH')).length;
        const tags = [];
        if (row.missing_days) tags.push(`<span class="cs-tag low">미수집 ${row.missing_days}일</span>`);
        if (lows) tags.push(`<span class="cs-tag low">이상 ${lows}일</span>`);
        if (highs) tags.push(`<span class="cs-tag high">확인 필요 ${highs}일</span>`);
        if (row.unknown_days) tags.push(`<span class="cs-tag">미집계 ${row.unknown_days}일</span>`);
        if (!tags.length) tags.push(`<span class="cs-tag ${row.partial ? '' : 'ok'}">${row.partial ? '부분 집계' : '집계 완료'}</span>`);
        return tags.join('');
    }
    function render() {
        if (!data) return;
        const rows = selectedRows(), metric = byId('cs-metric').value;
        const values = rows.filter(row => row.metrics[metric].sum != null);
        const sum = values.reduce((value, row) => value + row.metrics[metric].sum, 0);
        const days = values.reduce((value, row) => value + row.completed_days, 0);
        const missing = rows.reduce((value, row) => value + row.missing_days, 0);
        const expected = rows.reduce((value, row) => value + row.expected_days, 0);
        const completed = rows.reduce((value, row) => value + row.completed_days, 0);
        byId('cs-summary').innerHTML = [
            ['수집 합계', number(values.length ? sum : null), metricName[metric] + ' · 선택 기간'],
            ['업체·제품별 일평균', number(days ? sum / days : null), '완료된 대상일 기준 · 0건 포함'],
            ['미수집', rows.length ? number(missing) + '일' : '—', '업체·제품별 미수집 일수 합계'],
            ['집계 완료', rows.length ? number(completed) + ' / ' + number(expected) : '—', '업체·제품별 대상일 합계'],
        ].map(([label, value, note]) => `<div class="cs-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
        const series = [...data.weeks].reverse().map(week => {
            const available = week.rows.filter(row => row.metrics[metric].sum != null);
            return {week, value: available.length ? available.reduce((n, row) => n + row.metrics[metric].sum, 0) : null,
                partial: week.rows.some(row => row.partial)};
        });
        const max = Math.max(1, ...series.map(point => point.value || 0));
        byId('cs-chart').innerHTML = series.map(point => `<div class="cs-chart-column"><span class="cs-chart-value">${number(point.value)}</span><div class="cs-chart-bar${point.partial ? ' partial' : ''}" style="height:${point.value == null ? 0 : Math.round(point.value / max * 130)}px" title="${safe(point.week.start)}: ${number(point.value)}건"></div><span class="cs-chart-label">${safe(point.week.start.slice(5))}</span><span>${point.value == null ? '미집계' : point.partial ? '부분 집계' : '완료'}</span></div>`).join('');
        let index = 0;
        byId('cs-table-body').innerHTML = data.weeks.map(week => {
            if (!week.rows.length) return `<tr class="cs-week-start"><td>${safe(week.start)} ~ ${safe(week.end.slice(5))}</td><td colspan="8" class="cs-muted">집계된 데이터가 없습니다.</td></tr>`;
            return week.rows.map((row, rowIndex) => {
                const id = index++;
                return `<tr class="${rowIndex === 0 ? 'cs-week-start' : ''}"><td>${rowIndex === 0 ? safe(week.start) + ' ~ ' + safe(week.end.slice(5)) : ''}</td><td><strong>${safe(row.retailer)}</strong> <span class="cs-muted">${safe(row.product)}${row.slot !== 'daily' && row.slot !== '일일' ? ' · ' + safe(row.slot) : ''}</span></td><td>${number(row.metrics.main.sum)}</td><td>${number(row.metrics.bsr.sum)}</td><td class="cs-total">${number(row.metrics.total.sum)}</td><td>${number(row.metrics[metric].average)}</td><td>${row.completed_days} / ${row.expected_days}일</td><td>${stateTag(row)}</td><td><button type="button" class="cs-detail-button" data-detail="${id}" aria-expanded="false" aria-controls="cs-detail-${id}">상세</button></td></tr><tr class="cs-detail" id="cs-detail-${id}" hidden><td colspan="9">${detail(row, week)}</td></tr>`;
            }).join('');
        }).join('');
        byId('cs-results').hidden = false;
        byId('cs-message').hidden = rows.length > 0;
        byId('cs-message').textContent = '선택한 조건에 집계된 통계가 없습니다. 다른 기간이나 업체를 선택해보세요.';
    }
    function detail(row, week) {
        const names = {future: '예정', not_scheduled: '수집 시작 전', unknown: '미집계', pending: '수집 중', error: '갱신 실패'};
        const days = row.daily.map(day => {
            const alerts = day.alerts || [];
            let status = `<span class="cs-tag">${names[day.state] || '완료'}</span>`;
            if (day.state === 'complete') {
                if (day.total === 0) status = '<span class="cs-tag low">미수집</span>';
                else if (alerts.length) status = alerts.map(alert => `<span class="cs-tag ${alert.status === 'VOLUME_LOW' ? 'low' : 'high'}">${alert.status === 'VOLUME_LOW' ? '이상' : '확인 필요'} · ${metricName[alert.metric]} ${number(Math.abs(alert.percent))}% ${alert.percent < 0 ? '감소' : '증가'}</span>`).join('');
                else status = `<span class="cs-tag">${day.comparison_state === 'ready' ? '큰 변동 없음' : '비교 이력 부족'}</span>`;
            }
            return `<tr><td>${safe(day.date)}</td><td>${number(day.main)}</td><td>${number(day.bsr)}</td><td>${number(day.total)}</td><td>${status}</td></tr>`;
        }).join('');
        return `<div class="cs-detail-heading">${safe(row.retailer)} · ${safe(row.product)} · ${safe(week.start)} 주간</div><table class="cs-table"><thead><tr><th>데이터일</th><th>MAIN</th><th>BSR</th><th>총 건수</th><th>수집량 확인</th></tr></thead><tbody>${days}</tbody></table>`;
    }
    async function load() {
        const id = ++requestId;
        if (controller) controller.abort();
        controller = new AbortController();
        const activeController = controller;
        const params = new URLSearchParams(new FormData(byId('cs-filters')));
        byId('cs-message').hidden = false;
        byId('cs-message').className = 'cs-message';
        byId('cs-message').textContent = '주간 통계를 불러오는 중입니다.';
        byId('cs-results').hidden = true;
        const timeout = setTimeout(() => activeController.abort(), 10000);
        try {
            const response = await fetch('/dx/layer1/api/collection-statistics/?' + params, {signal: controller.signal});
            const result = await response.json();
            if (id !== requestId) return;
            if (!response.ok || result.error) throw new Error(result.error || '통계를 불러오지 못했습니다.');
            data = result;
            const selected = byId('cs-retailer').value;
            byId('cs-retailer').innerHTML = '<option value="">전체 업체</option>' + result.retailers.map(retailer => `<option value="${safe(retailer)}">${safe(retailer)}</option>`).join('');
            byId('cs-retailer').value = result.retailers.includes(selected) ? selected : '';
            byId('cs-updated').textContent = result.updated_at ? '집계 갱신 ' + new Date(result.updated_at).toLocaleString('ko-KR') : '아직 집계되지 않았습니다';
            history.replaceState(null, '', location.pathname + '?' + params);
            render();
        } catch (error) {
            if (id !== requestId) return;
            byId('cs-message').className = 'cs-message error';
            byId('cs-message').textContent = error.name === 'AbortError' ? '응답이 지연되고 있습니다. 조회를 다시 눌러주세요.' : error.message;
            byId('cs-updated').textContent = '집계 시각 확인 불가';
        } finally { clearTimeout(timeout); }
    }
    document.addEventListener('DOMContentLoaded', function () {
        const params = new URLSearchParams(location.search);
        byId('cs-date').value = params.get('date') || new Date().toLocaleDateString('en-CA', {timeZone: 'Asia/Seoul'});
        for (const key of ['country', 'product', 'weeks']) {
            const input = byId('cs-' + key), value = params.get(key);
            if (value && [...input.options].some(option => option.value === value)) input.value = value;
        }
        if (params.get('retailer')) {
            byId('cs-retailer').add(new Option(params.get('retailer'), params.get('retailer'), true, true));
        }
        byId('cs-filters').addEventListener('submit', event => {event.preventDefault(); load();});
        for (const key of ['country', 'product']) byId('cs-' + key).addEventListener('change', () => {byId('cs-retailer').value = ''; load();});
        byId('cs-metric').addEventListener('change', render);
        byId('cs-table-body').addEventListener('click', event => {
            const button = event.target.closest('[data-detail]');
            if (!button) return;
            const row = byId('cs-detail-' + button.dataset.detail);
            row.hidden = !row.hidden;
            button.setAttribute('aria-expanded', String(!row.hidden));
            button.textContent = row.hidden ? '상세' : '접기';
        });
        load();
    });
})();
