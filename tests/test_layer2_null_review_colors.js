const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const scriptRoot = 'apps/dx/dx_layer2/static/dx_layer2/';
const body = { innerHTML: '' };
const sandbox = {
    console, URLSearchParams,
    renderCountryFlagLabel: value => value,
    getDetailBody: () => body,
    getSelectedDate: () => '2026-09-13',
    isInlineMode: () => true
};
vm.createContext(sandbox);
for (const script of ['null_validation.js', 'dashboard.js', 'format_validation.js']) {
    vm.runInContext(fs.readFileSync(scriptRoot + 'js/' + script, 'utf8'), sandbox);
}

function retailer(overrides = {}) {
    return Object.assign({
        retailer: 'Lowes', total: 330, status: 'CRITICAL', total_null_count: 3,
        supports_null_auto_review: true, raw_null_count: 22,
        auto_reviewed_count: 17, manual_reviewed_count: 2, reviewed_null_count: 19,
        fields_detail: { ref_capacity: 3, sku: 0 },
        raw_fields_detail: { ref_capacity: 22, sku: 0 },
        reviewed_fields_detail: { ref_capacity: 19, sku: 0 },
        auto_reviewed_fields_detail: { ref_capacity: 17, sku: 0 },
        manual_reviewed_fields_detail: { ref_capacity: 2, sku: 0 }
    }, overrides);
}

function renderCard(data) {
    return sandbox.renderDXTableDetail({ type: 'null' }, {
        table: 'sea_ref_retail', table_name: 'SEA REF', retailers: [data]
    });
}

const mixed = renderCard(retailer());
assert.ok(mixed.includes('retailer-card null-review-unreviewed'));
assert.ok(mixed.includes('class="field-badge has-issue">ref_capacity: 확인 필요 3건'));
assert.ok(mixed.includes('class="field-badge automatic">ref_capacity: 자동확인 17건'));
assert.ok(mixed.includes('class="field-badge manual">ref_capacity: 수동확인 2건'));
assert.ok(mixed.includes('class="field-badge ok">sku: 0'));
assert.ok(mixed.includes("'Lowes', 22, 1"), 'query must include accepted findings');
const payload = JSON.parse(mixed.match(/data-fields='([^']+)'/)[1].replace(/&#39;/g, "'").replace(/&amp;/g, '&'));
assert.strictEqual(payload.auto_reviewed_fields_detail.ref_capacity, 17);
assert.strictEqual(payload.manual_reviewed_fields_detail.ref_capacity, 2);

const autoOnly = retailer({
    status: 'OK', total_null_count: 0, raw_null_count: 17,
    manual_reviewed_count: 0, reviewed_null_count: 17,
    fields_detail: { ref_capacity: 0 }, raw_fields_detail: { ref_capacity: 17 },
    reviewed_fields_detail: { ref_capacity: 17 }, manual_reviewed_fields_detail: { ref_capacity: 0 }
});
const automaticHtml = renderCard(autoOnly);
assert.ok(automaticHtml.includes('retailer-card null-review-automatic'));
assert.ok(automaticHtml.includes('retailer-issue-count null-review-automatic">자동확인 17건'));
assert.ok(automaticHtml.includes('class="field-badge automatic">ref_capacity: 자동확인 17건'));
assert.ok(!automaticHtml.includes('has-issue'));
assert.ok(!automaticHtml.includes('unreviewed'), 'zero pending findings must not receive red styling');
assert.ok(!automaticHtml.includes('ref_capacity: 0'), 'automatic NULL must not look like an absent NULL');
assert.ok(automaticHtml.includes("'Lowes', 17, 1"));

const manualOnly = retailer({
    status: 'OK', total_null_count: 0, raw_null_count: 2,
    auto_reviewed_count: 0, reviewed_null_count: 2,
    fields_detail: { ref_capacity: 0 }, raw_fields_detail: { ref_capacity: 2 },
    reviewed_fields_detail: { ref_capacity: 2 }, auto_reviewed_fields_detail: { ref_capacity: 0 }
});
const manualHtml = renderCard(manualOnly);
assert.ok(manualHtml.includes('retailer-card null-review-manual'));
assert.ok(manualHtml.includes('class="field-badge manual">ref_capacity: 수동확인 2건'));
assert.ok(!manualHtml.includes('field-badge automatic'));
assert.ok(!manualHtml.includes('has-issue'));

const clearHtml = renderCard(retailer({
    status: 'OK', total_null_count: 0, raw_null_count: 0,
    reviewed_null_count: 0, auto_reviewed_count: 0, manual_reviewed_count: 0,
    fields_detail: { sku: 0 }, raw_fields_detail: {}, reviewed_fields_detail: {},
    auto_reviewed_fields_detail: {}, manual_reviewed_fields_detail: {}
}));
assert.ok(clearHtml.includes('retailer-card null-review-clear'));
assert.ok(clearHtml.includes('NULL 없음'));
assert.ok(clearHtml.includes('class="field-badge ok">sku: 0'));

