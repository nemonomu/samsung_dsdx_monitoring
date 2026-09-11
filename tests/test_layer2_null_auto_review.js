const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const commonSource = fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/layer2-common.js', 'utf8');
const nullSource = fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/null_validation.js', 'utf8');
const dashboardSource = fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/dashboard.js', 'utf8');
const reviewLogSource = fs.readFileSync('apps/dx/dx_layer2/static/dx_layer2/js/null_review_log.js', 'utf8');
const escape = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function commonSandbox() {
    const sandbox = {
        console, URLSearchParams,
        window: { LAYER2: { section: 'null_validation' } },
        document: { addEventListener() {}, getElementById() { return null; }, querySelector() { return null; } },
        modalState: { days: 1, selectedField: 'ref_capacity', nullFieldsData: {} },
        esc: escape,
        FilterBar: function(selector, options) {
            this.render = () => this;
            this.getVisibleColumns = () => options.columnSelector.columns.filter(
                col => options.columnSelector.defaultVisible.includes(col.key)
            );
        },
        Pagination: function() {},
        showToast() {},
        getCsrfToken() { return 'csrf-placeholder'; }
    };
    vm.createContext(sandbox);
    vm.runInContext(commonSource, sandbox);
    sandbox._buildDetailTable = () => {};
    sandbox.detailRenderPage = () => {};
    return sandbox;
}

function renderRows(sandbox, overrides = {}) {
    const rows = [
        { id: 1, item: 'A', ref_capacity: null, crawl_datetime: '2026-09-13', null_fields: ['ref_capacity'] },
        { id: 2, item: 'B', ref_capacity: null, crawl_datetime: '2026-09-13', null_fields: ['ref_capacity'] },
        { id: 3, item: 'C', ref_capacity: null, crawl_datetime: '2026-09-13', null_fields: ['ref_capacity'] },
        { id: 4, item: 'A', ref_capacity: null, crawl_datetime: '2026-09-12', null_fields: ['ref_capacity'] }
    ];
    sandbox.renderDetailWithTable(Object.assign({
        config: [{ key: 'item', label: 'item' }, { key: 'ref_capacity', label: 'ref_capacity' }],
        data: rows, type: 'null', tableParam: 'sea_ref_retail',
        supportsNullAutoReview: true, nullReviewField: 'ref_capacity',
        crawlDate: '2026-09-13', editableDate: '2026-09-13', dateColumn: 'crawl_datetime',
        normalReviews: {
            '1_ref_capacity': { auto_applied: true, reason: '상품페이지 내 항목 부재 <script>',
                memo: '<img src=x onerror=bad()>',
                created_id: 'reviewer <1>', original_crawl_date: '2026-09-12',
                original_created_at: '2026-09-12 10:00', correction_id: 17, evidence_id: 501 },
            '2_ref_capacity': { auto_applied: false, reason: '해당값 정상 확인',
                created_id: 'reviewer2', original_crawl_date: '2026-09-13', correction_id: 18 }
        }
    }, overrides));
    return rows;
}

