const assert = require('assert');
const fs = require('fs');
const path = require('path');

function read(relativePath) {
    return fs.readFileSync(path.join(__dirname, '..', relativePath), 'utf8');
}

const dashboard = read('apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js');
const nullValidation = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js'
);
const common = read('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js');
const template = read('apps/dx/dx_layer2/templates/layer2_null_validation.html');

assert(dashboard.includes("name: 'SEG Retail'"));
assert(dashboard.includes(
    "tableCodes: ['seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail']"
));
assert(dashboard.indexOf("key: 'siel'") < dashboard.indexOf("key: 'seg'"));
assert(dashboard.indexOf("key: 'seg'") < dashboard.indexOf("key: 'sem'"));

assert(nullValidation.includes("'seg_tv_retail'"));
assert(nullValidation.includes('const isSegRetail'));
assert(nullValidation.includes('source.redirect IS NOT TRUE'));
assert(nullValidation.includes("UPPER(BTRIM(source.country)) = 'SEG'"));
assert(nullValidation.includes('(isSeaRetail || isSielRetail || isSegRetail)'));

assert(common.includes('var pageSize = detailViewState.pageSize || 100'));
assert(common.includes('e.shiftKey && detailViewState.reviewAnchorCell'));
assert(template.includes(
    "dx_layer2/js/null_validation.js' %}?v=20260909-2"
));
assert(template.includes(
    "dx_layer2/js/dashboard.js' %}?v=20260909-2"
));

console.log('Layer2 SEG NULL frontend tests passed.');
