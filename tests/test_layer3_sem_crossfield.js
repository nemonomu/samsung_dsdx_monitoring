const assert = require('assert');
const fs = require('fs');

const common = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/common.js', 'utf8'
);
const crossField = fs.readFileSync(
    'apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js', 'utf8'
);
const dashboard = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_dashboard.html', 'utf8'
);
const detail = fs.readFileSync(
    'apps/dx/dx_layer3/templates/layer3_cross_field.html', 'utf8'
);

assert(common.includes("const regionGroups = { sea: [], siel: [], sem: [], tse: [] }"));
assert(common.includes("{ key: 'sem', title: 'SEM Retail'"));
assert(common.includes("detailCode === 'sem_tv' || checkName.includes('SEM TV')"));
assert(common.includes("detailCode === 'sem_ref' || checkName.includes('SEM REF')"));
assert(common.includes("detailCode === 'sem_ldy' || checkName.includes('SEM LDY')"));
assert(common.includes("detailCode === 'siel_tv' || detailCode === 'sem_tv' || detailCode === 'tse_tv'"));
assert(common.includes("detailCode === 'siel_ref' || detailCode === 'sem_ref' || detailCode === 'tse_ref'"));
assert(common.includes("const isSemCrossfield = /^SEM (TV|REF|LDY)"));
assert(common.includes("type=${category}"));
assert(common.includes("const loadedRules = isSemCrossfield"));
assert(crossField.includes('function _cfPersistedRuleId'));
assert(crossField.includes('var ruleId = _cfPersistedRuleId('));
assert(dashboard.includes("common.js' %}?v=20260907-2"));
assert(dashboard.includes("cross-field.js' %}?v=19"));
assert(detail.includes("common.js' %}?v=20260907-2"));
assert(detail.includes("cross-field.js' %}?v=19"));

console.log('Layer3 SEM cross-field UI tests passed.');