function testVisibleReviewColumnsAndNoFormatChange() {
    const sandbox = commonSandbox();
    const rows = renderRows(sandbox);
    const keys = Array.from(sandbox.detailViewState.columns, col => col.key);
    assert.deepStrictEqual(keys, ['item', 'ref_capacity', '_null_review_status', '_null_review_reason', '_null_review_basis']);
    assert.strictEqual(rows[0]._null_review_status, '자동확인');
    assert.strictEqual(rows[1]._null_review_status, '수동확인');
    assert.strictEqual(rows[2]._null_review_status, '확인 필요');
    assert.strictEqual(rows[3]._null_review_status, '비교 이력');
    const reason = sandbox.getCellHtml(rows[0], { key: '_null_review_reason' }, 'sea_ref_retail');
    assert.ok(reason.includes('상품페이지 내 항목 부재 &lt;script&gt;'));
    assert.ok(!reason.includes('<script>'));
    assert.ok(reason.includes('&lt;img'));
    assert.ok(!reason.includes('<img'));
    assert.ok(reason.includes('메모: &lt;img'));
    assert.ok(!reason.includes('title='), 'reason must be visible without hover');
    const basis = sandbox.getCellHtml(rows[0], { key: '_null_review_basis' }, 'sea_ref_retail');
    assert.ok(basis.includes('2026-09-12'));
    assert.ok(basis.includes('reviewer &lt;1&gt;'));
    assert.ok(basis.includes('자동확인 중단'));
    const value = sandbox.getCellHtml(rows[0], { key: 'ref_capacity' }, 'sea_ref_retail');
    assert.ok(value.includes('>NULL</td>'));
    assert.ok(value.includes('class="cell-normal null-review-value automatic"'));
    assert.ok(!value.includes('null-value'));
    assert.ok(!value.includes('data-editable'));
    const manualValue = sandbox.getCellHtml(rows[1], { key: 'ref_capacity' }, 'sea_ref_retail');
    assert.ok(manualValue.includes('class="cell-normal null-review-value manual"'));
    assert.ok(!manualValue.includes('null-value'));
    const pendingValue = sandbox.getCellHtml(rows[2], { key: 'ref_capacity' }, 'sea_ref_retail');
    assert.ok(pendingValue.includes('class="null-value"'));
    assert.ok(!pendingValue.includes('cell-normal'));
    assert.ok(!pendingValue.includes('null-review-value'));

    sandbox.detailViewState.normalReviews['1_ref_capacity'].revoked_at = '2026-09-14';
    sandbox._annotateNullReviewRows(rows);
    const revoked = sandbox.getCellHtml(rows[0], { key: '_null_review_basis' }, 'sea_ref_retail');
    assert.ok(revoked.includes('근거 취소됨'));
    assert.ok(!revoked.includes('<button'));

    sandbox.detailViewState.filterBar.getValue = key => key === 'filterCol' ? '_null_review_status' : '자동확인';
    sandbox.applyDetailFilter();
    assert.deepStrictEqual(Array.from(sandbox.detailViewState.filteredData, row => row.id), [1]);

    renderRows(sandbox, { type: 'format', supportsNullAutoReview: true });
    assert.strictEqual(sandbox.detailViewState.supportsNullAutoReview, false);
    assert.ok(sandbox.detailViewState.columns.every(col => !col.key.startsWith('_null_review_')));
    assert.ok(!sandbox.getCellHtml(rows[0], { key: 'ref_capacity' }, 'sea_ref_retail').includes('null-review-value'));
    renderRows(sandbox, { supportsNullAutoReview: false });
    assert.ok(sandbox.detailViewState.columns.every(col => !col.key.startsWith('_null_review_')));
    assert.ok(!sandbox.getCellHtml(rows[0], { key: 'ref_capacity' }, 'sea_ref_retail').includes('null-review-value'));
    const config = [{ key: 'ref_capacity', label: 'ref_capacity' }];
    renderRows(sandbox, { config });
    renderRows(sandbox, { config });
    assert.strictEqual(config.length, 1);
    assert.strictEqual(sandbox.detailViewState.columns.filter(col => col.key === '_null_review_status').length, 1);
}

function testManualOnlyReviewExplainsAutomaticExclusion() {
    const sandbox = commonSandbox();
    for (const explanation of ['item 정보 부족', '제품명 정보 부족', '자동확인 대상 사유 아님', '<script>']) {
        const rows = renderRows(sandbox, { normalReviews: {
            '1_ref_capacity': { auto_applied: false, auto_eligible: false,
                auto_exclusion_reason: explanation, reason: '상품페이지 내 항목 부재',
                memo: '상품 상세페이지에 용량 정보가 표시되지 않음',
                original_crawl_date: '2026-09-13', created_id: 'reviewer', correction_id: 17 }
        } });
        assert.strictEqual(rows[0]._null_review_status, '수동확인');
        const basis = sandbox.getCellHtml(rows[0], { key: '_null_review_basis' }, 'sea_ref_retail');
        assert.ok(basis.includes('자동확인 제외 · ' + escape(explanation)));
        assert.ok(!basis.includes('<script>'));
        assert.ok(basis.includes('확인 취소'), 'manual-only acceptance must remain cancellable');
        const reason = sandbox.getCellHtml(rows[0], { key: '_null_review_reason' }, 'sea_ref_retail');
        assert.ok(reason.includes('상품페이지 내 항목 부재'));
        assert.ok(reason.includes('메모: 상품 상세페이지에 용량 정보가 표시되지 않음'));
    }
    for (const eligibility of [true, undefined]) {
        sandbox.detailViewState.normalReviews['1_ref_capacity'].auto_eligible = eligibility;
        const basis = sandbox.getCellHtml(sandbox.detailViewState.allData[0], { key: '_null_review_basis' }, 'sea_ref_retail');
        assert.ok(!basis.includes('자동확인 제외'), 'only explicit server ineligibility should be displayed');
    }
}

