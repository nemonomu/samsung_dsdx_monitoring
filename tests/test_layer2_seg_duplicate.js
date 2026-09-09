const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const common = fs.readFileSync(
    path.join(root, 'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js'),
    'utf8'
);
const dashboard = fs.readFileSync(
    path.join(root, 'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js'),
    'utf8'
);
const nullValidation = fs.readFileSync(
    path.join(root, 'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js'),
    'utf8'
);

assert(common.includes('/^seg_(tv|ref|ldy)_retail$/.test(tableParam)'));
assert(common.includes("return DETAIL_COLUMNS.dup_sea_retail;"));
assert(common.includes("/^seg_(tv|ref|ldy)_retail$/.test(String(tableParam || ''))"));
assert(dashboard.includes("const isSegRetail = /^seg_(tv|ref|ldy)_retail$/"));
assert(dashboard.includes('isSeaRetail || isSegRetail'));
assert(nullValidation.includes("tableName === 'SEG TV' ? 'seg_tv_retail'"));

console.log('Layer2 SEG duplicate frontend tests passed.');
