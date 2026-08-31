const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const retailPath = path.join(
    root, 'apps', 'dx', 'dx_layer1', 'static', 'dx_layer1', 'js', 'retail.js'
);
const retailTemplatePath = path.join(
    root, 'apps', 'dx', 'dx_layer1', 'templates', 'dx_layer1_retail.html'
);
const dashboardTemplatePath = path.join(
    root, 'apps', 'dx', 'dx_layer1', 'templates', 'dx_layer1_dashboard.html'
);
const dashboardPath = path.join(
    root, 'apps', 'dx', 'dx_layer1', 'static', 'dx_layer1', 'js', 'dashboard.js'
);
const source = fs.readFileSync(retailPath, 'utf8');
const dashboardSource = fs.readFileSync(dashboardPath, 'utf8');
const retailTemplate = fs.readFileSync(retailTemplatePath, 'utf8');
const dashboardTemplate = fs.readFileSync(dashboardTemplatePath, 'utf8');

let selectedDate = '2026-08-20';
const requests = [];
const summaries = {
    tv: {
        date: selectedDate,
        inspection_date: selectedDate,
        source_date: '2026-08-19',
        offset_days: -1,
        source_key: 'sea_tv',
        product_line: 'TV',
        has_extra_rank: true,
        extra_rank_name: 'Promotion',
        null_columns: [],
        totals: { grand_total: 60 },
        summary: [
            { retailer: 'Amazon', total: 10, batch_id: '', rows: [{ time_slot: '일일', main: 5, bsr: 3, extra: 2, total: 10, batch_id: '' }] },
            { retailer: 'Bestbuy', total: 20, batch_id: '', rows: [{ time_slot: '일일', main: 10, bsr: 6, extra: 4, total: 20, batch_id: '' }] },
            { retailer: 'Walmart', total: 30, batch_id: '', rows: [{ time_slot: '일일', main: 15, bsr: 9, extra: 6, total: 30, batch_id: '' }] },
        ],
    },
    ref: {
        date: selectedDate,
        inspection_date: selectedDate,
        source_date: '2026-08-19',
        offset_days: -1,
        source_key: 'sea_ref',
        product_line: 'REF',
        has_extra_rank: false,
        extra_rank_name: '',
        null_columns: [],
        totals: { grand_total: 30 },
        summary: [
            { retailer: 'Bestbuy', total: 12, batch_id: 'REF-BESTBUY-ANCHOR', rows: [{ time_slot: '일일', main: 8, bsr: 4, extra: 0, total: 12, batch_id: 'REF-BESTBUY-ANCHOR' }] },
            { retailer: 'Lowes', total: 18, batch_id: 'REF-LOWES-ANCHOR', rows: [{ time_slot: '일일', main: 12, bsr: 6, extra: 0, total: 18, batch_id: 'REF-LOWES-ANCHOR' }] },
        ],
    },
    ldy: {
        date: selectedDate,
        inspection_date: selectedDate,
        source_date: '2026-08-19',
        offset_days: -1,
        source_key: 'sea_ldy',
        product_line: 'LDY',
        has_extra_rank: false,
        extra_rank_name: '',
        null_columns: [],
        totals: { grand_total: 22 },
        summary: [
            { retailer: 'Bestbuy', total: 9, batch_id: 'LDY-BESTBUY-ANCHOR', rows: [{ time_slot: '일일', main: 6, bsr: 3, extra: 0, total: 9, batch_id: 'LDY-BESTBUY-ANCHOR' }] },
            { retailer: 'Lowes', total: 13, batch_id: 'LDY-LOWES-ANCHOR', rows: [{ time_slot: '일일', main: 8, bsr: 5, extra: 0, total: 13, batch_id: 'LDY-LOWES-ANCHOR' }] },
        ],
    },
};

