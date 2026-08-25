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
        'unified_inspection.js'
    ),
    'utf8'
);

function country(country, sourceDate, offsetDays) {
    const prefix = country.toLowerCase();
    return {
        country,
        inspection_date: '2026-08-20',
        source_date: sourceDate,
        offset_days: offsetDays,
        rule: offsetDays === -1 ? 'D-1' : 'D',
        sources: ['TV', 'REF', 'LDY'].map(product => ({
            source_key: prefix + '_' + product.toLowerCase(),
            product
        }))
    };
}

function pageData() {
    return {
        success: true,
        inspection_date: '2026-08-20',
        source_count: 15,
        countries: [
            country('SEA', '2026-08-19', -1),
            country('SEDA', '2026-08-19', -1),
            country('SEG', '2026-08-20', 0),
            country('SIEL', '2026-08-20', 0),
            country('TSE', '2026-08-20', 0)
        ]
    };
}

async function main() {
    const requests = [];
    const historyCalls = [];
    const elements = {
        'ui-mapping-body': { innerHTML: '' },
        'ui-inspection-date': { textContent: '-' },
        'ui-country-count': { textContent: '5개국' },
        'ui-source-count': { textContent: '15개' }
    };
    let selectedDate = '2026-08-20';
    let nextResponse = {
        ok: true,
        json: () => Promise.resolve(pageData())
    };

    const sandbox = {
        console,
        encodeURIComponent,
        document: {
            getElementById: id => elements[id]
        },
        fetch: url => {
            requests.push(url);
            return Promise.resolve(nextResponse);
        },
        getSelectedDate: () => selectedDate,
        window: {
            L4: { _sectionHandler: {} },
            location: { pathname: '/dx/layer4/unified-inspection/' },
            history: {
                replaceState: (...args) => historyCalls.push(args)
            }
        }
    };

    vm.runInNewContext(source, sandbox);
    const loadMapping = sandbox.window.L4._sectionHandler.unified_inspection;
    assert.strictEqual(typeof loadMapping, 'function');

    await loadMapping();

    assert.strictEqual(
        requests[0],
        '/dx/layer4/api/unified-inspection/date-mapping/?date=2026-08-20'
    );
    const html = elements['ui-mapping-body'].innerHTML;
    for (const countryCode of ['SEA', 'SEDA', 'SEG', 'SIEL', 'TSE']) {
        assert.ok(html.includes(countryCode));
    }
    assert.ok(html.includes('2026-08-19'));
    assert.ok(html.includes('2026-08-20'));
    assert.ok(html.includes('D-1'));
    assert.ok(html.includes('sea_tv (TV)'));
    assert.ok(html.includes('tse_ldy (LDY)'));
    assert.strictEqual(elements['ui-inspection-date'].textContent, '2026-08-20');
    assert.strictEqual(elements['ui-country-count'].textContent, '5개국');
    assert.strictEqual(elements['ui-source-count'].textContent, '15개');
    assert.strictEqual(
        historyCalls[0][2],
        '/dx/layer4/unified-inspection/?date=2026-08-20'
    );

    selectedDate = '2026-02-30';
    nextResponse = {
        ok: false,
        json: () => Promise.resolve({
            success: false,
            error: '존재하지 않는 검수일입니다.'
        })
    };
    await loadMapping();

    const errorHtml = elements['ui-mapping-body'].innerHTML;
    assert.ok(errorHtml.includes('존재하지 않는 검수일입니다.'));
    assert.ok(!errorHtml.includes('sea_tv'));

    let finishSlowRequest;
    selectedDate = '2026-08-20';
    sandbox.fetch = url => {
        requests.push(url);
        return new Promise(resolve => {
            finishSlowRequest = resolve;
        });
    };
    const slowRequest = loadMapping();
    selectedDate = '';
    await loadMapping();
    finishSlowRequest({
        ok: true,
        json: () => Promise.resolve(pageData())
    });
    await slowRequest;

    const emptyDateHtml = elements['ui-mapping-body'].innerHTML;
    assert.ok(emptyDateHtml.includes('검수일을 선택해 주세요.'));
    assert.ok(!emptyDateHtml.includes('sea_tv'));
    assert.strictEqual(elements['ui-inspection-date'].textContent, '-');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
