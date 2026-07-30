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

function loadPage(search, statsData = layer1Data) {
    const elements = {
        'cs-daily-container': { innerHTML: '' },
        'cs-email-container': { innerHTML: '' },
        'email-send-btn': {
            textContent: '',
            title: '',
            disabled: false,
            addEventListener: () => {}
        },
        'email-copy-btn': { addEventListener: () => {} }
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
        showConfirm: () => Promise.resolve(false),
        fetch: url => {
            if (url.startsWith('/dx/layer1/api/stats/')) {
                return response(statsData);
            }
            if (url.includes('email-check')) {
                return response({ count: 0 });
            }
            if (url.startsWith('/dx/layer4/api/collection-status/')) {
                return response({ success: true, retailers: [] });
            }
            return response({});
        },
        document: {
            cookie: '',
            getElementById: id => elements[id] || null,
            addEventListener: () => {},
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
    return { L4, elements };
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
    assert(emailHtml.includes('YouTube 국가 실행 (HHP)'));
    assert(emailHtml.includes('YouTube 완료 키워드 작업 (HHP)'));
    assert(emailHtml.includes('YouTube 영상 데이터 (HHP)'));
    assert(emailHtml.includes('YouTube 댓글 데이터 (HHP)'));
    assert(emailHtml.includes('youtube_country_collection_runs'));
    assert(emailHtml.includes('youtube_videos'));
    assert(emailHtml.includes('youtube_comments'));
    for (const value of ['10', '240', '841', '40938']) {
        assert(emailHtml.includes('>' + value + '</td>'));
    }

    const daily = loadPage('?focus=' + encodeURIComponent('일일 수집 현황'));
    daily.L4._sectionHandler.collection_status();
    await flushPromises();

    const dailyHtml = daily.elements['cs-daily-container'].innerHTML;
    assert(dailyHtml.includes('YouTube 영상 데이터 (HHP)'));
    assert(!dailyHtml.includes('YouTube 국가 실행 (HHP)'));

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