function testReasonAndMemoFollowCurrentQueryMetadata() {
    const sandbox = commonSandbox();
    const manual = { reason: '상품페이지 내 항목 부재', memo: '상품 상세페이지에 용량 정보가 표시되지 않음',
        auto_applied: false, auto_eligible: true, original_crawl_date: '2026-09-12',
        original_created_at: '2026-09-12T10:00:00+09:00', created_id: 'reviewer', correction_id: 17 };
    for (const day of ['2026-09-12', '2026-09-13']) {
        const automatic = day === '2026-09-13';
        renderRows(sandbox, { crawlDate: day, editableDate: day,
            data: [{ id: 7, item: 'A', retailer_sku_name: 'Refrigerator A', ref_capacity: null,
                crawl_datetime: day, null_fields: ['ref_capacity'] }],
            normalReviews: { '7_ref_capacity': Object.assign({}, manual, { auto_applied: automatic }) }
        });
        // Re-rendering with an API response replaces the prior query's review metadata.
        const row = sandbox.detailViewState.allData[0];
        assert.strictEqual(row._null_review_status, automatic ? '자동확인' : '수동확인');
        const reason = sandbox.getCellHtml(row, { key: '_null_review_reason' }, 'sea_ref_retail');
        assert.ok(reason.includes(manual.reason));
        assert.ok(reason.includes('메모: ' + manual.memo));
        const basis = sandbox.getCellHtml(row, { key: '_null_review_basis' }, 'sea_ref_retail');
        assert.ok(basis.includes('2026-09-12'));
        assert.ok(basis.includes('reviewer'));
        assert.ok(!basis.includes('자동확인 제외'));
    }
    renderRows(sandbox, { normalReviews: {} });
    const unreviewed = sandbox.detailViewState.allData[0];
    assert.strictEqual(unreviewed._null_review_status, '확인 필요');
    assert.strictEqual(sandbox.getCellHtml(unreviewed, { key: '_null_review_reason' }, 'sea_ref_retail'),
        '<td class="null-review-reason">-</td>');
}

function testDialogExplainsIdentityRequirementOnlyForNullAutoReview() {
    const sandbox = commonSandbox();
    const element = { addEventListener() {}, classList: { add() {} } };
    const overlay = { ...element, querySelector: () => element };
    sandbox.document.createElement = () => overlay;
    sandbox.document.body = { appendChild() {} };
    sandbox.setTimeout = fn => fn();
    sandbox.fetch = async () => ({ json: async () => ({ reasons: [] }) });
    renderRows(sandbox);
    sandbox._showReviewDialog(() => {});
    assert.ok(overlay.innerHTML.includes('같은 국가·리테일러·제품군'));
    assert.ok(overlay.innerHTML.includes('실제 확인일 다음 검수일부터'));
    assert.ok(overlay.innerHTML.includes('item·제품명 정보가 부족한 건은 이번 검수만 수동확인합니다.'));
    renderRows(sandbox, { type: 'format' });
    sandbox._showReviewDialog(() => {});
    assert.ok(!overlay.innerHTML.includes('null-review-dialog-note'));
    renderRows(sandbox, { supportsNullAutoReview: false });
    sandbox._showReviewDialog(() => {});
    assert.ok(!overlay.innerHTML.includes('null-review-dialog-note'));
}

function testResolvedNullFieldDoesNotDisplayPriorAcceptance() {
    const sandbox = commonSandbox();
    for (const automatic of [false, true]) {
        renderRows(sandbox, {
            tableParam: 'tse_ref_retail', nullReviewField: 'star_rating',
            config: [{ key: 'star_rating', label: 'star_rating' }],
            data: [{ id: 7, item: 'A', star_rating: 4.5, count_of_reviews: null,
                crawl_datetime: '2026-09-13', null_fields: ['count_of_reviews'] }],
            normalReviews: {
                '7_star_rating': { auto_applied: automatic, reason: '상품페이지 내 항목 부재',
                    memo: '이전 NULL 확인', correction_id: 17 }
            }
        });
        const row = sandbox.detailViewState.allData[0];
        assert.strictEqual(row._null_review_status, '정상');
        assert.strictEqual(row._null_review_reason, '-');
        assert.strictEqual(row._null_review_basis, '-');
        assert.strictEqual(sandbox._nullReviewForRow(row), null);
        assert.ok(!sandbox.getCellHtml(row, { key: 'star_rating' }, 'tse_ref_retail').includes('cell-normal'));
        assert.strictEqual(sandbox.getCellHtml(row, { key: '_null_review_reason' }, 'tse_ref_retail'),
            '<td class="null-review-reason">-</td>');
        assert.strictEqual(sandbox.getCellHtml(row, { key: '_null_review_basis' }, 'tse_ref_retail'),
            '<td class="null-review-basis">-</td>');
    }
}

