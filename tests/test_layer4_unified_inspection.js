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

function country(countryCode, inspectionDate, sourceDate, offsetDays) {
    const prefix = countryCode.toLowerCase();
    return {
        country: countryCode,
        inspection_date: inspectionDate,
        source_date: sourceDate,
        offset_days: offsetDays,
        rule: offsetDays === -1 ? 'D-1' : 'D',
        sources: ['TV', 'REF', 'LDY'].map(product => ({
            source_key: prefix + '_' + product.toLowerCase(),
            product
        }))
    };
}

function pageData(inspectionDate = '2026-08-20', tseSourceDate = inspectionDate) {
    return {
        success: true,
        inspection_date: inspectionDate,
        source_count: 15,
        countries: [
            country('SEA', inspectionDate, '2026-08-19', -1),
            country('SEDA', inspectionDate, '2026-08-19', -1),
            country('SEG', inspectionDate, inspectionDate, 0),
            country('SIEL', inspectionDate, inspectionDate, 0),
            country('TSE', inspectionDate, tseSourceDate, 0)
        ]
    };
}

function layer1Data(targetDate = '2026-08-20', status = 'OK', counts = [644, 607, 584]) {
    const products = [
        ['TV', 'tse_tv'],
        ['REF', 'tse_ref'],
        ['LDY', 'tse_ldy']
    ];
    return {
        target_date: targetDate,
        checks: [{
            check_type: 'tse_retail',
            status,
            phase: status === 'COLLECTING' ? 'collecting' : 'complete',
            collection_window: 'KST 09:00~11:00',
            actual: counts.reduce((sum, value) => sum + value, 0),
            expected: 1800,
            categories: products.map((product, index) => ({
                category: product[0],
                product_line: product[1],
                actual: counts[index],
                expected: 600,
                status
            }))
        }]
    };
}

function jsonResponse(data, ok = true) {
    return {
        ok,
        json: () => Promise.resolve(data)
    };
}

