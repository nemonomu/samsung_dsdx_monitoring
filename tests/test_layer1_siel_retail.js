const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer1', 'static',
        'dx_layer1', 'js', 'siel_retail.js'
    ),
    'utf8'
);
const commonSource = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer1', 'static',
        'dx_layer1', 'js', 'layer1-common.js'
    ),
    'utf8'
);
const dashboardSource = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer1', 'templates',
        'dx_layer1_dashboard.html'
    ),
    'utf8'
);
const baseSource = fs.readFileSync(
    path.join(
        __dirname, '..', 'apps', 'dx', 'dx_layer1', 'templates',
        'base_layer1.html'
    ),
    'utf8'
);

const context = {
    L1: { renderers: {} },
    displayCountryFlagLabel: value => '🇮🇳 ' + String(value),
    esc: value => String(value),
    getStatusBadge: status => '<status>' + status + '</status>',
    Number,
};

vm.runInNewContext(source, context);

const categoryHtml = context.renderSielCategory({
    name: 'LDY',
    actual: 549,
    status: 'OK',
    retailers: [{
        retailer: 'Amazon',
        batch_id: 'a_20260810_203042',
        main_count: 174,
        bsr_count: 100,
        actual: 240,
        status: 'OK',
    }, {
        retailer: 'Flipkart',
        batch_id: 'f_20260810_231559',
        main_count: 300,
        bsr_count: 100,
        actual: 309,
        status: 'OK',
    }],
}, 0, 2);

assert(categoryHtml.includes('<th>MAIN</th>'));
assert(categoryHtml.includes('<th>BSR</th>'));
assert(categoryHtml.includes('/ a_20260810_203042</span>'));
assert(categoryHtml.includes('<tr class="rt-sum"><td>합계</td><td>474</td><td>200</td><td>549</td>'));

const checkHtml = context.renderSielRetailCheck({
    name: 'SIEL Retail',
    inspection_date: '2026-08-11',
    source_date: '2026-08-11',
    actual: 1817,
    status: 'OK',
    categories: [],
}, 1);

assert(!checkHtml.includes('검수일 2026-08-11 · 데이터일 2026-08-11 (D)'));
assert(checkHtml.includes('<div class="value">1,817</div>'));
assert(checkHtml.includes('🇮🇳 SIEL Retail'));
assert(commonSource.includes("'SIEL Retail': '/dx/layer1/'"));
assert(baseSource.includes("{% static 'dx_layer1/js/layer1-common.js' %}?v=8"));
assert(dashboardSource.includes("{% static 'dx_layer1/js/siel_retail.js' %}?v=3"));
assert.strictEqual(context.L1.renderers.siel_retail, context.renderSielRetailCheck);

const commonContext = {
    window: {},
    document: {},
    localStorage: {},
    esc: value => String(value),
    Date,
};
vm.runInNewContext(commonSource, commonContext);
assert.strictEqual(commonContext.displayCountryFlagLabel('SEA Retail'), '🇺🇸 SEA Retail');
assert.strictEqual(commonContext.displayCountryFlagLabel('SIEL TV'), '🇮🇳 SIEL TV');
assert.strictEqual(commonContext.displayCountryFlagLabel('TSE LDY'), '🇹🇭 TSE LDY');
assert.strictEqual(commonContext.displayCountryFlagLabel('YouTube'), 'YouTube');

commonContext.currentStatsData = {
    checks: [{ check_type: 'siel_retail', rate: 98 }],
};
commonContext.currentCheckStatus = null;
const uncheckedBadge = commonContext.getCheckBadgeHtml('siel_retail');
assert(uncheckedBadge.includes("saveCheck('siel_retail', 1)"));
assert(!uncheckedBadge.includes("saveCheck('siel_retail', 2)"));

const details = commonContext.flattenCheckToDetails('siel_retail', {
    collection_window: 'KST 09:00 완료 기준',
    categories: [{
        category: 'LDY',
        retailers: [{
            retailer: 'Amazon',
            batch_id: 'a_20260810_203042',
            expected: 300,
            actual: 240,
            rate: 80,
            status: 'OK',
        }],
    }],
});
assert.strictEqual(details[0].category, 'LDY');
assert.strictEqual(details[0].time_slot, 'KST 09:00 완료 기준');
assert.strictEqual(details[0].item_name, 'a_20260810_203042');
