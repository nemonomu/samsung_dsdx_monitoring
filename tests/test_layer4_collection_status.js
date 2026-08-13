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
        'dx_layer4',
        'static',
        'dx_layer4',
        'js',
        'collection_status.js'
    ),
    'utf8'
);

const layer1Data = {
    checks: [{
        check_type: 'retail',
        name: 'Retail',
        is_target_date: true,
        categories: [{
            name: 'TV',
            expected: 900,
            total: 879
        }]
    }, {
        check_type: 'youtube',
        name: 'Consumer (YouTube)',
        is_target_date: true,
        categories: [{
            name: 'HHP',
            expected_country_count: 10,
            completed_country_count: 10,
            expected: 240,
            log_count: 240,
            video_count: 841,
            comment_count: 40938
        }]
    }]
};

const emailReportData = {
    success: true,
    complete: true,
    date: '2026-07-29',
    sources: [{
        key: 'sea_tv',
        country: 'SEA',
        product: 'TV',
        label: 'SEA TV 수집 데이터',
        table_name: 'public.tv_retail_com',
        total_count: 879,
        column_order: ['item'],
        retailers: [{
            retailer: 'Amazon',
            total_count: 248,
            redirect_true_count: 2,
            columns: [{ column: 'item', total_count: 248, null_count: 0 }]
        }, {
            retailer: 'Bestbuy',
            total_count: 315,
            redirect_true_count: 0,
            columns: [{ column: 'item', total_count: 315, null_count: 0 }]
        }]
    }, {
        key: 'sea_ref',
        country: 'SEA',
        product: 'REF',
        label: 'SEA REF 수집 데이터',
        table_name: 'public.ref_retail_com',
        total_count: 690,
        column_order: ['sku', 'bsr_rank', 'offer', 'ref_capacity', 'item'],
        retailers: [{
            retailer: 'Bestbuy',
            total_count: 390,
            collected_count: 390,
            has_data: true,
            columns: [
                { column: 'sku', total_count: 390, null_count: 0 },
                {
                    column: 'bsr_rank',
                    total_count: 100,
                    null_count: 0,
                    remark: 'BSR page count'
                },
                { column: 'ref_capacity', total_count: 390, null_count: 3 },
                { column: 'item', total_count: 390, null_count: 0 }
            ]
        }, {
            retailer: 'Lowes',
            total_count: 300,
            collected_count: 300,
            has_data: true,
            columns: [
                { column: 'sku', total_count: 300, null_count: 1 },
                { column: 'offer', total_count: 300, null_count: 5 },
                { column: 'ref_capacity', total_count: 300, null_count: 2 },
                { column: 'item', total_count: 300, null_count: 0 }
            ]
        }]
    }, {
        key: 'seda_tv',
        country: 'SEDA',
        product: 'TV',
        label: 'SEDA TV 수집 데이터',
        table_name: 'dx_seda.dx_seda_tv_retail_com',
        total_count: 546,
        column_order: ['screen_size'],
        retailers: [{
            retailer: 'Magalu',
            columns: [{ column: 'screen_size', total_count: 238, null_count: 3 }]
        }]
    }, {
        key: 'seg_tv',
        country: 'SEG',
        product: 'TV',
        label: 'SEG TV 수집 데이터',
        table_name: 'dx_seg.dx_seg_tv_retail_com',
        total_count: 935,
        column_order: ['screen_size'],
        retailers: []
    }, {
        key: 'siel_tv',
        country: 'SIEL',
        product: 'TV',
        label: 'SIEL TV 수집 데이터',
        table_name: 'dx_siel.dx_siel_tv_retail_com',
        total_count: 602,
        column_order: ['screen_size'],
        retailers: []
    }, {
        key: 'tse_ldy',
        country: 'TSE',
        product: 'LDY',
        label: 'TSE LDY 수집 데이터',
        table_name: 'dx_tse.dx_tse_ldy_retail_com',
        total_count: 287,
        column_order: ['ldy_capacity'],
        retailers: [{
            retailer: 'Homepro',
            columns: [{ column: 'ldy_capacity', total_count: 287, null_count: 6 }]
        }]
    }],
    errors: []
};

