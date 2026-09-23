const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const countries = ['SEDA', 'SIEL', 'SEM', 'SEG', 'TSE'];
const opened = [], scrolled = [];
const nodes = new Map(countries.map(country => [country.toLowerCase() + '_retail', {
    scrollIntoView() {scrolled.push(country);},
}]));
const sandbox = {
    console,
    window: {LAYER1:{section:'dashboard'}, location:{href:'/dx/layer1/'}},
    document: {
        addEventListener(){}, getElementById(){return null;},
        querySelector(selector) {return nodes.get(selector.match(/data-check-type="([^"]+)"/)[1]) || null;},
    },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('apps/dx/dx_layer1/static/dx_layer1/js/layer1-common.js', 'utf8'), sandbox);
sandbox.L1.retailStatus = {open: (element, index) => opened.push(index)};
sandbox.currentStatsData = {checks:countries.map(country => ({check_type:country.toLowerCase()+'_retail'}))};
sandbox.filterBar = {getDate:() => '2026-09-23'};
countries.forEach(country => sandbox.onSubitemClick('daily', country+' Retail'));
assert.equal(sandbox.window.location.href, '/dx/layer1/', 'loaded country selection must not reload the dashboard');
assert.deepEqual(opened, [0,1,2,3,4]);
assert.deepEqual(scrolled, countries);
sandbox.window.LAYER1.section = 'retail';
sandbox.onSubitemClick('daily', 'SEG Retail');
assert.equal(sandbox.window.location.href, '/dx/layer1/?date=2026-09-23', 'navigation from another page keeps selected date');
sandbox.window.LAYER1.section = 'dashboard';
sandbox.onSubitemClick('daily', 'SEA Retail');
assert.equal(sandbox.window.location.href, '/dx/layer1/retail/?date=2026-09-23');
console.log('Layer1 country navigation: five loaded sections expand without reload; other routes preserve date.');
