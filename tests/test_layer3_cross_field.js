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
const baseTemplate = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'templates',
        'base_layer3.html'
    ),
    'utf8'
);
const layer3Css = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'apps',
        'dx',
        'dx_layer3',
        'static',
        'dx_layer3',
        'css',
        'layer3.css'
    ),
    'utf8'
);

assert(commonSource.includes('/dx/layer1/retail/api/backup-status/'));
for (const label of [
    'SEA TV:', 'SEA REF:', 'SEA LDY:',
    'TSE TV:', 'TSE REF:', 'TSE LDY:'
]) {
    assert(commonSource.includes(label));
}
assert(commonSource.includes('검수 기준 안내'));
assert(commonSource.includes('SEA REF/LDY 크로스필드 검수 기준'));
assert(commonSource.includes('별점 0과 별점 수 0 일치'));
assert(commonSource.includes('<h3>Bestbuy</h3><span>7개</span>'));
assert(commonSource.includes('<h3>Lowes</h3><span>9개</span>'));
assert(commonSource.includes('function showCrossfieldGuide()'));
assert(commonSource.includes('새 대상도 등록 규칙을 자동 표시'));
assert(!commonSource.includes('D-1 (offset_days='));
assert(baseTemplate.includes("AppModal.create('crossfield-guide'"));
assert(baseTemplate.includes('dx_layer3/css/layer3.css\' %}?v=5'));
assert(layer3Css.includes('.btn-crossfield-guide'));
assert(layer3Css.includes('margin-left: auto'));
assert(commonSource.includes("{ key: 'sea', title: 'SEA Retail'"));
assert(commonSource.includes("{ key: 'tse', title: 'TSE Retail'"));
assert(commonSource.includes("toggleCrossfieldRegion('${groupId}', this)"));
assert(layer3Css.includes('.crossfield-region-children.show'));

function testCrossfieldRetailChecksRenderAsRegionAccordions() {
    const container = {
        innerHTML: '',
        querySelectorAll() { return []; },
    };
    const renderSandbox = {
        console,
        window: { LAYER3: { section: 'cross_field' } },
        document: {
            addEventListener() {},
            querySelector() { return null; },
            getElementById(id) {
                return id === 'categories-container' ? container : null;
            },
        },
        esc(value) { return String(value == null ? '' : value); },
        escJs(value) { return String(value == null ? '' : value); },
        AppModal: { getTitle() { return ''; } },
    };
    vm.createContext(renderSandbox);
    vm.runInContext(commonSource, renderSandbox);

    const check = (name, detailCode, checked, failed) => ({
        category: '크로스 필드 검증',
        name,
        detail_code: detailCode,
        description: `${detailCode} 설명`,
        checked,
        passed: checked - failed,
        failed,
        status: failed ? 'WARNING' : 'OK',
    });
    renderSandbox.renderData({
        checks: [
            check('SEA Retail', 'tv', 10, 1),
            check('SEA REF 논리적 일관성', 'sea_ref', 20, 0),
            check('SEA LDY 논리적 일관성', 'sea_ldy', 30, 2),
            check('TSE TV 논리적 일관성', 'tse_tv', 40, 0),
            check('TSE REF 논리적 일관성', 'tse_ref', 50, 0),
            check('TSE LDY 논리적 일관성', 'tse_ldy', 60, 0),
            check('TV Sentiment↔리뷰 일관성', '', 0, 0),
        ],
        summary: {},
    });

    const html = container.innerHTML;
    assert(html.includes('crossfield-region-0-sea'));
    assert(html.includes('crossfield-region-0-tse'));
    assert(html.includes('SEA TV/REF/LDY 크로스필드 검증'));
    assert(html.includes('TSE TV/REF/LDY 크로스필드 검증'));
    assert(html.includes('<div class="crossfield-region-name">SEA Retail</div>'));
    assert(html.includes('<div class="crossfield-region-name">TSE Retail</div>'));
    assert(html.includes('TV Sentiment↔리뷰 일관성'));
    assert(html.indexOf('SEA Retail') < html.indexOf('TSE Retail'));
    assert(html.indexOf('TSE Retail') < html.indexOf('TV Sentiment↔리뷰 일관성'));
    assert.strictEqual((html.match(/\bcrossfield-region-child\b/g) || []).length, 6);
}

testCrossfieldRetailChecksRenderAsRegionAccordions();

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

