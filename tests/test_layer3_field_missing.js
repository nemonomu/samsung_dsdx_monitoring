const assert = require('assert');
const fs = require('fs');

const source = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/field-missing.js', 'utf8'
);
const template = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_field_missing.html', 'utf8'
);
const dashboardTemplate = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_dashboard.html', 'utf8'
);
const indexTemplate = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_index.html', 'utf8'
);
const commonSource = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/common.js', 'utf8'
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
assert(source.includes("sea_ref: ['Bestbuy', 'Lowes']"));
assert(source.includes("sea_ldy: ['Bestbuy', 'Lowes']"));
assert(source.includes("row.finding_type === 'new'"));
assert(source.includes("row._findingType === 'new'"));
assert(source.includes('function _fmGetReviewRangeCells'));
assert(source.includes('e.shiftKey && window._fmReviewAnchorCell'));
assert(source.includes('function _fmSubmitReviews'));
assert(source.includes("cell.classList.add('cell-review-selected')"));
assert(source.includes('return Promise.all(requests)'));
assert(commonSource.includes('switchFieldMissingTab(detailCodeParam || focusParam.toLowerCase())'));
assert(template.includes("common.js' %}?v=20260903-2"));
assert(template.includes('id="field-missing-date-scope"'));
assert(template.includes('data-pl="sea_ref"'));
assert(template.includes('data-pl="sea_ldy"'));
assert(template.includes('data-retailer="Lowes"'));
assert(template.includes("field-missing.js' %}?v=5"));
assert(dashboardTemplate.includes('data-pl="sea_ref"'));
assert(dashboardTemplate.includes('data-pl="sea_ldy"'));
assert(dashboardTemplate.includes('data-retailer="Lowes"'));
assert(dashboardTemplate.includes("field-missing.js' %}?v=5"));
assert(indexTemplate.includes("field-missing.js' %}?v=5"));

console.log('Layer3 SEA field-missing date tests passed.');