function response(data) {
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(data)
    });
}

function loadPage(
    search,
    statsData = layer1Data,
    collectionData = { success: true, retailers: [] },
    integratedEmailData = emailReportData
) {
    const requests = [];
    const listeners = {};
    const selectedDate = { value: '2026-07-29' };
    const elements = {
        'cs-daily-container': { innerHTML: '' },
        'cs-container': { innerHTML: '' },
        'cs-email-container': { innerHTML: '' },
        'email-send-btn': {
            textContent: '',
            title: '',
            disabled: false,
            addEventListener: (type, handler) => {
                listeners['email-send-btn:' + type] = handler;
            }
        },
        'email-copy-btn': {
            addEventListener: (type, handler) => {
                listeners['email-copy-btn:' + type] = handler;
            }
        },
        'email-preview-content': {
            innerHTML: '<div>email body</div>',
            querySelector: selector => selector === '.email-subject'
                ? { textContent: 'monitoring subject' }
                : null
        }
    };
    const L4 = {
        _sectionInit: {},
        _sectionHandler: {},
        escapeHtml: value => String(value),
        formatNumber: value => String(value)
    };
    const context = {
        console: {
            log: () => {},
            warn: () => {},
            error: () => {}
        },
        Promise,
        URLSearchParams,
        setTimeout,
        clearTimeout,
        L4,
        getSelectedDate: () => selectedDate.value,
        showToast: () => {},
        showConfirm: () => Promise.resolve(true),
        fetch: (url, options) => {
            requests.push({ url, options });
            if (url.startsWith('/dx/layer1/api/stats/')) {
                return response(statsData);
            }
            if (url.includes('email-check')) {
                return response({ count: 0 });
            }
            if (url.includes('email-report-data')) {
                return response(integratedEmailData);
            }
            if (url.startsWith('/dx/layer4/api/collection-status/')) {
                if (collectionData.byCategory) {
                    const category = new URL('http://test' + url).searchParams.get('category');
                    return response(collectionData.byCategory[category] || { success: true, retailers: [] });
                }
                return response(collectionData);
            }
            return response({});
        },
        document: {
            cookie: '',
            getElementById: id => elements[id] || null,
            addEventListener: (type, handler) => {
                if (type === 'DOMContentLoaded') handler();
            },
            querySelectorAll: () => [],
            querySelector: () => null
        },
        window: {
            location: { search },
            getSelection: () => ({
                removeAllRanges: () => {},
                addRange: () => {}
            })
        }
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    return { L4, elements, requests, listeners, selectedDate };
}

async function flushPromises() {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
}

async function run() {
    const email = loadPage('?focus=' + encodeURIComponent('이메일 보고'));
    email.L4._sectionHandler.collection_status();
    await flushPromises();

    const emailHtml = email.elements['cs-email-container'].innerHTML;
    assert(!emailHtml.includes('YouTube 국가 실행 (HHP)'));
    assert(!emailHtml.includes('YouTube 완료 키워드 작업 (HHP)'));
    assert(emailHtml.includes('YouTube 영상 데이터 (HHP)'));
    assert(!emailHtml.includes('YouTube 댓글 데이터 (HHP)'));
    assert(!emailHtml.includes('youtube_country_collection_runs'));
    assert(emailHtml.includes('RAW_EXT_YOUTUBE_VIDEOS_VIEW'));
    assert(!emailHtml.includes('>youtube_videos</td>'));
    assert(!emailHtml.includes('youtube_comments'));
    assert(emailHtml.includes('>841</td>'));
    assert(!emailHtml.includes('예상건수'));
    assert(!emailHtml.includes('예상 건수'));
    assert(!emailHtml.includes('필터링 기준'));
    assert(emailHtml.includes('<tr><th colspan="4">합 계</th><th>4780</th></tr>'));
    assert(!emailHtml.includes('거래선 TV 제품 정보 / 감성점수'));
    const emailDailyTable = emailHtml.match(
        /<table class="e"[^>]*>[\s\S]*?<\/table>/
    )[0];
    assert.strictEqual(
        (emailDailyTable.match(/RAW_EXT_TV_RETAIL_COM_VIEW/g) || []).length,
        1
    );
    assert.strictEqual(
        (emailDailyTable.match(/RAW_EXT_REF_RETAIL_COM_VIEW/g) || []).length,
        1
    );
    assert.strictEqual(
        (emailDailyTable.match(/RAW_EXT_LDY_RETAIL_COM_VIEW/g) || []).length,
        1
    );
    assert(emailDailyTable.includes(
        '<td rowspan="4" align="center" valign="middle">RAW_EXT_TV_RETAIL_COM_VIEW</td>'
    ));
    assert(emailDailyTable.includes(
        '<td rowspan="1" align="center" valign="middle">RAW_EXT_REF_RETAIL_COM_VIEW</td>'
    ));
    assert(emailDailyTable.includes(
        '<td rowspan="1" align="center" valign="middle">RAW_EXT_LDY_RETAIL_COM_VIEW</td>'
    ));
    assert(emailDailyTable.indexOf('SEA TV 수집 데이터')
        < emailDailyTable.indexOf('SEG TV 수집 데이터'));
    assert(emailDailyTable.indexOf('SEG TV 수집 데이터')
        < emailDailyTable.indexOf('SIEL TV 수집 데이터'));
    assert(emailDailyTable.indexOf('SIEL TV 수집 데이터')
        < emailDailyTable.indexOf('SEDA TV 수집 데이터'));
    assert(emailDailyTable.indexOf('SEDA TV 수집 데이터')
        < emailDailyTable.indexOf('SEA REF 수집 데이터'));
    assert(emailDailyTable.indexOf('SEA REF 수집 데이터')
        < emailDailyTable.indexOf('TSE LDY 수집 데이터'));
    assert(emailDailyTable.indexOf('TSE LDY 수집 데이터')
        < emailDailyTable.indexOf('YouTube 영상 데이터 (HHP)'));
    assert.deepStrictEqual(
        Array.from(
            emailDailyTable.matchAll(/<tr><td align="center">(\d+)<\/td>/g),
            match => Number(match[1])
        ),
        [1, 2, 3, 4, 5, 6, 7]
    );
    assert(!emailDailyTable.includes('국가 공통'));
    assert(!emailDailyTable.includes('한 번만 표시'));
    assert(!emailDailyTable.includes('public.tv_retail_com'));
    assert(!emailDailyTable.includes('dx_tse.dx_tse_ldy_retail_com'));
    assert(emailHtml.includes('SEA TV 수집 데이터'));
    assert(emailHtml.includes('SEA REF 수집 데이터'));
    assert(emailHtml.includes('SEDA TV 수집 데이터'));
    assert(emailHtml.includes('SEG TV 수집 데이터'));
    assert(emailHtml.includes('SIEL TV 수집 데이터'));
    assert(emailHtml.includes('TSE LDY 수집 데이터'));
    assert(!emailHtml.includes('>bsr_rank</td>'));
    assert(!emailHtml.includes('BSR page count'));
    assert(emailHtml.includes('cellpadding="6"'));
    assert(!emailHtml.includes('cellpadding="5"'));
    assert(emailHtml.includes(
        '.e td,.e th{border:1px solid #ccc;padding:6px;text-align:center}'
    ));
    assert(emailHtml.includes('SEA - REF'));
    assert(emailHtml.includes('SEDA - TV'));
    assert(emailHtml.includes('TSE - LDY'));
    assert(emailHtml.includes('redirect'));
    assert(emailHtml.includes('Amazon redirect=TRUE 건수'));
    assert(emailHtml.includes('>2</td>'));
    assert(emailHtml.indexOf('>sku</td>') < emailHtml.indexOf('>offer</td>'));
    const seaRefTable = emailHtml.match(
        /<div class="et">SEA - REF<\/div>(<table[\s\S]*?<\/table>)/
    )[1];
    assert(seaRefTable.indexOf('>item</td>') < seaRefTable.indexOf('>sku</td>'));
    assert(seaRefTable.indexOf('>sku</td>') < seaRefTable.indexOf('>offer</td>'));
    assert(seaRefTable.indexOf('>offer</td>') < seaRefTable.indexOf('>ref_capacity</td>'));
    const itemRow = seaRefTable.match(/<tr><td[^>]*>item<\/td>([\s\S]*?)<\/tr>/);
    assert(itemRow);
    assert(itemRow[1].includes('>390</td><td align="center">0</td>'));
    assert(itemRow[1].includes('>300</td><td align="center">0</td>'));
    assert.strictEqual(
        (emailHtml.match(/<th class="ec" width="250" rowspan="2">수집항목<\/th>/g) || []).length,
        4
    );
    assert.strictEqual(
        (emailHtml.match(/<th rowspan="2">비고<\/th>/g) || []).length,
        4
    );
    const offerRow = emailHtml.match(/<tr><td[^>]*>offer<\/td>([\s\S]*?)<\/tr>/);
    assert(offerRow);
    assert.strictEqual((offerRow[1].match(/>-<\/td>/g) || []).length, 2);
    assert.strictEqual(email.elements['email-send-btn'].disabled, false);
    assert(email.requests.some(request => request.url ===
        '/dx/layer4/api/collection-status/email-report-data/?date=2026-07-29'
    ));
    assert(!email.requests.some(request => request.url.includes('category=tv')));

    const redirectData = {
        success: true,
        retailers: [{
            retailer: 'Amazon',
            total_count: 248,
            redirect_true_count: 2,
            columns: [{ column: 'item', total_count: 248, null_count: 0 }]
        }, {
            retailer: 'Bestbuy',
            total_count: 315,
            redirect_true_count: 0,
            columns: [{ column: 'item', total_count: 315, null_count: 0 }]
        }]
    };
    const nullPage = loadPage(
        '?focus=' + encodeURIComponent('항목별 NULL 현황'),
        layer1Data,
        redirectData
    );
    nullPage.L4._sectionHandler.collection_status();
    await flushPromises();
    const nullHtml = nullPage.elements['cs-container'].innerHTML;
    assert(!nullHtml.includes('redirect'));

    const daily = loadPage('?focus=' + encodeURIComponent('일일 수집 현황'));
    daily.L4._sectionHandler.collection_status();
    await flushPromises();

    const dailyHtml = daily.elements['cs-daily-container'].innerHTML;
    assert(dailyHtml.includes('YouTube 영상 데이터 (HHP)'));
    assert(!dailyHtml.includes('YouTube 국가 실행 (HHP)'));
    assert(dailyHtml.includes('예상건수'));

    const tseLayer1Data = {
        checks: [{
            check_type: 'tse_retail',
            name: 'TSE Retail',
            is_target_date: true,
            categories: [{
                name: 'TV',
                product_line: 'tse_tv',
                table_name: 'dx_tse.dx_tse_tv_retail_com',
                retailers: [{ retailer: 'Homepro', expected: 300, actual: 300 }]
            }, {
                name: 'REF',
                product_line: 'tse_ref',
                table_name: 'dx_tse.dx_tse_ref_retail_com',
                retailers: [{ retailer: 'Homepro', expected: 300, actual: 300 }]
            }, {
                name: 'LDY',
                product_line: 'tse_ldy',
                table_name: 'dx_tse.dx_tse_ldy_retail_com',
                retailers: [{ retailer: 'Homepro', expected: 300, actual: 287 }]
            }]
        }]
    };
    const tseCollections = {
        byCategory: {
            tv: { success: true, retailers: [] },
            tse_tv: {
                success: true,
                retailers: [{
                    retailer: 'Homepro',
                    total_count: 300,
                    columns: [{ column: 'screen_size', total_count: 300, null_count: 0 }]
                }]
            },
            tse_ref: {
                success: true,
                retailers: [{
                    retailer: 'Homepro',
                    total_count: 300,
                    columns: [{ column: 'ref_capacity', total_count: 300, null_count: 0 }]
                }]
            },
            tse_ldy: {
                success: true,
                retailers: [{
                    retailer: 'Homepro',
                    total_count: 287,
                    columns: [{ column: 'ldy_capacity', total_count: 287, null_count: 6 }]
                }]
            }
        }
    };
    const tseDaily = loadPage(
        '?focus=' + encodeURIComponent('일일 수집 현황'),
        tseLayer1Data,
        tseCollections
    );
    tseDaily.L4._sectionHandler.collection_status();
    await flushPromises();
    const tseDailyHtml = tseDaily.elements['cs-daily-container'].innerHTML;
    assert(tseDailyHtml.includes('TSE TV 수집 데이터'));
    assert(tseDailyHtml.includes('dx_tse.dx_tse_tv_retail_com'));

    const tseEmail = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        tseLayer1Data,
        tseCollections,
        emailReportData
    );
    tseEmail.L4._sectionHandler.collection_status();
    await flushPromises();
    const tseEmailHtml = tseEmail.elements['cs-email-container'].innerHTML;
    assert(!tseEmailHtml.includes('TSE TV 수집 데이터'));
    assert(tseEmailHtml.includes('TSE LDY 수집 데이터'));
    assert(tseEmailHtml.includes('RAW_EXT_LDY_RETAIL_COM_VIEW'));
    assert(tseEmailHtml.includes('TSE - LDY'));
    assert(tseEmailHtml.includes('ldy_capacity'));
    assert(!tseEmailHtml.includes('TSE Cross-field 검증 현황'));
    assert(!tseEmailHtml.includes('할인율 불일치'));
    assert(!tseEmail.requests.some(request =>
        request.url.startsWith('/dx/layer3/api/tse-crossfield-summary/')
    ));
    assert(!tseEmail.requests.some(request => request.url.includes('category=tse_tv')));
    assert(!tseEmail.requests.some(request => request.url.includes('category=tse_ref')));
    assert(!tseEmail.requests.some(request => request.url.includes('category=tse_ldy')));

    assert(source.includes("fetch('/dx/layer4/api/collection-status/send-email/'"));
    assert(source.includes('date: renderedDate'));

    email.listeners['email-send-btn:click']();
    await flushPromises();
    await flushPromises();
    const sendRequest = email.requests.find(request =>
        request.url === '/dx/layer4/api/collection-status/send-email/'
    );
    assert(sendRequest);
    assert.strictEqual(sendRequest.options.method, 'POST');
    const sendPayload = JSON.parse(sendRequest.options.body);
    assert.strictEqual(sendPayload.subject, 'monitoring subject');
    assert.strictEqual(sendPayload.html, '<div>email body</div>');
    assert.strictEqual(sendPayload.date, '2026-07-29');

    const staleDate = loadPage('?focus=' + encodeURIComponent('이메일 보고'));
    staleDate.L4._sectionHandler.collection_status();
    await flushPromises();
    staleDate.selectedDate.value = '2026-07-30';
    staleDate.listeners['email-send-btn:click']();
    await flushPromises();
    assert(!staleDate.requests.some(request =>
        request.url === '/dx/layer4/api/collection-status/send-email/'
    ));
    assert.strictEqual(staleDate.elements['email-send-btn'].disabled, true);

    const tseNull = loadPage(
        '?focus=' + encodeURIComponent('항목별 NULL 현황') + '&category=tse_ldy',
        tseLayer1Data,
        tseCollections
    );
    tseNull.L4._sectionHandler.collection_status();
    await flushPromises();
    assert(tseNull.elements['cs-container'].innerHTML.includes('ldy_capacity'));

    const marketData = {
        checks: [
            {
                check_type: 'market_trend',
                name: 'Market Trend',
                expected: 1,
                actual: 1
            },
            {
                check_type: 'market_demand',
                name: 'Market Demand',
                expected: 1,
                actual: 1
            },
            {
                check_type: 'market_promotion',
                name: 'Market Promotion',
                expected: 1,
                actual: 1
            },
            {
                check_type: 'market_competitor',
                name: 'Market Competitor',
                expected: 1,
                actual: 1
            },
            {
                check_type: 'market_competitor_event',
                name: 'Market Competitor Event',
                expected: 1,
                actual: 1
            }
        ]
    };
    const marketDaily = loadPage(
        '?focus=' + encodeURIComponent('?쇱씪 ?섏쭛 ?꾪솴'),
        marketData
    );
    marketDaily.L4._sectionHandler.collection_status();
    await flushPromises();
    const marketDailyHtml =
        marketDaily.elements['cs-daily-container'].innerHTML;
    assert(!marketDailyHtml.includes('RAW_EXT_MARKET_TREND_VIEW'));
    assert(!marketDailyHtml.includes('RAW_EXT_OPENAI_FORECAST_RESULTS_VIEW'));
    assert(!marketDailyHtml.includes('RAW_EXT_MARKET_COMP_EVENT_VIEW'));
    assert(!marketDailyHtml.includes(
        'RAW_EXT_OPENAI_RETAILER_PROMOTIONS_VIEW'
    ));
    assert(!marketDailyHtml.includes('Market Competitor'));

    const failed = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        { error: 'redacted' }
    );
    failed.L4._sectionHandler.collection_status();
    await flushPromises();
    const failedHtml = failed.elements['cs-email-container'].innerHTML;
    assert(failedHtml.includes('이메일 보고 데이터가 불완전하여 발송할 수 없습니다.'));
    assert(!failedHtml.includes('합 계'));
    assert.strictEqual(failed.elements['email-send-btn'].disabled, true);

    const incompleteData = {
        success: true,
        complete: false,
        date: '2026-07-29',
        sources: emailReportData.sources.slice(0, 1),
        errors: [{ key: 'seg_tv', message: 'SEG TV 조회 실패' }]
    };
    const incomplete = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        layer1Data,
        { success: true, retailers: [] },
        incompleteData
    );
    incomplete.L4._sectionHandler.collection_status();
    await flushPromises();
    const incompleteHtml = incomplete.elements['cs-email-container'].innerHTML;
    assert(incompleteHtml.includes('이메일 보고 데이터가 불완전하여 발송할 수 없습니다.'));
    assert(incompleteHtml.includes('SEG TV 조회 실패'));
    assert(incompleteHtml.includes('SEA TV 수집 데이터'));
    assert.strictEqual(incomplete.elements['email-send-btn'].disabled, true);
    incomplete.listeners['email-send-btn:click']();
    await flushPromises();
    assert(!incomplete.requests.some(request =>
        request.url === '/dx/layer4/api/collection-status/send-email/'
    ));

    const requiredApiFailed = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        layer1Data,
        { success: true, retailers: [] },
        { error: 'email report API unavailable' }
    );
    requiredApiFailed.L4._sectionHandler.collection_status();
    await flushPromises();
    assert(requiredApiFailed.elements['cs-email-container'].innerHTML.includes(
        '이메일 보고 데이터가 불완전하여 발송할 수 없습니다.'
    ));
    assert.strictEqual(requiredApiFailed.elements['email-send-btn'].disabled, true);
}

run().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
