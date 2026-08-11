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