function testRelatedNullFieldDoesNotInflateSelectedFieldSummary() {
    let rendered = '';
    const sandbox = {
        console, renderCountryFlagLabel: value => value,
        getSelectedDate: () => '2026-09-13', getDetailBody: () => ({}),
        isInlineMode: () => true,
        buildDetailContainerHtml: options => options.itemQueryHtml,
        renderDetailWithTable() {},
        ViewStack: { stack: [], push(html) { rendered = html; this.stack.push({}); } }
    };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    sandbox._buildTseNullQueryHtml = () => '';
    vm.runInContext("modalState.tableParam='tse_ref_retail'; modalState.tableName='TSE REF'; modalState.retailer='Powerbuy';", sandbox);
    sandbox.renderNullFieldDetailView('star_rating', {
        date: '2026-09-13', date_column: 'crawl_datetime', supports_null_auto_review: true,
        display_config: { star_rating: { select_columns: ['item', 'star_rating', 'count_of_reviews', 'crawl_datetime'] } },
        results: [
            { id: 1, star_rating: 4.5, null_fields: ['count_of_reviews'], crawl_datetime: '2026-09-13' },
            { id: 2, star_rating: 4.5, null_fields: ['count_of_reviews'], crawl_datetime: '2026-09-13' },
            { id: 3, star_rating: null, null_fields: ['star_rating'], crawl_datetime: '2026-09-13' },
            { id: 4, star_rating: null, null_fields: ['star_rating'], crawl_datetime: '2026-09-13' },
            { id: 5, star_rating: null, null_fields: ['star_rating'], crawl_datetime: '2026-09-13' }
        ],
        normal_reviews: {
            '1_star_rating': { auto_applied: false, reason: '상품페이지 내 항목 부재' },
            '2_star_rating': { auto_applied: true, reason: '상품페이지 내 항목 부재' },
            '3_star_rating': { auto_applied: false, reason: '상품페이지 내 항목 부재' },
            '4_star_rating': { auto_applied: true, reason: '상품페이지 내 항목 부재' }
        }
    });
    assert.ok(rendered.includes('수동확인 1건'));
    assert.ok(rendered.includes('자동확인 1건'));
    assert.ok(rendered.includes('확인 필요 1건'));
    assert.ok(!rendered.includes('수동확인 2건'));
    assert.ok(!rendered.includes('자동확인 2건'));
}

function testHistoryRowsDoNotInflateReviewSummary() {
    let rendered = '';
    const sandbox = {
        console, renderCountryFlagLabel: value => value,
        getSelectedDate: () => '2026-09-13', getDetailBody: () => ({}),
        isInlineMode: () => true,
        buildDetailContainerHtml: options => options.itemQueryHtml,
        renderDetailWithTable() {},
        ViewStack: { stack: [], push(html) { rendered = html; this.stack.push({}); } }
    };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    vm.runInContext("modalState.tableParam='sea_ref_retail'; modalState.tableName='SEA REF'; modalState.retailer='Lowes'; modalState.days=3;", sandbox);
    sandbox.renderNullFieldDetailView('ref_capacity', {
        date: '2026-09-13', source_date: '2026-09-12', date_column: 'crawl_strdatetime',
        supports_null_auto_review: true, supports_day_history: true, history_days: 3,
        display_config: { ref_capacity: { select_columns: ['item', 'ref_capacity', 'crawl_strdatetime'] } },
        results: [
            { id: 1, item: 'A', ref_capacity: null, crawl_strdatetime: '2026-09-12', null_fields: ['ref_capacity'] },
            { id: 2, item: 'A', ref_capacity: null, crawl_strdatetime: '2026-09-11', null_fields: ['ref_capacity'] },
            { id: 3, item: 'B', ref_capacity: null, crawl_strdatetime: '2026-09-12', null_fields: ['ref_capacity'] }
        ],
        normal_reviews: { '1_ref_capacity': { auto_applied: true, reason: '상품페이지 내 항목 부재' } }
    });
    assert.ok(rendered.includes('자동확인 1건'));
    assert.ok(rendered.includes('확인 필요 1건'));
    assert.ok(!rendered.includes('확인 필요 2건'));
    assert.strictEqual(sandbox.ViewStack.stack[0].nullReviewSummary, true);
}