async function main() {
    const requests = [];
    const historyCalls = [];
    const elements = {
        'ui-mapping-body': { innerHTML: '' },
        'ui-inspection-date': { textContent: '-' },
        'ui-country-count': { textContent: '5개국' },
        'ui-source-count': { textContent: '15개' },
        'ui-tse-body': { innerHTML: '' },
        'ui-tse-contract': { textContent: '' },
        'ui-tse-inspection-date': { textContent: '-' },
        'ui-tse-source-date': { textContent: '-' },
        'ui-tse-status': { textContent: '-' }
    };
    let selectedDate = '2026-08-20';
    let mappingResponse = jsonResponse(pageData());
    let tseResponse = jsonResponse(layer1Data());

    const sandbox = {
        console,
        encodeURIComponent,
        document: {
            getElementById: id => elements[id]
        },
        fetch: url => {
            requests.push(url);
            return Promise.resolve(
                url.includes('/dx/layer1/api/stats/')
                    ? tseResponse
                    : mappingResponse
            );
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

    assert.deepStrictEqual(requests.slice(0, 2), [
        '/dx/layer4/api/unified-inspection/date-mapping/?date=2026-08-20',
        '/dx/layer1/api/stats/?date=2026-08-20&check_type=tse_retail'
    ]);
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

    const tseHtml = elements['ui-tse-body'].innerHTML;
    for (const sourceKey of ['tse_tv', 'tse_ref', 'tse_ldy']) {
        assert.ok(tseHtml.includes(sourceKey));
    }
    for (const count of [644, 607, 584]) {
        assert.ok(tseHtml.includes(String(count)));
    }
    assert.ok(tseHtml.includes('정상'));
    assert.strictEqual(
        elements['ui-tse-contract'].textContent,
        'TSE · D'
    );
    assert.strictEqual(
        elements['ui-tse-inspection-date'].textContent,
        '2026-08-20'
    );
    assert.strictEqual(elements['ui-tse-source-date'].textContent, '2026-08-20');
    assert.strictEqual(
        elements['ui-tse-status'].textContent,
        '정상 · KST 09:00~11:00'
    );

    const beforeZero = requests.length;
    selectedDate = '2026-08-21';
    mappingResponse = {
        ok: true,
        json: () => {
            selectedDate = '2026-08-22';
            return Promise.resolve(pageData('2026-08-21'));
        }
    };
    tseResponse = jsonResponse(layer1Data('2026-08-21', 'CRITICAL', [0, 0, 0]));
    await loadMapping();

    assert.deepStrictEqual(requests.slice(beforeZero), [
        '/dx/layer4/api/unified-inspection/date-mapping/?date=2026-08-21',
        '/dx/layer1/api/stats/?date=2026-08-21&check_type=tse_retail'
    ]);
    assert.ok(elements['ui-tse-body'].innerHTML.includes('>0<span'));
    assert.ok(elements['ui-tse-body'].innerHTML.includes('심각'));
    assert.strictEqual(elements['ui-tse-source-date'].textContent, '2026-08-21');

    const tseCallsBeforeInvalid = requests.filter(
        url => url.includes('/dx/layer1/api/stats/')
    ).length;
    selectedDate = '2026-02-30';
    mappingResponse = jsonResponse({
        success: false,
        error: '존재하지 않는 검수일입니다.'
    }, false);
    await loadMapping();

    const errorHtml = elements['ui-mapping-body'].innerHTML;
    assert.ok(errorHtml.includes('존재하지 않는 검수일입니다.'));
    assert.ok(!errorHtml.includes('sea_tv'));
    assert.strictEqual(
        requests.filter(url => url.includes('/dx/layer1/api/stats/')).length,
        tseCallsBeforeInvalid
    );

    selectedDate = '2026-08-22';
    const malformedMapping = pageData('2026-08-22');
    malformedMapping.countries[4].source_date = '';
    mappingResponse = jsonResponse(malformedMapping);
    const tseCallsBeforeMalformed = requests.filter(
        url => url.includes('/dx/layer1/api/stats/')
    ).length;
    await loadMapping();
    assert.ok(
        elements['ui-tse-body'].innerHTML.includes(
            'TSE 날짜 매핑이 D 규칙과 일치하지 않습니다.'
        )
    );
    assert.strictEqual(
        requests.filter(url => url.includes('/dx/layer1/api/stats/')).length,
        tseCallsBeforeMalformed
    );

    selectedDate = '2026-08-23';
    mappingResponse = jsonResponse(pageData('2026-08-23'));
    tseResponse = jsonResponse(layer1Data('2026-08-22'));
    await loadMapping();
    assert.ok(elements['ui-mapping-body'].innerHTML.includes('TSE'));
    assert.ok(
        elements['ui-tse-body'].innerHTML.includes(
            'TSE 실제 조회일이 매핑된 데이터일과 일치하지 않습니다.'
        )
    );

    let finishSlowTse;
    let markSlowTseStarted;
    const slowTseStarted = new Promise(resolve => {
        markSlowTseStarted = resolve;
    });
    sandbox.fetch = url => {
        requests.push(url);
        if (url.includes('/date-mapping/')) {
            const requestDate = decodeURIComponent(url.split('date=')[1]);
            return Promise.resolve(jsonResponse(pageData(requestDate)));
        }
        if (url.includes('date=2026-08-24')) {
            markSlowTseStarted();
            return new Promise(resolve => {
                finishSlowTse = resolve;
            });
        }
        return Promise.resolve(jsonResponse(layer1Data('2026-08-25')));
    };
    selectedDate = '2026-08-24';
    const staleTseRequest = loadMapping();
    await slowTseStarted;
    selectedDate = '2026-08-25';
    await loadMapping();
    finishSlowTse(jsonResponse(
        layer1Data('2026-08-24', 'CRITICAL', [0, 0, 0])
    ));
    await staleTseRequest;
    assert.strictEqual(elements['ui-tse-source-date'].textContent, '2026-08-25');
    assert.strictEqual(
        elements['ui-tse-status'].textContent,
        '정상 · KST 09:00~11:00'
    );
    assert.ok(!elements['ui-tse-body'].innerHTML.includes('심각'));

    let finishSlowRequest;
    const callsBeforeSlowRequest = requests.length;
    selectedDate = '2026-08-26';
    sandbox.fetch = url => {
        requests.push(url);
        return new Promise(resolve => {
            finishSlowRequest = resolve;
        });
    };
    const slowRequest = loadMapping();
    selectedDate = '';
    await loadMapping();
    finishSlowRequest(jsonResponse(pageData('2026-08-26')));
    await slowRequest;

    const emptyDateHtml = elements['ui-mapping-body'].innerHTML;
    assert.ok(emptyDateHtml.includes('검수일을 선택해 주세요.'));
    assert.ok(!emptyDateHtml.includes('sea_tv'));
    assert.ok(elements['ui-tse-body'].innerHTML.includes('검수일을 선택해 주세요.'));
    assert.strictEqual(elements['ui-inspection-date'].textContent, '-');
    assert.strictEqual(requests.length, callsBeforeSlowRequest + 1);
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
