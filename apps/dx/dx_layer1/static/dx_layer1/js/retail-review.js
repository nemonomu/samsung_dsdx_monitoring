// Keep automatic verdicts for audit; review decisions never change collected counts.
(function () {
    const countries = {retail: 'SEA', seda_retail: 'SEDA', siel_retail: 'SIEL', seg_retail: 'SEG', sem_retail: 'SEM', tse_retail: 'TSE', seib_retail: 'SEIB', seuk_retail:'SEUK'};
    const reviewStatuses = ['REVIEW', 'VOLUME_REVIEW', 'VOLUME_HIGH', 'VOLUME_LOW'];
    let records = [], previousRecords = [], loadedDate = '', loadError = '', generation = 0, targets = [];
    const attr = value => esc(String(value)).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const stable = value => JSON.stringify(value, function (_, item) {
        return item && !Array.isArray(item) && typeof item === 'object'
            ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
    });
    const reviewed = (row, metric) => {
        if (row._metricDecisions) {
            const metrics = metric ? [metric] : [...new Set((row.volume_alerts || []).map(a=>a.metric).filter(m=>['main','bsr'].includes(m)))];
            return metrics.length > 0 && metrics.every(m=>row._metricDecisions[m]?.action === 'confirm');
        }
        return Boolean(row._normalReview && row._normalReview.active);
    };
    const rejected = (row, metric) => row._metricDecisions
        ? Object.entries(row._metricDecisions).some(([m, d])=>(!metric || metric===m) && d?.action==='reject')
        : Boolean(row._normalReview && !row._normalReview.active && row._normalReview.history.at(-1)?.action === 'reject');
    const number = value => Number(value).toLocaleString('ko-KR', {maximumFractionDigits: 2});
    const outstandingLow = row => row._metricDecisions
        ? (row.volume_alerts || []).some(a=>a.status==='VOLUME_LOW' && !reviewed(row,a.metric))
        : row.status === 'VOLUME_LOW' && !reviewed(row);

    function alertBasis(alerts) {
        return alerts.filter(a=>['main','bsr'].includes(a.metric)).map(a=>[a.metric,a.baseline,a.actual,
            a.rule || (a.metric==='main'?'median_28d':null),!!a.exact,
            a.metric==='bsr' && a.exact && a.status==='VOLUME_REVIEW'?'VOLUME_LOW':a.status]).sort((a,b)=>{
                for (let i=0;i<a.length;i++) {
                    if (a[i]===b[i]) continue;
                    return typeof a[i]==='number' && typeof b[i]==='number' ? a[i]-b[i] : String(a[i]).localeCompare(String(b[i]));
                }
                return 0;
            });
    }

    function attachMetricDecisions(row, context) {
        const candidates = records.filter(r=>['country','product','retailer','slot','source_date','batch_id'].every(k=>r.context[k]===context[k]));
        if (!candidates.some(r=>r.context.version===2)) return;
        const current = alertBasis(JSON.parse(context.basis).alerts || []);
        const decisions = {};
        candidates.sort((a,b)=>(a.history.at(-1)?.at || '').localeCompare(b.history.at(-1)?.at || '')).forEach(record=>{
            const c=record.context, metrics=c.version===2?[c.metric]:['main','bsr'];
            metrics.forEach(m=>decisions[m]=null);
            if (c.date!==context.date || stable(c.counts)!==stable(context.counts)) return;
            try {
                const basis=c.version===2?JSON.parse(c.basis).alerts:alertBasis(JSON.parse(c.basis).alerts || []);
                const expected=c.version===2?current.filter(a=>a[0]===c.metric):current;
                if (!basis.length || stable(basis)!==stable(expected)) return;
                const event=record.history.at(-1);
                if ((record.active && event?.action==='confirm') || (!record.active && event?.action==='reject')) {
                    basis.forEach(a=>decisions[a[0]]=event);
                }
            } catch (_) {}
        });
        row._metricDecisions=decisions;
    }

    function reasons(row) {
        const result = (row.volume_alerts || []).filter(alert => reviewStatuses.includes(alert.status)).map(alert =>
            alert.reason || `${String(alert.metric || '수집량').toUpperCase()} 기준 ${number(alert.baseline)}건 / 수집 ${number(alert.actual)}건 / ${number(alert.percent)}% 변동`);
        if (row.status === 'REVIEW' || (!row.volume_comparison_state && (row._volumeBaseStatus === 'REVIEW' || row._reviewAutomatic?.status === 'REVIEW'))) {
            const baseline = row.expected_precise == null ? row.expected : row.expected_precise;
            const actual = row.main_count == null ? row.actual : row.main_count;
            result.unshift(Number(actual) === 0 ? 'MAIN 수집 0건 · MAIN 데이터가 없어 확인이 필요합니다.' : baseline == null
                ? 'MAIN 비교 기준을 확인할 수 없습니다. 수집 결과를 확인해 주세요.'
                : `MAIN 과거 ${row.history_day_count || ''}일 평균 ${number(baseline)}건 / 수집 ${number(actual)}건 / ${number(Math.abs(actual - baseline))}건 ${actual < baseline ? '감소' : '증가'}\n판정 기준: 평균 대비 ${number(row.allowed_deviation == null ? 50 : row.allowed_deviation)}건 이상 차이`);
        }
        return [...new Set(result)].sort();
    }

    function prepareReview(row, country, product, slot, day, sourceDate) {
        if (row._reviewAutomatic && row._reviewPreparedSignature === stable({status:row.status, volume_alerts:row.volume_alerts})) Object.assign(row, row._reviewAutomatic);
        row._reviewAutomatic = {status: row.status, volume_alerts: row.volume_alerts};
        row._previousReview = null;
        const counts = L1.collectionVolume.metrics(row, country);
        if (['POLICY_PENDING','ERROR','CRITICAL','WARNING','COLLECTING','PENDING','ANALYZING','UNASSESSED'].includes(row.status)
            || counts.main <= 0 || counts.total <= 0) return;
        const previous = previousRecords.find(record => {
            const c = record.context;
            return record.active && c.date < day && c.source_date < sourceDate && c.country === country
                && c.product === product && c.retailer === row.retailer && c.slot === slot && c.counts[1] === counts.bsr;
        });
        row._previousReview = previous;
        const observing = row.observation_state === 'observing';
        row.volume_alerts = (row.volume_alerts || []).map(alert => {
            if (alert.status !== 'VOLUME_LOW' || alert.metric !== 'bsr' || !alert.exact) return alert;
            let sameBasis = false;
            if (previous) {
                try { sameBasis = (JSON.parse(previous.context.basis).alerts || []).some(old =>
                    old.metric === alert.metric && old.actual === alert.actual && old.baseline === alert.baseline
                    && old.rule === alert.rule && old.exact === alert.exact); } catch (_) {}
            }
            return observing || sameBasis ? {...alert, status:'VOLUME_REVIEW', reason:alert.reason + ' / 확인 필요'} : alert;
        });
        if (row.volume_alerts.some(a => a.status === 'VOLUME_LOW')) return;
        const requiresReview = row.volume_alerts.some(a => a.status === 'VOLUME_REVIEW');
        if (observing && requiresReview && (!reviewStatuses.includes(row.status) || row.status === 'VOLUME_LOW')) row.volume_alerts.push({metric:'observation', status:'VOLUME_REVIEW',
            reason:'신규 수집 · 관찰 중 (' + row.observation_days + '/5일) / 실제 수집 결과 확인 필요'});
        if ((!reviewStatuses.includes(row.status) || row.status === 'VOLUME_LOW') && requiresReview) row.status = 'VOLUME_REVIEW';
        // An exact-target retailer with an already normal 300/100 collection needs no manual observation review.
        const exactTarget = (country === 'SEUK' && row.retailer === 'Currys') || (country === 'SEG' && row.retailer === 'Expert')
            || (country === 'SEA' && ((row.retailer === 'Costco' && product !== 'TV') || (row.retailer === 'Bestbuy' && product === 'LDY_DRYER')));
        if (observing && exactTarget && row.status === 'VERIFYING' && row._volumeBaseStatus === 'OK'
            && counts.main === 300 && counts.bsr === 100 && !row.volume_alerts.length) row.status = 'OK';
    }

    function aggregate(rows, fallback) {
        rows = L1.collectionVolume.operatingRows(rows);
        const priority = {OK:0,PENDING:1,COLLECTING:2,ANALYZING:2,VERIFYING:3,INSUFFICIENT:3,POLICY_PENDING:3,UNASSESSED:3,
            REVIEW:4,VOLUME_HIGH:4,VOLUME_REVIEW:4,WARNING:5,VOLUME_LOW:6,CRITICAL:6,ERROR:7};
        return rows.reduce((status,row) => (priority[row.status] || 0) > (priority[status] || 0) ? row.status : status, rows.length ? 'OK' : fallback);
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
                        prepareReview(row, country, String(cat.name || cat.category || '').toUpperCase(),
                            slot.name || 'daily', day, cat.source_date || check.source_date || day);
                        row._reviewPreparedSignature = stable({status:row.status, volume_alerts:row.volume_alerts});
                        delete row._reviewContext;
                        delete row._normalReview;
                        delete row._metricDecisions;
                        row._reviewReasons = reasons(row);
                        if (!reviewStatuses.includes(row.status) || L1.collectionVolume.metrics(row, country).main <= 0
                            || L1.collectionVolume.metrics(row, country).total <= 0) return;
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
                        attachMetricDecisions(row, context);
                        row._reviewTarget = targets.push(row) - 1;
                    });
                    slot._reviewRows = rows;
                    slot.status = aggregate(rows, slot.status);
                    catRows.push(...rows);
                });
                cat._reviewRows = catRows;
                cat.status = aggregate(catRows, cat.status);
                checkRows.push(...catRows);
            });
            check._reviewRows = checkRows;
            check.status = aggregate(checkRows, check.status);
        });
        if (data.summary && !data.error) {
            const checked = (data.checks || []).filter(c=>c.is_target_date);
            data.summary.failed = checked.filter(c=> (c._reviewRows || []).length
                ? c._reviewRows.some(row => rejected(row) || outstandingLow(row) || ['CRITICAL','ERROR'].includes(row.status))
                : ['CRITICAL','VOLUME_LOW','ERROR'].includes(c.status)).length;
        }
    }

    function recordHtml(record) {
        const event = record?.history?.at(-1);
        if (!event) return '';
        return '<strong class="l1-review-memo">' + esc(event.memo) + '</strong><span class="l1-review-author">'
            + esc(event.username + ' · ' + new Date(event.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' (KST)') + '</span>';
    }

    function badge(row, status) {
        if (row._reviewContext && reviewStatuses.includes(status)) {
            const done = reviewed(row);
            const bad = rejected(row);
            if (row._metricDecisions && status === 'VOLUME_LOW' && !outstandingLow(row)) status = 'VOLUME_REVIEW';
            const title = (done ? '정상 확인\n\n최초 사유\n' : '확인 필요\n')
                + row._reviewReasons.join('\n\n') + '\n\n클릭하여 ' + (done ? '확인 이력 보기 · 확인 취소' : '검토');
            return `<button type="button" class="status-badge ${bad ? 'critical' : done ? 'ok' : status === 'VOLUME_LOW' ? 'critical' : 'volume-review'} l1-review-badge" title="${attr(bad ? '이상 확정\n'+'\n클릭하여 이력 보기 · 확정 취소' : title)}" aria-label="${attr(bad ? '이상 확정' : title)}" onclick="event.stopPropagation();L1.retailReview.open(${row._reviewTarget})">${bad ? '이상 확정' : done ? '✓ 정상 확인' : '<span class="status-dot"></span>' + (status === 'VOLUME_LOW' ? '이상' : '확인 필요')}</button>`;
        }
        const rows = L1.collectionVolume.operatingRows(row._reviewRows || []);
        const reviews = rows.filter(item => item._reviewContext);
        if (!reviews.length || !['OK', ...reviewStatuses].includes(status)) return null;
        if (reviews.some(item=>rejected(item))) return '<span class="status-badge critical">이상 확정</span>';
        const pending = reviews.filter(item => !reviewed(item));
        const done = !pending.length && rows.every(item => (item.status === 'OK' || reviewed(item)) && Number(item.batch_count || 0) < 2);
        // Confirmed reviews no longer mask siblings that are still collecting.
        // Keep automatic verdicts intact for review identity and cancellation.
        if (!pending.length && !done) {
            const priority = {OK: 0, PENDING: 1, COLLECTING: 2, ANALYZING: 2,
                VERIFYING: 3, INSUFFICIENT: 3, POLICY_PENDING: 3, UNASSESSED: 3, REVIEW: 4, VOLUME_HIGH: 4,
                VOLUME_REVIEW: 4, WARNING: 5, VOLUME_LOW: 6, CRITICAL: 6, ERROR: 7};
            const remaining = rows.map(item => Number(item.batch_count || 0) >= 2
                ? 'REVIEW' : reviewed(item) ? 'OK' : item.status);
            const effective = remaining.reduce((worst, value) =>
                (priority[value] || 0) > (priority[worst] || 0) ? value : worst, 'OK');
            return getStatusBadge(effective);
        }
        const title = reviews.map(item => `${item.retailer} · ${reviewed(item) ? '정상 확인' : '확인 필요'}\n${item._reviewReasons.join('\n')}`).join('\n\n');
        const low = pending.some(outstandingLow);
        return `<span class="status-badge ${done ? 'ok' : low ? 'critical' : 'volume-review'}" tabindex="0" title="${attr(title)}" aria-label="${attr(title)}">${done ? '✓ 정상 확인' : '<span class="status-dot"></span>' + (low ? '이상' : '확인 필요') + (pending.length ? ' · 미확인 ' + pending.length + '건' : '')}</span>`;
    }

    async function load(day) {
        const current = ++generation;
        loadedDate = ''; loadError = ''; records = []; previousRecords = [];
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try {
            const response = await fetch('/dx/layer1/api/retail-reviews/?date=' + encodeURIComponent(day), {signal: controller.signal});
            if (!response.ok) throw new Error('검토 기록을 불러오지 못했습니다. 새로고침 후 다시 시도하세요.');
            const payload = await response.json();
            if (current !== generation) return;
            if (payload.date !== day || !Array.isArray(payload.reviews)) throw new Error('검토 기록의 날짜가 일치하지 않습니다.');
            records = payload.reviews; previousRecords = payload.previous_reviews || []; loadedDate = day;
        } catch (error) {
            if (current === generation) loadError = '검토 기록을 불러오지 못했습니다. 새로고침 후 다시 시도하세요.';
        } finally { clearTimeout(timer); }
    }

    function repaint() {
        if (!currentStatsData) return;
        const expanded = Array.from(document.querySelectorAll('[id].show')).map(element => element.id);
        if (document.getElementById('section-content') && typeof renderSeaRetailSection === 'function') renderSeaRetailSection(currentStatsData);
        else renderLayer1Stats(currentStatsData);
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
        if (row._metricDecisions && window.CollectionVolumeReview) {
            const metrics=[...new Set((row.volume_alerts || []).map(a=>a.metric).filter(m=>['main','bsr'].includes(m)))];
            const launch = metric => CollectionVolumeReview.open({country:context.country,product:context.product,
                retailer:context.retailer,slot:context.slot,source_date:context.source_date,metric});
            if (metrics.length===1) return launch(metrics[0]);
            const picker=document.createElement('dialog');
            picker.className='l1-review-dialog';
            picker.innerHTML='<h2>확인할 수집 항목</h2>'+metrics.map(m=>`<p><button type="button" data-metric="${m}">${m.toUpperCase()} · ${reviewed(row,m)?'정상 확인 완료':rejected(row,m)?'이상 확정':'미처리'}</button></p>`).join('')+'<button type="button" data-close>닫기</button>';
            picker.querySelectorAll('[data-metric]').forEach(b=>b.onclick=()=>{picker.close();launch(b.dataset.metric);});
            picker.querySelector('[data-close]').onclick=()=>picker.close();
            picker.addEventListener('close',()=>picker.remove(),{once:true});
            document.body.appendChild(picker);picker.showModal();return;
        }
        const key = stable(context);
        const record = row._normalReview;
        const done = reviewed(row);
        const bad = rejected(row), decided = done || bad;
        const unavailable = loadedDate !== context.date;
        const dialog = document.createElement('dialog');
        dialog.className = 'l1-review-dialog';
        dialog.setAttribute('aria-labelledby', 'l1-review-title');
        dialog.innerHTML = `<form>
            <h2 id="l1-review-title">${bad ? '이상 확정 이력' : done ? '정상 확인 이력' : '수집 결과 확인'}</h2>
            <p class="l1-review-target">${esc(context.country)} · ${esc(context.product)} · ${esc(context.retailer)}<br>검수일 ${esc(context.date)} · 데이터일 ${esc(context.source_date)}<br>배치 ${esc(context.batch_id || '정보 없음')}</p>
            <div class="l1-review-reasons"><strong>${done ? '최초 확인 필요 사유' : '확인 필요 사유'}</strong><p>${esc(context.reasons.join('\n\n'))}</p></div>
            <p>현재 수집: MAIN ${number(context.counts[0])}건 · BSR ${number(context.counts[1])}건 · 총 ${number(context.counts[2])}건</p>
            ${row._previousReview ? '<details class="l1-previous-review"><summary>같은 BSR 수량의 이전 정상 확인 · '+esc(row._previousReview.context.date)+'</summary><p>'+recordHtml(row._previousReview)+'</p><p>이전 배치 '+esc(row._previousReview.context.batch_id)+' · BSR '+number(row._previousReview.context.counts[1])+'건</p></details>' : ''}
            ${decided ? '<p class="' + (done ? 'l1-review-confirmed' : 'l1-review-rejected') + '">' + (done ? '✓ 정상 확인' : '이상 확정') + recordHtml(record) + '</p>' : ''}
            ${(record && record.history.length) ? '<details><summary>확인·취소 이력</summary>' + record.history.map(event => '<p>' + esc((event.action === 'confirm' ? '정상 확인' : event.action === 'reject' ? '이상 확정' : '확인 취소') + ' · ' + event.username + ' · ' + new Date(event.at).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'}) + ' (KST)\n' + event.memo) + '</p>').join('') + '</details>' : ''}
            <label for="l1-review-memo">${decided ? '취소 사유' : '수집 결과 확인 근거'}</label>
            <textarea id="l1-review-memo" required maxlength="1000" rows="3" placeholder="${decided ? '확인을 취소하는 이유를 입력하세요.' : '예: 원본 사이트 상품 수와 일치함'}"></textarea>
            <p class="l1-review-help">이 확인은 해당 날짜·배치·수집 수치·판정 사유에만 적용됩니다.</p>
            <p class="l1-review-error" role="alert">${unavailable ? esc(loadError || '검토 기록을 불러오는 중입니다. 잠시 후 다시 열어 주세요.') : !context.batch_id ? '배치 정보가 없어 정상 확인할 수 없습니다.' : ''}</p>
            <div class="l1-review-actions"><button type="button" data-close>닫기</button><button type="submit" data-primary ${unavailable || !context.batch_id ? 'disabled' : ''}>${decided ? '확인 취소' : '정상 확인'}</button>${!decided ? '<button type="submit" data-reject '+(unavailable || !context.batch_id ? 'disabled' : '')+'>이상 확정</button>' : ''}</div>
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
            const action = decided ? 'cancel' : event.submitter?.hasAttribute('data-reject') ? 'reject' : 'confirm';
            dialog.querySelectorAll('[type="submit"]').forEach(b=>b.disabled=true);
            try {
                const response = await fetch('/dx/layer1/api/retail-reviews/', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
                    body: JSON.stringify({context, action,
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
                dialog.querySelectorAll('[type="submit"]').forEach(b=>b.disabled=false);
            }
        };
        dialog.showModal();
    }
    L1.retailReview = {load, decorate, badge, open, reviewed, rejected, reasons};
    window.addEventListener?.('collection-review-changed', async () => {
        if (typeof currentData === 'undefined' || !currentData) return;
        await load(getSelectedDate());
        repaint();
    });
})();
