const assert = require('assert');
const fs = require('fs');
const path = require('path');

function read(relativePath) {
    return fs.readFileSync(path.join(__dirname, '..', relativePath), 'utf8');
}

const common = read('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js');
const format = read('apps/dx/dx_layer2/static/dx_layer2/js/format_validation.js');
const anomaly = read('apps/dx/dx_layer2/static/dx_layer2/js/anomaly_validation.js');
const dashboard = read('apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js');

assert(common.includes('dup_tse_retail'));
assert(common.includes("'TSE TV': 'tse_tv'"));
assert(common.includes("'TSE REF': 'tse_ref'"));
assert(common.includes("'TSE LDY': 'tse_ldy'"));
assert(common.includes('!isReadOnlyDuplicateTable(detailViewState.tableParam)'));
assert(common.includes('return isTseDuplicateTable(tableParam)'));

assert(format.includes("const isTseRetail = /^tse_(tv|ref|ldy)_retail$/.test(tableParam)"));
assert(format.includes("'retailer_sku_name'"));
assert(format.includes('_buildTseNullQueryHtml('));
assert(format.includes('id="fmt-modal-days"'));

assert(anomaly.includes('TSE 중복 검증은 확인 전용이며 자동 삭제하지 않습니다.'));
assert(anomaly.includes('var allowCleanup = !data.readonly'));
assert(dashboard.includes('완전 중복 및 Item↔Retailer SKU Name 매핑 충돌'));

console.log('Layer 2 TSE format/duplicate UI tests passed');