const errorHtml = renderCard(retailer({
    status: 'ERROR', total_null_count: 0, raw_null_count: 0,
    auto_reviewed_count: 0, manual_reviewed_count: 0, reviewed_null_count: 0,
    fields_detail: {}, raw_fields_detail: {}, reviewed_fields_detail: {}
}));
assert.ok(errorHtml.includes('retailer-card error'));
assert.ok(errorHtml.includes('조회 실패'));
assert.ok(!errorHtml.includes('null-review-clear'));
assert.ok(!errorHtml.includes('NULL 없음'), 'a query failure is not a clear result');

const legacy = renderCard(retailer({ supports_null_auto_review: false }));
assert.ok(legacy.includes('retailer-card critical'));
assert.ok(legacy.includes('class="field-badge has-issue">ref_capacity: 3'));
assert.ok(!legacy.includes('null-review-status'));
assert.ok(!legacy.includes('field-badge automatic'));

function renderSummary(data) {
    sandbox.renderNullFieldSummary(Object.assign({}, data, { field_counts: data.fields_detail }));
    return body.innerHTML;
}
const automaticSummary = renderSummary(autoOnly);
assert.ok(automaticSummary.includes('null-field-card null-review-automatic'));
assert.ok(automaticSummary.includes('null-field-card-count">자동확인 17건'));
assert.ok(automaticSummary.includes("showNullFieldDetail('ref_capacity')"));
assert.ok(!automaticSummary.includes('null-review-unreviewed'));
const mixedSummary = renderSummary(retailer());
assert.ok(mixedSummary.includes('null-field-card null-review-unreviewed'));
assert.ok(mixedSummary.includes('null-field-card-count">확인 필요 3건'));
assert.ok(mixedSummary.includes('class="null-review-status automatic">자동확인 17건'));
assert.ok(mixedSummary.includes('class="null-review-status manual">수동확인 2건'));
const manualSummary = renderSummary(manualOnly);
assert.ok(manualSummary.includes('null-field-card null-review-manual'));
assert.ok(manualSummary.includes('null-field-card-count">확인 완료 2건'));

// Verify that the classes emitted by the renderers resolve to the intended colors.
const css = fs.readFileSync(scriptRoot + 'css/layer2.css', 'utf8');
for (const selector of ['.null-review-status.automatic', '.field-badge.automatic',
    '.retailer-issue-count.null-review-automatic', '.null-field-card.null-review-automatic .null-field-card-count']) {
    const declaration = css.slice(css.indexOf(selector)).split('}')[0];
    assert.ok(declaration.includes('color: #1d4ed8'), selector);
}
assert.ok(css.includes('.retailer-card.null-review-unreviewed { border-left: 4px solid var(--color-critical'));
async function testDateReloadKeepsFieldReviewColors() {
    vm.runInContext("modalState.tableParam = 'sea_ref_retail'; modalState.tableName = 'SEA REF'; modalState.retailer = 'Lowes'; modalState.selectedField = null;", sandbox);
    sandbox.fetch = async () => ({ json: async () => ({ validation_types: [{
        type: 'null', tables: [{ table: 'sea_ref_retail', retailers: [autoOnly] }]
    }] }) });
    await sandbox.reloadNullData('2026-09-14');
    assert.ok(body.innerHTML.includes('null-field-card null-review-automatic'));
    assert.ok(body.innerHTML.includes('null-field-card-count">자동확인 17건'));
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.auto_reviewed_fields_detail.ref_capacity', sandbox), 17);
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.manual_reviewed_fields_detail.ref_capacity', sandbox), 0);
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.date', sandbox), '2026-09-14');

    sandbox.fetch = async () => ({ json: async () => ({ validation_types: [{
        type: 'null', tables: [{ table: 'sea_ref_retail', retailers: [manualOnly] }]
    }] }) });
    await sandbox.reloadNullData('2026-09-15');
    assert.ok(body.innerHTML.includes('null-field-card null-review-manual'));
    assert.ok(body.innerHTML.includes('null-field-card-count">확인 완료 2건'));
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.auto_reviewed_fields_detail.ref_capacity', sandbox), 0);
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.manual_reviewed_fields_detail.ref_capacity', sandbox), 2);
}
testDateReloadKeepsFieldReviewColors().then(() => {
    console.log('Layer2 NULL review card and field color tests passed.');
}).catch(error => { console.error(error); process.exitCode = 1; });
