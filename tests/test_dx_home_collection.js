const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'apps', 'dx', 'dx_dashboard',
    'static', 'dx_dashboard', 'js', 'collection-overview.js'), 'utf8');

function node() {
    return {
        children: [], dataset: {}, textContent: '', classList: {add() {}},
        append(...children) { this.children.push(...children); },
        prepend(child) { this.children.unshift(child); },
        querySelector() { return node(); },
        setAttribute() {},
        replaceChildren() { this.children = []; },
        get childElementCount() { return this.children.length; }
    };
}

async function render(failures, stallSem = false) {
    const overview = node();
    const markets = node();
    const message = node();
    overview.dataset = { statusUrl: '/existing', semTvStatusUrl: '/sem', productIconUrl: '/icons/' };
    overview.querySelector = selector => ({
        '.dx-overview-message': message,
        '.dx-overview-markets': markets,
        time: {dateTime: '2026-11-27'}
    })[selector];
    const countries = {
        '/existing': [{country: 'SEA', source_date: '2026-11-27', retailers: [
            {retailer: 'Bestbuy', product: 'TV', status: 'uncollected'}
        ]}],
        '/sem': [{country: 'SEM', source_date: '2026-11-27', retailers: [
            {retailer: 'Walmart', product: 'TV', status: 'received'},
            {retailer: "Sam's Club", product: 'TV', status: 'uncollected'}
        ]}]
    };
    await vm.runInNewContext(script, {
        window: {renderCountryFlagLabel: name => name},
        document: {querySelector: () => overview, createElement: node},
        AbortSignal: {timeout: delay => {
            assert.equal(delay, 8000);
            return AbortSignal.timeout(10);
        }},
        fetch: async (url, options) => {
            if (url === '/sem' && stallSem) {
                assert.ok(options.signal);
                await new Promise((resolve, reject) => {
                    const timer = setTimeout(resolve, 100);
                    options.signal.addEventListener('abort', () => {
                        clearTimeout(timer);
                        reject(options.signal.reason);
                    }, {once: true});
                });
            }
            return {ok: !failures.includes(url), json: async () => ({countries: countries[url]})};
        }
    });
    const sellers = markets.children.flatMap(section =>
        section.children[1].children.map(row => row.children[0].textContent));
    return {sellers, message};
}

async function main() {
    const both = await render([]);
    assert.deepEqual(both.sellers, ['Bestbuy', "Sam's Club"]);
    assert.equal(both.message.hidden, true);
    for (const [failed, seller] of [['/existing', "Sam's Club"], ['/sem', 'Bestbuy']]) {
        const partial = await render([failed]);
        assert.deepEqual(partial.sellers, [seller]);
        assert.equal(partial.message.hidden, false);
        assert.match(partial.message.textContent, /일부 수집 현황/);
    }
    const unavailable = await render(['/existing', '/sem']);
    assert.deepEqual(unavailable.sellers, []);
    assert.match(unavailable.message.textContent, /수집 현황을 조회하지 못했습니다/);
    const stalled = await render([], true);
    assert.deepEqual(stalled.sellers, ['Bestbuy']);
    assert.match(stalled.message.textContent, /일부 수집 현황/);
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
