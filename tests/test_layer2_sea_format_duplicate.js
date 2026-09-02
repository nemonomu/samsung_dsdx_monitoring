const assert = require('assert');
const fs = require('fs');
const path = require('path');

function read(relativePath) {
    return fs.readFileSync(path.join(__dirname, '..', relativePath), 'utf8');
}

const common = read('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js');
const nullUi = read('apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js');
const format = read('apps/dx/dx_layer2/static/dx_layer2/js/format_validation.js');
const dashboard = read('apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js');
const seed = read('sql/seed_sea_ref_ldy_format.sql');

assert(common.includes('dup_sea_retail'));
assert(common.includes("/^sea_(ref|ldy)_retail$/"));
assert(common.includes("'SEA REF': 'ref_retail_com'"));
assert(common.includes("'SEA LDY': 'ldy_retail_com'"));
assert(common.includes("'crawl_strdatetime', label: 'crawl_strdatetime'"));

assert(nullUi.includes("tableName === 'SEA REF' ? 'sea_ref_retail'"));
assert(nullUi.includes("tableName === 'SEA LDY' ? 'sea_ldy_retail'"));
assert(nullUi.includes("'sea_ref_retail'"));
assert(nullUi.includes("'sea_ldy_retail'"));
assert(nullUi.includes('function getDefaultFormatHistoryDays(tableParam)'));
assert(nullUi.includes('? 3'));

assert(format.includes("const isSeaRetail = /^sea_(ref|ldy)_retail$/.test(tableParam)"));
assert(format.includes('(isTseRetail || isSeaRetail)'));
assert(format.includes('editableDate: data.editable_date || data.source_date || date'));

assert(dashboard.includes('buildLayer2NullGroups(vType.tables, vType)'));
assert(dashboard.includes('SEA TV/REF/LDY'));
assert(dashboard.includes('최신 배치의 Page Type + Item 중복 및 상품 매핑 충돌'));

assert(seed.includes("'ref_retail_com', 'REF'"));
assert(seed.includes("'ldy_retail_com', 'LDY'"));
assert(seed.includes('SEA_APPLIANCE_BESTBUY_URL'));
assert(seed.includes('SEA_APPLIANCE_LOWES_CAPACITY'));
assert(!seed.includes('recommendation_intent'));
assert(!seed.includes('ref_refrigerator_type'));
assert(!seed.includes('retailer_sku_name'));
assert(!seed.includes('main_rank'));
assert(!seed.includes('bsr_rank'));

console.log('Layer 2 SEA REF/LDY format/duplicate UI tests passed');
