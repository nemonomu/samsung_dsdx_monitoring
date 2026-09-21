const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const {execFileSync} = require('child_process');

// Use the service's actual summary and detail contracts, including D-1 history.
const fixtures = JSON.parse(execFileSync('python', ['-B', '-c', `
import json
from tests.unit.test_seda_recommendation_crossfield import SedaRecommendationTests, DAY
from apps.dx.dx_layer3.cross_field import seda_services as seda
case = SedaRecommendationTests()
case.setUp()
try:
    fixtures = []
    for index, product in enumerate(('seda_tv', 'seda_ref', 'seda_ldy'), 7):
        case.add(product, id=1, recommendation_intent='101% recommend this product')
        case.add(product, id=2, crawl_strdatetime='2026-09-19 10:00:00')
        fixtures.append({
            'summary': seda.get_seda_cross_field_summary(case.cursor, DAY, product),
            'detail': seda.get_seda_cross_field_rule_detail(case.cursor, DAY, product, index, 3),
        })
    print(json.dumps(fixtures))
finally:
    case.doCleanups()
`], {encoding: 'utf8'}));

(async () => {
    for (const fixture of fixtures) {
        const container = {innerHTML: ''};
        let requested;
        const context = {
            console,
            document: {addEventListener() {}, querySelector: selector =>
                selector === '.sidebar-group.expanded' ? null : container},
            getSelectedDate: () => '2026-09-21',
            esc: value => String(value == null ? '' : value),
            escJs: value => String(value),
            fetchAPI: async url => { requested = url; return fixture.summary; },
        };
        context.window = context;
        vm.createContext(context);
        for (const path of [
            'static/js/retail-review-columns.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/common.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js',
        ]) vm.runInContext(fs.readFileSync(path, 'utf8'), context);
        vm.runInContext('ViewStack.push = function() {};', context);
        context.isCrossFieldInline = () => true;
        const product = fixture.summary.product_line.toLowerCase();
        await context.showDetail('크로스 필드 검증', fixture.summary.label + ' 논리적 일관성', product);
        assert.strictEqual(new URL(requested, 'https://monitoring.test').searchParams.get('type'), product);
        assert(container.innerHTML.includes('추천 의향 형식·범위'));
        assert(container.innerHTML.includes('Casas Bahia'));
        assert(container.innerHTML.includes('D-1'));
        const action = [...container.innerHTML.matchAll(/onclick="(loadCrossfieldRuleDetail[^\"]+)"/g)][0][1];
        context.fetchAPI = async url => { requested = url; return fixture.detail; };
        await vm.runInContext(action, context);
        const params = new URL(requested, 'https://monitoring.test').searchParams;
        assert.strictEqual(params.get('date'), '2026-09-21');
        assert.strictEqual(params.get('type'), product);
        assert.strictEqual(params.get('rule_id'), String(fixture.detail.rule_id));
        assert.strictEqual(params.get('days'), '3');
        assert(container.innerHTML.includes('이상 1건'));
        assert(!container.innerHTML.includes('데이터 로드 실패'));
        assert(context._cfEditableColumns('Casas Bahia').has('recommendation_intent'));
        assert(!context._cfEditableColumns('Casas Bahia').has('count_of_reviews'));
        assert.strictEqual(context.crossfieldAnomalies.filter(row => row.row_role === 'target').length, 1);
        assert.strictEqual(context.crossfieldAnomalies.filter(row => row.row_role === 'comparison_history').length, 1);
        let detailHtml;
        vm.runInContext('ViewStack.push = function(html) { window.savedDetailHtml = html; };', context);
        context.renderProductUrl = value => String(value || '');
        context.FilterBar = function() { this.render = () => this; };
        context._cfRebuildTable = () => {};
        context.setTimeout = () => {};
        context.showRetailerDetail('Casas Bahia');
        detailHtml = context.savedDetailHtml;
        assert(detailHtml.includes('3일치 Item 조회 SQL'));
        assert(detailHtml.includes('dx_seda.dx_seda_'));
        assert(context._cfDetailState.visibleKeys.includes('recommendation_intent'));
        assert(context._cfDetailState.visibleKeys.includes('count_of_reviews'));
    }
    console.log('SEDA recommendation: product routing, D-1, summary/detail and read-only history passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