async function testManualSaveDisplaysServerMetadataAndRefreshes() {
    const sandbox = commonSandbox();
    renderRows(sandbox);
    sandbox._hideNullReviewBar = () => {};
    sandbox._clearNullReviewSelection = () => {};
    let refreshed = 0;
    const metadata = { reason: '수집 대상 제품 아님', auto_applied: false,
        memo: '검수 메모', auto_eligible: false, auto_exclusion_reason: '제품명 정보 부족',
        original_crawl_date: '2026-09-13', created_id: 'reviewer', correction_id: 20 };
    sandbox.fetch = async () => ({ json: async () => ({ success: true, normal_review: metadata }) });
    sandbox.refreshNullReviewDetail = async () => { refreshed++; };
    const cell = { dataset: { rowId: '3', col: 'ref_capacity' },
        removeAttribute() {}, querySelector: () => ({}) };
    await sandbox._submitNullReviews([cell], 'normal', metadata.memo, metadata.reason);
    assert.strictEqual(cell.className, 'cell-normal null-review-value manual');
    assert.strictEqual(sandbox.detailViewState.normalReviews['3_ref_capacity'], metadata);
    assert.strictEqual(sandbox.detailViewState.allData[2]._null_review_status, '수동확인');
    const saved = sandbox.detailViewState.allData[2];
    assert.ok(sandbox.getCellHtml(saved, { key: '_null_review_reason' }, 'sea_ref_retail').includes('메모: 검수 메모'));
    assert.ok(sandbox.getCellHtml(saved, { key: '_null_review_basis' }, 'sea_ref_retail').includes('자동확인 제외 · 제품명 정보 부족'));
    assert.strictEqual(refreshed, 1);
}

function testAcceptedOnlyResultsRemainReachable() {
    const body = { innerHTML: '' };
    const sandbox = {
        console, URLSearchParams, renderCountryFlagLabel: value => value,
        renderNullFieldsDetail: fields => Object.keys(fields || {}).join(','),
        getDetailBody: () => body, getSelectedDate: () => '2026-09-13',
        isInlineMode: () => true, ViewStack: { push() {} },
        showToast() { throw new Error('accepted rows must remain queryable'); }
    };
    vm.createContext(sandbox);
    vm.runInContext(dashboardSource, sandbox);
    vm.runInContext(nullSource, sandbox);
    for (const table of ['tv_retail', 'sem_ref_retail', 'siel_ref_retail', 'tse_ref_retail', 'seg_ref_retail']) {
        const html = sandbox.renderDXTableDetail({ type: 'null' }, {
            table, table_name: table, supports_null_auto_review: true,
            retailers: [{ retailer: 'Retailer', total: 3, total_null_count: 0,
                raw_null_count: 3, reviewed_null_count: 3, auto_reviewed_count: 2, manual_reviewed_count: 1,
                fields_detail: { ref_capacity: 0 }, raw_fields_detail: { ref_capacity: 3 },
                reviewed_fields_detail: { ref_capacity: 3 }, status: 'OK' }]
        });
        assert.ok(html.includes("'Retailer', 3, 1"));
        assert.ok(html.includes('class="null-review-status manual">수동확인 1건'));
        assert.ok(html.includes('class="null-review-status automatic">자동확인 2건'));
        const payload = JSON.parse(html.match(/data-fields='([^']+)'/)[1].replace(/&#39;/g, "'").replace(/&amp;/g, '&'));
        sandbox.openDetailModal('null', table, 'Retailer', 3, 1, payload, table);
        assert.ok(body.innerHTML.includes("showNullFieldDetail('ref_capacity')"));
        assert.ok(body.innerHTML.includes('확인 완료 3건 · 전체 조회 3건'));
        assert.ok(!body.innerHTML.includes('NULL 오류 데이터가 없습니다'));
    }
}

