const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const content = {innerHTML: '', querySelector: () => null, addEventListener() {}};
const notifications = [];
const copied = [];
let fallbackResult = true;
let throwFallback = false;
let temporaryInput;
const selection = {
    rangeCount: 0,
    removeAllRanges() { this.rangeCount = 0; this.range = null; },
    addRange(range) { this.rangeCount = 1; this.range = range; },
    getRangeAt() { return this.range; },
};
const sandbox = {
    console, isClosed: false, causeOptions: {},
    normalizeReportCause: value => value || '',
    getCauseOptionsHtml: () => '<option>원인</option>',
    // Match the shared esc(): escape text, but leave attribute quotes alone.
    esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    AppButton: {html: label => `<button>${label}</button>`, iconHtml: () => ''},
    enableColumnResize() {},
    showToast: (message, type) => notifications.push({message, type}),
    navigator: {clipboard: {writeText: async text => copied.push(text)}},
    window: {isSecureContext: true, getSelection: () => selection},
    document: {
        activeElement: {focus() {}},
        getElementById: () => content,
        createRange: () => ({selectNodeContents(node) { this.node = node; }, cloneRange() { return this; }}),
        createElement: () => (temporaryInput = {
            style: {}, focus() {}, select() {}, remove() { this.removed = true; },
        }),
        body: {appendChild() {}},
        execCommand(command) {
            assert.equal(command, 'copy');
            if (throwFallback) throw new Error('Clipboard unavailable');
            if (fallbackResult) copied.push(temporaryInput.value);
            return fallbackResult;
        },
    },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('apps/ds/ds_layer4/static/ds_layer4/js/report.js', 'utf8'), sandbox);

const imageUrl = 'https://example.com/images/long-name.jpg?size=1600&label="한글"';
const row = {id: 7, retailer: 'Amazon', retailersku: 'SKU-7', title: 'SSD "2TB" <b> & NVMe',
    imageurl: imageUrl, producturl: 'https://example.com/product/7', retailprice: 0, ships_from: null};
for (const closed of [false, true]) {
    sandbox.isClosed = closed;
    const retailerHtml = sandbox.renderAnomalyItems([row], 'Amazon');
    sandbox.renderAllAnomaliesTable({anomalies: [row]});
    for (const html of [retailerHtml, content.innerHTML]) {
        assert.match(html, /제목<\/th>\s*<th[^>]*>IMAGEURL<\/th>\s*<th[^>]*>가격<\/th>/);
        assert(html.includes('data-copy-text="0" data-copy-label="가격"'));
        assert(html.includes('data-copy-text="NULL" data-copy-label="SHIPS FROM"'));
        assert(html.includes('data-copy-text="SSD &quot;2TB&quot; &lt;b&gt; &amp; NVMe"'));
        assert(html.includes('data-copy-text="https://example.com/images/long-name.jpg?size=1600&amp;label=&quot;한글&quot;"'));
        assert(html.includes('rel="noopener noreferrer"'));
        assert(html.includes('class="report-copy-panel"'));
    }
    assert.equal(retailerHtml.includes('id="anomalyCheck_7"'), !closed);
    assert.equal(retailerHtml.includes('>저장</button>'), !closed);
}
for (const missing of [null, undefined, '', '   ']) {
    const html = sandbox.renderReportValueCell('IMAGEURL', missing, {link: true});
    assert(html.includes('null-value">NULL</span>'));
    assert(!html.includes('href='));
}
const unsafe = sandbox.renderReportValueCell('IMAGEURL', 'javascript:alert(1)', {link: true});
assert(!unsafe.includes('href='));
assert(unsafe.includes('data-copy-text="javascript:alert(1)"')); // Still inspect/copy malformed data.
const quoted = sandbox.renderReportValueCell('IMAGEURL', 'https://example.com/" onmouseover="alert(1)', {link: true});
assert(!/<[^>]*\sonmouseover="/.test(quoted));

// Selection exposes the complete original string and excludes button text.
const panel = {
    '.report-copy-label': {}, '.report-copy-value': {}, '.report-copy-selected': {disabled: true},
};
let priorDeselected = false;
const section = {
    querySelector: selector => panel[selector],
    querySelectorAll: () => [{classList: {remove() { priorDeselected = true; }}}],
};
const valueNode = {textContent: imageUrl};
const classes = new Set();
const cell = {
    dataset: {copyLabel: 'IMAGEURL', copyText: imageUrl},
    closest: () => section, querySelector: () => valueNode, focus() {},
    classList: {add: name => classes.add(name), remove: name => classes.delete(name)},
};
sandbox.selectReportValueCell(cell);
assert(priorDeselected);
assert.equal(panel['.report-copy-value'].value, imageUrl);
assert.equal(panel['.report-copy-selected'].disabled, false);
assert.strictEqual(selection.range.node, valueNode);
const selectedRange = selection.range;
sandbox.selectReportValueCell(cell, {target: {closest: () => ({})}});
assert.strictEqual(selection.range, selectedRange); // Controls/links keep their own interaction.

(async () => {
    await sandbox.copyReportValue(imageUrl);
    assert.equal(copied.at(-1), imageUrl);
    assert.equal(notifications.at(-1).type, 'success');
    sandbox.navigator.clipboard.writeText = async () => { throw new Error('Denied'); };
    await sandbox.copyReportValue(row.title);
    assert.equal(copied.at(-1), row.title);
    assert(temporaryInput.removed);
    assert.strictEqual(selection.range, selectedRange);
    sandbox.window.isSecureContext = false;
    sandbox.navigator.clipboard = undefined;
    await sandbox.copyReportValue('HTTP fallback');
    assert.equal(copied.at(-1), 'HTTP fallback');
    for (const throws of [false, true]) {
        fallbackResult = false;
        throwFallback = throws;
        await sandbox.copyReportValue('not copied');
        assert.equal(notifications.at(-1).type, 'warning');
        assert(temporaryInput.removed);
        assert.notEqual(copied.at(-1), 'not copied');
    }
    fallbackResult = true;
    throwFallback = false;
    let prevented = false;
    sandbox.handleReportValueKey({target: cell, key: 'c', ctrlKey: true, preventDefault() { prevented = true; }}, cell);
    assert(prevented);
    assert.equal(copied.at(-1), imageUrl);
    prevented = false;
    sandbox.handleReportValueKey({target: {}, key: 'c', ctrlKey: true, preventDefault() { prevented = true; }}, cell);
    assert(!prevented); // Nested controls retain keyboard behavior.
    sandbox.handleReportValueKey({target: cell, key: 'Escape'}, cell);
    assert.equal(panel['.report-copy-value'].value, '');
    assert.equal(panel['.report-copy-selected'].disabled, true);
    assert(!classes.has('report-cell-selected'));
    console.log('DS report image URL, full-value selection, escaping and clipboard fallback tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
