(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const safe = value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 1});
    const countries = ['SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE', 'SEIB'];
    const products = ['TV', 'REF', 'LDY', 'LDY_DRYER'];
    let data = null, controller = null, requestId = 0;
    let reviewTargets = [], reviewDialog = null;
    let livePoll = null;
    const liveUpdates = new Map();

    function applyCurrent(snapshot) {
        if (!data || snapshot.inspection_date !== byId('cs-date').value) return;
        const sourceDate = data.baseline_dates?.[snapshot.country];
        if (!sourceDate || (snapshot.available && snapshot.source_date !== sourceDate)) return;
        const week = data.weeks.find(item => item.start <= sourceDate && shiftDate(item.start, 6) >= sourceDate);
        if (!week) return;
        if (!snapshot.available) {
            for (const group of week.rows.filter(row => row.country === snapshot.country)) {
                group.daily = group.daily.map(day => day.date === sourceDate
                    ? {...day, state:'error', refresh_error:true, review:null} : day);
            }
            liveUpdates.set(snapshot.country, null);
        } else {
            const currentKeys = new Set(snapshot.rows.map(row => JSON.stringify([row.product, row.retailer, row.slot])));
            // Remove stale target-day entries, including sources no longer enabled.
            for (const group of week.rows.filter(row => row.country === snapshot.country)) {
                if (!currentKeys.has(JSON.stringify([group.product, group.retailer, group.slot]))) {
                    group.daily = group.daily.filter(day => day.date !== sourceDate);
                }
            }
            for (const row of snapshot.rows) {
                let group = week.rows.find(item => item.country === snapshot.country && item.product === row.product
                    && item.retailer === row.retailer && item.slot === row.slot);
                if (!group) {
                    group = {country:snapshot.country, product:row.product, retailer:row.retailer, slot:row.slot, daily:[]};
                    week.rows.push(group);
                }
                group.daily = group.daily.filter(day => day.date !== sourceDate).concat({...row, date:sourceDate});
            }
            liveUpdates.set(snapshot.country, snapshot.updated_at);
        }
        if (!reviewDialog && !L1.liveCollection.isInspecting()) {
            L1.liveCollection.preserveView(() => { syncRetailers(); render(); });
        }
    }

    function startLive() {
        if (typeof L1 === 'undefined' || !L1.liveCollection) return;
        livePoll?.stop();
        livePoll = L1.liveCollection.poll(() => ({date:byId('cs-date').value,
            countries:byId('cs-country').value === 'ALL' ? countries : [byId('cs-country').value]}), applyCurrent);
        livePoll.refresh();
    }

    function openReview(index) {
        const target = reviewTargets[index];
        if (!target) return;
        reviewDialog?.close();
        const dialog = document.createElement('dialog');
        reviewDialog = dialog;
        dialog.className = 'l1-review-dialog';
        dialog.setAttribute('aria-labelledby', 'cs-review-title');
        const title = target.entries.every(day => day.review?.action === 'confirm') ? '정상 확인 이력' : '수집 확인 이력';
        dialog.innerHTML = `<h2 id="cs-review-title">${title}</h2>
            <p class="l1-review-target">${safe(target.country)} · ${safe(target.product)} · ${safe(target.retailer)}<br>데이터일 ${safe(target.date)} · ${safe(target.metric.toUpperCase())}</p>`
            + target.entries.map(day => {
                const review = day.review;
                const confirmed = review?.action === 'confirm';
                const time = review?.at ? new Date(review.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' (KST)' : '';
                return `<section><p class="l1-review-target">${safe(day.slot || 'daily')} · 배치 ${safe(day.batch_id || '정보 없음')}${review?.inspection_date ? '<br>검수일 ' + safe(review.inspection_date) : ''}</p>
                    <p>MAIN ${number(day.main)}건 · BSR ${number(day.bsr)}건 · 총 ${number(day.total)}건</p>`
                    + (review ? `<p class="${confirmed ? 'l1-review-confirmed' : 'l1-review-rejected'}">${confirmed ? '✓ 정상 확인' : '이상 확정'}<strong class="l1-review-memo">${safe(review.memo)}</strong><span class="l1-review-author">${safe(review.username)} · ${safe(time)}</span></p>` : '<p>확인 필요 · 아직 처리하지 않은 수집입니다.</p>') + '</section>';
            }).join('') + '<div class="l1-review-actions"><button type="button" data-close autofocus>닫기</button></div>';
        document.body.appendChild(dialog);
        dialog.querySelector('[data-close]').onclick = () => dialog.close();
        dialog.addEventListener('close', () => {
            dialog.remove();
            if (reviewDialog === dialog) reviewDialog = null;
        }, {once:true});
        dialog.showModal();
    }

    function reviewLabel(day, metric, group, date) {
        const label = day[metric + 'Label'];
        if (!label) return '';
        const entries = day[metric + 'Reviews'] || [];
        if (!entries.some(entry => entry.review)) return `<small>${safe(label)}</small>`;
        const index = reviewTargets.push({country:group.country, product:group.product, retailer:group.retailer, date, metric, entries}) - 1;
        return `<small><button type="button" class="l1-review-label" data-cs-review="${index}" aria-haspopup="dialog" title="확인 이력 보기">${safe(label)}</button></small>`;
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
                group.daily.get(day.date).push({...day, slot:day.slot || row.slot});
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
        const observing = active.filter(day => day.observation_state === 'observing');
        const observation = observing.length
            ? `신규 · 관찰 중 (${Math.min(...observing.map(day => Math.max(0, Math.min(5, Number(day.observation_days) || 0))))}/5일)`
            : '';
        const annotate = result => ({...result, label: [result.label, observation].filter(Boolean).join(' · ')});
        if (!active.length) return {total: null, label: '수집 시작 전'};
        if (active.some(day => day.state === 'error' || day.base_status === 'ERROR')) return annotate({total: null, label: '갱신 실패', kind: 'low'});
        if (active.some(day => day.state === 'pending' && day.verification_state !== 'waiting')) return annotate({total: null, label: '수집 중'});
        if (active.every(day => day.state === 'unknown')) return {total: null, label: '미집계'};
        if (active.some(day => day.state === 'unknown')) return {total: null, label: '부분 집계'};
        if (active.some(day => day.state === 'future')) return {total: null, label: '예정'};
        const sum = metric => {
            const values = active.map(day => day[metric]).filter(value => value != null);
            return values.length ? values.reduce((total, value) => total + value, 0) : null;
        };
        const total = sum('total'), main = sum('main'), bsr = sum('bsr');
        if (active.some(day => day.state === 'pending')) {
            return annotate({total, main, bsr, provisional: true, label: '검증 대기'});
        }
        if (total === 0 && (main || 0) === 0 && (bsr || 0) === 0 && !sum('collected_count')) {
            return annotate({total, main, bsr, label: '미수집', kind: 'low'});
        }
        const visibleAlerts = day => (day.alerts || []).filter(alert =>
            alert.exact || !['observing', 'unknown'].includes(day.observation_state));
        const alerts = active.flatMap(visibleAlerts);
        function reviewInfo(metric) {
            const affected = active.filter(day => visibleAlerts(day).some(alert => alert.metric === metric));
            const decision = day => day.review?.metrics?.includes(metric) ? day.review : null;
            const confirmed = affected.length && affected.every(day => decision(day)?.action === 'confirm');
            const rejected = affected.some(day => decision(day)?.action === 'reject');
            return {confirmed, rejected, entries:affected.map(day => ({...day, review:decision(day)}))};
        }
        const bsrReview = reviewInfo('bsr'), mainReview = reviewInfo('main');
        const bsrAlerts = alerts.filter(alert => alert.metric === 'bsr' && ['VOLUME_LOW', 'VOLUME_REVIEW'].includes(alert.status));
        const bsrLow = bsrAlerts.some(alert => alert.status === 'VOLUME_LOW');
        const bsrInfo = {
            bsrKind: bsrReview.rejected ? 'low' : bsrReview.confirmed ? 'confirmed' : bsrAlerts.length ? (bsrLow ? 'low' : 'high') : '',
            bsrLabel: bsrReview.rejected ? '이상 확정' : bsrReview.confirmed ? '✓ 정상 확인' : bsrAlerts.length ? (bsrLow ? '이상' : '확인 필요') : observation || (active.some(day => day.bsr_comparison_state === 'insufficient') ? '비교 이력 부족' : ''),
            bsrReviews: bsrReview.entries,
            bsrReason: bsrAlerts.map(alert => alert.reason || 'BSR 수량 부족').join(' · '),
        };
        const mainAlerts = alerts.filter(alert => alert.metric === 'main');
        const low = mainAlerts.some(alert => alert.status === 'VOLUME_LOW');
        const high = mainAlerts.some(alert => ['VOLUME_HIGH', 'VOLUME_REVIEW'].includes(alert.status));
        return {total, main, bsr, ...bsrInfo,
            mainKind: mainReview.rejected ? 'low' : mainReview.confirmed ? 'confirmed' : low ? 'low' : high ? 'high' : '',
            mainLabel: mainReview.rejected ? '이상 확정' : mainReview.confirmed ? '✓ 정상 확인' : low ? '이상' : high ? '확인 필요' : '',
            mainReviews: mainReview.entries,
            mainReason: mainAlerts.map(alert => alert.reason || 'MAIN 수집량 변동').join(' · '),
            label: observation || (active.every(day => day.comparison_state === 'ready') ? '' : '비교 이력 부족')};
    }

    function baselineCell(entries) {
        const active = entries.filter(day => day.state !== 'not_scheduled');
        if (!active.length) return '<span class="cs-muted">기준값 없음</span>';
        return active.map(day => {
            const metrics = ['main', 'bsr'].map(metric => {
                const basis = day.baselines?.[metric];
                const fixed = metric === 'bsr' && basis?.rule === 'fixed_100' && basis.value === 100;
                const valid = basis && Number.isFinite(basis.value) && basis.value > 0
                    && (fixed || (Number.isFinite(basis.days) && basis.days >= 5
                        && !['observing', 'unknown'].includes(day.observation_state)
                        && (metric === 'main' || basis.rule === 'median_28d')))
                    && !['future', 'unknown'].includes(day.state);
                const missing = day.state === 'pending'
                    ? day.verification_state === 'waiting' ? '검증 대기'
                        : day.verification_state === 'pending' ? '수집 대기' : '수집 중'
                    : day.state === 'error' || day.refresh_error || day.base_status === 'ERROR' ? '갱신 실패'
                    : day.observation_state === 'observing' ? '관찰 중'
                    : ['unknown', 'future'].includes(day.state) ? '기준값 없음' : '비교 이력 부족';
                return `<div class="cs-baseline-metric"><span>${metric.toUpperCase()}</span> `
                    + (valid ? `<strong>${number(basis.value)}</strong>${fixed ? ' <span class="cs-baseline-note">(고정 기준)</span>' : ''}`
                        : `<span class="cs-baseline-note">— ${missing}</span>`) + '</div>';
            }).join('');
            return `<div class="cs-baseline-slot">${active.length > 1 ? `<small>${safe(day.slot || 'daily')}</small>` : ''}${metrics}</div>`;
        }).join('');
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
        reviewDialog?.close();
        reviewTargets = [];
        const endDate = byId('cs-date').value, dates = selectedDates(endDate, Number(byId('cs-days').value));
        const groups = selectedGroups(dates);
        byId('cs-selection').textContent = [
            byId('cs-country').value === 'ALL' ? '전체 국가' : byId('cs-country').value,
            byId('cs-product').value === 'ALL' ? '전체 제품군' : byId('cs-product').value,
            byId('cs-retailer').value || '전체 리테일러',
            `${dates[0]} ~ ${endDate} · ${groups.length}개 조합`,
        ].join(' · ');
        byId('cs-table-head').innerHTML = '<tr><th scope="col" rowspan="2">리테일러</th><th scope="col" rowspan="2">정상 중앙값<br><small>(기준: 28일)</small></th>'
            + dates.map(day => `<th scope="colgroup" colspan="3">${safe(day.slice(5))}</th>`).join('') + '</tr>'
            + '<tr>' + dates.map(() => '<th scope="col">MAIN</th><th scope="col">BSR</th><th scope="col" class="cs-total-heading">총수량</th>').join('') + '</tr>';
        let previousCountry = '', previousProduct = '';
        byId('cs-table-body').innerHTML = groups.map(group => {
            let heading = '';
            if (group.country !== previousCountry) {
                heading += `<tr class="cs-country-row"><th colspan="${dates.length * 3 + 2}"><span class="cs-group-label">${safe(group.country)}</span></th></tr>`;
                previousCountry = group.country;
                previousProduct = '';
            }
            if (group.product !== previousProduct) {
                heading += `<tr class="cs-product-row"><th colspan="${dates.length * 3 + 2}"><span class="cs-group-label">${safe(group.product)}</span></th></tr>`;
                previousProduct = group.product;
            }
            const results = dates.map(day => dayResult(group.daily.get(day) || []));
            const baselineDate = data.baseline_dates?.[group.country];
            return heading + `<tr class="cs-retailer-row"><th scope="row" class="cs-identity"><strong>${safe(group.retailer)}</strong></th>`
                + `<td class="cs-baseline">${baselineCell(group.daily.get(baselineDate) || [])}${baselineDate ? `<small>데이터일 ${safe(baselineDate)}</small>` : ''}</td>`
                + results.map((day, index) => {
                    const title = day.total == null ? day.label
                        : `총 ${number(day.total)} · MAIN ${number(day.main)} · BSR ${number(day.bsr)}${day.label ? ' · ' + day.label : ''}`;
                    if (day.total == null) return `<td class="cs-day-cell cs-unavailable${day.kind ? ' ' + day.kind : ''}" colspan="3" title="${safe(title)}"><strong>—</strong><small>${safe(day.label)}</small></td>`;
                    return `<td class="cs-day-cell${day.mainKind ? ' ' + day.mainKind + ' cs-main-' + day.mainKind : ''}"${day.mainReason ? ` title="${safe(day.mainReason)}"` : ''}>${number(day.main)}${reviewLabel(day, 'main', group, dates[index])}</td>`
                        + `<td class="cs-day-cell${day.bsrKind ? ' ' + day.bsrKind + (day.bsrKind === 'confirmed' ? ' cs-bsr-confirmed' : day.bsrKind === 'low' ? ' cs-bsr-low' : ' cs-bsr-review') : ''}"${day.bsrReason || day.bsrLabel ? ` title="${safe(day.bsrReason || day.bsrLabel)}"` : ''}>${number(day.bsr)}${reviewLabel(day, 'bsr', group, dates[index])}</td>`
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
        const visibleCountries = byId('cs-country').value === 'ALL' ? countries : [byId('cs-country').value];
        const checked = visibleCountries.map(country => liveUpdates.get(country)).filter(Boolean).sort();
        if (checked.length) byId('cs-updated').textContent = '현재 건수 확인 '
            + new Date(checked[0]).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' · 15초마다 자동 갱신';
        if (visibleCountries.some(country => liveUpdates.has(country) && !liveUpdates.get(country))) {
            setMessage('일부 국가의 현재 수집 건수를 확인하지 못했습니다. 자동으로 다시 조회합니다.', true);
        }
        history.replaceState(null, '', location.pathname + '?' + new URLSearchParams({
            country: byId('cs-country').value, product: byId('cs-product').value,
            retailer: byId('cs-retailer').value, days: byId('cs-days').value, date: endDate,
        }));
    }

    async function load(preferredRetailer = byId('cs-retailer').value) {
        if (!byId('cs-filters').reportValidity()) return;
        livePoll?.stop();
        liveUpdates.clear();
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
        reviewDialog?.close();
        reviewTargets = [];
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
            startLive();
        } catch (error) {
            if (request === requestId) setMessage(error.name === 'AbortError' ? '응답이 지연되고 있습니다. 조회를 다시 눌러주세요.' : error.message, true);
        } finally { clearTimeout(timeout); }
    }

    document.addEventListener('DOMContentLoaded', function () {
        byId('cs-table-body').addEventListener('click', event => {
            const button = event.target.closest('[data-cs-review]');
            if (button) openReview(Number(button.dataset.csReview));
        });
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
            livePoll?.refresh();
        });
        byId('cs-retailer').addEventListener('change', render);
        for (const key of ['days', 'date']) byId('cs-' + key).addEventListener('change', () => load());
        load(params.get('retailer') || '');
    });
})();