async function testCancellationUsesManualCorrectionOnly() {
    const sandbox = commonSandbox();
    renderRows(sandbox);
    let requests = [], refreshed = 0;
    sandbox.showConfirm = async () => ({ confirmed: true, value: '잘못 확인함' });
    sandbox.fetch = async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        return { ok: true, json: async () => ({ success: true, cancelled: 1 }) };
    };
    sandbox.refreshNullReviewDetail = async () => { refreshed++; };
    const button = { dataset: { reviewKey: '1_ref_capacity' }, disabled: false };
    await sandbox.cancelNullReviewEvidence(button);
    assert.deepStrictEqual(requests, [{ url: '/dx/layer4/api/corrections/cancel/', body: { ids: [17], cancel_memo: '잘못 확인함' } }]);
    assert.strictEqual(refreshed, 1);
    assert.strictEqual(button.disabled, false);
    sandbox.showConfirm = async () => ({ confirmed: false });
    await sandbox.cancelNullReviewEvidence(button);
    assert.strictEqual(requests.length, 1);
    sandbox.detailViewState.normalReviews['1_ref_capacity'].correction_id = 'auto:17';
    await sandbox.cancelNullReviewEvidence(button);
    assert.strictEqual(requests.length, 1);
}

async function testRefreshRetainsSummaryAndSelectedField() {
    const sandbox = { console, URLSearchParams, getSelectedDate: () => '2026-09-13',
        isInlineMode: () => true, ViewStack: {}, showToast() {} };
    vm.createContext(sandbox);
    vm.runInContext(nullSource, sandbox);
    vm.runInContext("modalState.tableParam='sem_ref_retail'; modalState.retailer='Retailer A'; modalState.selectedField='ref_capacity'; modalState.nullFieldsData={date:'2026-09-13'};", sandbox);
    let requested, detailCall;
    sandbox.fetch = async url => {
        requested = url;
        return { ok: true, json: async () => ({ supports_null_auto_review: true,
            field_counts: { ref_capacity: 0 }, raw_fields_detail: { ref_capacity: 1 }, reviewed_fields_detail: { ref_capacity: 1 } }) };
    };
    sandbox.showNullFieldDetail = async (field, push) => { detailCall = [field, push]; };
    await sandbox.refreshNullReviewDetail();
    assert.ok(requested.includes('table=sem_ref_retail'));
    assert.ok(requested.includes('retailer=Retailer+A'));
    assert.deepStrictEqual(detailCall, ['ref_capacity', false]);
    assert.strictEqual(vm.runInContext('modalState.nullFieldsData.reviewed_fields_detail.ref_capacity', sandbox), 1);
    assert.strictEqual(sandbox.ViewStack.nullReviewStatsDirty, true);
}

function testTseLogPolicyMatchesSelectedDate() {
    const elements = {};
    const sandbox = { document: {
        addEventListener() {},
        getElementById(id) { return elements[id] || (elements[id] = {}); }
    } };
    vm.createContext(sandbox);
    vm.runInContext(reviewLogSource, sandbox);
    sandbox._renderNullReviewLogs({ date: '2026-09-12', logs: [], supports_null_auto_review: true });
    assert.strictEqual(elements['review-log-heading'].textContent, 'NULL 확인 이력');
    assert.ok(!elements['review-log-policy'].textContent.includes('14일'));
    sandbox._renderNullReviewLogs({ date: '2026-09-11', logs: [] });
    assert.ok(elements['review-log-policy'].textContent.includes('14일'));
}

(async () => {
    testVisibleReviewColumnsAndNoFormatChange();
    testManualOnlyReviewExplainsAutomaticExclusion();
    testReasonAndMemoFollowCurrentQueryMetadata();
    testDialogExplainsIdentityRequirementOnlyForNullAutoReview();
    testResolvedNullFieldDoesNotDisplayPriorAcceptance();
    testRelatedNullFieldDoesNotInflateSelectedFieldSummary();
    testAcceptedOnlyResultsRemainReachable();
    testHistoryRowsDoNotInflateReviewSummary();
    testTseLogPolicyMatchesSelectedDate();
    await testCancellationUsesManualCorrectionOnly();
    await testRefreshRetainsSummaryAndSelectedField();
    await testManualSaveDisplaysServerMetadataAndRefreshes();
    console.log('Layer2 NULL automatic review frontend tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
