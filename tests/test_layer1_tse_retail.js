const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer1',
        'static',
        'dx_layer1',
        'js',
        'tse_retail.js'
    ),
    'utf8'
);
const commonSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer1',
        'static',
        'dx_layer1',
        'js',
        'layer1-common.js'
    ),
    'utf8'
);
const dashboardSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer1',
        'templates',
        'dx_layer1_dashboard.html'
    ),
    'utf8'
);

const context = {
    L1: { renderers: {} },
    esc: value => String(value),
    getStatusBadge: status => '<status>' + status + '</status>',
    Number,
};

vm.runInNewContext(source, context);

const html = context.renderTseCategory({
    name: 'TV',
    expected: 600,
    actual: 550,
    status: 'WARNING',
    retailers: [{
        retailer: 'Homepro',
        batch_id: 'hidden-batch-id',
        main_count: 180,
        bsr_count: 100,
        actual: 300,
        status: 'OK',
    }, {
        retailer: 'New Retail',
        batch_id: 'another-hidden-batch-id',
        main_count: 150,
        bsr_count: 80,
        actual: 250,
        status: 'WARNING',
    }],
}, 0, 0);

assert(html.includes('<th>MAIN</th>'));
assert(html.includes('<th>BSR</th>'));
assert(html.includes('<th>총 건수</th>'));
assert(html.includes('batch_id: hidden-batch-id'));
assert(html.includes('batch_id: another-hidden-batch-id'));
assert(!html.includes('Anchor batch_id:'));
assert(html.includes('<td>330</td>'));
assert(html.includes('<td>180</td>'));
assert(html.includes('<td>550</td>'));
assert(commonSource.includes("'TSE Retail': '/dx/layer1/'"));
assert(dashboardSource.includes("{% static 'dx_layer1/js/tse_retail.js' %}?v=7"));

const checkHtml = context.renderTseRetailCheck({
    name: 'TSE Retail',
    expected: 900,
    actual: 882,
    status: 'OK',
    categories: [],
}, 1);

assert(checkHtml.includes('<div class="value">882</div>'));
assert(!checkHtml.includes('882/900'));
assert(!checkHtml.includes('check-criteria'));
assert(!checkHtml.includes('Homepro: 200건 이상 정상'));
assert(!checkHtml.includes('Lotuss: 최근 7개 유효일 MAIN 평균과 차이 20건 이상 심각'));
assert(!checkHtml.includes('경고: 200~299건'));

const lotussHtml = context.renderTseCategory({
    name: 'TV',
    expected: 376,
    actual: 386,
    status: 'OK',
    retailers: [{
        retailer: 'Homepro',
        main_count: 300,
        bsr_count: 100,
        bsr_applicable: true,
        actual: 300,
        expected: 300,
        status: 'OK',
    }, {
        retailer: 'Lotuss',
        main_count: 86,
        bsr_count: 0,
        bsr_applicable: false,
        actual: 86,
        expected: 76,
        status: 'OK',
        status_basis: 'previous_main_average',
        history_day_count: 7,
    }],
}, 0, 1);

assert(!lotussHtml.includes('최근 7일 MAIN 평균 76건'));
assert(lotussHtml.includes('<td class="rt-name">Lotuss</td><td>86</td><td>-</td>'));
assert(lotussHtml.includes('<tr class="rt-sum"><td>합계</td><td>386</td><td>100</td><td>386</td>'));
assert(lotussHtml.includes('386/376건'));

const inactiveLotussHtml = context.renderTseCategory({
    name: 'TV',
    expected: 300,
    actual: 300,
    status: 'OK',
    retailers: [{
        retailer: 'Homepro',
        main_count: 300,
        bsr_count: 100,
        bsr_applicable: true,
        actual: 300,
        expected: 300,
        status: 'OK',
    }],
}, 0, 1);

assert(inactiveLotussHtml.includes('<td class="rt-name">Homepro</td>'));
assert(!inactiveLotussHtml.includes('Lotuss'));
assert(inactiveLotussHtml.includes('<tr class="rt-sum"><td>합계</td><td>300</td><td>100</td><td>300</td>'));

const firstDayHtml = context.renderTseCategory({
    name: 'TV',
    expected: 86,
    actual: 86,
    status: 'OK',
    retailers: [{
        retailer: 'Lotuss',
        main_count: 86,
        bsr_count: 0,
        bsr_applicable: false,
        actual: 86,
        expected: 86,
        status: 'OK',
        status_basis: 'previous_main_average',
        history_day_count: 0,
    }],
}, 0, 1);

assert(!firstDayHtml.includes('기준 산정 중'));
assert(!firstDayHtml.includes('일부 기준 산정 중'));
assert(firstDayHtml.includes('<span class="sentiment-category-count">86/86건</span>'));

const commonContext = {
    window: {},
    document: {},
    localStorage: {},
    esc: value => String(value),
    Date,
};
vm.runInNewContext(commonSource, commonContext);

commonContext.currentStatsData = {
    checks: [{ check_type: 'tse_retail', rate: 100 }],
};
commonContext.currentCheckStatus = null;
const uncheckedBadge = commonContext.getCheckBadgeHtml('tse_retail');
assert(uncheckedBadge.includes("saveCheck('tse_retail', 1)"));
assert(!uncheckedBadge.includes("saveCheck('tse_retail', 2)"));

commonContext.currentStatsData.checks[0].rate = 98;
commonContext.currentCheckStatus = {
    sections: {
        tse_retail: {
            confirm_step: 1,
            created_id: 'tester',
            created_at: '2026-08-12T10:00:00+09:00',
        },
    },
};
const checkedBadge = commonContext.getCheckBadgeHtml('tse_retail');
assert(checkedBadge.includes("saveCheck('tse_retail', 2)"));
assert(!checkedBadge.includes('disabled'));
