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
assert(!html.includes('최신 배치'));
assert(!html.includes('hidden-batch-id'));
assert(html.includes('<td>330</td>'));
assert(html.includes('<td>180</td>'));
assert(html.includes('<td>550</td>'));
assert(commonSource.includes("'TSE Retail': '/dx/layer1/'"));

const checkHtml = context.renderTseRetailCheck({
    name: 'TSE Retail',
    expected: 900,
    actual: 882,
    status: 'OK',
    categories: [],
}, 1);

assert(checkHtml.includes('<div class="value">882</div>'));
assert(!checkHtml.includes('882/900'));
assert(checkHtml.includes('정상: 200건 이상'));
assert(!checkHtml.includes('경고: 200~299건'));

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
