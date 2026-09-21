const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const {execFileSync} = require('child_process');

const fixtures = JSON.parse(execFileSync('python', ['-B', '-c', `
import json
from tests.unit.test_seda_crossfield import SedaCrossfieldIntegrationTests, DAY, body
from apps.dx.dx_layer3.cross_field import seda_services as seda
case = SedaCrossfieldIntegrationTests()
case.setUp()
try:
    fixtures = []
    for product in ('seda_tv', 'seda_ref', 'seda_ldy'):
        case.add(product, id=1, crawl_strdatetime='2026-09-15 10:00:00')
        case.add(product, id=2, summarized_review_content=None)
        case.add(product, id=3, item='short', account_name='Casas Bahia', count_of_reviews='25', count_of_star_ratings='25', detailed_review_content=body(19))
        case.add(product, id=4, item='zero', count_of_reviews='0')
        case.add(product, id=5, item='price', account_name='Casas Bahia', count_of_star_ratings='6', final_sku_price='R$1.500,00', savings='Baixou 10%')
        summary=seda.get_seda_cross_field_summary(case.cursor, DAY, product)
        for key, retailer in (('summary_review_disappeared','Magalu'), ('review_body_count','Casas Bahia'), ('review_zero_body','Magalu'), ('final_original_price','Casas Bahia'), ('review_count_match','Casas Bahia')):
            detail=case.detail(key, product=product)
            fixtures.append(dict(summary=summary, detail=detail, key=key, retailer=retailer))
    print(json.dumps(fixtures))
finally:
    case.doCleanups()
`], {encoding: 'utf8'}));

(async () => {
    for (const fixture of fixtures) {
        const container = {innerHTML: ''};
        const context = {
            console, document: {addEventListener() {}, querySelector: () => container},
            esc: value => String(value == null ? '' : value), escJs: value => String(value),
            getSelectedDate: () => '2026-09-21', fetchAPI: async () => fixture.detail,
        };
        context.window = context;
        vm.createContext(context);
        for (const file of ['static/js/retail-review-columns.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/common.js',
            'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js']) {
            vm.runInContext(fs.readFileSync(file, 'utf8'), context);
        }
        vm.runInContext('ViewStack.push = function(html) { window.savedHtml = html; };', context);
        context.isCrossFieldInline = () => true;
        context.renderCrossfieldSummaryContent('SEDA', '', fixture.summary);
        assert.strictEqual(fixture.summary.rule_summary.length, 11);
        assert.strictEqual(fixture.summary.failed_records, 2);
        assert.strictEqual(fixture.summary.review_needed_records, 2);
        for (const rule of fixture.summary.rule_summary) {
            assert(container.innerHTML.includes(rule.detail_name));
            const card = container.innerHTML.split(`data-rule-id="${rule.rule_id}"`)[1].split('class="rule-count-group"')[0];
            assert(card.includes('적용 대상: ' + rule.retailers.join(' · ')));
        }
        const actions = [...container.innerHTML.matchAll(/onclick="(loadCrossfieldRuleDetail[^\"]+)"/g)];
        const action = actions.find(match => match[1].includes(`'${fixture.detail.rule_id}'`));
        assert(action, 'rule detail action exists');
        await vm.runInContext(action[1], context);
        const isReview = ['summary_review_disappeared', 'review_body_count'].includes(fixture.key);
        assert(container.innerHTML.includes(isReview ? '확인 필요 1건' : '이상 1건'));
        context.renderProductUrl = value => String(value || '');
        context.FilterBar = function() { this.render = () => this; };
        context._cfRebuildTable = () => {};
        context.setTimeout = () => {};
        context.showRetailerDetail(fixture.retailer);
        assert(context.savedHtml.includes('3일치 Item 조회 SQL'));
        assert(context._cfUsesEqualReviewCounts('SEDA_TV', 'Casas Bahia'));
        assert(!context._cfUsesEqualReviewCounts('SEDA_TV', 'Magalu'));
        const state = context._cfDetailState;
        assert.strictEqual(state.allData.filter(row => row._rowRole === 'target').length, 1);
        if (fixture.key === 'summary_review_disappeared') {
            assert.strictEqual(state.allData.filter(row => row._rowRole === 'comparison_history').length, 1);
            assert(state.allData.some(row => row._rowDate === '2026-09-15'));
            assert(state.visibleKeys.includes('summarized_review_content'));
            assert(state.editableCols.has('summarized_review_content'));
        } else if (fixture.key === 'final_original_price') {
            for (const field of ['original_sku_price', 'final_sku_price', 'savings']) {
                assert(state.visibleKeys.includes(field));
                assert(context.savedHtml.includes('source.' + field));
            }
            assert(state.editableCols.has('original_sku_price'));
            assert(state.editableCols.has('final_sku_price'));
            assert(state.allData.some(row => row.savings === 'Baixou 10%'));
        } else if (fixture.key === 'review_count_match') {
            for (const field of ['star_rating', 'count_of_star_ratings', 'count_of_reviews']) {
                assert(state.visibleKeys.includes(field));
                assert(context.savedHtml.includes('source.' + field));
            }
            assert(state.editableCols.has('count_of_star_ratings'));
            assert(state.editableCols.has('count_of_reviews'));
        } else {
            assert(state.visibleKeys.includes('review_body_count'));
        }
    }
    console.log('SEDA full cross-field UI: all 11 cards, severity, retailer scope, evidence and SQL passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
