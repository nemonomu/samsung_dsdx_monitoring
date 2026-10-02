// Manual review never changes the automatic status or collection counts.
(function () {
    const countries = {retail: 'SEA', seda_retail: 'SEDA', siel_retail: 'SIEL', seg_retail: 'SEG', sem_retail: 'SEM', tse_retail: 'TSE'};
    const reviewStatuses = ['REVIEW', 'VOLUME_REVIEW', 'VOLUME_HIGH'];
    let records = [], loadedDate = '', loadError = '', generation = 0, targets = [];
    const attr = value => esc(String(value)).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const stable = value => JSON.stringify(value, function (_, item) {
        return item && !Array.isArray(item) && typeof item === 'object'
            ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
    });
    const reviewed = row => Boolean(row._normalReview && row._normalReview.active);
    const number = value => Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 2});

    function reasons(row) {
        const result = (row.volume_alerts || []).filter(alert => reviewStatuses.includes(alert.status)).map(alert =>
            alert.reason || `${String(alert.metric || '수집량').toUpperCase()} 기준 ${number(alert.baseline)}건 / 수집 ${number(alert.actual)}건 / ${number(alert.percent)}% 변동`);
        if (row.status === 'REVIEW' || (!row.volume_comparison_state && row._volumeBaseStatus === 'REVIEW')) {
            const baseline = row.expected_precise == null ? row.expected : row.expected_precise;
            const actual = row.main_count == null ? row.actual : row.main_count;
            result.unshift(Number(actual) === 0 ? 'MAIN 수집 0건 · MAIN 데이터가 없어 확인이 필요합니다.' : baseline == null
                ? 'MAIN 비교 기준을 확인할 수 없습니다. 수집 결과를 확인해 주세요.'
                : `MAIN 과거 ${row.history_day_count || ''}일 평균 ${number(baseline)}건 / 수집 ${number(actual)}건 / ${number(Math.abs(actual - baseline))}건 ${actual < baseline ? '감소' : '증가'}\n판정 기준: 평균 대비 ${number(row.allowed_deviation == null ? 50 : row.allowed_deviation)}건 이상 차이`);
        }
        return [...new Set(result)].sort();
    }

    function decorate(data, day) {
        targets = [];
        (data.checks || []).forEach(check => {
            const country = countries[check.check_type];
            if (!country) return;
            const checkRows = [];
            (check.categories || []).forEach(cat => {
                const catRows = [];
                const slots = cat.time_slots || [{name: 'daily', retailers: cat.retailers || []}];
                slots.forEach(slot => {
                    const rows = slot.retailers || [];
                    rows.forEach(row => {
                        delete row._reviewContext;
                        delete row._normalReview;
                        row._reviewReasons = reasons(row);
                        if (!reviewStatuses.includes(row.status)) return;
                        if (!row._reviewReasons.length) row._reviewReasons = ['수집량이 자동 판정 기준을 벗어났습니다. 수집 결과를 확인해 주세요.'];
                        const metrics = L1.collectionVolume.metrics(row, country);
                        const context = {
                            version: 1, date: day,
                            source_date: cat.source_date || check.source_date || day,
                            country, product: String(cat.name || cat.category || '').toUpperCase(),
                            slot: slot.name || 'daily', retailer: row.retailer || '', batch_id: String(row._volumeBatchId || row.batch_id || ''),
                            status: row.status,
                            counts: [metrics.main, metrics.bsr, metrics.total, Number(row.batch_count || 0)],
                            reasons: row._reviewReasons,
                            basis: stable({base_status: row._volumeBaseStatus || row.status,
                                expected: row.expected_precise == null ? row.expected : row.expected_precise,
                                allowed_deviation: row.allowed_deviation,
                                alerts: (row.volume_alerts || []).map(alert => ({...alert})).sort((a, b) => stable(a).localeCompare(stable(b)))}),
                        };
                        row._reviewContext = context;
                        row._normalReview = records.find(record => stable(record.context) === stable(context));
                        row._reviewTarget = targets.push(row) - 1;
                    });
                    slot._reviewRows = rows;
                    catRows.push(...rows);
                });
                cat._reviewRows = catRows;
                checkRows.push(...catRows);
            });
            check._reviewRows = checkRows;
        });
    }

    function recordText(record) {
        const event = record && record.history && record.history.at(-1);
        if (!event) return '';
        return `${event.memo}\n${event.username} · ${new Date(event.at).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'})} (KST)`;
    }

    function badge(row, status) {
        if (row._reviewContext && reviewStatuses.includes(status)) {
            const done = reviewed(row);
            const title = (done ? '정상 확인\n' + recordText(row._normalReview) + '\n\n최초 사유\n' : '확인 필요\n')
                + row._reviewReasons.join('\n\n') + '\n\n클릭하여 ' + (done ? '확인 이력 보기 · 확인 취소' : '검토');
            return `<button type="button" class="status-badge ${done ? 'ok' : 'volume-review'} l1-review-badge" title="${attr(title)}" aria-label="${attr(title)}" onclick="event.stopPropagation();L1.retailReview.open(${row._reviewTarget})">${done ? '✓ 정상 확인' : '<span class="status-dot"></span>확인 필요'}</button>`;
        }
        const rows = row._reviewRows || [];
        const reviews = rows.filter(item => item._reviewContext);
        if (!reviews.length || !['OK', ...reviewStatuses].includes(status)) return null;
        const pending = reviews.filter(item => !reviewed(item));
        const done = !pending.length && rows.every(item => (item.status === 'OK' || reviewed(item)) && Number(item.batch_count || 0) < 2);
        const title = reviews.map(item => `${item.retailer} · ${reviewed(item) ? '정상 확인' : '확인 필요'}\n${item._reviewReasons.join('\n')}`
            + (reviewed(item) ? '\n' + recordText(item._normalReview) : '')).join('\n\n');
        return `<span class="status-badge ${done ? 'ok' : 'volume-review'}" tabindex="0" title="${attr(title)}" aria-label="${attr(title)}">${done ? '✓ 정상 확인' : '<span class="status-dot"></span>확인 필요' + (pending.length ? ' · 미확인 ' + pending.length + '건' : '')}</span>`;
    }

    async function load(day) {
        const current = ++generation;
        loadedDate = ''; loadError = ''; records = [];
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try {
            const response = await fetch('/dx/layer1/api/retail-reviews/?date=' + encodeURIComponent(day), {signal: controller.signal});
            if (!response.ok) throw new Error('검토 기록을 불러오지 못했습니다. 새로고침 후 다시 시도하세요.');
            const payload = await response.json();
            if (current !== generation) return;
            if (payload.date !== day || !Array.isArray(payload.reviews)) throw new Error('검토 기록의 날짜가 일치하지 않습니다.');
            records = payload.reviews; loadedDate = day;
        } catch (error) {
            if (current === generation) loadError = '검토 기록을 불러오지 못했습니다. 새로고침 후 다시 시도하세요.';
        } finally { clearTimeout(timer); }
    }

    function repaint() {
        if (!currentStatsData) return;
        const expanded = Array.from(document.querySelectorAll('[id].show')).map(element => element.id);
        renderLayer1Stats(currentStatsData);
        expanded.forEach(id => {
            const element = document.getElementById(id);
            if (!element) return;
            element.classList.add('show');
            const header = element.previousElementSibling;
            if (header) header.querySelectorAll('.toggle-icon, .toggle-icon-small').forEach(icon => icon.classList.add('expanded'));
        });
    }

    function open(index) {
        const row = targets[index];
        if (!row || !row._reviewContext) return;
        const context = row._reviewContext;
        const key = stable(context);
        const record = row._normalReview;
        const done = reviewed(row);
        const unavailable = loadedDate !== context.date;
        const dialog = document.createElement('dialog');
        dialog.className = 'l1-review-dialog';
        dialog.setAttribute('aria-labelledby', 'l1-review-title');
        dialog.innerHTML = `<form>
            <h2 id="l1-review-title">${done ? '정상 확인 이력' : '수집 결과 확인'}</h2>
            <p class="l1-review-target">${esc(context.country)} · ${esc(context.product)} · ${esc(context.retailer)}<br>검수일 ${esc(context.date)} · 데이터일 ${esc(context.source_date)}<br>배치 ${esc(context.batch_id || '정보 없음')}</p>
            <div class="l1-review-reasons"><strong>${done ? '최초 확인 필요 사유' : '확인 필요 사유'}</strong><p>${esc(context.reasons.join('\n\n'))}</p></div>
            ${done ? '<p class="l1-review-confirmed">✓ 정상 확인<br>' + esc(recordText(record)) + '</p>' : ''}
            ${(record && record.history.length) ? '<details><summary>확인·취소 이력</summary>' + record.history.map(event => '<p>' + esc((event.action === 'confirm' ? '정상 확인' : '확인 취소') + ' · ' + event.username + ' · ' + new Date(event.at).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'}) + ' (KST)\n' + event.memo) + '</p>').join('') + '</details>' : ''}
            <label for="l1-review-memo">${done ? '취소 사유' : '정상으로 확인한 근거'}</label>
            <textarea id="l1-review-memo" required maxlength="1000" rows="3" placeholder="${done ? '확인을 취소하는 이유를 입력하세요.' : '예: 원본 사이트 상품 수와 일치함'}"></textarea>
            <p class="l1-review-help">이 확인은 해당 날짜·배치·수집 수치·판정 사유에만 적용됩니다.</p>
            <p class="l1-review-error" role="alert">${unavailable ? esc(loadError || '검토 기록을 불러오는 중입니다. 잠시 후 다시 열어 주세요.') : !context.batch_id ? '배치 정보가 없어 정상 확인할 수 없습니다.' : ''}</p>
            <div class="l1-review-actions"><button type="button" data-close>닫기</button><button type="submit" ${unavailable || !context.batch_id ? 'disabled' : ''}>${done ? '확인 취소' : '정상 확인'}</button></div>
        </form>`;
        document.body.appendChild(dialog);
        dialog.querySelector('[data-close]').onclick = () => dialog.close();
        dialog.addEventListener('close', () => dialog.remove(), {once: true});
        dialog.querySelector('form').onsubmit = async event => {
            event.preventDefault();
            const error = dialog.querySelector('.l1-review-error');
            // Async count refreshes/date navigation must not confirm a different result.
            if (getSelectedDate() !== context.date || !targets.some(target => stable(target._reviewContext) === key)) {
                error.textContent = '수집 결과가 변경되었습니다. 창을 닫고 현재 항목을 다시 확인하세요.';
                return;
            }
            const submit = dialog.querySelector('[type="submit"]');
            submit.disabled = true;
            try {
                const response = await fetch('/dx/layer1/api/retail-reviews/', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
                    body: JSON.stringify({context, action: done ? 'cancel' : 'confirm',
                        memo: dialog.querySelector('textarea').value, revision: record ? record.revision : 0}),
                });
                const payload = await response.json();
                if (!response.ok || !payload.review) throw new Error(payload.error || '저장하지 못했습니다. 다시 시도하세요.');
                if (getSelectedDate() === context.date && loadedDate === context.date) {
                    records = records.filter(item => stable(item.context) !== key).concat(payload.review);
                    repaint();
                }
                dialog.close();
            } catch (failure) {
                error.textContent = failure.message;
                submit.disabled = false;
            }
        };
        dialog.showModal();
    }
    L1.retailReview = {load, decorate, badge, open, reviewed, reasons};
})();
