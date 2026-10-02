// Re-evaluate live MAIN/BSR counts against saved historical bases.
(function () {
    const countries = {retail: 'SEA', seda_retail: 'SEDA', siel_retail: 'SIEL', seg_retail: 'SEG', sem_retail: 'SEM', tse_retail: 'TSE'};
    const pending = ['PENDING', 'COLLECTING', 'ANALYZING', 'VERIFYING'];
    function metrics(row, country) {
        if (row._volumeCounts) return row._volumeCounts;
        const items = Object.fromEntries((row.items || []).map(item => [item.name, Number(item.count || 0)]));
        const totalKey = ['raw_count', 'actual', 'count', 'total'].find(key => row[key] != null);
        return {main: Number(row.main_count == null ? items['Main Rank'] || 0 : row.main_count),
            bsr: Number(row.bsr_count == null ? items['BSR Rank'] || 0 : row.bsr_count),
            total: Number((['SEM', 'TSE'].includes(country) || row.bsr_applicable === false) && row.actual != null ? row.actual : totalKey ? row[totalKey] : 0)};
    }
    function restore(item) {
        if (!Object.prototype.hasOwnProperty.call(item, '_volumeBaseStatus')) item._volumeBaseStatus = item.status;
        item.status = item._volumeBaseStatus;
        delete item._volumeCounts;
        delete item._volumeBatchId;
        delete item.volume_alerts;
        delete item.verification_reason;
    }
    function worst(rows, fallback = 'VERIFYING') {
        const priority = {OK: 0, PENDING: 1, COLLECTING: 2, ANALYZING: 2, VERIFYING: 3,
            UNASSESSED: 3, REVIEW: 4, VOLUME_HIGH: 4, VOLUME_REVIEW: 4, WARNING: 5,
            VOLUME_LOW: 6, CRITICAL: 6, ERROR: 7};
        return rows.length ? rows.reduce((a, b) => (priority[a.status] || 0) >= (priority[b.status] || 0) ? a : b).status : fallback;
    }
    function windowComplete(check, slot, row) {
        if (row.collection_phase) return row.collection_phase === 'complete';
        if (check.phase && check.phase !== 'complete') return false;
        const original = item => Object.prototype.hasOwnProperty.call(item, '_volumeBaseStatus') ? item._volumeBaseStatus : item.status;
        return !pending.includes(original(row)) && !pending.includes(row.collection_status)
            && (check.phase === 'complete' || !pending.includes(original(slot)));
    }
    function received(row, country) {
        return Object.values(metrics(row, country)).some(value => value > 0)
            || Number(row.raw_count || row.actual_count || 0) > 0;
    }
    function collectedToday(check, slots, retailer, country) {
        return slots.some(slot => (slot.retailers || []).some(row =>
            row.retailer === retailer && windowComplete(check, slot, row)
            && row.status !== 'ERROR' && received(row, country)));
    }
    function compare(metric, current, rule) {
        if (!rule || !Number.isInteger(current) || current < 0 || !Number.isFinite(rule.baseline) || rule.baseline <= 0) return null;
        const fixed = metric === 'bsr' && rule.rule === 'fixed_100' && rule.baseline === 100;
        if (!fixed && (rule.rule !== 'median_28d' || !Number.isFinite(rule.days) || rule.days < 5 || !Number.isFinite(rule.low_percent))) return null;
        const baseline = rule.baseline, change = (current - baseline) * 100;
        let status, reason;
        if (fixed ? current < baseline : change <= -baseline * rule.low_percent) {
            status = 'VOLUME_LOW';
            reason = fixed ? `BSR 기준 100개 / 수집 ${current}개 / ${100 - current}개 부족`
                : `${metric.toUpperCase()} 과거 중앙값 ${baseline}개 / 수집 ${current}개 / ${rule.low_percent}% 이상 감소`;
        } else if (rule.review_percent != null && change <= -baseline * rule.review_percent) {
            status = 'VOLUME_REVIEW';
            reason = `${metric.toUpperCase()} 과거 중앙값 ${baseline}개 / 수집 ${current}개 / ${rule.review_percent}% 이상 감소 / 확인 필요`;
        } else if (rule.high_percent != null && change >= baseline * rule.high_percent) {
            status = 'VOLUME_HIGH';
            reason = `${metric.toUpperCase()} 과거 중앙값 ${baseline}개 / 수집 ${current}개 / ${rule.high_percent}% 이상 증가 / 확인 필요`;
        }
        return {status: status || 'OK', alert: status ? {metric, baseline, actual: current,
            percent: Math.round(change / baseline * 10) / 10, status, rule: rule.rule, reason} : null};
    }
    function decorate(data, payload, selectedDate, seaSummaries) {
        const snapshots = payload && payload.policy_version === 3 && payload.inspection_date === selectedDate ? payload.snapshots || [] : [];
        (data.checks || []).forEach(check => {
            const country = countries[check.check_type];
            if (!country) return;
            restore(check);
            const snapshot = snapshots.find(s => s.country === country && s.available);
            (check.categories || []).forEach(cat => {
                restore(cat);
                const product = String(cat.name || cat.category || '').toUpperCase();
                const slots = cat.time_slots || [{name: 'daily', retailers: cat.retailers || []}];
                slots.forEach((slot, slotIndex) => {
                    restore(slot);
                    (slot.retailers || []).forEach(row => {
                        restore(row);
                        const summary = country === 'SEA' && seaSummaries && seaSummaries[product.toLowerCase()];
                        const displayedRetailer = summary && (summary.summary || []).find(r => r.retailer === row.retailer);
                        const displayedRows = displayedRetailer && displayedRetailer.rows || [];
                        const displayed = displayedRows.find(r => r.time_slot === slot.name) || displayedRows[slotIndex];
                        const datesMatch = (!check.inspection_date || check.inspection_date === selectedDate)
                            && (!cat.inspection_date || cat.inspection_date === selectedDate)
                            && (!displayed || (!(summary.inspection_date || summary.date) || (summary.inspection_date || summary.date) === selectedDate)
                                && (!cat.source_date || !summary.source_date || cat.source_date === summary.source_date));
                        if (displayed && datesMatch) {
                            row._volumeCounts = {main: Number(displayed.main), bsr: Number(displayed.bsr), total: Number(displayed.total)};
                            row._volumeBatchId = String(displayed.batch_id || displayedRetailer.batch_id || '');
                        }
                        const counts = metrics(row, country);
                        const saved = datesMatch && snapshot && (!cat.source_date || cat.source_date === snapshot.source_date)
                            && (!check.source_date || check.source_date === snapshot.source_date)
                            && (snapshot.rows || []).find(s => s.product === product && s.retailer === row.retailer && s.slot === (slot.name || 'daily'));
                        const complete = windowComplete(check, slot, row);
                        row.observation_state = saved && saved.observation_state || 'unknown';
                        row.observation_days = row.observation_state === 'observing'
                            ? Math.min(5, Number(saved.observation_prior_days || 0) + (collectedToday(check, slots, row.retailer, country) ? 1 : 0)) : null;
                        row.volume_alerts = [];
                        row.volume_comparison_state = 'unavailable';
                        row.verification_state = row.status === 'ERROR' ? 'error' : complete ? 'waiting' : received(row, country) ? 'waiting' : 'collecting';
                        if (row.status === 'ERROR') return;
                        if (!complete) {
                            row.status = check.phase === 'pending' || row.collection_phase === 'pending' ? 'PENDING' : 'COLLECTING';
                            return;
                        }
                        if (datesMatch && (!received(row, country) || counts.main === 0)) {
                            row.status = 'CRITICAL';
                            row.verification_state = 'ready';
                            return;
                        }
                        const decisions = ['main', 'bsr'].map(metric => compare(metric, counts[metric], saved && saved.observation_state === 'ready' && saved.rules && saved.rules[metric]));
                        row.volume_alerts = decisions.filter(Boolean).map(decision => decision.alert).filter(Boolean);
                        const ready = decisions.every(Boolean);
                        row.volume_comparison_state = ready ? 'ready' : saved ? saved.observation_state === 'observing' ? 'observing' : 'insufficient' : 'unavailable';
                        row.status = worst(decisions.filter(Boolean).concat(ready ? [] : [{status: 'VERIFYING'}]));
                        row.verification_state = ready ? 'ready' : 'waiting';
                        if (row.status === 'VERIFYING') {
                            row.verification_reason = !payload ? '수집량 판정을 불러오는 중입니다.'
                                : payload.load_state === 'error' ? '수집량 판정을 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.'
                                : row.observation_state === 'observing' ? '신규 리테일러의 수집 이력을 관찰하고 있습니다.'
                                : '현재 MAIN·BSR 건수를 비교할 유효한 과거 중앙값이 아직 준비되지 않았습니다.';
                        }
                    });
                    slot.status = worst(slot.retailers || [], slot.status === 'ERROR' ? 'ERROR' : 'VERIFYING');
                });
                cat.status = worst(slots, cat.status === 'ERROR' ? 'ERROR' : 'VERIFYING');
            });
            check.status = worst(check.categories || [], check.status === 'ERROR' ? 'ERROR' : 'VERIFYING');
        });
        if (data.summary && !data.error) {
            const targets = (data.checks || []).filter(check => check.is_target_date);
            data.summary.passed = targets.filter(check => check.status === 'OK').length;
            data.summary.failed = targets.filter(check => ['CRITICAL', 'VOLUME_LOW'].includes(check.status)).length;
            data.summary.total_completed = targets.filter(check => !pending.includes(check.status)).length;
            data.summary.pass_rate = targets.length ? Math.round(data.summary.passed * 1000 / targets.length) / 10 : 0;
        }
        return data;
    }
    let loadGeneration = 0, activeController = null;
    async function load(day) {
        const generation = ++loadGeneration;
        if (activeController) activeController.abort();
        for (let attempt = 0; attempt < 3; attempt++) {
            if (attempt) await new Promise(resolve => setTimeout(resolve, attempt * 500));
            if (generation !== loadGeneration) return null;
            const controller = new AbortController();
            activeController = controller;
            const timeout = setTimeout(() => controller.abort(), 8000);
            try {
                const response = await fetch('/dx/layer1/api/collection-volume/?date=' + encodeURIComponent(day),
                    {signal: controller.signal, cache: 'no-store'});
                if (!response.ok) continue;
                const result = await response.json();
                if (generation !== loadGeneration) return null;
                if (result && result.policy_version === 3 && result.inspection_date === day && Array.isArray(result.snapshots)) return result;
            } catch (_) {
                if (generation !== loadGeneration) return null;
            } finally {
                clearTimeout(timeout);
                if (activeController === controller) activeController = null;
            }
        }
        return {inspection_date: day, policy_version: 3, snapshots: [], load_state: 'error'};
    }
    L1.collectionVolume = {load, decorate, metrics};
})();
