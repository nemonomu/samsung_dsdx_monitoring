const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/layer1-common.js', 'utf8');
let now = Date.UTC(2026, 8, 22, 14, 59); // KST 2026-09-22 23:59
class ClockDate extends Date {
    static now() { return now; }
}
const saved = new Map();
const toasts = [];
const columnAlertDates = [];
let loads = 0;
let bar;
class FilterBar {
    constructor(_selector, config) {
        this.config = config;
        this.input = {value: config.controls[0].value, max: config.controls[0].max};
        this.barEl = {querySelector: () => this.input};
        bar = this;
    }
    render() { return this; }
    getDate() { return this.input.value; }
    setDate(value) { this.input.value = value; }
    prevDay() { this.input.value = shift(this.input.value, -1); }
    nextDay() {
        const next = shift(this.input.value, 1);
        if (next <= this.input.max) this.input.value = next;
    }
}
function shift(value, days) {
    const date = new Date(value + 'T00:00:00Z');
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

const sandbox = {
    Date: ClockDate, FilterBar,
    window: { location: {search:''} }, URLSearchParams,
    sessionStorage: {getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value)},
    showToast: message => toasts.push(message),
    loadAllData: () => { loads++; },
    ColumnAlertSummary: {load: (date, force = false) => columnAlertDates.push({date, force})},
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
sandbox.initFilterBar();
assert.strictEqual(bar.config.controls[0].max, '2026-09-23');
assert.strictEqual(bar.config.controls[0].maxToday, false);
assert.strictEqual(bar.getDate(), '2026-09-22');
assert.deepStrictEqual(columnAlertDates.at(-1), {date:'2026-09-22',force:false});

const next = bar.config.controls.find(control => control.label === '다음날');
next.onClick();
assert.strictEqual(bar.getDate(), '2026-09-23');
assert.strictEqual(loads, 1);
assert.deepStrictEqual(columnAlertDates.at(-1), {date:'2026-09-23',force:true});
next.onClick();
assert.strictEqual(bar.getDate(), '2026-09-23');
assert.strictEqual(loads, 1);
assert(toasts.at(-1).includes('내일 이후'));

now = Date.UTC(2026, 8, 22, 15, 1); // KST 2026-09-23 00:01, same open page
next.onClick();
assert.strictEqual(bar.input.max, '2026-09-24');
assert.strictEqual(bar.getDate(), '2026-09-24');
assert.strictEqual(loads, 2);

bar.setDate('2026-09-25');
bar.config.controls.find(control => control.label === '조회').onClick();
assert.strictEqual(bar.getDate(), '2026-09-24');
assert.strictEqual(loads, 2);

const events = {};
sandbox.document = {addEventListener: (name, listener) => events[name] = listener};
sandbox.window.addEventListener = sandbox.document.addEventListener;
sandbox.L1.initLayer1Page();
assert.equal(typeof sandbox.window.onload, 'function', 'a section registers the legacy init');
sandbox.L1.initLayer1Page({loadOnDomReady:true});
assert.equal(sandbox.window.onload, null, 'dashboard replaces the bundled section init');
events.DOMContentLoaded();
assert.equal(loads, 3, 'dashboard starts one load without waiting for window load');
events.pageshow({persisted:false});
assert.equal(loads, 3);
events.pageshow({persisted:true});
assert.equal(loads, 4, 'back-forward cache restore revalidates once');

console.log('Layer1 allows only the next KST inspection date, including after midnight.');