function testTseCorrectionQueryRendersInInlineAndModalDetail() {
    const displayQuery = "SELECT <unsafe> FROM source WHERE item = 'TV''1';";
    sandbox.window.crossfieldRetailerData = {
        Homepro: {
            rows: [{
                id: 7,
                item: "TV'1",
                retailer_sku_name: 'Example TV',
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
    assert(inlineHtml.includes('3일 수정용 조회 SQL'));
    assert(inlineHtml.includes('cf-tse-display-query-Homepro'));
    assert(inlineHtml.includes('&lt;unsafe&gt;'));
    assert(!inlineHtml.includes('<unsafe>'));

    sandbox.isCrossFieldInline = () => false;
    sandbox.showRetailerDetail('Homepro');
    assert(modal.body.includes('3일 수정용 조회 SQL'));
    assert(modal.body.includes('&lt;unsafe&gt;'));
    assert(modal.body.includes('id="item-list-Homepro"'));

    sandbox.window.crossfieldRetailerData.Homepro.rows[0].item = null;
    sandbox.window.crossfieldRetailerSummary.Homepro.items = [];
    sandbox.showRetailerDetail('Homepro');
    assert(modal.body.includes('ID 목록 (1개)'));
    assert(modal.body.includes('id="item-list-Homepro"'));
}

testTseCorrectionQueryRendersInInlineAndModalDetail();

function testSeaCorrectionQueryUsesInspectionAndSourceDates() {
    sandbox.window.crossfieldProductLine = 'SEA_REF';
    sandbox.window.crossfieldDate = '2026-08-31';
    sandbox.window.crossfieldSourceDate = '2026-08-30';
    sandbox.window.crossfieldDateCol = 'crawl_strdatetime';
    sandbox.window.crossfieldDisplayQueries = {
        Homepro: 'SELECT product_url FROM public.ref_retail_com;'
    };

    inlineHtml = '';
    sandbox.isCrossFieldInline = () => true;
    sandbox.showRetailerDetail('Homepro');

    assert(inlineHtml.includes('검수일 2026-08-31'));
    assert(inlineHtml.includes('데이터일 2026-08-30'));
    assert(inlineHtml.includes('SELECT product_url FROM public.ref_retail_com;'));
}

testSeaCorrectionQueryUsesInspectionAndSourceDates();
assert(commonSource.includes('window.crossfieldDisplayQuery = data.query ||'));
assert(commonSource.includes('window.crossfieldDisplayQueries = data.queries ||'));
assert(commonSource.includes("? (rule.query || '쿼리 없음')"));
assert(commonSource.includes('preserveRaw === true ? text : formatSQL(text)'));
assert(source.includes("itemTitle.textContent = listLabel + ' 목록 ('"));
assert(source.includes("document.getElementById('${queryId}'), true"));
assert(source.includes("if (!isCrossFieldInline())"));
assert(/fixedKeys = \[\s*'_no', 'id', 'item', 'retailer_sku_name'/.test(source));
assert(source.includes("if (urlKey) defaultVisibleSet.add('product_url')"));
assert(source.includes("r['product_url'] = renderProductUrl(row[urlKey])"));
assert(source.includes('window.crossfieldSourceDate'));
assert(source.includes("/^(SEA_|TSE_)/.test(productLineDisplay)"));
assert(source.includes('Shift+클릭으로 범위 선택'));
assert(source.includes("showToast(successCount + '건 확인 처리 완료'"));

function makeReviewCell(rowId, col) {
    const classes = new Set();
    return {
        dataset: { rowId: String(rowId), col },
        isConnected: true,
        classList: {
            add(value) { classes.add(value); },
            remove(value) { classes.delete(value); },
            contains(value) { return classes.has(value); },
        },
        classes,
    };
}

function testCrossfieldShiftRangeUsesOneColumnAndSkipsCompletedCells() {
    const first = makeReviewCell(1, 'star_rating');
    const second = makeReviewCell(2, 'star_rating');
    const completed = makeReviewCell(3, 'star_rating');
    completed.classList.add('cell-normal');
    const fourth = makeReviewCell(4, 'star_rating');
    const otherColumn = makeReviewCell(5, 'count_of_reviews');
    const cells = [first, second, completed, fourth, otherColumn];
    const table = { querySelectorAll() { return cells; } };

    assert.deepStrictEqual(
        Array.from(sandbox._cfGetReviewRangeCells(table, first, fourth)),
        [first, second, fourth]
    );
    assert.deepStrictEqual(
        Array.from(sandbox._cfGetReviewRangeCells(
            table, first, otherColumn
        )),
        []
    );

    sandbox._cfSetReviewSelection([first, second], true);
    assert.strictEqual(sandbox.window._cfReviewAnchorCell, first);
    assert.strictEqual(sandbox.window._cfReviewSelectedCells.length, 2);
    assert(first.classList.contains('cell-review-selected'));
    assert(second.classList.contains('cell-review-selected'));
}

testCrossfieldShiftRangeUsesOneColumnAndSkipsCompletedCells();

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
        esc: value => String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;'),
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
    vm.runInContext(source, commonSandbox);

    assert.strictEqual(commonSandbox.getDefaultCrossfieldHistoryDays('tv'), 2);
    assert.strictEqual(commonSandbox.getDefaultCrossfieldHistoryDays('sea_ref'), 2);
    assert.strictEqual(commonSandbox.getDefaultCrossfieldHistoryDays('tse_ldy'), 2);
    assert.strictEqual(commonSandbox.getDefaultCrossfieldHistoryDays('hhp'), 1);

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
    assert(detailModal.body.includes('onclick="showCrossfieldGuide()"'));
    assert.strictEqual(detailModal.opened, true);

    await commonSandbox.loadCrossfieldRuleDetail(
        'tse_tv', 'rule-1', '2026-08-11', 'TSE 규칙'
    );
    assert.strictEqual(
        requestedUrl,
        '/layer3/api/cross-field-detail/?date=2026-08-11&type=tse_tv&rule_id=rule-1&days=2'
    );

    commonSandbox.window.crossfieldSummaryData = {
        product_line: 'TSE_TV',
        date: '2026-08-11',
        source_date: '2026-08-11',
        rule_summary: [{
            detail_name: '리뷰 수 일치',
            detail_code: 'review_count_match',
            field1: 'count_of_reviews',
            field2: 'count_of_star_ratings',
            error_message: '두 값이 다르면 이상입니다.',
        }],
    };
    commonSandbox.window.crossfieldTitle = 'TSE TV 논리적 일관성';
    commonSandbox.showCrossfieldGuide();

    assert.strictEqual(detailModal.title, 'TSE TV 논리적 일관성 검수 기준 안내');
    assert(detailModal.body.includes('리뷰 수 일치'));
    assert(detailModal.body.includes('count_of_reviews ↔ count_of_star_ratings'));
    assert(detailModal.body.includes('현재 등록된 규칙 1개'));
    assert(detailModal.body.includes('새 대상도 등록 규칙을 자동 표시'));
}

testSeaRetailDisplayKeepsCanonicalTvRoute().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
