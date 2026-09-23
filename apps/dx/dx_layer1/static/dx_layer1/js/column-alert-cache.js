(function () {
    'use strict';
    // Only derived comparison counts are retained, never raw product/review data.
    // Per-tab, per-user, date/retailer-specific and short-lived across navigation.
    const storageKey = 'column-alert-comparisons:v1:' + (window.LAYER1.username || '');
    const ttl = 60000;
    let entries = {};
    try { entries = JSON.parse(window.sessionStorage.getItem(storageKey) || '{}'); } catch (_) {}
    if (!entries || typeof entries !== 'object' || Array.isArray(entries)) entries = {};
    const keyFor = (job, date) => JSON.stringify([date, job.country, job.product, job.retailer]);
    const fresh = entry => entry && Number.isFinite(entry.at)
        && Date.now() >= entry.at && Date.now() - entry.at < ttl
        && Array.isArray(entry.data?.comparisons);
    function persist() {
        entries = Object.fromEntries(Object.entries(entries).filter(([, entry]) => fresh(entry))
            .sort((a, b) => b[1].at - a[1].at).slice(0, 128));
        try { window.sessionStorage.setItem(storageKey, JSON.stringify(entries)); } catch (_) {}
    }
    function remember(job, date, data) {
        if (!Array.isArray(data.comparisons)) return;
        const comparisons = data.comparisons.map(row => Object.fromEntries(
            ['column', 'status', 'history_days', 'baseline', 'current', 'ratio', 'delta']
                .filter(key => Object.hasOwn(row, key)).map(key => [key, row[key]])
        ));
        entries[keyFor(job, date)] = {at: Date.now(), data: {
            comparison_date: data.comparison_date || date, comparisons,
        }};
        persist();
    }
    async function load(job, date, {signal, force = false} = {}) {
        const key = keyFor(job, date);
        if (!force && fresh(entries[key])) return structuredClone(entries[key].data);
        // A failed manual refresh must not leave an earlier successful value behind.
        delete entries[key];
        persist();
        const query = new URLSearchParams({...job, date, days: '5'});
        const response = await fetch('/dx/layer1/api/column-statistics/?' + query, {signal});
        if (!response.ok) throw new Error('Query failed');
        const data = await response.json();
        if (!Array.isArray(data.comparisons)) throw new Error('Invalid comparison response');
        if (!signal?.aborted) remember(job, date, data);
        return data;
    }
    window.ColumnAlertCache = {load, remember};
})();
