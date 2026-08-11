const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'static',
        'dx_layer3',
        'js',
        'cross-field.js'
    ),
    'utf8'
);
const commonSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'static',
        'dx_layer3',
        'js',
        'common.js'
    ),
    'utf8'
);

assert(commonSource.includes('/dx/layer1/retail/api/backup-status/'));
for (const label of ['SEA TV:', 'TSE TV:', 'TSE REF:', 'TSE LDY:']) {
    assert(commonSource.includes(label));
}

let inlineHtml = '';
const modal = { title: '', body: '', opened: false };
const sandbox = {
    console,
    document: {
        addEventListener() {},
        getElementById() { return null; },
        querySelector() { return null; },
    },
    window: { crossfieldRetailerData: null },
    esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    },
    renderProductUrl(value) { return value || ''; },
    FilterBar: function FilterBar() {
        this.render = function render() { return this; };
    },
    setTimeout() {},
    isCrossFieldInline: () => true,
    ViewStack: {
        push(html) { inlineHtml = html; },
    },
    AppModal: {
        setTitle(_name, title) { modal.title = title; },
        setBody(_name, body) { modal.body = body; },
        open() { modal.opened = true; },
        getTitle() { return ''; },
    },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

sandbox.showRetailerDetail('Homepro');
assert(inlineHtml.includes('상세 데이터를 찾을 수 없습니다'));
assert(inlineHtml.includes('ViewStack.pop()'));

sandbox.isCrossFieldInline = () => false;
sandbox.window.crossfieldRetailerData = {};
sandbox.showRetailerDetail('Homepro');
assert.strictEqual(modal.title, 'Homepro - 상세 조회');
assert(modal.body.includes('다시 조회해 주세요'));
assert.strictEqual(modal.opened, true);

function testTseCanonicalQueryRendersInInlineAndModalDetail() {
    const displayQuery = "WITH batches AS (<unsafe>) SELECT * FROM source WHERE item = 'TV''1';";
    sandbox.window.crossfieldRetailerData = {
        Homepro: {
            rows: [{
                id: 7,
                item: "TV'1",
                account_name: 'Homepro',
                crawl_datetime: '2026-08-10T09:10:00+09:00',
            }],
        },
    };
    sandbox.window.crossfieldRetailerSummary = {
        Homepro: { count: 1, items: ["TV'1"] },
    };
    sandbox.window.crossfieldProductLine = 'TSE_TV';
    sandbox.window.crossfieldDate = '2026-08-10';
    sandbox.window.crossfieldDateCol = 'crawl_datetime';
    sandbox.window.crossfieldRuleName = '가격 검증';
    sandbox.window.crossfieldDisplayQueries = { Homepro: displayQuery };
    sandbox.window.crossfieldDays = 3;
    sandbox.window.crossfieldRetailerColumns = {};

    inlineHtml = '';
    sandbox.isCrossFieldInline = () => true;
    sandbox.showRetailerDetail('Homepro');
    assert(inlineHtml.includes('3일치 최신 배치 조회 SQL'));
    assert(inlineHtml.includes('cf-tse-display-query-Homepro'));
    assert(inlineHtml.includes('&lt;unsafe&gt;'));
    assert(!inlineHtml.includes('<unsafe>'));

    sandbox.isCrossFieldInline = () => false;
    sandbox.showRetailerDetail('Homepro');
    assert(modal.body.includes('3일치 최신 배치 조회 SQL'));
    assert(modal.body.includes('&lt;unsafe&gt;'));
    assert(modal.body.includes('id="item-list-Homepro"'));

    sandbox.window.crossfieldRetailerData.Homepro.rows[0].item = null;
    sandbox.window.crossfieldRetailerSummary.Homepro.items = [];
    sandbox.showRetailerDetail('Homepro');
    assert(modal.body.includes('ID 목록 (1개)'));
    assert(modal.body.includes('id="item-list-Homepro"'));
}

testTseCanonicalQueryRendersInInlineAndModalDetail();
assert(commonSource.includes('window.crossfieldDisplayQuery = data.query ||'));
assert(commonSource.includes('window.crossfieldDisplayQueries = data.queries ||'));
assert(commonSource.includes("? (rule.query || '쿼리 없음')"));
assert(commonSource.includes('preserveRaw === true ? text : formatSQL(text)'));
assert(source.includes("itemTitle.textContent = listLabel + ' 목록 ('"));
assert(source.includes("document.getElementById('${queryId}'), true"));
assert(source.includes("if (!isCrossFieldInline())"));

async function testSeaRetailDisplayKeepsCanonicalTvRoute() {
    let requestedUrl = '';
    const detailModal = { title: '', body: '', opened: false };
    const commonSandbox = {
        console,
        window: { LAYER3: { section: 'dashboard' } },
        document: {
            addEventListener() {},
            querySelector() { return null; },
            getElementById() { return null; },
        },
        getSelectedDate: () => '2026-08-11',
        escJs: value => String(value || ''),
        fetchAPI: async url => {
            requestedUrl = url;
            return {
                date: '2026-08-11',
                product_line: 'tv',
                total_anomalies: 0,
                anomalies: [],
                rule_summary: [],
            };
        },
        AppModal: {
            setTitle(_name, title) { detailModal.title = title; },
            setBody(_name, body) { detailModal.body = body; },
            open() { detailModal.opened = true; },
            getTitle() { return ''; },
        },
    };

    vm.createContext(commonSandbox);
    vm.runInContext(commonSource, commonSandbox);

    let copiedSql = '';
    commonSandbox.navigator = {
        clipboard: {
            writeText(value) {
                copiedSql = value;
                return Promise.resolve();
            },
        },
    };
    commonSandbox.window.isSecureContext = true;
    commonSandbox.copyQueryToClipboard({
        textContent: "SELECT * FROM x WHERE item = 'A AND B';",
        previousElementSibling: null,
        nextElementSibling: null,
    }, true);
    assert.strictEqual(copiedSql, "SELECT * FROM x WHERE item = 'A AND B';");

    assert.strictEqual(
        commonSandbox.getLayer3DisplayName('TV 논리적 일관성', ''),
        'SEA Retail'
    );
    await commonSandbox.showDetail('크로스 필드 검증', 'SEA Retail', 'tv');

    assert.strictEqual(
        requestedUrl,
        '/layer3/api/cross-field-detail/?date=2026-08-11&type=tv'
    );
    assert.strictEqual(detailModal.title, 'SEA Retail (0건)');
    assert(detailModal.body.includes('논리 오류 데이터가 없습니다'));
    assert.strictEqual(detailModal.opened, true);
}

testSeaRetailDisplayKeepsCanonicalTvRoute().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
