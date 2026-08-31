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
            { table: 'youtube', table_name: 'YouTube', total_records: 0, total_issues: 0, status: 'OK' },
            { table: 'tse_ref_retail', table_name: 'TSE REF', total_records: 612, total_issues: 22, status: 'CRITICAL' },
            { table: 'tse_tv_retail', table_name: 'TSE TV', total_records: 993, total_issues: 8, status: 'CRITICAL' },
            { table: 'sea_ldy_retail', table_name: 'LDY', total_records: 468, total_issues: 0, status: 'OK' },
            { table: 'tv_retail', table_name: 'TV Retail', total_records: 316, total_issues: 5, status: 'CRITICAL' },
            { table: 'tse_ldy_retail', table_name: 'TSE LDY', total_records: 583, total_issues: 18, status: 'CRITICAL' },
            { table: 'sea_ref_retail', table_name: 'REF', total_records: 625, total_issues: 57, status: 'CRITICAL' }
        ]
    }]
};
sandbox.prepareLayer2DisplayData(data);
assert.deepStrictEqual(
    data.validation_types[0].tables.map(table => table.table),
    [
        'tv_retail', 'sea_ref_retail', 'sea_ldy_retail',
        'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail', 'youtube'
    ]
);
assert.strictEqual(data.validation_types[0].tables[0].table_name, 'SEA TV');
assert.strictEqual(data.validation_types[0].tables[1].table_name, 'SEA REF');
assert.strictEqual(data.validation_types[0].tables[2].table_name, 'SEA LDY');

const groups = sandbox.buildLayer2NullGroups(data.validation_types[0].tables);
assert.deepStrictEqual(
    JSON.parse(JSON.stringify(groups.map(entry => ({
        type: entry.type,
        name: entry.name || entry.member.table.table_name,
        total_records: entry.total_records,
        total_issues: entry.total_issues,
        status: entry.status
    })))),
    [
        { type: 'group', name: 'SEA Retail', total_records: 1409, total_issues: 62, status: 'CRITICAL' },
        { type: 'group', name: 'TSE Retail', total_records: 2188, total_issues: 48, status: 'CRITICAL' },
        { type: 'table', name: 'YouTube' }
    ]
);

const groupedHtml = sandbox.renderInlineNullGroups(data.validation_types[0]);
assert.ok(groupedHtml.includes('SEA TV/REF/LDY NULL 검증'));
assert.ok(groupedHtml.includes('TSE TV/REF/LDY NULL 검증'));
assert.ok(groupedHtml.includes('SEA TV'));
assert.ok(groupedHtml.includes('SEA REF'));
assert.ok(groupedHtml.includes('SEA LDY'));
assert.ok(groupedHtml.includes('YouTube'));
assert.ok(groupedHtml.indexOf('SEA Retail') < groupedHtml.indexOf('TSE Retail'));

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
assert.ok(!html.includes('batch_id:'));
assert.ok(html.includes("this.dataset.fields, 'sea_ldy_retail'"));

assert.ok(nullSource.includes("/^sea_(ref|ldy)_retail$/.test(tableParam)"));
assert.ok(nullSource.includes("IN ('MAIN', 'BSR')"));
assert.ok(nullSource.includes('data.source_date || date'));
assert.ok(nullSource.includes('data.actual_table'));
assert.ok(!nullSource.includes('· batch_id: ${data.batch_id'));

console.log('Layer2 SEA NULL frontend tests passed.');
