const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const dashboardSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js', 'utf8'
);
const nullSource = fs.readFileSync(
    'apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js', 'utf8'
);

const sandbox = {
    console,
    renderNullFieldsDetail(fields) {
        return Object.keys(fields || {}).join(',');
    }
};
vm.createContext(sandbox);
vm.runInContext(dashboardSource, sandbox);

const data = {
    validation_types: [{
        tables: [
            { table: 'youtube', table_name: 'YouTube' },
            { table: 'tse_tv_retail', table_name: 'TSE TV' },
            { table: 'sea_ldy_retail', table_name: 'LDY' },
            { table: 'tv_retail', table_name: 'TV Retail' },
            { table: 'sea_ref_retail', table_name: 'REF' }
        ]
    }]
};
sandbox.prepareLayer2DisplayData(data);
assert.deepStrictEqual(
    data.validation_types[0].tables.map(table => table.table),
    [
        'tv_retail', 'sea_ref_retail', 'sea_ldy_retail',
        'tse_tv_retail', 'youtube'
    ]
);
assert.strictEqual(data.validation_types[0].tables[1].table_name, 'SEA REF');
assert.strictEqual(data.validation_types[0].tables[2].table_name, 'SEA LDY');

const html = sandbox.renderDXTableDetail(
    { type: 'null' },
    {
        table: 'sea_ldy_retail',
        table_name: 'SEA LDY',
        inspection_date: '2026-08-31',
        source_date: '2026-08-30',
        offset_days: -1,
        retailers: [{
            retailer: 'Lowes',
            total: 197,
            total_null_count: 1,
            status: 'CRITICAL',
            batch_id: 'l_260830_191936',
            fields_detail: { sku: 1 }
        }]
    }
);
assert.ok(html.includes('검수일 2026-08-31'));
assert.ok(html.includes('데이터일 2026-08-30'));
assert.ok(html.includes('D-1 (offset_days=-1)'));
assert.ok(html.includes('batch_id: l_260830_191936'));
assert.ok(html.includes("this.dataset.fields, 'sea_ldy_retail'"));

assert.ok(nullSource.includes("/^sea_(ref|ldy)_retail$/.test(tableParam)"));
assert.ok(nullSource.includes("IN ('MAIN', 'BSR')"));
assert.ok(nullSource.includes('data.source_date || date'));
assert.ok(nullSource.includes('data.actual_table'));

console.log('Layer2 SEA NULL frontend tests passed.');
