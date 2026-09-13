const assert = require('assert');
const fs = require('fs');

const common = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/common.js', 'utf8'
);
const crossField = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js', 'utf8'
);
const dashboard = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_dashboard.html', 'utf8'
);
const detail = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_cross_field.html', 'utf8'
);

assert(common.includes("const regionGroups = { sea: [], siel: [], seg: [], sem: [], tse: [] }"));
assert(common.includes("{ key: 'sem', title: 'SEM Retail'"));
assert(common.includes("detailCode === 'sem_tv' || checkName.includes('SEM TV')"));
assert(common.includes("detailCode === 'sem_ref' || checkName.includes('SEM REF')"));
assert(common.includes("detailCode === 'sem_ldy' || checkName.includes('SEM LDY')"));
assert(common.includes("detailCode === 'siel_tv' || detailCode === 'seg_tv' || detailCode === 'sem_tv' || detailCode === 'tse_tv'"));
assert(common.includes("detailCode === 'siel_ref' || detailCode === 'seg_ref' || detailCode === 'sem_ref' || detailCode === 'tse_ref'"));
assert(common.includes("const isSemCrossfield = /^SEM (TV|REF|LDY)"));
assert(common.includes("type=${category}"));
assert(common.includes("const loadedRules = isSemCrossfield"));
assert(crossField.includes('function _cfPersistedRuleId'));
assert(crossField.includes('var ruleId = _cfPersistedRuleId('));
assert(dashboard.includes("common.js' %}?v=20260910-3"));
assert(dashboard.includes("cross-field.js' %}?v=25"));
assert(detail.includes("common.js' %}?v=20260910-3"));
assert(detail.includes("cross-field.js' %}?v=25"));

console.log('Layer3 SEM cross-field UI tests passed.');

// Use real SEM service responses so a missing response field cannot be hidden
// by a hand-written frontend fixture.
const {execFileSync} = require('child_process');
const vm = require('vm');
const fixtures = JSON.parse(execFileSync('python', ['-B', '-c', `
import json
from datetime import date
from unittest.mock import patch
from apps.dx.dx_layer3.cross_field import sem_services
row = {
    'id': 1, 'item': 'example', 'account_name': 'Liverpool', 'country': 'SEM',
    'crawl_datetime': '2026-09-13 10:00:00',
    'final_sku_price': '$100.00', 'original_sku_price': '$100.00',
}
mapping = {'inspection_date': '2026-09-13', 'source_date': '2026-09-13', 'offset_days': 0}
fixtures = []
with patch.object(sem_services, '_latest_rows', return_value=([row], mapping)), patch.object(sem_services, '_history_rows', return_value=[]):
    for product in ('sem_tv', 'sem_ref', 'sem_ldy'):
        summary = sem_services.get_sem_cross_field_summary(None, date(2026, 9, 13), product)
        detail = sem_services.get_sem_cross_field_rule_detail(None, date(2026, 9, 13), product, product + ':final_original_price', days=3)
        fixtures.append({'summary': summary, 'detail': detail})
print(json.dumps(fixtures))
`], {encoding: 'utf8'}));

(async () => {
    for (const fixture of fixtures) {
        const container = {innerHTML: ''};
        let requested;
        const context = {
            console,
            document: {addEventListener() {}, querySelector: () => container},
            getSelectedDate: () => '2026-09-13',
            esc: value => String(value == null ? '' : value),
            escJs: value => String(value),
            ViewStack: {push() {}},
            fetchAPI: async url => { requested = url; return fixture.detail; },
        };
        context.window = context;
        vm.createContext(context);
        vm.runInContext(common, context);
        vm.runInContext(crossField, context);
        vm.runInContext('ViewStack.push = function() {};', context);
        context.isCrossFieldInline = () => true;
        context.renderCrossfieldSummaryContent('SEM', '', fixture.summary);
        assert(!container.innerHTML.includes('D-1'));
        const actions = [...container.innerHTML.matchAll(/onclick="(loadCrossfieldRuleDetail[^\"]+)"/g)];
        const action = actions.find(match => match[1].includes(':final_original_price'))[1];
        await vm.runInContext(action, context);
        const params = new URL(requested, 'https://monitoring.test').searchParams;
        assert.strictEqual(params.get('date'), '2026-09-13');
        assert.strictEqual(params.get('type'), fixture.summary.product_line);
        assert.strictEqual(params.get('rule_id'), fixture.detail.rule_id);
        assert.strictEqual(params.get('days'), '3');
        assert(container.innerHTML.includes('Liverpool'));
        assert(container.innerHTML.includes('이상 1건'));
        assert(!container.innerHTML.includes('데이터 로드 실패'));
    }
    console.log('Layer3 SEM real summary-to-detail date routing tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
