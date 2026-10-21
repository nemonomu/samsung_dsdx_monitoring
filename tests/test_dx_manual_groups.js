// Run: node --test tests/test_dx_manual_groups.js
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, 'apps/dx/dx_document/manual_column_groups.js'), 'utf8'), context);
const {manualCommonKeys, manualFieldsForScope} = context;
const data = JSON.parse(fs.readFileSync(path.join(root, 'apps/dx/dx_document/manual_data/seed.json'), 'utf8'));

test('every retailer/product field appears exactly once across common and product scopes', () => {
  const before = JSON.stringify(data);
  for (const retailer of Object.keys(data.profiles)) {
    const datasets = data.datasets.filter(ds => ds.retailer === retailer);
    for (const ds of datasets) {
      const common = manualFieldsForScope(datasets, ds.category, 'common');
      const specific = manualFieldsForScope(datasets, ds.category, ds.category);
      const all = [...common, ...specific];
      assert.equal(new Set(all.map(f => f.field)).size, ds.fields.length, ds.key);
      assert.equal(all.length, ds.fields.length, ds.key);
      for (const field of all) assert.ok(ds.fields.includes(field), 'must retain editable original objects');
    }
  }
  assert.equal(JSON.stringify(data), before, 'grouping must not mutate saved data');
});

test('Costco has 17 common fields; capacity and schema-specific fields stay in their product', () => {
  const datasets = data.datasets.filter(ds => ds.retailer === 'SEA/costco');
  assert.equal(manualCommonKeys(datasets).size, 17);
  assert.deepEqual(Array.from(manualFieldsForScope(datasets, 'ref', 'ref'), f => f.field), ['ref_capacity', 'ref_refrigerator_type']);
  assert.ok(manualFieldsForScope(datasets, 'ldy_dryer', 'ldy_dryer').some(f => f.field === 'batch_id'));
});

test('missing, unknown or differently sourced fields are never merged by name', () => {
  const field = (name, direct = true) => ({field: name, direct});
  const datasets = [
    {category: 'tv', fields: [field('sku'), field('savings'), field('custom'), field('star_rating')]},
    {category: 'ref', fields: [field('sku'), field('savings', false), field('custom')]},
  ];
  assert.deepEqual(Array.from(manualCommonKeys(datasets)), ['sku']);
  assert.equal(manualCommonKeys(datasets.slice(0, 1)).size, 0);
  assert.equal(manualCommonKeys([]).size, 0);
  assert.equal(manualFieldsForScope(datasets, 'absent', 'common').length, 0);
});

test('two-product retailers and the dryer category alias use only their own registered datasets', () => {
  for (const retailer of ['SEA/homedepot', 'SEIB/mmkt']) {
    const datasets = data.datasets.filter(ds => ds.retailer === retailer);
    assert.ok(manualCommonKeys(datasets).size > 0);
    for (const key of manualCommonKeys(datasets)) assert.ok(datasets.every(ds => ds.fields.some(f => f.field === key)));
  }
  const datasets = data.datasets.filter(ds => ds.retailer === 'SEIB/mmkt');
  assert.ok(manualFieldsForScope(datasets, 'dryer', 'dryer').length > 0);
});
