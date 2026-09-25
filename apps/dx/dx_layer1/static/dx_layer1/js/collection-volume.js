// History comparisons use saved decisions; fixed BSR targets use current counts.
// Never requests history or blocks the counts request.
(function () {
    const countries = {retail: 'SEA', seda_retail: 'SEDA', siel_retail: 'SIEL', seg_retail: 'SEG', sem_retail: 'SEM', tse_retail: 'TSE'};
    const pending = ['PENDING', 'COLLECTING', 'ANALYZING'];
    function metrics(row, country) {
        const items = Object.fromEntries((row.items || []).map(item => [item.name, Number(item.count || 0)]));
        const totalKey = ['raw_count', 'actual', 'count', 'total'].find(key => row[key] != null);
        return {main: Number(row.main_count == null ? items['Main Rank'] || 0 : row.main_count),
            bsr: Number(row.bsr_count == null ? items['BSR Rank'] || 0 : row.bsr_count),
            total: Number((['SEM', 'TSE'].includes(country) || row.bsr_applicable === false) && row.actual != null ? row.actual : totalKey ? row[totalKey] : 0)};
    }
    function restore(item) {
        if (item._volumeBaseStatus === undefined) item._volumeBaseStatus = item.status;
        item.status = item._volumeBaseStatus;
        delete item.volume_alerts;
    }
    function merge(base, alerts) {
        if (base === 'WARNING' && alerts.some(alert => alert.metric === 'bsr' && alert.status === 'VOLUME_LOW')) return 'VOLUME_LOW';
        if (['CRITICAL', 'ERROR', 'WARNING'].includes(base) || pending.includes(base)) return base;
        if (alerts.some(alert => alert.status === 'VOLUME_LOW')) return 'VOLUME_LOW';
        if (alerts.some(alert => alert.status === 'VOLUME_REVIEW')) return 'VOLUME_REVIEW';
        if (alerts.some(alert => alert.status === 'VOLUME_HIGH')) return 'VOLUME_HIGH';
        return base;
    }
    function variableBsr(country, product, retailer) {
        const name = String(retailer || '').trim().toLowerCase();
        return (country === 'SEA' && ['REF', 'LDY'].includes(product) && name === 'lowes')
            || (name === 'amazon' && ({SEA: ['TV'], SIEL: ['TV', 'REF', 'LDY'], SEG: ['TV', 'REF']}[country] || []).includes(product))
            || (country === 'SEM' && name === 'homedepot');
    }
    function fixedBsrAlert(check, cat, slot, row, counts, displayed, summary, selectedDate) {
        if ((check.phase && check.phase !== 'complete') || pending.includes(row.status)
            || pending.includes(slot.status) || row.status === 'ERROR'
            || pending.includes(row.collection_status)
            || (check.inspection_date && check.inspection_date !== selectedDate)
            || (cat.inspection_date && cat.inspection_date !== selectedDate)) return null;
        if (displayed && ((summary.inspection_date || summary.date) && (summary.inspection_date || summary.date) !== selectedDate
            || (cat.source_date && summary.source_date && cat.source_date !== summary.source_date))) return null;
        const item = (row.items || []).find(item => item.name === 'BSR Rank');
        const raw = displayed ? displayed.bsr : row.bsr_count != null ? row.bsr_count : item && item.count;
        if (raw == null || String(raw).trim() === '') return null;
        const bsr = Number(raw);
        const current = displayed || counts;
        if (!Number.isInteger(bsr) || bsr < 0 || bsr >= 100
            || ['main', 'bsr', 'total'].every(key => Number(current[key] || 0) === 0)) return null;
        return {metric: 'bsr', baseline: 100, actual: bsr, percent: bsr - 100,
            status: 'VOLUME_LOW', rule: 'fixed_100',
            reason: `BSR 기준 100개 / 수집 ${bsr}개 / ${100 - bsr}개 부족`};
    }
    function decorate(data, payload, selectedDate, seaSummaries) {
        const snapshots = payload && payload.inspection_date === selectedDate ? payload.snapshots || [] : [];
        (data.checks || []).forEach(check => {
            const country = countries[check.check_type];
            if (!country) return;
            restore(check);
            const snapshot = snapshots.find(s => s.country === country && s.available);
            const checkAlerts = [];
            (check.categories || []).forEach(cat => {
                restore(cat);
                const product = String(cat.name || cat.category || '').toUpperCase();
                const catAlerts = [];
                const slots = cat.time_slots || [{name: 'daily', retailers: cat.retailers || []}];
                slots.forEach((slot, slotIndex) => {
                    restore(slot);
                    const slotAlerts = [];
                    (slot.retailers || []).forEach(row => {
                        restore(row);
                        const counts = metrics(row, country);
                        const saved = snapshot && (snapshot.rows || []).find(s => s.product === product && s.retailer === row.retailer && s.slot === (slot.name || 'daily'));
                        const summary = country === 'SEA' && seaSummaries && seaSummaries[product.toLowerCase()];
                        const displayedRetailer = summary && (summary.summary || []).find(r => r.retailer === row.retailer);
                        const displayedRows = displayedRetailer && displayedRetailer.rows || [];
                        const displayed = displayedRows.find(r => r.time_slot === slot.name) || displayedRows[slotIndex];
                        const displayMatches = !displayed || (saved && ['main', 'bsr', 'total'].every(key => Number(displayed[key] || 0) === saved[key])
                            && String(displayed.batch_id || displayedRetailer.batch_id || '') === String(saved.batch_id || ''));
                        const matches = saved && saved.complete && !pending.includes(row.status)
                            && displayMatches
                            && (!check.phase || check.phase === 'complete') && !pending.includes(slot.status)
                            && (!cat.source_date || cat.source_date === snapshot.source_date)
                            && String(saved.batch_id || '') === String(row.batch_id || '')
                            && ['main', 'bsr', 'total'].every(key => counts[key] === saved[key]);
                        row.volume_comparison_state = matches ? saved.comparison_state : 'unavailable';
                        row.volume_alerts = matches ? (saved.alerts || []).slice() : [];
                        if (!variableBsr(country, product, row.retailer)) {
                            row.volume_alerts = row.volume_alerts.filter(alert => alert.metric !== 'bsr');
                            const fixedAlert = fixedBsrAlert(check, cat, slot, row, counts, displayed, summary, selectedDate);
                            if (fixedAlert) row.volume_alerts.push(fixedAlert);
                        }
                        if (!matches && !row.volume_alerts.length) return;
                        const homeDepotReady = matches && country === 'SEA' && row.retailer === 'HomeDepot'
                            && ['REF', 'LDY'].includes(product) && row.status === 'UNASSESSED'
                            && saved.comparison_state === 'ready' && counts.total > 0;
                        row.status = merge(homeDepotReady ? 'OK' : row.status, row.volume_alerts);
                        slotAlerts.push(...row.volume_alerts);
                    });
                    slot.status = merge(slot.status, slotAlerts);
                    catAlerts.push(...slotAlerts);
                });
                cat.status = merge(cat.status, catAlerts);
                checkAlerts.push(...catAlerts);
            });
            check.status = merge(check.status, checkAlerts);
        });
        if (data.summary && !data.error) {
            const targets = (data.checks || []).filter(check => check.is_target_date);
            data.summary.passed = targets.filter(check => check.status === 'OK').length;
            data.summary.failed = targets.filter(check => ['CRITICAL', 'VOLUME_LOW'].includes(check.status)).length;
        }
        return data;
    }
    async function load(day) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const response = await fetch('/dx/layer1/api/collection-volume/?date=' + encodeURIComponent(day), {signal: controller.signal});
            if (!response.ok) return null;
            return await response.json();
        } catch (_) { return null; }
        finally { clearTimeout(timeout); }
    }
    L1.collectionVolume = {load: load, decorate: decorate, metrics: metrics, merge: merge};
})();
