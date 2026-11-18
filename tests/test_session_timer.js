// node tests/test_session_timer.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/js/session.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const DAY = 86400000;

function setup({remaining = DAY, clockSkew = 0} = {}) {
    let serverNow = 1800000000000, clientNow = serverNow + clockSkew;
    let expiry = serverNow + remaining, calls = 0, prompts = 0, offline = false;
    const classes = new Set(), docEvents = {}, windowEvents = {}, intervals = [];
    const label = {textContent: '', removeAttribute(name) {delete this[name];}};
    const container = {
        dataset: {statusUrl: '/accounts/session-status/', loginUrl: '/accounts/login/'},
        classList: {
            add(value) {classes.add(value);},
            toggle(value, enabled) {enabled ? classes.add(value) : classes.delete(value);},
        },
    };
    const document = {
        hidden: false, cookie: 'sessionid_expires=' + expiry,
        getElementById: () => label, querySelector: () => container,
        addEventListener(name, callback) {docEvents[name] = callback;},
    };
    const window = {
        location: {href: ''},
        addEventListener(name, callback) {windowEvents[name] = callback;},
    };
    const context = {
        document, window, console, AbortController,
        Date: {now: () => clientNow},
        setInterval(callback) {intervals.push(callback);},
        setTimeout: () => 1, clearTimeout() {},
        showConfirm() {prompts++; return Promise.resolve();},
        async fetch(url, options) {
            calls++;
            assert.equal(url, '/accounts/session-status/');
            assert.equal(options.cache, 'no-store');
            assert.equal(options.credentials, 'same-origin');
            if (offline) throw new Error('offline');
            if (expiry <= serverNow) return {ok: false, status: 401};
            return {ok: true, status: 200, json: async () => ({
                authenticated: true, expiresAt: expiry, serverTime: serverNow,
                expiryCookie: 'sessionid_expires',
            })};
        },
    };
    vm.runInNewContext(source, context);
    return {
        label, classes, document, window, docEvents, windowEvents,
        get calls() {return calls;}, get prompts() {return prompts;},
        setOffline(value) {offline = value;},
        extend() {expiry = serverNow + DAY; document.cookie = 'sessionid_expires=' + expiry;},
        async tick(ms) {
            serverNow += ms; clientNow += ms;
            intervals.forEach(callback => callback());
            await flush();
        },
    };
}

(async () => {
    const normal = setup({clockSkew: 7 * 60 * 60 * 1000});
    await flush();
    assert.equal(normal.label.textContent, '24:00:00', 'server time compensates for client clock skew');
    await normal.tick(61000);
    assert.equal(normal.label.textContent, '23:58:59');
    assert.equal(normal.calls, 1, 'countdown does not send keepalives');
    for (const name of ['click', 'keypress', 'scroll']) assert.equal(normal.docEvents[name], undefined);

    normal.extend(); // Simulates an API response or a request in another tab.
    await normal.tick(1000);
    assert.equal(normal.label.textContent, '23:59:59');
    assert.equal(normal.calls, 1, 'server cookie extension is picked up without a new request');

    normal.document.hidden = true;
    await normal.tick(3 * 60 * 60 * 1000);
    assert.equal(normal.label.textContent, '20:59:59', 'background throttling does not slow the countdown');
    assert.equal(normal.calls, 1, 'hidden tabs do not poll');
    normal.document.hidden = false;
    normal.docEvents.visibilitychange();
    await flush();
    assert.equal(normal.calls, 2, 'returning to a tab verifies persisted expiry');

    const warning = setup({remaining: 9 * 60 * 1000});
    await flush();
    assert(warning.classes.has('warning'));
    await warning.tick(4 * 60 * 1000);
    assert(warning.classes.has('critical'));
    assert(!warning.classes.has('warning'));

    const expired = setup({remaining: 1000});
    await flush();
    await expired.tick(1000);
    assert.equal(expired.prompts, 1);
    assert.equal(expired.label.textContent, '00:00:00');
    assert.equal(expired.window.location.href, '/accounts/login/', 'expiry never calls logout');
    await expired.tick(10000);
    assert.equal(expired.prompts, 1, 'expiry prompt is shown only once');

    const offline = setup({remaining: 1000});
    await flush();
    offline.setOffline(true);
    await offline.tick(1000);
    assert.equal(offline.prompts, 0, 'network failures cannot confirm logout');
    assert.equal(offline.label.textContent, '확인 중');
    const failedCalls = offline.calls;
    await offline.tick(1000);
    assert.equal(offline.calls, failedCalls, 'failed requests are throttled');
    offline.extend();
    offline.setOffline(false);
    offline.windowEvents.online();
    await flush();
    assert.equal(offline.label.textContent, '24:00:00');
    assert.equal(offline.prompts, 0);

    const crossTabLogout = setup();
    await flush();
    crossTabLogout.document.cookie = '';
    await crossTabLogout.tick(1000);
    assert.equal(crossTabLogout.calls, 2, 'missing cookie triggers a server check');
    assert.equal(crossTabLogout.prompts, 0, 'missing metadata alone is not treated as logout');
    console.log('Session timer scenarios passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
