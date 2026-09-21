const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const requests = [];
const nodes = { 'l1-query-sql': {} };
let inserted, modalBody, copied;
const context = {
    L1: {}, URLSearchParams,
    // The app's text-node escaping deliberately leaves quotes unchanged.
    esc: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    getStatusBadge: value => value,
    showToast() {},
    navigator: { clipboard: { writeText: async value => { copied = value; } } },
    isSecureContext: true,
    fetch: url => new Promise(resolve => requests.push({ url, resolve })),
    document: {
        createElement: tag => ({ tag, cells: [], isConnected: true, appendChild(child) { this.cells.push(child); } }),
        getElementById: id => nodes[id],
    },
    AppModal: { create() {}, setTitle() {}, open() {}, setBody(id, html) { modalBody = html; } },
};
context.window = context;
vm.createContext(context);
for (const file of ['retail-query', 'retail-status', 'retail-batches']) {
    vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/' + file + '.js', 'utf8'), context);
}
const batchContext = { check_type: 'seg_retail', product_line: 'seg_tv', source_date: '2026-09-21', retailer: 'Amazon' };
const badge = context.L1.retailStatus.rowBadge({ status: 'OK', batch_count: 2, batch_context: batchContext });
assert(badge.includes('<button') && badge.includes('배치 2개 ▾') && badge.includes('critical'));
assert(badge.includes('aria-expanded="false"') && badge.includes('data-batch-context='));
assert.deepStrictEqual(JSON.parse(badge.match(/data-batch-context="([^"]*)"/)[1].replace(/&quot;/g, '"')), batchContext);
assert(!context.L1.retailStatus.rowBadge({ status: 'OK', batch_count: 1, batch_context: batchContext }).includes('<button'));
assert.strictEqual(requests.length, 0);

const parent = { cells: Array(5), insertAdjacentElement(position, row) { assert.strictEqual(position, 'afterend'); inserted = row; } };
const attrs = { 'aria-expanded': 'false' };
const button = {
    dataset: { batchCount: '2', batchContext: JSON.stringify(batchContext) },
    closest: () => parent,
    getAttribute: key => attrs[key], setAttribute: (key, value) => { attrs[key] = value; },
};
const api = context.L1.retailBatches;
const data = { retailer: 'Amazon', source_date: '2026-09-21', time_basis: '원본 기록 시각', aggregation_basis: '최신 MAIN 배치 반영', batches: [
    { batch_id: '<old>', started_at: '09:00', ended_at: '09:30', main_count: 280, bsr_count: 100, applied: false, sql: "SELECT * WHERE batch_id = '<old>';" },
    { batch_id: 'new', started_at: '11:00', ended_at: '11:35', main_count: 300, bsr_count: 100, applied: true, sql: "SELECT * WHERE batch_id = 'new';" },
] };
(async function() {
    const first = api.toggle(button);
    assert.strictEqual(inserted.cells[0].colSpan, 5);
    assert.strictEqual(attrs['aria-expanded'], 'true');
    assert.strictEqual(requests.length, 1);
    const url = new URL(requests[0].url, 'http://test');
    for (const [key, value] of Object.entries(batchContext)) assert.strictEqual(url.searchParams.get(key), value);
    api.toggle(button); // Closing during the request must stay closed when it completes.
    assert.strictEqual(inserted.hidden, true);
    requests[0].resolve({ ok: true, json: async () => data });
    await first;
    assert.strictEqual(inserted.hidden, true);
    api.toggle(button);
    assert.strictEqual(requests.length, 1);
    assert.strictEqual(inserted.hidden, false);
    const html = inserted.cells[0].innerHTML;
    assert(html.includes('09:00 ~ 09:30') && html.includes('11:00 ~ 11:35'));
    assert(html.includes('&lt;old&gt;') && !html.includes('<old>'));
    assert.strictEqual((html.match(/>반영<\/span>/g) || []).length, 1);
    assert.strictEqual((html.match(/>조회 SQL<\/button>/g) || []).length, 2);
    const child = { closest: () => inserted };
    api.sql(child, 1);
    assert.strictEqual(nodes['l1-query-sql'].textContent, data.batches[1].sql);
    assert(modalBody.includes('복사'));
    await context.L1.retailQuery.copy();
    assert.strictEqual(copied, data.batches[1].sql);

    const failed = api.reload(child);
    requests[1].resolve({ ok: false });
    await failed;
    assert(inserted.cells[0].innerHTML.includes('다시 조회'));
    const retry = api.reload(child);
    requests[2].resolve({ ok: true, json: async () => data });
    await retry;
    assert(inserted.cells[0].innerHTML.includes('배치별 내역'));

    const stale = api.reload(child);
    const pendingHtml = inserted.cells[0].innerHTML;
    inserted.isConnected = false;
    requests[3].resolve({ ok: true, json: async () => data });
    await stale;
    assert.strictEqual(inserted.cells[0].innerHTML, pendingHtml);
    console.log('Batch row expansion, lazy fetch, SQL copy, retry and stale response tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
