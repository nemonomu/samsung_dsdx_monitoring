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

function response(data) {
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(data)
    });
}

function loadPage(
    search,
    statsData = layer1Data,
    collectionData = { success: true, retailers: [] }
) {
    const requests = [];
    const listeners = {};
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
        getSelectedDate: () => '2026-07-29',
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
    return { L4, elements, requests, listeners };
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
    assert(emailHtml.includes('거래선 TV 제품 정보 / 감성점수'));
    assert(emailHtml.includes('RAW_EXT_TV_RETAIL_COM_VIEW'));
    assert(emailHtml.includes('>879</td>'));

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
    const redirectEmail = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        layer1Data,
        redirectData
    );
    redirectEmail.L4._sectionHandler.collection_status();
    await flushPromises();
    const redirectEmailHtml = redirectEmail.elements['cs-email-container'].innerHTML;
    assert(redirectEmailHtml.includes('redirect'));
    assert(redirectEmailHtml.includes('Amazon redirect=TRUE'));
    assert(redirectEmailHtml.includes('>2</td>'));

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
    const tseEmail = loadPage(
        '?focus=' + encodeURIComponent('이메일 보고'),
        tseLayer1Data,
        tseCollections
    );
    tseEmail.L4._sectionHandler.collection_status();
    await flushPromises();
    const tseEmailHtml = tseEmail.elements['cs-email-container'].innerHTML;
    assert(tseEmailHtml.includes('TSE TV 수집 데이터'));
    assert(tseEmailHtml.includes('dx_tse.dx_tse_tv_retail_com'));
    assert(tseEmailHtml.includes('TSE - TV'));
    assert(tseEmailHtml.includes('TSE - REF'));
    assert(tseEmailHtml.includes('TSE - LDY'));
    assert(tseEmailHtml.includes('ldy_capacity'));
    assert(!tseEmailHtml.includes('TSE Cross-field 검증 현황'));
    assert(!tseEmailHtml.includes('할인율 불일치'));
    assert(tseEmailHtml.includes('>6</td>'));
    assert(!tseEmail.requests.some(request =>
        request.url.startsWith('/dx/layer3/api/tse-crossfield-summary/')
    ));
    assert(tseEmail.requests.some(request => request.url.includes('category=tse_tv')));
    assert(tseEmail.requests.some(request => request.url.includes('category=tse_ref')));
    assert(tseEmail.requests.some(request => request.url.includes('category=tse_ldy')));

    assert(source.includes("fetch('/dx/layer4/api/collection-status/send-email/'"));
    assert(source.includes('date: getSelectedDate()'));

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
    assert(failedHtml.includes('오류가 발생했습니다.'));
    assert(!failedHtml.includes('합 계'));
}

run().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
