const assert = require('assert');
const fs = require('fs');

function read(path) {
    return fs.readFileSync(path, 'utf8');
}

const common = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js'
);
const nullUi = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js'
);
const format = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/format_validation.js'
);
const anomaly = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/anomaly_validation.js'
);
const dashboard = read(
    'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js'
);
const formatTemplate = read(
    'apps/dx/dx_layer2/templates/layer2_format_validation.html'
);

assert(common.includes('dup_siel_retail'));
assert(common.includes('/^siel_(tv|ref|ldy)_retail$/'));
assert(common.includes("'SIEL TV': 'siel_tv'"));
assert(common.includes("'SIEL REF': 'siel_ref'"));
assert(common.includes("'SIEL LDY': 'siel_ldy'"));
assert(common.includes("'siel_tv_retail': 'siel_tv'"));
assert(common.includes("'siel_ref_retail': 'siel_ref'"));
assert(common.includes("'siel_ldy_retail': 'siel_ldy'"));
assert(common.includes('tableNameMap[tableName] || tableName'));
assert(!common.includes("tableNameMap[tableName] || 'tv_retail_com'"));
assert(common.includes('function isReadOnlyDuplicateTable(tableParam)'));

assert(nullUi.includes('SIEL_NULL_HISTORY_TABLES.has(tableCode)'));
assert(format.includes(
    'const isSielRetail = /^siel_(tv|ref|ldy)_retail$/.test(tableParam)'
));
assert(format.includes('(isTseRetail || isSeaRetail || isSielRetail)'));
assert(format.includes(
    "new Set(['country', 'account_name', 'page_type'])"
));
assert(format.includes('selectCols = columnNames.filter'));
assert(common.includes('var sielUrlEditAttr'));
assert(common.includes("/^siel_(tv|ref|ldy)_retail$/.test("));

assert(anomaly.includes('data.readonly_message'));
assert(dashboard.includes(
    '당일 최신 배치의 Page Type + Item 중복 및 상품 매핑 충돌'
));
assert(dashboard.includes("openRuleModal('${tableCode}', '${retailer.retailer}')"));
assert(formatTemplate.includes(
    "dx_layer2/js/layer2-common.js' %}?v=20260904-1"
));
assert(formatTemplate.includes(
    "dx_layer2/js/format_validation.js' %}?v=20260903-3"
));
assert(formatTemplate.includes(
    "dx_layer2/js/dashboard.js' %}?v=20260903-3"
));

console.log('Layer 2 SIEL format/duplicate UI tests passed.');
