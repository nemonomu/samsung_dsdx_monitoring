const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
function read(relativePath) {
    return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

const format = read('apps/dx/dx_layer2/static/dx_layer2/js/format_validation.js');
const common = read('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js');

assert(format.includes('const isSegRetail = /^seg_(tv|ref|ldy)_retail$/'));
assert(format.includes('isSeaRetail || isSielRetail || isSegRetail'));
assert(format.includes("tableName: 'dx_seg.dx_seg_tv_retail_com'"));
assert(format.includes("dateColumn: 'crawl_strdatetime'"));
assert(common.includes("'seg_tv_retail': 'seg_tv'"));
assert(common.includes("'seg_ref_retail': 'seg_ref'"));
assert(common.includes("'seg_ldy_retail': 'seg_ldy'"));

console.log('Layer2 SEG format frontend tests passed.');
