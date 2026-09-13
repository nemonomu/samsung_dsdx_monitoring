const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const source = fs.readFileSync(path.join(__dirname,
    '../apps/dx/dx_layer3/static/dx_layer3/js/cross-field.js'), 'utf8');
const card = {innerHTML: ''};
const sandbox = {
    window: {}, console,
    document: {
        addEventListener() {},
        querySelector(selector) {
            return selector.startsWith('.rule-summary-card[')
                ? {querySelector: () => card} : null;
        },
        querySelectorAll() { return []; },
    },
    esc: value => String(value == null ? '' : value),
    isCrossFieldInline: () => false,
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
assert.strictEqual(sandbox.getDefaultCrossfieldHistoryDays('new_country_ldy'), 3);
for (const days of [3, 4]) {
    const rows = Array.from({length: days}, (_, i) => ({
        id: i + 1, item: 'same', account_name: 'New retailer',
        row_role: i === days - 1 ? 'target' : 'comparison_history',
        crawl_datetime: `2026-09-${String(14-days+i).padStart(2,'0')}`,
        value: i === days - 1 ? null : 'normal value',
    }));
    sandbox.window.crossfieldRetailerData = {'New retailer': {rows}};
    sandbox.window.crossfieldRuleId = 'new-rule';
    sandbox.window.crossfieldEditableCols = new Set(['value']);
    sandbox.window.crossfieldNormalReviews = {'1_value': {reason: 'accepted history'}};
    sandbox.window.crossfieldSourceDate = '2026-09-13';
    let htmlRows;
    sandbox.window._cfDetailState = {
        allData: rows.map(row => ({...row, _rowId: row.id,
            _rowRole: row.row_role, _rowDate: row.crawl_datetime})),
        allColumns: [{key: 'crawl_datetime'}, {key: 'value'}],
        editableCols: sandbox.window.crossfieldEditableCols,
        normalReviews: sandbox.window.crossfieldNormalReviews,
        table: {renderBody(data, render) { htmlRows = data.map(render); }},
    };
    sandbox._cfSortAndRender();
    assert.strictEqual(htmlRows.length, days, 'reviewed history must stay visible');
    htmlRows.slice(0, -1).forEach(html => {
        assert(!html.includes('data-editable'));
        assert(html.includes('cf-history-date-row'));
    });
    assert(htmlRows.at(-1).includes('data-editable="true"'));
    sandbox._cfUpdateRetailerCounts();
    assert(card.innerHTML.includes('이상 1건'));
    sandbox._cfUpdateRuleCardCount();
    assert(card.innerHTML.includes('이상 1건'));
    sandbox.window.crossfieldNormalReviews[`${days}_value`] = {reason: 'accepted target'};
    sandbox._cfSortAndRender();
    assert.strictEqual(htmlRows.length, days);
    sandbox._cfUpdateRetailerCounts();
    assert(card.innerHTML.includes('0건'));
}
console.log('Cross-field history display, edit scope and recount tests passed.');
