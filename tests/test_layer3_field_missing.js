const assert = require('assert');
const fs = require('fs');

const source = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/field-missing.js', 'utf8'
);
const template = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_field_missing.html', 'utf8'
);

assert(source.includes('data.inspection_date || date'));
assert(source.includes('data.source_date || data.date || date'));
assert(source.includes('검수일 ${inspectionDate} · 데이터일 ${sourceDate} · D-1'));
assert(source.includes('st.sourceDate || window._fmSourceDate'));
assert(source.includes('window._fmDate = inspectionDate'));
assert(source.includes('window._fmSourceDate = sourceDate'));
assert(source.includes('crawl_date: window._fmDate'));
assert(source.includes('pageSize: 100'));
assert(source.includes('getPageSize() : 100'));
assert(template.includes('id="field-missing-date-scope"'));
assert(template.includes("field-missing.js' %}?v=3"));

console.log('Layer3 SEA field-missing date tests passed.');