const context = {
    L1: {
        renderers: {},
        initLayer1Page: function() {},
    },
    RawDataView: function(options) {
        return {
            options: options,
            checkUrlAndShow: function() { return false; },
        };
    },
    AppModal: {
        setTitle: function() {},
        setBody: function() {},
        open: function() {},
        close: function() {},
    },
    getSelectedDate: function() { return selectedDate; },
    getStatusClass: function(status) { return String(status || '').toLowerCase(); },
    getStatusBadge: function(status) { return '<status>' + status + '</status>'; },
    esc: function(value) {
        return String(value === undefined || value === null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },
    currentRetailSummary: null,
    currentNullData: null,
    console: { error: function() {} },
    fetch: async function(url) {
        requests.push(url);
        const parsed = new URL('http://layer1.local' + url);
        const type = parsed.searchParams.get('type');
        assert.strictEqual(parsed.searchParams.get('date'), selectedDate);
        assert.ok(summaries[type], 'unexpected summary type: ' + type);
        return {
            ok: true,
            json: async function() { return summaries[type]; },
        };
    },
};

vm.runInNewContext(source, context);

function categoryFromSummary(key) {
    const data = summaries[key];
    return {
        name: key.toUpperCase(),
        product_line: key,
        inspection_date: data.inspection_date,
        source_date: data.source_date,
        offset_days: data.offset_days,
        has_extra_rank: data.has_extra_rank,
        extra_rank_name: data.extra_rank_name,
        total: data.totals.grand_total,
        status: 'OK',
        time_slots: [{
            name: '일일',
            total: data.totals.grand_total,
            status: 'OK',
            retailers: data.summary.map(function(retailer) {
                return {
                    retailer: retailer.retailer,
                    count: retailer.total,
                    batch_id: retailer.batch_id,
                    status: 'OK',
                    items: [],
                };
            }),
        }],
    };
}

(async function run() {
    const loaded = await context.loadSeaRetailSummaries(selectedDate);
    assert.strictEqual(requests.length, 3);
    assert.deepStrictEqual(
        requests.map(function(url) {
            return new URL('http://layer1.local' + url).searchParams.get('type');
        }).sort(),
        ['ldy', 'ref', 'tv']
    );
    assert.strictEqual(Object.keys(loaded).sort().join(','), 'ldy,ref,tv');
    assert.strictEqual(context.currentRetailSummary.ref, summaries.ref);
    assert.strictEqual(context.currentNullData.ldy, summaries.ldy.null_columns);

    const refHtml = context.renderRetailCategory(categoryFromSummary('ref'), 0, 1);
    assert.ok(refHtml.includes('검수일 2026-08-20'));
    assert.ok(refHtml.includes('데이터일 2026-08-19'));
    assert.ok(refHtml.includes('D-1 (offset_days=-1)'));
    assert.ok(refHtml.includes('Anchor batch_id: REF-BESTBUY-ANCHOR'));
    assert.ok(refHtml.includes('Anchor batch_id: REF-LOWES-ANCHOR'));
    assert.ok(refHtml.includes('category=REF'));
    assert.ok(refHtml.includes('date=2026-08-20'));
    assert.ok(refHtml.includes('<th>MAIN</th>'));
    assert.ok(refHtml.includes('<th>BSR</th>'));
    assert.ok(!refHtml.includes('rt-extra'));
    assert.ok(!refHtml.includes('<th>Extra</th>'));
    assert.ok(!refHtml.includes('<th>Promotion</th>'));
    assert.ok(!refHtml.includes('Amazon'));
    assert.ok(!refHtml.includes('Walmart'));

    const mixedCaseRef = categoryFromSummary('ref');
    mixedCaseRef.time_slots[0].retailers[0].retailer = 'BESTBUY';
    mixedCaseRef.time_slots[0].retailers[0].status = 'CRITICAL';
    const mixedCaseHtml = context.renderRetailCategory(mixedCaseRef, 0, 1);
    assert.ok(mixedCaseHtml.includes('<status>CRITICAL</status>'));

    const ldyHtml = context.renderRetailCategory(categoryFromSummary('ldy'), 0, 2);
    assert.ok(ldyHtml.includes('category=LDY'));
    assert.ok(ldyHtml.includes('Anchor batch_id: LDY-LOWES-ANCHOR'));
    assert.ok(!ldyHtml.includes('rt-extra'));

    const tvHtml = context.renderRetailCategory(categoryFromSummary('tv'), 0, 0);
    assert.ok(tvHtml.includes('<th>Promotion</th>'));
    assert.ok(tvHtml.includes('class="rt-extra"'));
    assert.ok(tvHtml.includes('Amazon'));
    assert.ok(tvHtml.includes('Bestbuy'));
    assert.ok(tvHtml.includes('Walmart'));
    assert.ok(!tvHtml.includes('Anchor batch_id:'));

    const fallbackHtml = context.renderRetailCheck({
        name: 'SEA Retail',
        description: 'fallback',
        actual: 0,
        status: 'PENDING',
        categories: [],
    }, 0);
    const tvIndex = fallbackHtml.indexOf('sentiment-category-name">TV');
    const refIndex = fallbackHtml.indexOf('sentiment-category-name">REF');
    const ldyIndex = fallbackHtml.indexOf('sentiment-category-name">LDY');
    assert.ok(tvIndex >= 0 && refIndex > tvIndex && ldyIndex > refIndex);
    assert.ok(fallbackHtml.includes('category=TV'));
    assert.ok(fallbackHtml.includes('category=REF'));
    assert.ok(fallbackHtml.includes('category=LDY'));
    assert.ok(fallbackHtml.includes('Amazon'));
    assert.ok(fallbackHtml.includes('Walmart'));
    assert.ok(fallbackHtml.includes('Lowes'));

    assert.ok(dashboardSource.includes('await loadSeaRetailSummaries(selectedDate);'));
    assert.ok(!dashboardSource.includes("summary/?type=tv"));

    assert.ok(source.includes("switchColumnsTab(\\'tv\\')"));
    assert.ok(!source.includes("switchColumnsTab(\\'ref\\')"));
    assert.ok(!source.includes("switchColumnsTab(\\'ldy\\')"));
    assert.ok(retailTemplate.includes("{% static 'dx_layer1/js/retail.js' %}?v=9"));
    assert.ok(dashboardTemplate.includes("{% static 'dx_layer1/js/retail.js' %}?v=9"));
    assert.ok(dashboardTemplate.includes("{% static 'dx_layer1/js/dashboard.js' %}?v=5"));
    assert.ok(!dashboardTemplate.includes('installSeaRetailDashboardLoader();'));
    assert.ok(dashboardTemplate.includes("{% static 'dx_layer1/js/tse_retail.js' %}?v=6"));

    console.log('Layer1 SEA retail frontend tests passed');
})().catch(function(error) {
    console.error(error);
    process.exitCode = 1;
});
