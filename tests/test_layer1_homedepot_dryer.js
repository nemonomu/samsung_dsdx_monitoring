const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let day = '2026-10-15';
const context = { getSelectedDate: () => day, esc: String, RawDataView: function () {},
    L1: { initLayer1Page() {}, renderers: {} } };
vm.createContext(context);
for (const file of ['retail', 'collection-status']) {
    vm.runInContext(fs.readFileSync(`apps/dx/dx_layer1/static/dx_layer1/js/${file}.js`, 'utf8'), context);
}
const rows = () => context.buildSeaRetailFallbackCategories().find(c => c.name === 'LDY_DRYER').time_slots[0].retailers;
assert(!rows().some(r => r.retailer === 'HomeDepot'));
day = '2026-10-16';
assert(rows().some(r => r.retailer === 'HomeDepot'));
const html = context.renderDdayCollection({ source_date: '2026-10-15', retailers: [{
    product: 'LDY_DRYER', retailer: 'HomeDepot', count: 268, main_count: 268, bsr_count: 100,
    status: 'received', scheduled_at: null, batch_id: 'h1', last_collected_at: '2026-10-15 13:00:07'
}] });
assert(html.includes('HomeDepot'));
assert(html.includes('미정'));
assert(html.includes('수집 확인'));
assert(!html.includes('368'));
console.log('HomeDepot dryer launch and receipt display passed.');
