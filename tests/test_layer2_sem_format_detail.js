const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const body = {innerHTML: ''};
const subtitle = {textContent: '', innerHTML: ''};
const inputs = {};
const requests = [];
let response;
const context = {
    console: {error() {}},
    document: {getElementById: id => inputs[id] || null},
    getSelectedDate: () => '2026-09-13',
    isInlineMode: () => true,
    renderCountryFlagLabel: value => String(value),
    getDetailBody: () => body,
    getDetailSubtitle: () => subtitle,
    ViewStack: {push() {}},
    fetch: async url => { requests.push(url); return response; },
};
context.window = context;
vm.createContext(context);
for (const name of ['null_validation', 'format_validation']) {
    vm.runInContext(fs.readFileSync(
        'apps/dx/dx_layer2/static/dx_layer2/js/' + name + '.js', 'utf8'
    ), context);
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
    for (const product of ['TV', 'REF', 'LDY']) {
        response = {ok: true, json: async () => ({
            date: '2026-09-13', field_counts: {final_sku_price: 3},
            results: [{id: 1, error_fields: ['final_sku_price']}],
        })};
        context.openDetailModal('format', 'SEM ' + product, 'Liverpool', 3);
        await settle();
        assert(requests.at(-1).includes('table=sem_' + product.toLowerCase() + '_retail'));
        assert(body.innerHTML.includes("showFormatFieldDetail('final_sku_price')"));
        assert(body.innerHTML.includes('3건'));
        assert(!body.innerHTML.includes('데이터가 없습니다'));
    }
    for (const failure of [
        {ok: false, status: 400, json: async () => ({error: 'Invalid table'})},
        {ok: false, status: 500, json: async () => { throw new SyntaxError('HTML response'); }},
        {ok: true, status: 200, json: async () => ({error: 'Lookup failed'})},
    ]) {
        response = failure;
        context.openDetailModal('format', 'SEM REF', 'Liverpool', 3);
        await settle();
        assert(body.innerHTML.includes('데이터 로딩 실패'));
        assert(!body.innerHTML.includes('데이터가 없습니다'));
        await context.reloadFormatData('2026-09-12');
        assert(body.innerHTML.includes('데이터 로드 실패'));
        assert(!body.innerHTML.includes('데이터가 없습니다'));
        inputs['fmt-detail-days'] = {value: '5'};
        context.reloadFormatDays();
        await settle();
        assert(requests.at(-1).includes('days=5'));
        assert(body.innerHTML.includes('데이터 로드 실패'));
    }
    response = {ok: true, json: async () => ({results: [], field_counts: {}})};
    context.openDetailModal('format', 'SEM REF', 'Liverpool', 3);
    await settle();
    assert(body.innerHTML.includes('형식 오류 데이터가 없습니다.'));
    console.log('Layer2 SEM format detail and request failure tests passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
