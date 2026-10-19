const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const root = 'apps/dx/dx_layer3';
const calls = [];
const context = vm.createContext({
    console,
    window: { LAYER3: { section: 'cross_field' } },
    document: {
        addEventListener() {},
        querySelector() { return null; },
        getElementById() { return null; },
    },
    getSelectedDate() { return '2026-10-11'; },
    fetchAPI: async url => { calls.push(url); return {}; },
    renderCrossfieldSummaryContent() {},
});
vm.runInContext(fs.readFileSync(`${root}/static/dx_layer3/js/common.js`, 'utf8'), context);

(async () => {
    // Exercise the actual click handler, including a stale display title.
    for (const [code, name] of [
        ['seg_ldy_dryer', 'SEG LDY_DRYER 논리적 일관성'],
        ['seg_ldy_dryer', 'SEG LDY 논리적 일관성'],
        ['seg_ldy', 'SEG LDY 논리적 일관성'],
        ['sea_ldy_dryer', 'SEA LDY_DRYER 논리적 일관성'],
        ['sea_ldy', 'SEA LDY 논리적 일관성'],
    ]) {
        await context.showDetail('크로스 필드 검증', name, code);
        assert.strictEqual(calls.at(-1), `/layer3/api/cross-field-detail/?date=2026-10-11&type=${code}`);
    }
    for (const file of fs.readdirSync(`${root}/templates`).filter(name => name.endsWith('.html'))) {
        const html = fs.readFileSync(`${root}/templates/${file}`, 'utf8');
        for (const line of html.split('\n')) {
            if (line.includes('dx_layer3/js/common.js') || line.includes('dx_layer3/js/cross-field.js')) {
                assert(line.includes('?v=20261019-seib-crossfield'), `${file}: stale script version`);
            }
        }
    }
    console.log('Dryer detail routing and template cache checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
